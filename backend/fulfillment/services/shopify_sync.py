"""
Outbound sync of pickup RSVPs to Shopify customer metafields.

Shopify is the source of truth for the warehouse queue: hob (the
houseofbeers_whatsapp app) reads `custom.queue` / `custom.priority` straight
from the Shopify customer, so the app writes those metafields DIRECTLY.
This replaced the old HMAC HTTP push to hob (hob_sync) — that endpoint no
longer exists.

Because staff (via hob) also set queue/priority, the values that were there
BEFORE an RSVP are preserved in a single-slot snapshot metafield,
`custom.pickup_prior` (JSON: {"queue", "priority", "captured_at"}), living
on the Shopify customer so BOTH systems can restore from it:

- the app restores it when the user cancels their last upcoming RSVP;
- hob restores the prior priority when staff move the customer out of the
  Afhalen queue after the pickup (see hob's update_customer_queue).

Its presence means "the app's values are applied on this customer"; restore
deletes it. It never accumulates history — one object or absent.

Semantics are read-modify-write and idempotent:

- rsvp:   capture `pickup_prior` FIRST when absent (so retries can never
          record our own values as "prior"), then queue -> 'Afhalen' (only
          if different) and priority -> max(current, 80) (only if different
          — an existing HIGHER priority is never lowered).
- cancel: ONLY when the user has no other active upcoming RSVP (a member
          coming both Friday and Saturday who de-selects Friday must stay in
          the queue for Saturday). Then restore the snapshot per field,
          each behind a staleness check: queue is restored only if still
          exactly 'Afhalen', priority only if still exactly 80 — a value
          staff changed in the meantime is never touched. Finally the
          snapshot itself is deleted. Without a snapshot (cycle started
          before this feature existed) our own values are simply deleted.

A repeat call after success performs zero writes and still reports success.
"""
import json
import logging

from django.utils import timezone

from users.services.shopify import ShopifyService

logger = logging.getLogger(__name__)

# The queue value a pickup RSVP puts the customer in. This choice should
# exist in the Shopify customer-metafield definition for custom.queue so it
# shows up in hob's queue-filter dropdown (the write itself is not
# choice-validated — verified live 2026-09-18).
PICKUP_QUEUE = 'Afhalen'

# hob treats a Shopify priority > 50 as manually set and keeps it; a value
# <= 50 or an absent metafield makes hob auto-recalculate. Restore therefore
# DELETES the metafield when the snapshot recorded no prior priority.
PICKUP_PRIORITY = 80

QUEUE_KEY = 'queue'
PRIORITY_KEY = 'priority'
PRIOR_KEY = 'pickup_prior'
QUEUE_TYPE = 'single_line_text_field'
PRIORITY_TYPE = 'number_integer'
PRIOR_TYPE = 'json'

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
    current = service.get_customer_pickup_state(customer_id)
    if current is None:
        return (
            'failed',
            f'Could not read pickup state for customer {customer_id} '
            f'(Shopify error or customer not found)',
        )

    if log.action == 'rsvp':
        return _apply_rsvp(service, customer_id, current)
    return _apply_cancel(service, customer_id, current)


def _apply_rsvp(service, customer_id, current) -> tuple:
    queue = current.get('queue')
    priority = current.get('priority')
    prior = current.get('pickup_prior')
    changes = []

    # Capture the snapshot BEFORE any write: a retry after a partial write
    # then finds the snapshot already present and never records our own
    # 'Afhalen'/80 as "prior". An existing snapshot (second date, retry, or
    # an unfinished earlier cycle) is kept — it is the true pre-pickup state.
    if prior is None:
        snapshot = {
            'queue': queue,
            'priority': priority,
            'captured_at': timezone.now().isoformat(),
        }
        if service.set_customer_metafield(
            customer_id, PRIOR_KEY, json.dumps(snapshot), PRIOR_TYPE,
        ) is None:
            return (
                'failed',
                f'Capturing pickup_prior failed for customer {customer_id}',
            )
        changes.append(
            f'captured prior (queue={queue!r}, priority={priority})'
        )

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

    return _summary(customer_id, changes)


def _apply_cancel(service, customer_id, current) -> tuple:
    queue = current.get('queue')
    priority = current.get('priority')
    prior = current.get('pickup_prior')
    changes = []

    # Restore per field, each only when the current value is still exactly
    # ours — a value staff changed mid-RSVP wins. Without a snapshot
    # (pre-snapshot cycles) restoring degrades to deleting our own values.
    prior_queue = (prior or {}).get('queue') or None
    prior_priority = (prior or {}).get('priority')
    if not isinstance(prior_priority, int):
        prior_priority = None

    if queue == PICKUP_QUEUE:
        if prior_queue:
            ok = service.set_customer_metafield(
                customer_id, QUEUE_KEY, prior_queue, QUEUE_TYPE,
            ) is not None
            desc = f"queue restored to {prior_queue!r}"
        else:
            ok = service.delete_customer_metafield(customer_id, QUEUE_KEY)
            desc = f"queue '{PICKUP_QUEUE}' removed"
        if not ok:
            return (
                'failed',
                f'Restoring queue failed for customer {customer_id}',
            )
        changes.append(desc)

    if priority == PICKUP_PRIORITY:
        if prior_priority is not None:
            ok = service.set_customer_metafield(
                customer_id, PRIORITY_KEY, str(prior_priority), PRIORITY_TYPE,
            ) is not None
            desc = f'priority restored to {prior_priority}'
        else:
            ok = service.delete_customer_metafield(customer_id, PRIORITY_KEY)
            desc = f'priority {PICKUP_PRIORITY} removed'
        if not ok:
            return (
                'failed',
                f'Restoring priority failed for customer {customer_id}',
            )
        changes.append(desc)

    # Drop the snapshot last: if a restore above failed we returned 'failed'
    # with the snapshot intact, so the retry can finish the job.
    if prior is not None:
        if not service.delete_customer_metafield(customer_id, PRIOR_KEY):
            return (
                'failed',
                f'Deleting pickup_prior failed for customer {customer_id}',
            )
        changes.append('prior snapshot dropped')

    return _summary(customer_id, changes)


def _summary(customer_id, changes) -> tuple:
    if changes:
        text = f"Customer {customer_id}: {'; '.join(changes)}"
    else:
        text = f'Customer {customer_id}: already in sync, no writes needed'
    return 'success', text[:MAX_RESPONSE_CHARS]
