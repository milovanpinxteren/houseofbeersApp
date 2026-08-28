"""Campaign raffle draws: atomic winner selection, prize fulfillment,
result/reminder notifications and best-effort redemption detection.

The draw mirrors events/models.py:Raffle.draw_winners (select_for_update,
status re-check) but samples WITHOUT replacement weighted by ticket_count, so
a user wins at most once and more tickets mean better odds.
"""
import logging
import random
import secrets
import string
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

logger = logging.getLogger(__name__)

# Reminders go out when the draw is at most this far away (see
# campaign_raffle_scheduler, which runs every 5 minutes).
REMINDER_WINDOW = timedelta(hours=3)


def _generate_prize_code() -> str:
    # WIN- prefix: raffle prizes. HOB- (loyalty), BDAY- (birthday) and SIX-
    # (sixpack) are taken; a distinct prefix keeps order attribution clean.
    chars = string.ascii_uppercase + string.digits
    return 'WIN-' + ''.join(secrets.choice(chars) for _ in range(8))


def _first_name(user) -> str:
    return user.first_name or user.email.split('@')[0]


def _weighted_sample_without_replacement(entries, num_to_draw):
    """
    Draw `num_to_draw` distinct entries, each pick weighted by ticket_count.
    Equivalent to putting ticket_count lots per user in a hat and drawing
    until num_to_draw distinct users have come up.
    """
    pool = list(entries)
    selected = []
    while pool and len(selected) < num_to_draw:
        weights = [max(entry.ticket_count, 1) for entry in pool]
        pick = random.choices(pool, weights=weights, k=1)[0]
        selected.append(pick)
        pool.remove(pick)
    return selected


def draw_raffle(raffle):
    """
    Draw the raffle. Returns the list of CampaignRaffleWinner in draw order,
    or None when the raffle was already drawn (double-draw safe).

    Winner selection and the status flips happen inside one locked
    transaction, so a concurrent draw sees status='drawn' and backs off.
    Fulfillment and notifications run AFTER commit: they do network I/O and
    their failure must never undo (or re-run) the draw itself.
    """
    from loyalty.models import CampaignRaffle, CampaignRaffleWinner

    with transaction.atomic():
        locked = CampaignRaffle.objects.select_for_update().select_related(
            'campaign'
        ).get(pk=raffle.pk)
        if locked.status != 'open':
            return None

        entries = list(locked.entries.select_related('user'))
        num_to_draw = min(locked.num_winners, len(entries))
        winning_entries = _weighted_sample_without_replacement(entries, num_to_draw)

        # Individual creates (not bulk_create): draw order = pk order, and
        # SQLite does not return ids from bulk_create anyway.
        winners = [
            CampaignRaffleWinner.objects.create(raffle=locked, user=entry.user)
            for entry in winning_entries
        ]

        locked.status = 'drawn'
        locked.drawn_at = timezone.now()
        locked.save(update_fields=['status', 'drawn_at'])

        campaign = locked.campaign
        campaign.status = 'completed'
        campaign.save(update_fields=['status', 'updated_at'])

        # Keep the caller's instance consistent with the DB.
        raffle.status = locked.status
        raffle.drawn_at = locked.drawn_at

    _fulfill_winners(locked, winners)
    _notify_draw_results(locked, entries, winners)

    logger.info(
        f"Raffle {locked.id} ({locked.prize_name}) drawn: "
        f"{len(winners)} winner(s) from {len(entries)} entrant(s)"
    )
    return winners


# ============ Fulfillment ============

def _fulfill_winners(raffle, winners):
    """
    shopify_code -> mint a prize code per winner (campaign discount_* fields
    are the prize config); a failed mint leaves the winner 'pending' so
    "Check redemptions"/a re-run can retry by hand. manual -> manual_pending.
    """
    from loyalty.services.discounts import create_discount_code

    campaign = raffle.campaign
    for winner in winners:
        if raffle.fulfillment_type == 'manual':
            winner.fulfillment_status = 'manual_pending'
            winner.save(update_fields=['fulfillment_status'])
            continue

        code = _generate_prize_code()
        result = create_discount_code(winner.user, campaign, code)
        if result:
            winner.prize_code = result.get('code') or code
            winner.shopify_discount_id = str(result.get('discount_id', ''))
            winner.cart_url = result.get('cart_url') or ''
            winner.code_expires_at = result.get('expires_at')
            winner.fulfillment_status = 'code_issued'
            winner.save(update_fields=[
                'prize_code', 'shopify_discount_id', 'cart_url',
                'code_expires_at', 'fulfillment_status',
            ])
        else:
            # create_discount_code never raises; None = Shopify refused.
            # Status stays 'pending' - visible in the Studio monitor as
            # needing attention, and the draw/notifications proceed.
            logger.error(
                f"Prize code creation failed for raffle {raffle.id}, "
                f"winner {winner.user.email}; fulfillment left pending"
            )


# ============ Notifications ============

def _winner_body(raffle, winner) -> str:
    body = f"Gefeliciteerd! Je hebt gewonnen: {raffle.prize_name}."
    if winner.prize_code:
        body += f" Je code: {winner.prize_code}."
        if winner.code_expires_at:
            local = timezone.localtime(winner.code_expires_at)
            body += f" Geldig tot {local.strftime('%d-%m-%Y')}."
    elif raffle.fulfillment_type == 'manual':
        body += " We nemen contact met je op over je prijs."
    return body


def _notify_draw_results(raffle, entries, winners):
    """
    One result notification per entrant, via the notifications outbox
    (dedupe_key makes a re-run harmless). Winners with a code get
    email_policy='always': the code must reach an inbox. Failures are logged
    per user and never abort the rest of the fan-out.
    """
    campaign = raffle.campaign
    url = f'/raffle/{raffle.id}'
    winners_by_user = {winner.user_id: winner for winner in winners}

    for entry in entries:
        user = entry.user
        winner = winners_by_user.get(user.id)
        try:
            from notifications.services import send_notification

            if winner:
                delivery = send_notification(
                    user,
                    kind='raffle',
                    title='Je hebt gewonnen!',
                    body=_winner_body(raffle, winner),
                    data={'url': url},
                    dedupe_key=f'campaign:{campaign.id}:{user.id}:result',
                    email_policy='always' if winner.prize_code else None,
                )
                delivery_id = getattr(delivery, 'id', None)
                if delivery_id:
                    winner.result_delivery_id = delivery_id
                    winner.save(update_fields=['result_delivery_id'])
            else:
                send_notification(
                    user,
                    kind='raffle',
                    title=f'De trekking van {raffle.prize_name} is geweest',
                    body=(
                        'Helaas, dit keer geen prijs. Bekijk de trekking in '
                        'de app - en tot de volgende actie!'
                    ),
                    data={'url': url},
                    dedupe_key=f'campaign:{campaign.id}:{user.id}:result',
                )
        except Exception as e:
            logger.error(
                f"Result notification failed for raffle {raffle.id}, "
                f"user {user.email}: {e}",
                exc_info=True,
            )


def send_raffle_reminders() -> int:
    """
    Reminder for every open raffle drawing within REMINDER_WINDOW whose
    reminder hasn't gone out yet. One notification per entrant; the raffle is
    marked reminded even when individual sends fail (dedupe keys make a
    retry safe, and a broken subscription must not re-spam the rest).
    Returns the number of raffles reminded.
    """
    from loyalty.models import CampaignRaffle

    now = timezone.now()
    due = CampaignRaffle.objects.filter(
        status='open',
        send_reminder=True,
        reminder_sent_at__isnull=True,
        draw_at__isnull=False,
        draw_at__gt=now,
        draw_at__lte=now + REMINDER_WINDOW,
    ).select_related('campaign')

    reminded = 0
    for raffle in due:
        campaign = raffle.campaign
        local_draw = timezone.localtime(raffle.draw_at)
        for entry in raffle.entries.select_related('user'):
            try:
                from notifications.services import send_notification

                send_notification(
                    entry.user,
                    kind='raffle',
                    title='De trekking komt eraan!',
                    body=(
                        f'Om {local_draw.strftime("%H:%M")} uur trekken we de '
                        f'winnaar van {raffle.prize_name}. '
                        f'Jij doet mee met {entry.ticket_count} '
                        f'{"lot" if entry.ticket_count == 1 else "loten"}.'
                    ),
                    data={'url': f'/raffle/{raffle.id}'},
                    dedupe_key=f'campaign:{campaign.id}:{entry.user_id}:reminder',
                )
            except Exception as e:
                logger.error(
                    f"Reminder failed for raffle {raffle.id}, "
                    f"user {entry.user.email}: {e}",
                    exc_info=True,
                )
        raffle.reminder_sent_at = timezone.now()
        raffle.save(update_fields=['reminder_sent_at'])
        reminded += 1

    return reminded


# ============ Redemption detection ============

def check_winner_redemptions() -> dict:
    """
    Best-effort: for issued prize codes not yet marked redeemed, ask Shopify
    (codeDiscountNodeByCode usage count) whether the code was used and stamp
    redeemed_at. One Shopify hiccup skips that winner, never the run.
    """
    from loyalty.models import CampaignRaffleWinner
    from users.services import ShopifyService

    pending = CampaignRaffleWinner.objects.filter(
        fulfillment_status='code_issued',
        redeemed_at__isnull=True,
    ).exclude(prize_code='').select_related('user', 'raffle')

    checked = 0
    redeemed = 0
    service = ShopifyService()
    for winner in pending:
        try:
            usage = service.get_discount_code_usage(winner.prize_code)
            checked += 1
            if usage and usage > 0:
                winner.redeemed_at = timezone.now()
                winner.save(update_fields=['redeemed_at'])
                redeemed += 1
                logger.info(
                    f"Prize code {winner.prize_code} "
                    f"({winner.user.email}) marked redeemed"
                )
        except Exception as e:
            logger.error(
                f"Redemption check failed for {winner.prize_code}: {e}",
                exc_info=True,
            )

    return {'checked': checked, 'redeemed': redeemed}
