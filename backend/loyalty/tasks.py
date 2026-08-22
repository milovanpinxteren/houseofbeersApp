import calendar
import logging
import secrets
import string
from datetime import date, timedelta
from zoneinfo import ZoneInfo

from celery import shared_task
from django.db import IntegrityError, transaction
from django.utils import timezone

logger = logging.getLogger(__name__)

# Gifts are scheduled for a civil local hour, never "whenever the cron fired".
BIRTHDAY_TZ = ZoneInfo('Europe/Amsterdam')

# Birthdays that fell in the last N days with nothing issued are still
# honoured, so an outage does not silently swallow somebody's gift.
BIRTHDAY_CATCHUP_DAYS = 3


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def partial_sync_user_points(self, user_id):
    """Incrementally sync new orders since last sync for a single user."""
    from users.models import User
    from loyalty.services import LoyaltyService

    try:
        user = User.objects.get(id=user_id)
    except User.DoesNotExist:
        logger.error(f"User {user_id} not found for partial sync")
        return

    service = LoyaltyService()
    result = service.partial_sync_for_user(user)

    if result.get('success'):
        logger.info(
            f"Partial sync completed for {user.email}: "
            f"+{result.get('total_awarded', 0)} points from "
            f"{result.get('processed_count', 0)} orders"
        )
    else:
        error = result.get('error', 'Unknown error')
        if error == 'Sync already in progress':
            logger.info(f"Skipping {user.email}: sync already in progress")
            return
        logger.error(f"Partial sync failed for {user.email}: {error}")
        raise self.retry(exc=Exception(error))


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def intermediate_sync_user_points(self, user_id):
    """Fetch all orders, process only unprocessed ones."""
    from users.models import User
    from loyalty.services import LoyaltyService

    try:
        user = User.objects.get(id=user_id)
    except User.DoesNotExist:
        logger.error(f"User {user_id} not found for intermediate sync")
        return

    service = LoyaltyService()
    result = service.intermediate_sync_for_user(user)

    if result.get('success'):
        logger.info(
            f"Intermediate sync completed for {user.email}: "
            f"+{result.get('total_awarded', 0)} points from "
            f"{result.get('processed_count', 0)} orders"
        )
    else:
        error = result.get('error', 'Unknown error')
        if error == 'Sync already in progress':
            logger.info(f"Skipping {user.email}: sync already in progress")
            return
        logger.error(f"Intermediate sync failed for {user.email}: {error}")
        raise self.retry(exc=Exception(error))


@shared_task(bind=True, max_retries=2, default_retry_delay=120)
def full_sync_user_points(self, user_id):
    """Check-and-correct: recalculate points per order, adjust differences. Admin only."""
    from users.models import User
    from loyalty.services import LoyaltyService

    try:
        user = User.objects.get(id=user_id)
    except User.DoesNotExist:
        logger.error(f"User {user_id} not found for full sync")
        return

    service = LoyaltyService()
    result = service.full_sync_for_user(user)

    if result.get('success'):
        logger.info(
            f"Full sync completed for {user.email}: "
            f"net adjustment {result.get('net_adjustment', 0):+d}, "
            f"{result.get('corrected_count', 0)} corrected, "
            f"{result.get('new_count', 0)} new"
        )
    else:
        error = result.get('error', 'Unknown error')
        if error == 'Sync already in progress':
            logger.info(f"Skipping {user.email}: sync already in progress")
            return
        logger.error(f"Full sync failed for {user.email}: {error}")
        raise self.retry(exc=Exception(error))


def _generate_birthday_code() -> str:
    """Generate an unguessable single-use birthday discount code."""
    chars = string.ascii_uppercase + string.digits
    return 'BDAY-' + ''.join(secrets.choice(chars) for _ in range(8))


def _celebration_keys(day: date) -> set:
    """
    The (month, day) birthdate values that are celebrated on `day`.
    On 28 February of a non-leap year that also includes 29 February.
    """
    keys = {(day.month, day.day)}
    if day.month == 2 and day.day == 28 and not calendar.isleap(day.year):
        keys.add((2, 29))
    return keys


def _offer_label(config) -> str:
    """Human-readable description of the configured offer."""
    value = config.discount_value
    text = str(int(value)) if value == int(value) else str(value)
    if config.discount_type == 'percentage':
        return f"{text}% off"
    return f"€{text} off"


def _issue_birthday_gift(user, year: int, config) -> bool:
    """
    Issue one birthday gift. Returns True if a gift was issued.
    Raises on Shopify failure so the caller can log it per-user.

    No lead-time rule: the birthdate is set-once (see User.birthdate_locked),
    which already prevents moving your birthday around to farm gifts.
    """
    from loyalty.models import BirthdayReward
    from users.services import ShopifyService

    if BirthdayReward.objects.filter(user=user, year=year).exists():
        logger.debug(f"Birthday gift already issued to {user.email} for {year}")
        return False

    code = _generate_birthday_code()
    expires_at = timezone.now() + timedelta(days=config.validity_days)

    # A code without a linked customer cannot be locked to one, but
    # usage_limit=1 bounds the exposure to exactly the gift we intended.
    customer_id = user.shopify_customer_id or None

    result = ShopifyService().create_discount_code(
        code=code,
        discount_type=config.discount_type,
        value=float(config.discount_value),
        usage_limit=1,
        customer_id=customer_id,
        ends_at=expires_at,
    )
    if not result:
        raise RuntimeError(f"Shopify refused to create birthday code {code}")

    try:
        with transaction.atomic():
            reward = BirthdayReward.objects.create(
                user=user,
                year=year,
                discount_code=code,
                expires_at=expires_at,
            )
    except IntegrityError:
        # Another worker won the race; the unique constraint did its job.
        logger.info(f"Birthday gift for {user.email} ({year}) already created by another run")
        return False

    offer = _offer_label(config)
    name = user.first_name or 'there'
    title = 'Happy birthday from House of Beers!'
    body = f"Here is {offer} as a birthday gift. Use code {code} before {expires_at.date()}."

    try:
        # Imported here, not at module level, so loyalty does not hard-depend
        # on the notifications app at import time.
        from notifications.services import send_notification

        delivery = send_notification(
            user,
            kind='birthday_gift',
            title=title,
            body=body,
            data={'url': '/loyalty', 'discount_code': code},
            dedupe_key=f'birthday:{user.id}:{year}',
            email_subject=title,
            email_body=(
                f"Hi {name},\n\n"
                f"Happy birthday! Here is {offer} on your next order at House of Beers.\n\n"
                f"Your code: {code}\n"
                f"Valid until: {expires_at.date()}\n\n"
                f"Cheers,\nHouse of Beers Team"
            ),
        )
        delivery_id = getattr(delivery, 'id', None)
        if delivery_id:
            reward.delivery_id = delivery_id
            reward.save(update_fields=['delivery_id'])
    except Exception as e:
        # The gift itself is safely recorded; only the message failed.
        logger.error(
            f"Birthday gift {code} issued to {user.email} ({year}) but the "
            f"notification failed: {e}",
            exc_info=True,
        )

    logger.info(f"Issued birthday gift {code} to {user.email} for {year}")
    return True


@shared_task
def birthday_scan():
    """
    Hourly: issue birthday gifts at the configured local send hour.

    Runs every hour so the send hour stays admin-tunable and so birthdays
    missed during an outage are caught up (see BIRTHDAY_CATCHUP_DAYS).
    """
    from loyalty.models import BirthdayRewardConfig
    from users.models import User

    config = BirthdayRewardConfig.load()

    if not config.is_active:
        logger.info("Birthday scan skipped: feature is not active")
        return {'skipped': 'inactive'}

    now_local = timezone.now().astimezone(BIRTHDAY_TZ)
    if now_local.hour != config.send_hour:
        logger.debug(
            f"Birthday scan skipped: hour {now_local.hour} != send hour {config.send_hour}"
        )
        return {'skipped': 'outside send hour'}

    today = now_local.date()

    # (month, day) -> the calendar year that birthday belongs to. Walking
    # backwards means the catch-up window can cross a year boundary
    # (e.g. 30 December when today is 1 January).
    key_years = {}
    for offset in range(BIRTHDAY_CATCHUP_DAYS + 1):
        day = today - timedelta(days=offset)
        for key in _celebration_keys(day):
            key_years.setdefault(key, day.year)

    issued = 0
    skipped = 0
    failed = 0

    for (month, day), year in key_years.items():
        candidates = User.objects.filter(
            is_active=True,
            birthdate__isnull=False,
            birthdate__month=month,
            birthdate__day=day,
        ).exclude(
            birthday_rewards__year=year
        )

        for user in candidates:
            try:
                if _issue_birthday_gift(user, year, config):
                    issued += 1
                else:
                    skipped += 1
            except Exception as e:
                # One user's failure must never abort the whole run.
                failed += 1
                logger.error(
                    f"Birthday gift failed for {user.email} ({year}): {e}",
                    exc_info=True,
                )

    logger.info(
        f"Birthday scan complete for {today}: {issued} issued, "
        f"{skipped} skipped, {failed} failed"
    )
    return {'issued': issued, 'skipped': skipped, 'failed': failed}


@shared_task(bind=True, max_retries=2, default_retry_delay=120)
def campaign_backfill(self, campaign_id, preview_id=None):
    """
    Shop-wide order scan for one campaign. With preview_id: dry-run whose
    result lands in that CampaignPreview (Studio preview flow); without:
    live run that writes progress/awards/entries.
    """
    from loyalty.models import Campaign, CampaignPreview
    from loyalty.services.campaigns import run_backfill

    try:
        campaign = Campaign.objects.get(id=campaign_id)
    except Campaign.DoesNotExist:
        logger.error(f"Campaign {campaign_id} not found for backfill")
        return

    if preview_id:
        try:
            preview = CampaignPreview.objects.get(id=preview_id)
        except CampaignPreview.DoesNotExist:
            logger.error(f"CampaignPreview {preview_id} not found")
            return

        preview.status = 'running'
        preview.save(update_fields=['status'])
        try:
            result = run_backfill(campaign, dry_run=True)
        except Exception as e:
            preview.status = 'failed'
            preview.error = str(e)
            preview.finished_at = timezone.now()
            preview.save(update_fields=['status', 'error', 'finished_at'])
            logger.error(f"Preview failed for campaign {campaign_id}: {e}", exc_info=True)
            return

        preview.status = 'done'
        preview.result = result
        preview.finished_at = timezone.now()
        preview.save(update_fields=['status', 'result', 'finished_at'])

        # A fresh preview unlocks activation in the Studio. Queryset .update()
        # deliberately bypasses Campaign.save()'s stale-marking.
        updates = {'preview_stale': False}
        if campaign.status == 'draft':
            updates['status'] = 'previewed'
        Campaign.objects.filter(pk=campaign.pk).update(**updates)
        return result

    try:
        result = run_backfill(campaign, dry_run=False)
    except Exception as e:
        # Shopify down mid-scan: retry the whole run — processed_order_ids
        # makes re-applying already-seen orders a no-op.
        logger.error(f"Live backfill failed for campaign {campaign_id}: {e}", exc_info=True)
        raise self.retry(exc=e)
    logger.info(
        f"Campaign backfill completed for {campaign.name}: "
        f"{result.get('orders_scanned', 0)} orders scanned, "
        f"{result.get('qualified_count', 0)} qualified"
    )
    return result


@shared_task
def refresh_campaign_snapshots():
    """
    Nightly: re-resolve tag/collection matcher snapshots for active campaigns
    and complete non-raffle campaigns past their window_end (raffle campaigns
    complete when their raffle is drawn).
    """
    from loyalty.models import Campaign
    from loyalty.services.campaigns import resolve_product_matchers

    now = timezone.now()
    completed = 0
    refreshed = 0
    failed = 0

    for campaign in Campaign.objects.filter(status='active'):
        if campaign.action_type != 'raffle' and campaign.window_end < now:
            campaign.status = 'completed'
            campaign.save(update_fields=['status', 'updated_at'])
            completed += 1
            continue
        try:
            resolve_product_matchers(campaign)
            refreshed += 1
        except Exception as e:
            failed += 1
            logger.error(
                f"Snapshot refresh failed for campaign {campaign.id}: {e}",
                exc_info=True,
            )

    logger.info(
        f"Campaign snapshot refresh: {refreshed} refreshed, "
        f"{completed} completed, {failed} failed"
    )
    return {'refreshed': refreshed, 'completed': completed, 'failed': failed}


@shared_task(bind=True, max_retries=2, default_retry_delay=60)
def draw_campaign_raffle(self, raffle_id):
    """
    Draw one campaign raffle (scheduled by campaign_raffle_scheduler or
    dispatched from the Studio's "Trek nu" button). Safe to retry/dispatch
    twice: an already-drawn raffle is a logged no-op.
    """
    from loyalty.models import CampaignRaffle
    from loyalty.services.raffles import draw_raffle

    try:
        raffle = CampaignRaffle.objects.get(id=raffle_id)
    except CampaignRaffle.DoesNotExist:
        logger.error(f"CampaignRaffle {raffle_id} not found for draw")
        return

    try:
        winners = draw_raffle(raffle)
    except Exception as e:
        logger.error(f"Draw failed for raffle {raffle_id}: {e}", exc_info=True)
        raise self.retry(exc=e)

    if winners is None:
        logger.info(f"Raffle {raffle_id} already drawn, skipping")
        return {'already_drawn': True}
    return {'winners': len(winners)}


@shared_task
def campaign_raffle_scheduler():
    """
    Every 5 minutes: draw open raffles whose draw_at has passed and send
    reminders for raffles drawing within the reminder window. Draws run
    inline (we're already in a worker); one raffle's failure never blocks
    another's.
    """
    from loyalty.models import CampaignRaffle
    from loyalty.services.raffles import draw_raffle, send_raffle_reminders

    now = timezone.now()
    due = CampaignRaffle.objects.filter(
        status='open', draw_at__isnull=False, draw_at__lte=now,
    )

    drawn = 0
    failed = 0
    for raffle in due:
        try:
            if draw_raffle(raffle) is not None:
                drawn += 1
        except Exception as e:
            failed += 1
            logger.error(
                f"Scheduled draw failed for raffle {raffle.id}: {e}",
                exc_info=True,
            )

    try:
        reminded = send_raffle_reminders()
    except Exception as e:
        reminded = 0
        logger.error(f"Raffle reminders failed: {e}", exc_info=True)

    if drawn or failed or reminded:
        logger.info(
            f"Raffle scheduler: {drawn} drawn, {failed} failed, "
            f"{reminded} raffle(s) reminded"
        )
    return {'drawn': drawn, 'failed': failed, 'reminded': reminded}


@shared_task
def check_winner_redemptions():
    """
    Daily (and on demand from the Studio's "Check redemptions" button):
    mark issued prize codes as redeemed once Shopify reports usage.
    """
    from loyalty.services.raffles import check_winner_redemptions as check

    result = check()
    logger.info(
        f"Raffle redemption check: {result['checked']} checked, "
        f"{result['redeemed']} newly redeemed"
    )
    return result


@shared_task
def periodic_partial_sync():
    """Every 3 hours: partial sync (new orders only) for all active users."""
    from users.models import User

    users = User.objects.filter(
        shopify_customer_id__isnull=False
    ).exclude(
        shopify_customer_id=''
    )

    count = 0
    for i, user in enumerate(users):
        partial_sync_user_points.apply_async(
            args=[user.id],
            countdown=i * 2,  # Stagger 2s apart to respect Shopify rate limits
        )
        count += 1

    logger.info(f"Dispatched partial sync for {count} users")


@shared_task
def periodic_intermediate_sync():
    """Nightly: intermediate sync (all orders, process unprocessed) for all active users."""
    from users.models import User

    users = User.objects.filter(
        shopify_customer_id__isnull=False
    ).exclude(
        shopify_customer_id=''
    )

    count = 0
    for i, user in enumerate(users):
        intermediate_sync_user_points.apply_async(
            args=[user.id],
            countdown=i * 2,
        )
        count += 1

    logger.info(f"Dispatched intermediate sync for {count} users")
