"""Staff points tool: award or correct a member's points from the admin.

Why this exists: 20% of every point ever awarded came from a handful of manual
`adjusted` transactions written straight into the database. Those render in the
member's app as a generic "Adjustment by House of Beers" — the member is told
nothing about why they got points, which is exactly backwards for a reward
meant to celebrate something (an Instagram post, a WhatsApp invite).

Two modes, two DELIBERATELY different transaction shapes:

* **Add** is something the member EARNED. It goes through
  `grants.create_grant` — the one path in this codebase for "award points with
  a reason" (the hob service API and the signup bonus use it too). That
  produces an `earned` transaction with `rule=None`, NO `shopify_order_id` (a
  full sync deletes rows that carry one it cannot reproduce) and a breakdown
  whose `rule_name` is what the app's history expander shows. So the member
  reads "Instagram post", not "Adjustment".
* **Set** is a CORRECTION, not something the member earned, so it stays an
  `adjusted` transaction via `LoyaltyService.adjust_points`. That method
  already applies the delta to `lifetime_earned` (never `lifetime_spent`,
  which is reserved for redemptions), keeping the ledger invariant
  `balance == lifetime_earned - lifetime_spent` intact. We compute the delta,
  it does the arithmetic.

Both modes read the balance under `select_for_update` so a redemption landing
at the same moment cannot be lost: add mode via `grants._fulfil_grant`, set
mode via `LoyaltyService._get_locked_balance` (which we need anyway — a delta
computed from an unlocked read is a delta computed from a stale number).

Every action is logged as a Django admin `LogEntry` against the MEMBER, so it
shows up in that user's admin history with the staff member's name attached.
The member-facing text never carries a staff name.
"""
import logging
import uuid

from django.contrib.admin.models import CHANGE, LogEntry
from django.db import transaction

from loyalty.services.grants import (
    GrantError, MAX_GRANT_POINTS, create_grant, grant_notification_text,
)
from loyalty.services.points_value import (
    euro_per_point, format_euro, points_to_euro,
)

logger = logging.getLogger(__name__)

# Marks the admin log entries this tool writes, so the tool can list its own
# recent actions (and so they are recognisable in the member's admin history).
LOG_PREFIX = '[Puntentool]'

# Above this the confirmation step shows a loud warning. It does NOT block:
# a big award can be perfectly legitimate (a prize, a goodwill gesture), it
# just must never happen because someone's finger slipped on the keyboard.
# 2000 punten is €100 at the current rate.
WARN_POINTS = 2000

# Same ceiling the service API uses; a manual award is not more trusted than
# an automated one.
MAX_POINTS = MAX_GRANT_POINTS

SOURCE = 'staff_tool'


class PointsToolError(Exception):
    """Validation/execution error with an NL message safe to show staff."""


def new_action_token():
    """
    One-shot token minted when the confirmation screen is rendered and posted
    back with it. It becomes the grant's `dedupe_key`, so a double-submitted
    confirmation (double click, browser resend) awards points once, not twice.
    """
    return uuid.uuid4().hex


def award_warnings(points):
    """NL warnings to show on the confirmation step. Never blocks."""
    warnings = []
    if abs(points) >= WARN_POINTS:
        warnings.append(
            f'Dit is een grote correctie: {abs(points)} punten '
            f'({format_euro(points_to_euro(abs(points)))}). '
            'Controleer of er geen cijfer te veel is ingetypt.'
        )
    return warnings


def _log(staff_user, member, message):
    """Admin history entry against the member, naming the staff user."""
    LogEntry.objects.log_actions(
        user_id=staff_user.pk,
        queryset=[member],
        action_flag=CHANGE,
        change_message=f'{LOG_PREFIX} {message}',
        single_object=True,
    )


def add_points(*, member, points, reason, staff_user, notify=True, token=None):
    """
    Award `points` to `member` with a member-visible `reason`.

    Returns a result dict: {'points', 'balance', 'created', 'notified'}.
    `created` is False when this token was already processed (idempotent
    re-submit) — the caller should say so rather than award again.
    """
    reason = (reason or '').strip()
    if not reason:
        raise PointsToolError('Vul een reden in — die ziet het lid in de app.')
    if not isinstance(points, int) or points < 1:
        raise PointsToolError('Vul een aantal punten in (minimaal 1).')
    if points > MAX_POINTS:
        raise PointsToolError(
            f'Maximaal {MAX_POINTS} punten per keer.'
        )

    token = token or new_action_token()
    try:
        # The balance row is locked inside create_grant -> _fulfil_grant, so
        # a concurrent redemption cannot race this award.
        grant, created = create_grant(
            dedupe_key=f'pointstool:{token}',
            points=points,
            reason=reason,
            source=SOURCE,
            # Same calling convention as the signup bonus: identify by email.
            # `User.email` is unique and get_by_natural_key matches exactly
            # first, so this always resolves back to this same member.
            email=member.email,
            context={
                'tool': 'points_tool',
                'staff_user_id': staff_user.pk,
                'staff_email': staff_user.email,
            },
            notify=notify,
        )
    except GrantError as e:
        raise PointsToolError(f'Punten toekennen mislukt: {e}')

    if not created:
        return {
            'points': grant.points, 'balance': _balance_of(member),
            'created': False, 'notified': False,
        }
    if grant.user_id != member.pk or grant.status != 'granted':
        # Defensive: identity resolution should be exact (see above), but this
        # moves real money — fail loudly rather than credit the wrong person.
        raise PointsToolError(
            'De punten konden niet aan dit lid gekoppeld worden. '
            'Controleer het account en probeer het opnieuw.'
        )

    balance = _balance_of(member)
    _log(
        staff_user, member,
        f'+{points} punten toegekend ("{reason}"). Nieuw saldo: {balance}.',
    )
    logger.info(
        f"Points tool: {staff_user.email} awarded {points} points to "
        f"{member.email} ({reason})"
    )
    return {
        'points': points, 'balance': balance, 'created': True,
        'notified': bool(notify),
    }


def set_balance(*, member, target, reason, staff_user, notify=False):
    """
    Set `member`'s balance to exactly `target`, writing the difference as an
    `adjusted` transaction. Returns {'delta', 'balance', 'previous'}.
    """
    reason = (reason or '').strip()
    if not reason:
        raise PointsToolError('Vul een reden in voor de correctie.')
    if not isinstance(target, int):
        raise PointsToolError('Vul een geldig saldo in.')
    if target < 0:
        raise PointsToolError(
            'Een saldo kan niet negatief zijn — vul 0 of hoger in.'
        )
    if abs(target) > MAX_POINTS:
        raise PointsToolError(f'Een saldo van meer dan {MAX_POINTS} punten kan niet.')

    from loyalty.services.points import LoyaltyService

    service = LoyaltyService()
    with transaction.atomic():
        # Locked read: the delta must be computed from the balance nobody else
        # can change until we have written the correction.
        balance = service._get_locked_balance(member)
        previous = balance.balance
        delta = target - previous
        if delta == 0:
            raise PointsToolError(
                f'Het saldo is al {target} punten — er is niets te wijzigen.'
            )
        if previous + delta < 0:  # pragma: no cover - target >= 0 guards this
            raise PointsToolError(
                'Deze correctie zou het saldo negatief maken en is geweigerd.'
            )

        # `adjust_points` owns the arithmetic (delta on balance AND on
        # lifetime_earned, never lifetime_spent).
        service.adjust_points(member, delta, f'Saldocorrectie: {reason}'[:500])
        _log(
            staff_user, member,
            f'Saldo ingesteld op {target} punten (was {previous}, '
            f'verschil {delta:+d}) — "{reason}".',
        )

    if notify:
        _notify_correction(member, target, reason)

    logger.info(
        f"Points tool: {staff_user.email} set {member.email} balance to "
        f"{target} (was {previous}, delta {delta:+d}): {reason}"
    )
    return {'delta': delta, 'balance': target, 'previous': previous}


def correction_notification_text(target, reason):
    """(title, body) for the set-mode notification — mirrors
    `grants.grant_notification_text` so both modes can preview their copy."""
    return (
        'Je puntensaldo is bijgewerkt',
        f'Je saldo staat nu op {target} punten ({reason}).',
    )


def _notify_correction(member, target, reason):
    """In-app notification for a corrected balance; never raises.

    Kind `announcement` with no email-policy override: by explicit decision
    this tool is in-app only.
    """
    try:
        from notifications.services import send_notification

        title, body = correction_notification_text(target, reason)
        send_notification(
            member,
            kind='announcement',
            title=title,
            body=body,
            data={'url': '/loyalty'},
            dedupe_key=f'pointstool:correction:{member.pk}:{new_action_token()}',
        )
    except Exception as e:
        logger.error(
            f"Points tool correction notification failed for {member.email}: {e}",
            exc_info=True,
        )


def _balance_of(member):
    from loyalty.models import PointsBalance

    row = PointsBalance.objects.filter(user=member).first()
    return row.balance if row else 0


def member_snapshot(member):
    """Balance figures + Shopify link state for the member card."""
    from loyalty.models import PointsBalance

    balance = PointsBalance.objects.filter(user=member).first()
    current = balance.balance if balance else 0
    return {
        'balance': current,
        'balance_euro': format_euro(points_to_euro(current, euro_per_point())),
        'lifetime_earned': balance.lifetime_earned if balance else 0,
        'lifetime_spent': balance.lifetime_spent if balance else 0,
        'shopify_customer_id': member.shopify_customer_id or '',
        'has_shopify': bool(member.shopify_customer_id),
    }


def recent_actions(limit=20):
    """The tool's own last actions, newest first — mistakes stay visible."""
    return list(
        LogEntry.objects.filter(change_message__startswith=LOG_PREFIX)
        .select_related('user')
        .order_by('-action_time')[:limit]
    )
