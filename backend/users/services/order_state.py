"""
Line-item state derivation for the app's orders screen.

Pure (except for one warning log) so the business rules are testable as a
table: a line item ends up in exactly one of five states —

    shipped       order line fulfilled by Shopify
    partial       order line partially fulfilled
    in_warehouse  no ETA metafield (business rule: no ETA means the beer is
                  on the shelf), or an ETA that has passed — the ETA day
                  itself counts as arrived, matching hob's graduation rule
    incoming      ETA strictly in the future (a pre-order still underway)
    unknown       the metafield fetch failed for this product, or the
                  metafield held an unparseable value

"Today" must be the WAREHOUSE's calendar day (timezone.localdate() with
TIME_ZONE = Europe/Amsterdam), not the customer's phone — the caller passes
it in so this stays pure.
"""
import logging
from datetime import date

logger = logging.getLogger(__name__)

STATE_SHIPPED = 'shipped'
STATE_PARTIAL = 'partial'
STATE_IN_WAREHOUSE = 'in_warehouse'
STATE_INCOMING = 'incoming'
STATE_UNKNOWN = 'unknown'


def derive_line_state(*, product_id, raw_eta, unresolved_ids, today,
                      fulfillment_status=None):
    """
    (state, estimated_delivery_date) for one line item.

    product_id: numeric id, str or None (custom draft lines have none).
    raw_eta: the custom.estimated_delivery_date metafield value, or None.
    unresolved_ids: set of str product ids whose metafield fetch failed.
    fulfillment_status: Shopify's per-line status for ORDER lines; draft
        lines pass None so they always take the ETA path.

    The second element is the normalized ISO date string when the metafield
    parsed, else None — the raw value is NEVER forwarded to the app.
    """
    if fulfillment_status == 'fulfilled':
        state = STATE_SHIPPED
    elif fulfillment_status == 'partial':
        state = STATE_PARTIAL
    else:
        state = None  # fall through to the ETA logic

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
