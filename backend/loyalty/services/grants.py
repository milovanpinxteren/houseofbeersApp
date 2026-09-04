"""
Service grants: points awarded by trusted external systems (hob).

The flow mirrors campaign qualification (`fire_qualification`): a
unique-constrained row (`ServiceGrant.dedupe_key`) is the idempotency guard,
the points land as an `earned` PointsTransaction with `rule=None` and an
empty `shopify_order_id` — the shape every sync tier and the
repair_loyalty_history invariant already preserve — and the notification goes
through the notifications outbox, best-effort.

A grant whose identity matches no member is stored `pending` and claimed
automatically by `claim_pending_grants(user)`, hooked into registration and
Shopify linking.
"""
import logging

from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

logger = logging.getLogger(__name__)

# Sanity ceiling so a typo in an admin chat message ("1000000 punten") cannot
# nuke the ledger. Deliberately generous; raise it if a real action needs to.
MAX_GRANT_POINTS = 100_000


class GrantError(Exception):
    """Validation/resolution error safe to expose to the (trusted) caller."""


def resolve_user(shopify_customer_id='', email=''):
    """
    Find the member a grant belongs to. Returns a User or None (no match).

    Raises GrantError on an AMBIGUOUS match — two users sharing a Shopify
    customer id (the field is not unique) or a legacy case-duplicate email
    pair. Granting to the wrong person silently is worse than failing loudly.
    """
    from users.models import User

    if shopify_customer_id:
        matches = list(User.objects.filter(
            shopify_customer_id=str(shopify_customer_id)
        )[:2])
        if len(matches) > 1:
            raise GrantError(
                f"shopify_customer_id {shopify_customer_id} matches multiple users"
            )
        if matches:
            return matches[0]

    if email:
        try:
            return User.objects.get_by_natural_key(email)
        except User.DoesNotExist:
            pass
        except User.MultipleObjectsReturned:
            raise GrantError(f"email {email} matches multiple users")

    return None


def create_grant(*, dedupe_key, points, reason, source='hob',
                 shopify_customer_id='', email='', phone='',
                 context=None, notify=True):
    """
    Create (or return the existing) grant for this dedupe_key.

    Returns (grant, created). When a member matches, the points are awarded
    immediately; otherwise the grant is stored `pending`.
    """
    from loyalty.models import ServiceGrant

    dedupe_key = (dedupe_key or '').strip()
    reason = (reason or '').strip()
    if not dedupe_key:
        raise GrantError("dedupe_key is required")
    if len(dedupe_key) > 255:
        raise GrantError("dedupe_key too long (max 255)")
    if not reason:
        raise GrantError("reason is required")
    if not isinstance(points, int) or isinstance(points, bool):
        raise GrantError("points must be an integer")
    if points < 1 or points > MAX_GRANT_POINTS:
        raise GrantError(f"points must be between 1 and {MAX_GRANT_POINTS}")
    if not (shopify_customer_id or email or phone):
        raise GrantError(
            "at least one of shopify_customer_id, email, phone is required"
        )

    existing = ServiceGrant.objects.filter(dedupe_key=dedupe_key).first()
    if existing:
        return existing, False

    # Resolve BEFORE creating the row: an ambiguous identity must fail the
    # request, not park an unclaimable pending grant.
    user = resolve_user(shopify_customer_id=shopify_customer_id, email=email)

    try:
        with transaction.atomic():
            grant = ServiceGrant.objects.create(
                dedupe_key=dedupe_key,
                source=source or 'hob',
                points=points,
                reason=reason[:255],
                context=context,
                shopify_customer_id=str(shopify_customer_id or ''),
                email=(email or '').strip().lower(),
                phone=(phone or '').strip(),
                notify=notify,
                status='pending',
            )
            if user:
                _fulfil_grant(grant, user)
    except IntegrityError:
        # Concurrent request with the same dedupe_key won the race.
        return ServiceGrant.objects.get(dedupe_key=dedupe_key), False

    if user:
        _notify_grant(grant)
    return grant, True


def _fulfil_grant(grant, user):
    """
    Award the points and flip the grant to granted. Caller must hold a
    transaction; the balance row is locked so a concurrent sync/redeem
    cannot lose the read-modify-write.
    """
    from loyalty.models import PointsBalance, PointsTransaction

    balance, _ = PointsBalance.objects.select_for_update().get_or_create(user=user)
    balance.balance += grant.points
    # lifetime_spent only tracks reward redemptions; everything else lands in
    # lifetime_earned (same rule as adjustments and campaign awards), keeping
    # balance == lifetime_earned - lifetime_spent intact.
    balance.lifetime_earned += grant.points
    balance.save()

    # `earned` with rule=None and NO shopify_order_id: rendered verbatim by
    # the app (description fallback), never touched by full sync's
    # check-and-correct, counted by repair_loyalty_history's earned_total.
    # `rule_name` in the breakdown is what the mobile expander displays.
    txn = PointsTransaction.objects.create(
        user=user,
        transaction_type='earned',
        points=grant.points,
        balance_after=balance.balance,
        description=grant.reason,
        breakdown=[{
            'grant_id': grant.id,
            'source': grant.source,
            'rule_name': grant.reason,
            'points': grant.points,
        }],
    )

    grant.user = user
    grant.transaction = txn
    grant.status = 'granted'
    grant.granted_at = timezone.now()
    grant.save(update_fields=['user', 'transaction', 'status', 'granted_at'])
    logger.info(
        f"Service grant {grant.dedupe_key}: {grant.points} points to "
        f"{user.email} ({grant.reason})"
    )


def grant_notification_text(points, reason):
    """
    (title, body) of the grant notification.

    Public so a UI that awards points can show staff the EXACT text the member
    will read before they confirm — a preview that guesses at the copy is a
    preview that goes stale.
    """
    return 'Je hebt punten gekregen!', f'{points} punten: {reason}'


def _notify_grant(grant):
    """In-app notification via the outbox; never raises."""
    if not grant.notify or not grant.user:
        return
    try:
        # Imported here, not at module level, so loyalty does not hard-depend
        # on the notifications app at import time.
        from notifications.services import send_notification

        title, body = grant_notification_text(grant.points, grant.reason)
        delivery = send_notification(
            grant.user,
            kind='announcement',
            title=title,
            body=body,
            data={'url': '/loyalty'},
            dedupe_key=f'grant:{grant.dedupe_key}',
        )
        delivery_id = getattr(delivery, 'id', None)
        if delivery_id:
            grant.notified_delivery_id = delivery_id
            grant.save(update_fields=['notified_delivery_id'])
    except Exception as e:
        logger.error(
            f"Grant notification failed for {grant.dedupe_key}: {e}",
            exc_info=True,
        )


def claim_pending_grants(user):
    """
    Fulfil every pending grant matching this user's shopify_customer_id or
    email. Called after registration and after Shopify linking; safe to call
    repeatedly. Returns the number of grants claimed.
    """
    from loyalty.models import ServiceGrant

    identity = Q()
    if user.shopify_customer_id:
        identity |= Q(shopify_customer_id=str(user.shopify_customer_id))
    if user.email:
        identity |= Q(email__iexact=user.email)
    if not identity:
        return 0

    claimed = 0
    pending_ids = list(
        ServiceGrant.objects.filter(identity, status='pending')
        .values_list('id', flat=True)
    )
    for grant_id in pending_ids:
        try:
            with transaction.atomic():
                grant = (
                    ServiceGrant.objects.select_for_update()
                    .get(pk=grant_id)
                )
                if grant.status != 'pending':
                    continue
                _fulfil_grant(grant, user)
            _notify_grant(grant)
            claimed += 1
        except Exception as e:
            logger.error(
                f"Claiming pending grant {grant_id} for {user.email} "
                f"failed: {e}",
                exc_info=True,
            )
    if claimed:
        logger.info(f"Claimed {claimed} pending grant(s) for {user.email}")
    return claimed


def revoke_grant(dedupe_key, reason=''):
    """
    Undo a grant. Pending grants are simply marked revoked; granted ones get
    a compensating negative `earned` transaction. Idempotent — revoking an
    already-revoked grant returns it unchanged.
    """
    from loyalty.models import PointsBalance, PointsTransaction, ServiceGrant

    with transaction.atomic():
        try:
            grant = (
                ServiceGrant.objects.select_for_update().get(dedupe_key=dedupe_key)
            )
        except ServiceGrant.DoesNotExist:
            raise GrantError(f"no grant with dedupe_key {dedupe_key}")

        if grant.status == 'revoked':
            return grant

        if grant.status == 'granted' and grant.user:
            balance, _ = (
                PointsBalance.objects.select_for_update()
                .get_or_create(user=grant.user)
            )
            balance.balance -= grant.points
            balance.lifetime_earned -= grant.points
            balance.save()
            description = f"Teruggedraaid: {grant.reason}"
            if reason:
                description = f"{description} ({reason})"
            PointsTransaction.objects.create(
                user=grant.user,
                transaction_type='earned',
                points=-grant.points,
                balance_after=balance.balance,
                description=description[:500],
                breakdown=[{
                    'grant_id': grant.id,
                    'source': grant.source,
                    'rule_name': description[:255],
                    'points': -grant.points,
                }],
            )

        grant.status = 'revoked'
        grant.revoked_at = timezone.now()
        grant.save(update_fields=['status', 'revoked_at'])
        logger.info(f"Service grant {dedupe_key} revoked ({reason or 'no reason'})")
        return grant
