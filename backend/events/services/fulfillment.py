"""
Prize fulfillment for livestream raffles and auctions: create the prize as
an UNLISTED Shopify product, then put it on each winner's (draft) order.

Same discipline as the pickup app's Shopify sync: every outcome lands in a
status field with the error text stored on the row, every step is an
idempotent retry (re-clicking a failed button is the recovery path), and a
Shopify hiccup can never 500 the regie page. All functions return a dict:
{'ok': True, ...} or {'error': '<human-readable NL message>'}.

Works on ended events — fulfillment is explicitly a post-stream activity
(event 3 is processed through this after the fact).
"""
import logging

from django.utils import timezone

from users.services.shopify import ShopifyService

from ..models import AuctionItem, Raffle, RaffleWinner

logger = logging.getLogger(__name__)

# A winner counts as "verwerkt" in the regie progress line once the prize
# is on an order (or explicitly handled). 'failed'/'pending' need attention.
PROCESSED_STATUSES = {'draft_created', 'added_to_order', 'invoice_sent', 'fulfilled'}


def _prize_price(obj):
    """What the winner pays: the raffle's winner_price (None/empty = free
    prize = €0 product) or the auction's winning bid."""
    if isinstance(obj, Raffle):
        return obj.winner_price or 0
    return obj.final_price or 0


def ensure_prize_product(obj):
    """Create (or reuse) the UNLISTED Shopify product for a Raffle or a sold
    AuctionItem and store the gids on the row. Idempotent: stored gids mean
    the product exists and the call is skipped (the service's title-reuse
    search is the second guard underneath).
    """
    if obj.shopify_product_gid and obj.shopify_variant_gid:
        return {'ok': True, 'skipped': True}

    if isinstance(obj, Raffle):
        if obj.fulfillment_type != 'shopify':
            return {'error': (
                f"'{obj.prize_name}' heeft afhandeling "
                f"'{obj.get_fulfillment_type_display()}' — geen Shopify-product nodig."
            )}
        quantity = obj.winners.count()
        if not quantity:
            return {'error': f"'{obj.prize_name}' heeft nog geen winnaars."}
        title = obj.prize_name
        description = None
        image_url = None
    else:
        if obj.status != 'sold':
            return {'error': f"'{obj.title}' is nog niet verkocht."}
        quantity = 1
        title = obj.title
        parts = [p for p in [obj.brewery, obj.size] if p]
        description = ' · '.join(parts) if parts else None
        if obj.description:
            description = f'{obj.description}\n{description}' if description else obj.description
        image_url = obj.image_url or None

    try:
        result = ShopifyService().create_unlisted_product(
            title=title,
            price=_prize_price(obj),
            quantity=quantity,
            description=description,
            image_url=image_url,
        )
    except Exception as e:
        logger.error(f'Prize product creation crashed for {obj!r}: {e}',
                     exc_info=True)
        result = None
    if not result:
        return {'error': f"Shopify-product aanmaken mislukt voor '{title}'."}

    obj.shopify_product_gid = result['product_gid']
    obj.shopify_variant_gid = result['variant_gid']
    obj.save(update_fields=['shopify_product_gid', 'shopify_variant_gid'])
    logger.info(
        f"Prize product ready for '{title}': {result['product_gid']} "
        f"(reused={result.get('reused')})"
    )
    return {'ok': True, 'reused': result.get('reused', False)}


def _target_parts(target):
    """(user, variant_gid, prize_title) for a RaffleWinner or AuctionItem."""
    if isinstance(target, RaffleWinner):
        return target.user, target.raffle.shopify_variant_gid, target.raffle.prize_name
    return target.winner, target.shopify_variant_gid, target.title


def _store_failure(target, error):
    target.fulfillment_status = 'failed'
    target.fulfillment_error = error
    target.save(update_fields=['fulfillment_status', 'fulfillment_error'])
    return {'error': error}


def attach_to_winner(target):
    """Put the prize variant on the winner's open draft order (or a new
    one). `target` is a RaffleWinner or a sold AuctionItem. Failures land in
    fulfillment_status/fulfillment_error and are safe to retry.
    """
    user, variant_gid, title = _target_parts(target)
    if user is None:
        return {'error': f"'{title}' heeft geen winnaar."}
    if not variant_gid:
        return {'error': f"Maak eerst het Shopify-product aan voor '{title}'."}
    if not user.shopify_customer_id:
        return _store_failure(
            target, f'Geen Shopify-koppeling voor {user.email}.')

    try:
        result = ShopifyService().attach_variant_to_customer(
            user.shopify_customer_id, variant_gid)
    except Exception as e:
        logger.error(f'Prize attach crashed for {target!r}: {e}', exc_info=True)
        result = {'error': str(e)}
    if result.get('error'):
        return _store_failure(
            target,
            f"Toevoegen aan bestelling mislukt: {result['error']}",
        )

    target.fulfillment_status = (
        'draft_created' if result['action'] == 'draft_created'
        else 'added_to_order'
    )
    target.fulfillment_error = ''
    target.shopify_order_gid = result['draft_gid']
    target.save(update_fields=[
        'fulfillment_status', 'fulfillment_error', 'shopify_order_gid',
    ])
    logger.info(
        f"Prize '{title}' -> {user.email}: {result['action']} "
        f"({result['draft_gid']})"
    )
    return {'ok': True, 'status': target.fulfillment_status,
            'invoice_url': result.get('invoice_url')}


def send_invoice(target, custom_message=None):
    """Email the winner the pay link for their prize draft order. Only for
    priced prizes — a €0 draft needs no invoice. An invoice failure keeps
    the current status (the prize IS on the draft) and stores the error."""
    user, _, title = _target_parts(target)
    if not target.shopify_order_gid:
        return {'error': f"'{title}': nog geen draft order om te factureren."}

    try:
        result = ShopifyService().send_draft_invoice(
            target.shopify_order_gid, custom_message=custom_message)
    except Exception as e:
        logger.error(f'Prize invoice crashed for {target!r}: {e}', exc_info=True)
        result = None
    if not result:
        target.fulfillment_error = 'Factuur versturen mislukt.'
        target.save(update_fields=['fulfillment_error'])
        return {'error': f"Factuur versturen mislukt voor '{title}'."}

    target.fulfillment_status = 'invoice_sent'
    target.fulfillment_error = ''
    target.save(update_fields=['fulfillment_status', 'fulfillment_error'])
    logger.info(f"Prize invoice sent for '{title}' to {user and user.email}")
    return {'ok': True, 'invoice_url': result.get('invoice_url')}


def mark_fulfilled(target):
    """Manual 'afgehandeld' toggle — the terminal state for every
    fulfillment type (handed over / picked up / paid)."""
    target.fulfillment_status = 'fulfilled'
    target.fulfillment_error = ''
    target.fulfilled_at = timezone.now()
    target.save(update_fields=[
        'fulfillment_status', 'fulfillment_error', 'fulfilled_at',
    ])
    return {'ok': True}


def unmark_fulfilled(target):
    """Undo an accidental 'afgehandeld': back to the state the Shopify
    fields imply (on a draft already = draft_created, else pending)."""
    target.fulfillment_status = (
        'draft_created' if target.shopify_order_gid else 'pending'
    )
    target.fulfilled_at = None
    target.save(update_fields=['fulfillment_status', 'fulfilled_at'])
    return {'ok': True}


def fulfillment_progress(event):
    """(processed, total) prize units for the regie header. Points prizes
    are credited inside the draw itself, so they always count as processed;
    everything else counts once its status reaches PROCESSED_STATUSES."""
    processed = 0
    total = 0
    winners = (
        RaffleWinner.objects
        .filter(raffle__event=event)
        .select_related('raffle')
    )
    for winner in winners:
        total += 1
        if (winner.raffle.fulfillment_type == 'points'
                or winner.fulfillment_status in PROCESSED_STATUSES):
            processed += 1
    for item in event.auction_items.filter(status='sold'):
        total += 1
        if item.fulfillment_status in PROCESSED_STATUSES:
            processed += 1
    return processed, total
