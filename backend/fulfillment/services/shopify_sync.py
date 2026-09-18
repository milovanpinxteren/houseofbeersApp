"""
Outbound sync of pickup RSVPs to Shopify customer metafields.

Shopify is the source of truth for the warehouse queue: hob (the
houseofbeers_whatsapp app) reads `custom.queue` / `custom.priority` straight
from the Shopify customer, so the app writes those metafields DIRECTLY.
This replaced the old HMAC HTTP push to hob (hob_sync) — that endpoint no
longer exists.

Semantics are read-modify-write and idempotent:

- rsvp:   queue -> 'Afhalen' (only if different), priority ->
          max(current, 80) (only if different — an existing HIGHER priority
          is never lowered).
- cancel: ONLY when the user has no other active upcoming RSVP (a member
          coming both Friday and Saturday who de-selects Friday must stay in
          the queue for Saturday). Then: delete the queue metafield only if
          it is still exactly 'Afhalen', delete the priority metafield only
          if it is still exactly 80 — a staff-set queue or priority is never
          touched.

A repeat call after success performs zero writes and still reports success.
"""
import logging

from django.utils import timezone

from users.services.shopify import ShopifyService

logger = logging.getLogger(__name__)

# The queue value a pickup RSVP puts the customer in. This choice must exist
# in the Shopify customer-metafield definition for custom.queue (it is a
# constrained-choice definition) or the write may be rejected.
PICKUP_QUEUE = 'Afhalen'

# hob treats a Shopify priority > 50 as manually set and keeps it; a value
# <= 50 or an absent metafield makes hob auto-recalculate. Cancel therefore
# DELETES the metafield (back to auto) rather than writing a low number.
PICKUP_PRIORITY = 80

QUEUE_KEY = 'queue'
PRIORITY_KEY = 'priority'
QUEUE_TYPE = 'single_line_text_field'
PRIORITY_TYPE = 'number_integer'

# Stored response texts are capped so the log table cannot bloat.
MAX_RESPONSE_CHARS = 2000


def _customer_id(user):
    """The user's Shopify customer id as an int, or None when unlinked."""
    if not user.shopify_customer_id:
        return None
    try:
        return int(user.shopify_customer_id)
    except (TypeError, ValueError):
        return None


def _has_other_active_rsvps(user):
    """
    True while the user still has an active RSVP for today or later. Past
    dates don't count: an RSVP whose day has passed is spent, and per the
    no-automation rule its queue entry is staff's to clear — it should not
    keep a fresh cancel from reverting Shopify. (The row being cancelled
    was already flipped to 'cancelled' by the view before dispatch, so no
    exclusion is needed here.)
    """
    from fulfillment.models import PickupRSVP

    return PickupRSVP.objects.filter(
        user=user,
        status=PickupRSVP.STATUS_ACTIVE,
        date__gte=timezone.localdate(),
    ).exists()


def push_pickup_action(log) -> tuple:
    """
    Apply one PickupActionLog row to the customer's Shopify queue/priority
    metafields. Returns (sync_status, response_text) where sync_status is
    'success' | 'failed' | 'skipped'. Never raises: the caller (the Celery
    task) decides whether a failure is worth a retry.
    """
    try:
        return _push_pickup_action(log)
    except Exception as e:  # a sync bug must never break the RSVP flow
        logger.exception(f"Shopify pickup sync crashed for log {log.id}")
        return 'failed', f'Unexpected error: {e}'[:MAX_RESPONSE_CHARS]


def _push_pickup_action(log) -> tuple:
    customer_id = _customer_id(log.user)
    if customer_id is None:
        return (
            'skipped',
            'No linked Shopify customer (shopify_customer_id empty or '
            'non-numeric); nothing to sync.',
        )

    if log.action == 'cancel' and _has_other_active_rsvps(log.user):
        return (
            'success',
            f'Customer {customer_id}: other active RSVPs remain, '
            f'Shopify untouched',
        )

    service = ShopifyService()

    # Read current values first. A None here is either a transient Shopify
    # hiccup or a deleted customer — either way 'failed', so the task
    # retries instead of silently dropping the update.
    current = service.get_customer_queue_priority(customer_id)
    if current is None:
        return (
            'failed',
            f'Could not read queue/priority for customer {customer_id} '
            f'(Shopify error or customer not found)',
        )

    queue = current.get('queue')
    priority = current.get('priority')
    changes = []

    if log.action == 'rsvp':
        if queue != PICKUP_QUEUE:
            if service.set_customer_metafield(
                customer_id, QUEUE_KEY, PICKUP_QUEUE, QUEUE_TYPE,
            ) is None:
                return (
                    'failed',
                    f"Setting queue='{PICKUP_QUEUE}' failed for "
                    f'customer {customer_id}',
                )
            changes.append(f"queue {queue!r} -> '{PICKUP_QUEUE}'")

        target_priority = max(priority or 0, PICKUP_PRIORITY)
        if target_priority != priority:
            if service.set_customer_metafield(
                customer_id, PRIORITY_KEY, str(target_priority), PRIORITY_TYPE,
            ) is None:
                return (
                    'failed',
                    f'Setting priority={target_priority} failed for '
                    f'customer {customer_id}',
                )
            changes.append(f'priority {priority} -> {target_priority}')

    else:  # cancel: revert ONLY our own values, never a staff-set one
        if queue == PICKUP_QUEUE:
            if not service.delete_customer_metafield(customer_id, QUEUE_KEY):
                return (
                    'failed',
                    f'Deleting queue metafield failed for customer {customer_id}',
                )
            changes.append(f"queue '{PICKUP_QUEUE}' removed")
        if priority == PICKUP_PRIORITY:
            if not service.delete_customer_metafield(customer_id, PRIORITY_KEY):
                return (
                    'failed',
                    f'Deleting priority metafield failed for '
                    f'customer {customer_id}',
                )
            changes.append(f'priority {PICKUP_PRIORITY} removed')

    if changes:
        text = f"Customer {customer_id}: {'; '.join(changes)}"
    else:
        text = f'Customer {customer_id}: already in sync, no writes needed'
    return 'success', text[:MAX_RESPONSE_CHARS]
