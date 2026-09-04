"""Signup code redemption: flyer QR -> registration -> welcome bonus.

The bonus deliberately goes through loyalty's service-grant machinery
(`loyalty.services.grants.create_grant`) rather than writing its own
transaction: that helper already produces the one transaction shape the whole
ledger agrees on — `earned`, `rule=None`, NO `shopify_order_id` (a full sync
would delete a row that carries one), a breakdown whose `rule_name` is what
the app's history expander renders — and it updates the balance under
`select_for_update`. The grant's `dedupe_key` (`signup:<user_id>`) is what
makes the bonus at-most-once per user, forever.

The notification is ours rather than the grant's, so the copy can name the
flyer; kind `announcement`, no email policy override — this is an in-app
feature by explicit decision.
"""
import logging

from django.db import transaction
from django.utils import timezone

logger = logging.getLogger(__name__)


def resolve_signup_code(raw):
    """Look up a raw code. Returns (SignupCode|None, usable: bool)."""
    from users.models import SignupCode

    normalized = SignupCode.normalize(raw)
    if not normalized:
        return None, False

    code = SignupCode.objects.filter(code=normalized).first()
    if not code:
        return None, False
    usable, _ = code.check_usable()
    return code, usable


def attach_signup_code(user, raw):
    """
    Record the code this member arrived with. Returns the usable SignupCode
    or None.

    `signup_code_raw` is written unconditionally (attribution beats
    correctness here). The FK — which is also the max_uses meter — is only
    written when the code is redeemable, and the check plus the write happen
    under a row lock so two simultaneous registrations cannot both take the
    last slot of a capped code.
    """
    from users.models import SignupCode

    raw = (raw or '').strip()
    if not raw:
        return None

    user.signup_code_raw = raw[:64]
    normalized = SignupCode.normalize(raw)
    usable_code = None

    with transaction.atomic():
        code = (
            SignupCode.objects.select_for_update()
            .filter(code=normalized)
            .first()
        )
        if code:
            usable, reason = code.check_usable()
            if usable:
                user.signup_code = code
                usable_code = code
            else:
                logger.info(
                    f"Signup code {normalized} not usable for {user.email}: {reason}"
                )
        else:
            logger.info(f"Unknown signup code {normalized} used by {user.email}")

        user.save(update_fields=['signup_code', 'signup_code_raw'])

    return usable_code


def award_signup_bonus(user):
    """
    Award the welcome bonus for `user.signup_code`. Returns points awarded
    (0 when there is nothing to award).

    At most once per user, ever, enforced at the DB level: the user row is
    locked, `welcome_bonus_awarded_at` is checked AND set inside the same
    transaction as the points write (which locks the balance row in turn, see
    grants._fulfil_grant). A retried request, a double-submitted form or a
    future caller blocks on the lock and then finds the marker already set.
    The grant's unique `dedupe_key` is a second, independent guard.
    """
    from loyalty.services.grants import create_grant
    from users.models import User

    code = user.signup_code
    if not code or code.points < 1:
        return 0

    reason = f"Welkomstbonus: {code.label}"[:255]

    with transaction.atomic():
        locked = User.objects.select_for_update().get(pk=user.pk)
        if locked.welcome_bonus_awarded_at:
            logger.info(f"Signup bonus already awarded to {user.email}, skipping")
            return 0

        grant, created = create_grant(
            dedupe_key=f'signup:{user.id}',
            points=code.points,
            reason=reason,
            source='signup_code',
            email=user.email,
            context={'signup_code': code.code, 'signup_code_id': code.id},
            # We send our own notification below (after commit) so the copy
            # can name the flyer.
            notify=False,
        )

        if not created or grant.status != 'granted':
            # The grant existed already (a marker-less legacy award, or a
            # concurrent writer that beat us to the dedupe_key).
            return 0

        awarded_at = timezone.now()
        User.objects.filter(pk=user.pk).update(welcome_bonus_awarded_at=awarded_at)
        user.welcome_bonus_awarded_at = awarded_at

    # Network I/O after commit: a failing push must never undo the points.
    _notify_signup_bonus(user, code)
    logger.info(
        f"Signup bonus: {code.points} points to {user.email} via {code.code}"
    )
    return code.points


def _notify_signup_bonus(user, code):
    """In-app welcome notification via the outbox; never raises."""
    try:
        # Imported here so users does not hard-depend on the notifications app
        # at import time (same convention as loyalty's grant notification).
        from notifications.services import send_notification

        send_notification(
            user,
            kind='announcement',
            title='Welkom bij House of Beers!',
            body=(
                f'Je hebt {code.points} welkomstpunten gekregen '
                f'({code.label}). Proost!'
            ),
            data={'url': '/loyalty'},
            dedupe_key=f'signup:{user.id}',
        )
    except Exception as e:
        logger.error(
            f"Signup bonus notification failed for {user.email}: {e}",
            exc_info=True,
        )
