"""
Payment tracking for livestream prize/auction draft orders: did the winner
actually pay?

Fulfillment (services/fulfillment.py) puts the prize on a Shopify DRAFT
order and emails the invoice — after that the app used to go blind. This
module asks Shopify what became of each draft and lands the answer in
payment_status/paid_at on the RaffleWinner/AuctionItem row.

The status mapping deliberately mirrors hob's sync_draft_order_status
(houseofbeers_whatsapp, apps/integrations/shopify/orders.py) so both
systems speak the same paid/invoiced/pending/cancelled vocabulary:

- draft gone (deleted in Shopify admin)       -> cancelled
- draft converted to an order:
    PAID / PARTIALLY_PAID                     -> paid (paid_at = order date)
    REFUNDED / PARTIALLY_REFUNDED             -> paid (money DID arrive)
    VOIDED                                    -> cancelled
    anything else (PENDING, AUTHORIZED, ...)  -> invoiced
- no order yet: INVOICE_SENT -> invoiced, COMPLETED -> paid, else pending

Same discipline as fulfillment.py: best effort per target, a Shopify
hiccup skips that row and never breaks the sweep, and everything is safe
to re-run (paid/cancelled rows are simply no longer selected).
"""
import logging

from django.utils import timezone
from django.utils.dateparse import parse_datetime

from users.services.shopify import ShopifyService

from ..models import AuctionItem, RaffleWinner

logger = logging.getLogger(__name__)

# Rows in these states still need watching; paid/cancelled are terminal.
OPEN_PAYMENT_STATUSES = ('pending', 'invoiced')

_PAID = {'PAID', 'PARTIALLY_PAID', 'REFUNDED', 'PARTIALLY_REFUNDED'}


def payment_targets(event=None):
    """All rows whose draft order still needs a payment check: priced
    prizes/auction wins that are on a draft and not yet paid/cancelled.
    €0 prizes never enter payment tracking — there is nothing to pay."""
    winners = (
        RaffleWinner.objects
        .filter(
            payment_status__in=OPEN_PAYMENT_STATUSES,
            raffle__fulfillment_type='shopify',
            raffle__winner_price__gt=0,
        )
        .exclude(shopify_order_gid='')
        .select_related('raffle', 'user')
    )
    items = (
        AuctionItem.objects
        .filter(
            payment_status__in=OPEN_PAYMENT_STATUSES,
            status='sold',
            final_price__gt=0,
        )
        .exclude(shopify_order_gid='')
        .select_related('winner')
    )
    if event is not None:
        winners = winners.filter(raffle__event=event)
        items = items.filter(event=event)
    return list(winners) + list(items)


def check_payment(target, service=None):
    """Refresh one row's payment_status from Shopify. Returns
    {'ok': True, 'status': <new>, 'changed': bool} or {'error': ...}
    (transport failure — nothing was written)."""
    service = service or ShopifyService()
    state = service.get_draft_order_payment_state(target.shopify_order_gid)
    if state is None:
        return {'error': 'Shopify-lookup mislukt'}

    old_status = target.payment_status
    order = state.get('order')
    if not state.get('found'):
        # Draft deleted in the Shopify admin = staff called it off.
        target.payment_status = 'cancelled'
    elif order:
        financial = (order.get('financial_status') or '').upper()
        if financial in _PAID:
            target.payment_status = 'paid'
            if not target.paid_at:
                target.paid_at = (
                    parse_datetime(order.get('created_at') or '')
                    or timezone.now()
                )
        elif financial == 'VOIDED':
            target.payment_status = 'cancelled'
        else:
            # An order exists but the money isn't in yet (PENDING etc.) —
            # from our side that is "invoice out, waiting".
            target.payment_status = 'invoiced'
        target.shopify_final_order_gid = order.get('order_gid') or ''
        target.shopify_final_order_name = order.get('name') or ''
    else:
        draft_status = state.get('status')
        if draft_status == 'INVOICE_SENT':
            target.payment_status = 'invoiced'
        elif draft_status == 'COMPLETED':
            # Completed without a visible order (e.g. marked as paid by
            # staff) — the draft is settled.
            target.payment_status = 'paid'
            if not target.paid_at:
                target.paid_at = timezone.now()
        else:
            target.payment_status = 'pending'

    target.payment_checked_at = timezone.now()
    target.save(update_fields=[
        'payment_status', 'paid_at', 'payment_checked_at',
        'shopify_final_order_gid', 'shopify_final_order_name',
    ])
    changed = target.payment_status != old_status
    if changed:
        logger.info(
            f'Prize payment {old_status} -> {target.payment_status} '
            f'for {target!r} (draft {target.shopify_order_gid})'
        )
    return {'ok': True, 'status': target.payment_status, 'changed': changed}


def sweep_payments(event=None):
    """Check every open payment target (optionally one event's). Returns a
    summary dict for the regie message / task log."""
    targets = payment_targets(event)
    summary = {'checked': 0, 'paid': 0, 'changed': 0, 'failed': 0}
    if not targets:
        return summary
    service = ShopifyService()
    for target in targets:
        try:
            result = check_payment(target, service=service)
        except Exception as e:  # one bad row must not kill the sweep
            logger.error(f'Payment check crashed for {target!r}: {e}',
                         exc_info=True)
            result = {'error': str(e)}
        if result.get('error'):
            summary['failed'] += 1
            continue
        summary['checked'] += 1
        if result['changed']:
            summary['changed'] += 1
        if result['status'] == 'paid':
            summary['paid'] += 1
    return summary
