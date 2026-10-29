"""
Missed items: per-(sale, customer) snapshots pushed by hob.

Mirrors the loyalty service-grant flow (loyalty/services/grants.py) with one
deliberate difference in identity resolution: an AMBIGUOUS match (two users
sharing a Shopify customer id) leaves the record unresolved instead of
failing the push. A grant moves money, so granting to the wrong person
silently is worse than failing loudly; a missed-items snapshot is pure
display, so losing it over a duplicate account would be the worse outcome —
it stays `pending` and is logged.

A record whose identity matches no member is claimed automatically by
`claim_pending_missed(user)`, hooked into registration and Shopify linking
right next to `claim_pending_grants`.
"""
import logging
from datetime import date

from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils.dateparse import parse_datetime

logger = logging.getLogger(__name__)

# The inbound reasons hob sends today. Unknown reasons are stored verbatim
# rather than rejected — a new hob reason must not drop snapshots on the
# floor while the two sides deploy independently.
KNOWN_REASONS = ('out_of_stock', 'max_per_customer', 'unavailable')


class MissedItemsError(Exception):
    """Validation error safe to expose to the (trusted) caller."""


def _resolve_user(shopify_customer_id='', email=''):
    """
    Find the member a snapshot belongs to. Returns a User or None.

    Unlike grants' resolve_user this NEVER raises on ambiguity: multiple
    users sharing the Shopify id (the field is not unique) just means
    "unresolved" — logged so the duplicate can be cleaned up, but the push
    itself must succeed.
    """
    from users.models import User

    if shopify_customer_id:
        matches = list(User.objects.filter(
            shopify_customer_id=str(shopify_customer_id)
        )[:2])
        if len(matches) > 1:
            logger.warning(
                f"Missed-items: shopify_customer_id {shopify_customer_id} "
                f"matches multiple users — leaving record unresolved"
            )
            return None
        if matches:
            return matches[0]

    if email:
        try:
            return User.objects.get_by_natural_key(email)
        except User.DoesNotExist:
            pass
        except User.MultipleObjectsReturned:
            logger.warning(
                f"Missed-items: email {email} matches multiple users — "
                f"leaving record unresolved"
            )

    return None


def _validated_fields(payload):
    """Field dict for update_or_create, or raise MissedItemsError."""
    if not isinstance(payload, dict):
        raise MissedItemsError("payload must be a JSON object")

    dedupe_key = str(payload.get('dedupe_key') or '').strip()
    if not dedupe_key:
        raise MissedItemsError("dedupe_key is required")
    if len(dedupe_key) > 120:
        raise MissedItemsError("dedupe_key too long (max 120)")

    sale = payload.get('sale')
    if not isinstance(sale, dict):
        raise MissedItemsError("sale must be an object")
    try:
        sale_id = int(sale.get('id'))
    except (TypeError, ValueError):
        raise MissedItemsError("sale.id must be an integer")
    try:
        sale_date = date.fromisoformat(str(sale.get('date') or '')[:10])
    except ValueError:
        raise MissedItemsError("sale.date must be an ISO date (YYYY-MM-DD)")

    lines = payload.get('lines')
    if not isinstance(lines, list):
        raise MissedItemsError("lines must be a list")
    for line in lines:
        if not isinstance(line, dict):
            raise MissedItemsError("every line must be an object")

    pushed_at = None
    if payload.get('pushed_at'):
        pushed_at = parse_datetime(str(payload['pushed_at']))
        if pushed_at is None:
            raise MissedItemsError("pushed_at must be an ISO datetime")

    return {
        'dedupe_key': dedupe_key,
        'source': str(payload.get('source') or 'hob')[:50],
        'shopify_customer_id': str(payload.get('shopify_customer_id') or ''),
        'email': str(payload.get('email') or '').strip().lower(),
        'phone': str(payload.get('phone') or '').strip(),
        'sale_id': sale_id,
        'sale_name': str(sale.get('name') or '')[:100],
        'sale_date': sale_date,
        'draft_order_id': str(payload.get('draft_order_id') or '')[:64],
        'draft_order_name': str(payload.get('draft_order_name') or '')[:64],
        'shopify_order_id': str(payload.get('shopify_order_id') or '')[:64],
        'lines': lines,
        'pushed_at': pushed_at,
    }


def upsert_missed(payload):
    """
    Create or replace the record for this dedupe_key.

    Returns (record, created). A re-push replaces the lines and the
    draft/order ids wholesale (hob re-pushes after refulfilments), and an
    empty `lines` list means "cleared": the row stays as the idempotency
    guard but must stop appearing in the orders API.
    """
    from fulfillment.models import MissedItemsRecord

    fields = _validated_fields(payload)
    dedupe_key = fields.pop('dedupe_key')

    resolved = _resolve_user(
        shopify_customer_id=fields['shopify_customer_id'],
        email=fields['email'],
    )

    def _apply(fields, existing_user):
        # A previously attached record keeps its user even when this push's
        # identity no longer resolves (e.g. the member unlinked Shopify in
        # between) — the attachment was made on good evidence once.
        user = resolved or existing_user
        if not fields['lines']:
            status = 'cleared'
        else:
            status = 'attached' if user else 'pending'
        return {**fields, 'user': user, 'status': status}

    try:
        with transaction.atomic():
            existing = (
                MissedItemsRecord.objects.select_for_update()
                .filter(dedupe_key=dedupe_key)
                .first()
            )
            if existing:
                for key, value in _apply(fields, existing.user).items():
                    setattr(existing, key, value)
                existing.save()
                return existing, False
            record = MissedItemsRecord.objects.create(
                dedupe_key=dedupe_key, **_apply(fields, None)
            )
    except IntegrityError:
        # Concurrent request with the same dedupe_key won the race; apply
        # this push as the update it effectively is.
        with transaction.atomic():
            existing = (
                MissedItemsRecord.objects.select_for_update()
                .get(dedupe_key=dedupe_key)
            )
            for key, value in _apply(fields, existing.user).items():
                setattr(existing, key, value)
            existing.save()
            return existing, False

    logger.info(
        f"Missed-items record {dedupe_key} created "
        f"({len(record.lines)} line(s), {record.status})"
    )
    return record, True


def claim_pending_missed(user):
    """
    Attach every pending record matching this user's shopify_customer_id or
    email. Called after registration and after Shopify linking, and at the
    top of the orders view; safe to call repeatedly. Returns the number of
    records attached.
    """
    from fulfillment.models import MissedItemsRecord

    identity = Q()
    if user.shopify_customer_id:
        identity |= Q(shopify_customer_id=str(user.shopify_customer_id))
    if user.email:
        identity |= Q(email__iexact=user.email)
    if not identity:
        return 0

    claimed = (
        MissedItemsRecord.objects.filter(identity, status='pending')
        .update(user=user, status='attached')
    )
    if claimed:
        logger.info(
            f"Attached {claimed} pending missed-items record(s) to {user.email}"
        )
    return claimed
