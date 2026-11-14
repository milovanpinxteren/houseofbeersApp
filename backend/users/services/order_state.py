"""
Line-item state derivation for the app's orders screen.

Pure (except for one warning log) so the business rules are testable as a
table: a line item ends up in exactly one of seven states —

    cancelled     the ORDER was cancelled or restocked — nothing is owed
    shipped       order line fulfilled by Shopify
    partial       order line partially fulfilled
    handled       the ORDER was archived in Shopify while this line was never
                  fulfilled: we are done with it, we just cannot say which
                  way it left (counter handover, merged shipment)
    in_warehouse  no ETA metafield (business rule: no ETA means the beer is
                  on the shelf), or an ETA that has passed — the ETA day
                  itself counts as arrived, matching hob's graduation rule
    incoming      ETA strictly in the future (a pre-order still underway)
    unknown       the metafield fetch failed for this product, or the
                  metafield held an unparseable value

"Today" must be the WAREHOUSE's calendar day (timezone.localdate() with
TIME_ZONE = Europe/Amsterdam), not the customer's phone — the caller passes
it in so this stays pure.

Note that `in_warehouse` says WHERE the beer is, never what happens next:
whether the customer collects it or we ship it is the order's DELIVERY
METHOD, derived separately below. Telling a shipping customer their beer is
"ready for pickup" was the complaint that made this split necessary.

`cancelled` and `handled` are ORDER-level outcomes pushed down onto the
lines (see derive_order_outcome). They exist because Shopify's per-line
`fulfillment_status` stays null forever on an order we finished WITHOUT
fulfilling it — which is most of the ways an order actually ends here:
merged into another order and cancelled, handed over at the counter, or
simply archived when done. Those lines used to fall through to
`in_warehouse`, so the app told members their beer was still waiting for
them months after they got it (reported 2026-11-14 for the merged-away
HoB9027, and true of ~460 orders older than 45 days).
"""
import logging
from datetime import date

logger = logging.getLogger(__name__)

STATE_CANCELLED = 'cancelled'
STATE_SHIPPED = 'shipped'
STATE_PARTIAL = 'partial'
STATE_HANDLED = 'handled'
STATE_IN_WAREHOUSE = 'in_warehouse'
STATE_INCOMING = 'incoming'
STATE_UNKNOWN = 'unknown'

OUTCOME_CANCELLED = 'cancelled'
OUTCOME_HANDLED = 'handled'

# Shopify order-level fulfillment_status when a cancellation put the stock
# back on the shelf. The lines keep fulfillment_status null, so this is the
# only per-order signal besides cancelled_at.
FULFILLMENT_RESTOCKED = 'restocked'

# hob tags the source order of a merge `merged, merged-into-HoB8556`. The
# customer paid once and received everything under the target order, so
# naming that order is the whole answer to "where is my beer?".
MERGED_INTO_PREFIX = 'merged-into-'

DELIVERY_PICKUP = 'pickup'
DELIVERY_SHIPPING = 'shipping'
DELIVERY_UNKNOWN = 'unknown'

# Our in-store pickup rate is titled exactly "House of Beers"; the keywords
# cover a renamed rate. Deliberately short: a wrong `pickup` tells someone
# who paid for shipping to drive to Uden, so anything we do not recognise
# must fall through to `shipping`/`unknown` instead of being guessed at.
PICKUP_TITLE = 'house of beers'
PICKUP_KEYWORDS = ('ophalen', 'afhalen')


def derive_order_outcome(order):
    """
    'cancelled' | 'handled' | None — whether the ORDER is finished, from the
    only two signals Shopify gives us for an order that was never fulfilled.

    `cancelled_at` or a `restocked` order status means nothing is owed. An
    archived order (`closed_at`) means staff marked it as needing no further
    action; for a line that never got fulfilled that is the closest thing to
    a handover receipt we have.

    The remaining risk is an order archived for tidiness while the beer is
    still on our shelf, which would read "afgehandeld" too early. Accepted
    deliberately: the opposite error — a finished order promising "ligt bij
    ons klaar" forever — is the one members actually complain about, and
    archiving in Shopify means "no further action" by definition.
    """
    order = order or {}
    if (order.get('cancelled_at')
            or order.get('fulfillment_status') == FULFILLMENT_RESTOCKED):
        return OUTCOME_CANCELLED
    if order.get('closed_at'):
        return OUTCOME_HANDLED
    return None


def merged_into_order_name(order):
    """
    The order name this one was merged into ('HoB8556'), '' when it wasn't.

    Reads hob's `merged-into-<name>` tag, case-insensitively on the prefix
    but preserving the name's own casing.
    """
    tags = (order or {}).get('tags') or ''
    for tag in str(tags).split(','):
        tag = tag.strip()
        if tag.lower().startswith(MERGED_INTO_PREFIX):
            name = tag[len(MERGED_INTO_PREFIX):].strip()
            if name:
                return name
    return ''


def derive_line_state(*, product_id, raw_eta, unresolved_ids, today,
                      fulfillment_status=None, order_outcome=None):
    """
    (state, estimated_delivery_date) for one line item.

    product_id: numeric id, str or None (custom draft lines have none).
    raw_eta: the custom.estimated_delivery_date metafield value, or None.
    unresolved_ids: set of str product ids whose metafield fetch failed.
    fulfillment_status: Shopify's per-line status for ORDER lines; draft
        lines pass None so they always take the ETA path.
    order_outcome: derive_order_outcome() for the parent order; drafts pass
        None (an unpaid draft has no outcome yet).

    The second element is the normalized ISO date string when the metafield
    parsed, else None — the raw value is NEVER forwarded to the app.
    """
    # A cancelled order owes nothing, so this outranks everything — including
    # a line fulfilled before the cancellation, whose stock came back.
    if order_outcome == OUTCOME_CANCELLED:
        return STATE_CANCELLED, None

    if fulfillment_status == 'fulfilled':
        state = STATE_SHIPPED
    elif fulfillment_status == 'partial':
        state = STATE_PARTIAL
    else:
        state = None  # fall through to the ETA logic

    # Archived order, line never fulfilled: done with us, by some route we
    # cannot name. Deliberately ahead of the metafield logic — an ETA says
    # nothing once the order is closed, and `unknown` would be a worse answer
    # than the outcome we actually know.
    if state is None and order_outcome == OUTCOME_HANDLED:
        return STATE_HANDLED, None

    pid = str(product_id) if product_id is not None else None
    if pid is not None and pid in unresolved_ids:
        # We could not learn whether an ETA exists; claiming "in warehouse"
        # here would promise stock we know nothing about.
        return (state or STATE_UNKNOWN), None

    if raw_eta is None or not str(raw_eta).strip():
        return (state or STATE_IN_WAREHOUSE), None

    # Strict ISO parse. The metafield is a typed Shopify `date`, so this
    # should never fail — the warning is the alarm if it ever does.
    try:
        eta = date.fromisoformat(str(raw_eta).strip()[:10])
    except ValueError:
        logger.warning(
            f"Unparseable estimated_delivery_date for product {pid}: "
            f"{raw_eta!r}"
        )
        return (state or STATE_UNKNOWN), None

    eta_iso = eta.isoformat()
    if state:
        return state, eta_iso
    return (STATE_INCOMING if eta > today else STATE_IN_WAREHOUSE), eta_iso


def shipping_method_title(order):
    """
    The order's shipping-line title, '' when it carries none.

    Shopify's `customers/{id}/orders.json` already returns `shipping_lines`,
    so this costs no extra API call. Normally there is exactly one line; we
    take the first one that actually has a title rather than indexing [0]
    blindly, since an empty title tells us nothing either way.
    """
    for line in (order or {}).get('shipping_lines') or []:
        title = (line or {}).get('title')
        if title and str(title).strip():
            return str(title).strip()
    return ''


def derive_delivery_method(shipping_method):
    """
    'pickup' | 'shipping' | 'unknown' from a shipping-line title.

    An EMPTY title is `unknown`, NOT pickup: roughly a thousand orders since
    01-09-2026 have no shipping line because they are POS/in-store sales,
    which are handed over at the counter — neither a pickup promise nor a
    shipping promise is true for them. The app renders `unknown` with
    neutral wording ("in stock with us"), so an order we are unsure about
    never claims the customer has to come and collect it.
    """
    title = (shipping_method or '').strip().lower()
    if not title:
        return DELIVERY_UNKNOWN
    if title == PICKUP_TITLE or any(word in title for word in PICKUP_KEYWORDS):
        return DELIVERY_PICKUP
    return DELIVERY_SHIPPING


def display_title(raw_title, metafields):
    """
    The clean name for the app: custom.app_title when present, else the raw
    Shopify title. WhatsApp-sale products are titled "24-10 - K - Beer" for
    pipeline idempotency; app_title carries the human name.
    """
    app_title = (metafields or {}).get('app_title')
    if app_title and str(app_title).strip():
        return str(app_title).strip()
    return raw_title
