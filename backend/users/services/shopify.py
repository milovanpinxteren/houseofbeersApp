import logging
import requests
from typing import Optional
from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)

# Shopify defaults every combinesWith field to false, which means "this code
# cannot be used together with ANY other discount". A member can easily hold
# several of our codes at once (a reward, a campaign code, a raffle prize, a
# birthday gift, a sixpack code), and they told us they could not use them in
# one order — this default was why. Every code we mint opts in to all three
# discount classes.
#
# Combination is symmetric: the OTHER discount has to allow it too, so any
# discount created by hand in the Shopify admin still needs its own
# Combinations boxes ticked. Shopify also caps a checkout at 5 product/order
# codes plus 1 shipping code, and order+order combination is only offered to
# stores without checkout.liquid customizations.
COMBINES_WITH_ALL = {
    'orderDiscounts': True,
    'productDiscounts': True,
    'shippingDiscounts': True,
}


class ShopifyService:
    """Service for interacting with Shopify Admin API."""

    def __init__(self):
        store_url = settings.SHOPIFY_STORE_URL.rstrip('/')
        # Ensure URL has https:// prefix
        if not store_url.startswith('http://') and not store_url.startswith('https://'):
            store_url = f'https://{store_url}'
        self.store_url = store_url
        self.access_token = settings.SHOPIFY_ACCESS_TOKEN
        self.api_version = '2024-01'

    @property
    def headers(self) -> dict:
        return {
            'X-Shopify-Access-Token': self.access_token,
            'Content-Type': 'application/json',
        }

    @property
    def base_url(self) -> str:
        return f"{self.store_url}/admin/api/{self.api_version}"

    def _request(self, method: str, endpoint: str, **kwargs) -> Optional[dict]:
        """Make a request to Shopify API."""
        url = f"{self.base_url}/{endpoint}"
        logger.info(f"Shopify API request: {method} {url}")
        try:
            response = requests.request(
                method,
                url,
                headers=self.headers,
                timeout=30,
                **kwargs
            )
            logger.info(f"Shopify API response: {response.status_code}")
            response.raise_for_status()
            data = response.json()
            logger.debug(f"Shopify API data: {data}")
            return data
        except requests.exceptions.RequestException as e:
            logger.error(f"Shopify API error: {e}")
            if hasattr(e, 'response') and e.response is not None:
                logger.error(f"Response body: {e.response.text}")
            return None

    def find_customer_by_email(self, email: str) -> Optional[dict]:
        """
        Find a Shopify customer by email.
        Returns customer data or None if not found.
        """
        logger.info(f"Searching for Shopify customer with email: {email}")
        data = self._request('GET', f'customers/search.json?query=email:{email}')
        if data and data.get('customers'):
            customer = data['customers'][0]
            logger.info(f"Found Shopify customer: ID={customer.get('id')}, email={customer.get('email')}")
            return customer
        logger.info(f"No Shopify customer found for email: {email}")
        return None

    def get_customer(self, customer_id: str) -> Optional[dict]:
        """Get a Shopify customer by ID."""
        data = self._request('GET', f'customers/{customer_id}.json')
        if data:
            return data.get('customer')
        return None

    def get_customer_orders(self, customer_id: str, limit: int = 50) -> list:
        """Get orders for a Shopify customer."""
        data = self._request(
            'GET',
            f'customers/{customer_id}/orders.json?limit={limit}&status=any'
        )
        if data:
            return data.get('orders', [])
        return []

    def _paginated_request(self, endpoint: str, data_key: str = 'orders',
                           raise_on_error: bool = False) -> list:
        """
        Fetch all pages from a paginated Shopify REST endpoint.
        Follows Link header with rel="next" for cursor-based pagination.

        raise_on_error=False (the sync paths' historical behavior) returns
        whatever was fetched before a failure; raise_on_error=True re-raises,
        for callers that must distinguish "no results" from "Shopify down"
        (campaign backfill, tag/collection snapshots).
        """
        all_results = []
        url = f"{self.base_url}/{endpoint}"

        while url:
            try:
                response = requests.get(url, headers=self.headers, timeout=30)
                response.raise_for_status()
                data = response.json()

                results = data.get(data_key, [])
                all_results.extend(results)
                logger.info(f"Fetched {len(results)} {data_key} (total: {len(all_results)})")

                # Follow pagination via Link header
                url = None
                link_header = response.headers.get('Link', '')
                if 'rel="next"' in link_header:
                    for part in link_header.split(','):
                        if 'rel="next"' in part:
                            url = part.split(';')[0].strip().strip('<>')
                            break
            except requests.exceptions.RequestException as e:
                logger.error(f"Paginated request error: {e}")
                if raise_on_error:
                    raise
                break

        return all_results

    def get_all_customer_orders(self, customer_id: str) -> list:
        """
        Get ALL orders for a Shopify customer, paginating through all pages.
        Used for full sync / recalculation.
        """
        return self._paginated_request(
            f'customers/{customer_id}/orders.json?limit=250&status=any'
        )

    @staticmethod
    def _variant_available(variant: dict) -> bool:
        """
        A variant is purchasable when Shopify doesn't track its inventory,
        when it keeps selling while out of stock, or when stock is positive.
        """
        if not variant.get('inventory_management'):
            return True
        if variant.get('inventory_policy') == 'continue':
            return True
        return (variant.get('inventory_quantity') or 0) > 0

    def get_active_products(self) -> list:
        """
        Fetch all active, in-stock products from the store.

        Paginates through products.json (250/page) and returns a compact
        dict per product: id, title, product_type, tags (list), price
        (first variant), variant_id, image_url, handle and created_at.
        Out-of-stock products (no purchasable variant) are excluded.
        """
        raw_products = self._paginated_request(
            'products.json?limit=250&status=active',
            data_key='products',
        )

        products = []
        for product in raw_products:
            variants = product.get('variants') or []
            if not any(self._variant_available(v) for v in variants):
                continue

            first_variant = variants[0] if variants else {}
            image = product.get('image') or {}
            # REST API returns tags as a comma-separated string
            tags = [
                tag.strip()
                for tag in (product.get('tags') or '').split(',')
                if tag.strip()
            ]

            products.append({
                'id': product.get('id'),
                'title': product.get('title') or '',
                'product_type': (product.get('product_type') or '').strip(),
                'tags': tags,
                'price': first_variant.get('price'),
                'variant_id': str(first_variant.get('id') or ''),
                'image_url': image.get('src') or '',
                'handle': product.get('handle') or '',
                'created_at': product.get('created_at') or '',
            })

        logger.info(f"Fetched {len(products)} active in-stock products from Shopify")
        return products

    def get_shop_orders_in_window(self, start, end) -> list:
        """
        Get ALL paid shop orders created inside [start, end], newest-first,
        paginating through all pages. Used by the campaign backfill scan.
        Raises on a Shopify failure — a backfill/preview must report failure,
        not silently conclude "no orders".
        """
        return self._paginated_request(
            f'orders.json?limit=250&status=any&financial_status=paid'
            f'&order=created_at+desc'
            f'&created_at_min={start.isoformat()}&created_at_max={end.isoformat()}',
            raise_on_error=True,
        )

    def get_product_ids_by_tag(self, tag: str) -> list:
        """
        Get ids of all products carrying `tag` (case-insensitive).
        Fetches only id+tags fields, paginated, to keep the scan light.
        Raises on a Shopify failure so snapshot refreshes keep the previous
        snapshot instead of overwriting it with an empty list.
        """
        products = self._paginated_request(
            'products.json?limit=250&fields=id,tags',
            data_key='products',
            raise_on_error=True,
        )
        wanted = tag.strip().lower()
        matched = []
        for product in products:
            # REST API returns tags as a comma-separated string
            tags = [t.strip().lower() for t in (product.get('tags') or '').split(',')]
            if wanted in tags:
                matched.append(product.get('id'))
        logger.info(f"Found {len(matched)} products with tag '{tag}'")
        return matched

    def get_collection_product_ids(self, collection_id) -> list:
        """Get ids of all products in a collection (custom or smart).
        Raises on a Shopify failure (see get_product_ids_by_tag)."""
        products = self._paginated_request(
            f'collections/{collection_id}/products.json?limit=250&fields=id',
            data_key='products',
            raise_on_error=True,
        )
        return [product.get('id') for product in products]

    def get_customer_orders_since(self, customer_id: str, since_date) -> list:
        """
        Get orders for a Shopify customer created after since_date.
        Used for partial/incremental sync.
        """
        since_iso = since_date.isoformat()
        return self._paginated_request(
            f'customers/{customer_id}/orders.json?limit=250&status=any&created_at_min={since_iso}'
        )

    def link_customer_to_user(self, user, email: str = None) -> bool:
        """
        Find and link a Shopify customer to a local user.
        Returns True if successfully linked.
        """
        from users.models import User

        search_email = email or user.email
        customer = self.find_customer_by_email(search_email)

        if customer:
            user.shopify_customer_id = str(customer['id'])
            user.shopify_linked_at = timezone.now()
            user.save(update_fields=['shopify_customer_id', 'shopify_linked_at'])
            logger.info(f"Linked user {user.email} to Shopify customer {customer['id']}")

            # Points granted before this person joined (WhatsApp actions etc.)
            # are parked as pending service grants keyed on the Shopify
            # customer id — the link is the moment they become claimable.
            try:
                from loyalty.services.grants import claim_pending_grants
                claim_pending_grants(user)
            except Exception as e:
                logger.error(f"Pending grant claim failed for {user.email}: {e}")
            return True

        logger.info(f"No Shopify customer found for {search_email}")
        return False

    def sync_all_users(self) -> dict:
        """
        Sync all users without a Shopify customer ID.
        Returns stats about the sync.
        """
        from users.models import User

        stats = {'processed': 0, 'linked': 0, 'not_found': 0, 'errors': 0}

        users_to_sync = User.objects.filter(shopify_customer_id__isnull=True)

        for user in users_to_sync:
            stats['processed'] += 1
            try:
                if self.link_customer_to_user(user):
                    stats['linked'] += 1
                else:
                    stats['not_found'] += 1
            except Exception as e:
                logger.error(f"Error syncing user {user.email}: {e}")
                stats['errors'] += 1

        logger.info(f"Shopify sync complete: {stats}")
        return stats

    def resync_user(self, user) -> bool:
        """
        Re-sync a specific user (even if already linked).
        Useful for updating customer data.
        """
        return self.link_customer_to_user(user)

    # The REST price-rule discount creator that used to live here is gone: the
    # REST API has no combinesWith field, so every code it minted was
    # permanently non-combinable. Its one caller (the birthday gift in
    # loyalty/tasks.py) now uses create_basic_discount.

    # ============ GraphQL API Methods ============

    @property
    def graphql_url(self) -> str:
        return f"{self.store_url}/admin/api/{self.api_version}/graphql.json"

    def _graphql_request(self, query: str, variables: dict = None) -> Optional[dict]:
        """Make a GraphQL request to Shopify API."""
        logger.info(f"Shopify GraphQL request")
        try:
            payload = {"query": query}
            if variables:
                payload["variables"] = variables

            response = requests.post(
                self.graphql_url,
                headers=self.headers,
                json=payload,
                timeout=30,
            )
            logger.info(f"Shopify GraphQL response: {response.status_code}")
            response.raise_for_status()
            data = response.json()

            if "errors" in data:
                logger.error(f"GraphQL errors: {data['errors']}")
                return None

            return data.get("data")
        except requests.exceptions.RequestException as e:
            logger.error(f"Shopify GraphQL error: {e}")
            if hasattr(e, "response") and e.response is not None:
                logger.error(f"Response body: {e.response.text}")
            return None

    def get_app_only_products(self) -> list:
        """
        Fetch app-exclusive products: leftover WhatsApp-sale stock tagged
        `app-only` by the hob pipeline.

        These products are UNLISTED (invisible in webshop listings and in the
        status:active caches) but buyable via cart permalink. Each has an
        "Editie" option with a Sale and an App variant; ONLY the App variant
        (secondary price) is for the app — never use variants[0] here.

        Returns a list of dicts with the App variant's price/variant_id, the
        Sale variant's price (sale_price, the WhatsApp deal price shown for
        comparison) and the Untappd metafields for a rich card UI.

        Buyability: products additionally tagged `app-archived` had their app
        window closed by a newer sale — they stay in the list with
        buyable=False as the "gemist" FOMO wall. Non-archived products whose
        App variant is out of stock are excluded (sold out mid-window is a
        normal disappearance, not a missed deal). Buyable products sort
        first, newest first within each batch.
        """
        query = """
        query appOnlyProducts($cursor: String) {
            products(first: 50, after: $cursor, query: "tag:'app-only'") {
                pageInfo { hasNextPage endCursor }
                edges {
                    node {
                        id
                        legacyResourceId
                        title
                        handle
                        status
                        tags
                        createdAt
                        description(truncateAt: 600)
                        featuredImage { url }
                        variants(first: 10) {
                            edges {
                                node {
                                    id
                                    legacyResourceId
                                    price
                                    inventoryQuantity
                                    selectedOptions { name value }
                                }
                            }
                        }
                        metafields(first: 30, namespace: "custom") {
                            edges { node { key value type } }
                        }
                    }
                }
            }
        }
        """

        products = []
        cursor = None
        for _page in range(10):  # safety bound; app-only sets are small
            data = self._graphql_request(query, {"cursor": cursor})
            if not data:
                break
            conn = data.get('products') or {}
            for edge in conn.get('edges') or []:
                node = edge['node']
                parsed = self._parse_app_only_product(node)
                if parsed:
                    products.append(parsed)
            page_info = conn.get('pageInfo') or {}
            if not page_info.get('hasNextPage'):
                break
            cursor = page_info.get('endCursor')

        # Buyable batch first, archived (gemist) wall after; newest first
        # within each batch (ISO timestamps compare lexicographically, and the
        # stable buyable pass preserves the date order per batch)
        products.sort(key=lambda p: p.get('created_at') or '', reverse=True)
        products.sort(key=lambda p: not p['buyable'])
        return products

    @staticmethod
    def _parse_app_only_product(node: dict) -> Optional[dict]:
        """Parse one GraphQL product node into an app-shop dict (or None)."""
        import json as _json

        # The App variant carries the secondary price and the leftover stock;
        # the Sale variant's price is the WhatsApp deal shown for comparison.
        app_variant = None
        sale_variant = None
        for v_edge in (node.get('variants') or {}).get('edges') or []:
            v = v_edge['node']
            options = {o['name']: o['value'] for o in v.get('selectedOptions') or []}
            if options.get('Editie') == 'App':
                app_variant = v
            elif options.get('Editie') == 'Sale':
                sale_variant = v
        if not app_variant:
            return None

        # `app-archived` = app window closed by a newer sale: keep the product
        # visible as a missed deal (not buyable). Without the tag, zero
        # inventory just means sold out — drop it as before.
        archived = 'app-archived' in (node.get('tags') or [])
        inventory = app_variant.get('inventoryQuantity') or 0
        if inventory <= 0 and not archived:
            return None
        buyable = not archived and inventory > 0

        metafields = {}
        for m_edge in (node.get('metafields') or {}).get('edges') or []:
            m = m_edge['node']
            metafields[m['key']] = m['value']

        def _mf_json(key):
            raw = metafields.get(key)
            if not raw:
                return None
            try:
                return _json.loads(raw)
            except (ValueError, TypeError):
                return None

        rating = None
        score = _mf_json('untappd_score')
        if isinstance(score, dict):
            try:
                rating = float(score.get('value'))
            except (TypeError, ValueError):
                rating = None
        if rating is None and metafields.get('untappd_rating'):
            try:
                rating = float(metafields['untappd_rating'])
            except (TypeError, ValueError):
                rating = None

        untappd_link = _mf_json('untappd_link')
        untappd_url = untappd_link.get('url') if isinstance(untappd_link, dict) else None

        checkins = None
        if metafields.get('untappd_checkins'):
            try:
                checkins = int(metafields['untappd_checkins'])
            except (TypeError, ValueError):
                checkins = None

        image = node.get('featuredImage') or {}

        return {
            'id': node.get('legacyResourceId'),
            'title': metafields.get('app_title') or node.get('title'),
            'shopify_title': node.get('title'),
            'handle': node.get('handle'),
            'description': node.get('description') or '',
            'image_url': image.get('url') or '',
            'tags': node.get('tags') or [],
            'created_at': node.get('createdAt'),
            'price': app_variant.get('price'),
            'sale_price': sale_variant.get('price') if sale_variant else None,
            'buyable': buyable,
            'variant_id': str(app_variant.get('legacyResourceId') or ''),
            'inventory': inventory,
            'untappd_rating': rating,
            'untappd_checkins': checkins,
            'untappd_url': untappd_url,
            'style': metafields.get('soort_bier') or '',
            'abv': metafields.get('alcoholpercentage') or '',
            'country': metafields.get('land_van_herkomst') or '',
            'volume': metafields.get('inhoud') or '',
            'deposit': metafields.get('deposit') or '',
        }

    # Every discount code the app mints carries one of these prefixes, so a
    # code on an order attributes that order to the app feature that made it.
    APP_CODE_PREFIXES = {
        'SIX-': 'sixpack',     # sixpack generator packs
        'HOB-': 'loyalty',     # loyalty reward redemptions + campaign qualification codes
        'BDAY-': 'birthday',   # birthday gift codes
        'WIN-': 'raffle',      # campaign raffle prize codes
    }

    def get_app_sales_report(self, start_date: str, end_date: str) -> Optional[dict]:
        """
        One scan of paid orders created in [start_date, end_date] (inclusive
        ISO dates) that attributes all app-driven money:

        - app_shop: order lines on an App variant (option Editie=App). The App
          variant is only purchasable through the PWA, so these lines are
          exactly the app-shop's sales. Revenue is the discounted line total
          (gross of order-level discount codes).
        - sixpack: orders redeeming a SIX- code or tagged
          attributes[source]=app-sixpack. Revenue is the order subtotal
          actually paid (after discounts, before shipping).
        - codes: per app feature (sixpack/loyalty/birthday), how many orders
          used one of its codes, the revenue on those orders and the € the
          codes discounted — i.e. what each program cost and touched.

        Scans newest-first (bounded at 10000 orders; `truncated` flags when
        the window held more, dropping only the oldest tail). Returns None
        when the order query fails, so callers can distinguish 'no sales'
        from 'no data'. Slow for big ranges — run it in a Celery task, not a
        request cycle.
        """
        from datetime import date, timedelta

        end_exclusive = (date.fromisoformat(end_date) + timedelta(days=1)).isoformat()
        order_filter = (
            f"created_at:>={start_date} AND created_at:<{end_exclusive}"
            f" AND financial_status:paid"
        )
        query = """
        query appSalesReport($cursor: String, $q: String!) {
            orders(first: 250, after: $cursor, query: $q, sortKey: CREATED_AT, reverse: true) {
                pageInfo { hasNextPage endCursor }
                edges {
                    node {
                        name
                        customAttributes { key value }
                        discountCodes
                        currentSubtotalPriceSet { shopMoney { amount } }
                        totalDiscountsSet { shopMoney { amount } }
                        lineItems(first: 50) {
                            edges {
                                node {
                                    quantity
                                    discountedTotalSet { shopMoney { amount } }
                                    variant { selectedOptions { name value } }
                                }
                            }
                        }
                    }
                }
            }
        }
        """

        app_shop = {'units': 0, 'revenue': 0.0, 'orders': set()}
        sixpack = {'orders': set(), 'revenue': 0.0}
        codes = {
            feature: {'orders': 0, 'revenue': 0.0, 'discounted': 0.0}
            for feature in self.APP_CODE_PREFIXES.values()
        }
        truncated = True
        cursor = None
        for _page in range(40):  # bounded: 10000 most recent orders max
            data = self._graphql_request(
                query,
                {"cursor": cursor, "q": order_filter},
            )
            if not data:
                return None
            conn = data.get('orders') or {}
            for edge in conn.get('edges') or []:
                node = edge['node']
                name = node.get('name')
                subtotal = float(((node.get('currentSubtotalPriceSet') or {})
                                  .get('shopMoney') or {}).get('amount') or 0)
                discounts = float(((node.get('totalDiscountsSet') or {})
                                   .get('shopMoney') or {}).get('amount') or 0)
                attrs = {
                    a['key']: a['value']
                    for a in node.get('customAttributes') or []
                }

                for li_edge in (node.get('lineItems') or {}).get('edges') or []:
                    li = li_edge['node']
                    options = {
                        o['name']: o['value']
                        for o in (li.get('variant') or {}).get('selectedOptions') or []
                    }
                    if options.get('Editie') == 'App':
                        app_shop['units'] += li.get('quantity') or 0
                        amount = ((li.get('discountedTotalSet') or {})
                                  .get('shopMoney') or {}).get('amount')
                        app_shop['revenue'] += float(amount or 0)
                        app_shop['orders'].add(name)

                order_features = set()
                for code in node.get('discountCodes') or []:
                    for prefix, feature in self.APP_CODE_PREFIXES.items():
                        if code.upper().startswith(prefix):
                            order_features.add(feature)
                for feature in order_features:
                    codes[feature]['orders'] += 1
                    codes[feature]['revenue'] += subtotal
                    codes[feature]['discounted'] += discounts

                if 'sixpack' in order_features or attrs.get('source') == 'app-sixpack':
                    sixpack['orders'].add(name)
                    sixpack['revenue'] += subtotal

            page_info = conn.get('pageInfo') or {}
            if not page_info.get('hasNextPage'):
                truncated = False
                break
            cursor = page_info.get('endCursor')

        for feature in codes.values():
            feature['revenue'] = round(feature['revenue'], 2)
            feature['discounted'] = round(feature['discounted'], 2)

        return {
            'app_shop': {
                'units': app_shop['units'],
                'revenue': round(app_shop['revenue'], 2),
                'orders': len(app_shop['orders']),
            },
            'sixpack': {
                'orders': len(sixpack['orders']),
                'revenue': round(sixpack['revenue'], 2),
            },
            'codes': codes,
            'truncated': truncated,
        }

    def create_basic_discount(
        self,
        code: str,
        title: str,
        discount_type: str,
        value: float,
        usage_limit: int = 1,
        product_ids: list = None,
        applies_once_per_customer: bool = True,
        ends_at=None,
        minimum_subtotal: float = None,
        customer_id: str = None,
        combines_with: dict = None,
    ) -> Optional[dict]:
        """
        Create a basic discount code (fixed amount or percentage off).

        Args:
            code: The discount code string
            title: Title for the discount
            discount_type: 'fixed_amount' or 'percentage'
            value: Discount value (amount or percentage 0-100)
            usage_limit: Max number of uses
            product_ids: List of product GIDs to apply to (None = all products)
            applies_once_per_customer: Limit to one use per customer
            ends_at: datetime the code expires (optional, None = never expires)
            minimum_subtotal: Minimum cart subtotal required for the code
            customer_id: Numeric Shopify customer id — locks the code to that
                one customer (None = usable by anyone holding the code)
            combines_with: Override the discount classes this code stacks with
                (defaults to COMBINES_WITH_ALL; pass {} for a code that must
                stand alone)
        """
        # Build the discount value
        if discount_type == "percentage":
            customer_gets_value = {
                "percentage": value / 100  # Convert to decimal (10% = 0.1)
            }
        else:  # fixed_amount
            customer_gets_value = {
                "discountAmount": {
                    "amount": str(value),
                    "appliesOnEachItem": False
                }
            }

        # Build items targeting
        if product_ids:
            items = {
                "products": {
                    "productsToAdd": product_ids
                }
            }
        else:
            items = {"all": True}

        query = """
        mutation discountCodeBasicCreate($basicCodeDiscount: DiscountCodeBasicInput!) {
            discountCodeBasicCreate(basicCodeDiscount: $basicCodeDiscount) {
                codeDiscountNode {
                    id
                    codeDiscount {
                        ... on DiscountCodeBasic {
                            codes(first: 1) {
                                nodes {
                                    code
                                }
                            }
                        }
                    }
                }
                userErrors {
                    code
                    field
                    message
                }
            }
        }
        """

        # A linked customer narrows the code to exactly one person; without
        # one, usage_limit bounds the exposure instead.
        if customer_id:
            customer_selection = {
                "customers": {"add": [f"gid://shopify/Customer/{customer_id}"]}
            }
        else:
            customer_selection = {"all": True}

        variables = {
            "basicCodeDiscount": {
                "title": title,
                "code": code,
                "startsAt": timezone.now().isoformat(),
                "usageLimit": usage_limit,
                "appliesOncePerCustomer": applies_once_per_customer,
                "customerSelection": customer_selection,
                "combinesWith": (
                    COMBINES_WITH_ALL if combines_with is None else combines_with
                ),
                "customerGets": {
                    "value": customer_gets_value,
                    "items": items
                }
            }
        }

        # Optional expiry
        if ends_at:
            variables["basicCodeDiscount"]["endsAt"] = ends_at.isoformat()

        # Optional minimum cart subtotal
        if minimum_subtotal is not None:
            variables["basicCodeDiscount"]["minimumRequirement"] = {
                "subtotal": {
                    "greaterThanOrEqualToSubtotal": str(minimum_subtotal)
                }
            }

        data = self._graphql_request(query, variables)
        if not data:
            return None

        result = data.get("discountCodeBasicCreate", {})
        user_errors = result.get("userErrors", [])

        if user_errors:
            logger.error(f"Discount creation errors: {user_errors}")
            return None

        discount_node = result.get("codeDiscountNode")
        if discount_node:
            logger.info(f"Created Shopify discount code: {code}")
            return {
                "discount_id": discount_node["id"],
                "code": code,
            }

        return None

    def create_free_shipping_discount(
        self,
        code: str,
        title: str,
        usage_limit: int = 1,
        applies_once_per_customer: bool = True,
        combines_with: dict = None,
    ) -> Optional[dict]:
        """
        Create a free shipping discount code.

        `combines_with` defaults to COMBINES_WITH_ALL. Note that Shopify never
        stacks two shipping discounts on one order regardless of this flag —
        the flag is what lets this code ride along with a product or order
        discount.
        """

        query = """
        mutation discountCodeFreeShippingCreate($freeShippingCodeDiscount: DiscountCodeFreeShippingInput!) {
            discountCodeFreeShippingCreate(freeShippingCodeDiscount: $freeShippingCodeDiscount) {
                codeDiscountNode {
                    id
                    codeDiscount {
                        ... on DiscountCodeFreeShipping {
                            codes(first: 1) {
                                nodes {
                                    code
                                }
                            }
                        }
                    }
                }
                userErrors {
                    code
                    field
                    message
                }
            }
        }
        """

        variables = {
            "freeShippingCodeDiscount": {
                "title": title,
                "code": code,
                "startsAt": timezone.now().isoformat(),
                "usageLimit": usage_limit,
                "appliesOncePerCustomer": applies_once_per_customer,
                "customerSelection": {"all": True},
                "combinesWith": (
                    COMBINES_WITH_ALL if combines_with is None else combines_with
                ),
                "destination": {"all": True}
            }
        }

        data = self._graphql_request(query, variables)
        if not data:
            return None

        result = data.get("discountCodeFreeShippingCreate", {})
        user_errors = result.get("userErrors", [])

        if user_errors:
            logger.error(f"Free shipping discount creation errors: {user_errors}")
            return None

        discount_node = result.get("codeDiscountNode")
        if discount_node:
            logger.info(f"Created Shopify free shipping code: {code}")
            return {
                "discount_id": discount_node["id"],
                "code": code,
            }

        return None

    def create_free_product_discount(
        self,
        code: str,
        title: str,
        product_id: str,
        usage_limit: int = 1,
        applies_once_per_customer: bool = True,
    ) -> Optional[dict]:
        """
        Create a 100% off discount for a specific product (free product).

        Args:
            code: The discount code string
            title: Title for the discount
            product_id: Shopify product GID (e.g., gid://shopify/Product/123456)
            usage_limit: Max number of uses
        """
        return self.create_basic_discount(
            code=code,
            title=title,
            discount_type="percentage",
            value=100,  # 100% off = free
            usage_limit=usage_limit,
            product_ids=[product_id],
            applies_once_per_customer=applies_once_per_customer,
        )

    def get_product_cart_variant_id(self, product_gid: str) -> Optional[str]:
        """
        Numeric variant id to use in a /cart/<variant>:1 permalink for a
        product GID. Prefers the first variant that is available for sale so a
        cart link never lands on a sold-out variant; falls back to the first
        variant. Returns None when the lookup fails or the product has none —
        callers must treat None as "no cart link", never as an error.

        Note: for app-only sale products variants[0] is the Sale variant, but
        those are never used as campaign/prize products (the App variant is
        addressed directly by /api/recommendations/app-shop/).
        """
        query = """
        query cartVariant($id: ID!) {
            product(id: $id) {
                variants(first: 20) {
                    nodes { id availableForSale }
                }
            }
        }
        """
        data = self._graphql_request(query, {"id": product_gid})
        if not data:
            return None
        product = data.get("product") or {}
        nodes = (product.get("variants") or {}).get("nodes") or []
        if not nodes:
            return None
        chosen = next((n for n in nodes if n.get("availableForSale")), nodes[0])
        # gid://shopify/ProductVariant/123 -> 123 (cart permalinks want numeric)
        return str(chosen.get("id", "")).rsplit("/", 1)[-1] or None

    def get_discount_code_usage(self, code: str) -> Optional[int]:
        """
        How many times a discount code has been used, via
        codeDiscountNodeByCode. Returns None when the lookup fails or the code
        does not exist (callers must treat None as "unknown", not "unused").

        asyncUsageCount is Shopify's eventually-consistent usage counter; for
        our usage_limit=1 codes any value > 0 means redeemed.
        """
        query = """
        query codeUsage($code: String!) {
            codeDiscountNodeByCode(code: $code) {
                codeDiscount {
                    ... on DiscountCodeBasic { asyncUsageCount }
                    ... on DiscountCodeFreeShipping { asyncUsageCount }
                    ... on DiscountCodeBxgy { asyncUsageCount }
                }
            }
        }
        """
        data = self._graphql_request(query, {"code": code})
        if not data:
            return None
        node = data.get("codeDiscountNodeByCode")
        if not node:
            return None
        usage = (node.get("codeDiscount") or {}).get("asyncUsageCount")
        return int(usage) if usage is not None else None

    def set_discount_combines_with(
        self, code: str, combines_with: dict = None
    ) -> Optional[str]:
        """
        Make an ALREADY-MINTED code combinable.

        combinesWith lives on the Shopify discount, not on our row, so codes
        issued before we started sending the field stay stuck at
        "combines with nothing" until they are updated here. Used by
        `backfill_discount_combines`.

        Returns a short status string — 'updated', 'not_found', or 'failed' —
        rather than a bool, so the backfill can report per-code. Never raises.
        """
        combines_with = COMBINES_WITH_ALL if combines_with is None else combines_with

        lookup = """
        query codeNode($code: String!) {
            codeDiscountNodeByCode(code: $code) {
                id
                codeDiscount {
                    __typename
                }
            }
        }
        """
        data = self._graphql_request(lookup, {"code": code})
        if not data:
            return 'failed'

        node = data.get("codeDiscountNodeByCode")
        if not node:
            # Deleted in the Shopify admin, or never created. Nothing to fix.
            return 'not_found'

        typename = (node.get("codeDiscount") or {}).get("__typename")
        node_id = node["id"]

        # Each discount type has its own update mutation and input key; a
        # DiscountCodeBasic cannot be updated through the free-shipping one.
        if typename == 'DiscountCodeBasic':
            mutation_name, input_key, input_type = (
                'discountCodeBasicUpdate', 'basicCodeDiscount', 'DiscountCodeBasicInput'
            )
        elif typename == 'DiscountCodeFreeShipping':
            mutation_name, input_key, input_type = (
                'discountCodeFreeShippingUpdate', 'freeShippingCodeDiscount',
                'DiscountCodeFreeShippingInput',
            )
        else:
            logger.warning(f"Cannot set combinesWith on {code}: type {typename}")
            return 'failed'

        mutation = """
        mutation update($id: ID!, $input: %s!) {
            %s(id: $id, %s: $input) {
                userErrors { code field message }
            }
        }
        """ % (input_type, mutation_name, input_key)

        result = self._graphql_request(
            mutation, {"id": node_id, "input": {"combinesWith": combines_with}}
        )
        if not result:
            return 'failed'

        user_errors = (result.get(mutation_name) or {}).get("userErrors") or []
        if user_errors:
            logger.error(f"combinesWith update failed for {code}: {user_errors}")
            return 'failed'

        logger.info(f"Updated combinesWith on discount code {code}")
        return 'updated'

    def search_products(self, query: str, limit: int = 10) -> Optional[list]:
        """
        Live product search by title (active products only), via GraphQL —
        the REST products.json title filter only does exact matches.

        Returns a list of {'id', 'gid', 'title', 'sku', 'price', 'image_url',
        'tags'} dicts (first variant's sku/price), or None when the Shopify
        call fails so callers can distinguish 'no matches' from 'no answer'.
        Used by the Campagne Studio's product picker.
        """
        graphql = """
        query searchProducts($query: String!, $first: Int!) {
          products(first: $first, query: $query) {
            edges {
              node {
                id
                title
                tags
                featuredImage { url }
                variants(first: 1) { edges { node { sku price } } }
              }
            }
          }
        }
        """
        # Strip characters that would break out of the Shopify query string.
        safe = query.replace('\\', '').replace('"', '').replace("'", '')
        data = self._graphql_request(
            graphql,
            {'query': f'status:active AND title:*{safe}*', 'first': limit},
        )
        if data is None:
            return None

        return [
            self._product_node_to_dict(edge.get('node') or {})
            for edge in ((data.get('products') or {}).get('edges') or [])
        ]

    @staticmethod
    def _product_node_to_dict(node):
        """GraphQL product node -> the picker dict shape (see search_products)."""
        gid = node.get('id') or ''
        variant_edges = ((node.get('variants') or {}).get('edges') or [])
        variant = (variant_edges[0].get('node') if variant_edges else None) or {}
        image = node.get('featuredImage') or {}
        return {
            'id': gid.rsplit('/', 1)[-1],
            'gid': gid,
            'title': node.get('title') or '',
            'sku': variant.get('sku') or '',
            'price': variant.get('price'),
            'image_url': image.get('url') or '',
            'tags': node.get('tags') or [],
        }

    def get_products_by_ids(self, product_ids: list) -> Optional[list]:
        """
        Fetch products by numeric id (any status) via GraphQL nodes, in the
        same dict shape as search_products. Ids Shopify doesn't know are
        simply absent from the result. Returns None when the call fails so
        callers can distinguish 'not found' from 'no answer'. Used by the
        Campagne Studio picker when an admin pastes product ids.
        """
        graphql = """
        query productsByIds($ids: [ID!]!) {
          nodes(ids: $ids) {
            ... on Product {
              id
              title
              tags
              featuredImage { url }
              variants(first: 1) { edges { node { sku price } } }
            }
          }
        }
        """
        gids = [f'gid://shopify/Product/{pid}' for pid in product_ids]
        data = self._graphql_request(graphql, {'ids': gids})
        if data is None:
            return None
        return [
            self._product_node_to_dict(node)
            for node in (data.get('nodes') or [])
            if node and node.get('id')
        ]

    def get_product_image(self, product_gid: str) -> Optional[str]:
        """
        Get the featured image URL for a product.

        Args:
            product_gid: Shopify product GID (e.g., gid://shopify/Product/123456)

        Returns:
            Image URL or None
        """
        query = """
        query getProductImage($id: ID!) {
            product(id: $id) {
                featuredImage {
                    url
                }
            }
        }
        """

        data = self._graphql_request(query, {"id": product_gid})
        if data and data.get("product") and data["product"].get("featuredImage"):
            return data["product"]["featuredImage"]["url"]
        return None

    def get_product_metafield(self, product_id: str, namespace: str, key: str) -> Optional[str]:
        """
        Get a specific metafield value for a product.

        Args:
            product_id: Shopify product ID (numeric, not GID)
            namespace: Metafield namespace (e.g., 'custom')
            key: Metafield key (e.g., 'estimated_delivery_date')

        Returns:
            Metafield value or None if not found
        """
        query = """
        query getProductMetafield($id: ID!, $namespace: String!, $key: String!) {
            product(id: $id) {
                metafield(namespace: $namespace, key: $key) {
                    value
                }
            }
        }
        """

        # Convert numeric ID to GID format
        gid = f"gid://shopify/Product/{product_id}"

        variables = {
            "id": gid,
            "namespace": namespace,
            "key": key
        }

        data = self._graphql_request(query, variables)
        if data and data.get("product") and data["product"].get("metafield"):
            return data["product"]["metafield"]["value"]
        return None

    def get_products_metafields(self, product_ids: list, namespace: str, key: str) -> dict:
        """
        Get a specific metafield value for multiple products in a single request.

        Args:
            product_ids: List of Shopify product IDs (numeric, not GIDs)
            namespace: Metafield namespace (e.g., 'custom')
            key: Metafield key (e.g., 'estimated_delivery_date')

        Returns:
            Dict mapping product_id to metafield value (only includes products that have the metafield)
        """
        if not product_ids:
            return {}

        # Remove duplicates and limit to 250 (Shopify's max for bulk queries)
        unique_ids = list(set(product_ids))[:250]

        # Build the query with aliases for each product
        query_parts = []
        for i, pid in enumerate(unique_ids):
            gid = f"gid://shopify/Product/{pid}"
            query_parts.append(f'''
                product_{i}: product(id: "{gid}") {{
                    id
                    metafield(namespace: "{namespace}", key: "{key}") {{
                        value
                    }}
                }}
            ''')

        query = "query { " + " ".join(query_parts) + " }"

        data = self._graphql_request(query)
        if not data:
            return {}

        result = {}
        for i, pid in enumerate(unique_ids):
            product_data = data.get(f"product_{i}")
            if product_data and product_data.get("metafield"):
                result[str(pid)] = product_data["metafield"]["value"]

        return result

    # ============ Customer Metafields (warehouse queue/priority) ============

    def get_customer_queue_priority(self, customer_id) -> Optional[dict]:
        """
        Read the warehouse queue metafields (`custom.queue` /
        `custom.priority`) from a customer. Shopify is the source of truth
        for these values (hob reads them from Shopify too); the pickup RSVP
        sync reads them here before deciding what to write.

        Args:
            customer_id: Shopify customer ID (numeric, not GID)

        Returns:
            {'queue': str|None, 'priority': int|None} — each None when the
            metafield is absent (a non-integer priority value also yields
            None). Returns None when the request fails OR the customer does
            not exist on Shopify; callers cannot distinguish the two and
            should treat None as "no answer", never as "no metafields".
        """
        query = """
        query getCustomerQueuePriority($id: ID!) {
            customer(id: $id) {
                queue: metafield(namespace: "custom", key: "queue") { value }
                priority: metafield(namespace: "custom", key: "priority") { value }
            }
        }
        """
        variables = {"id": f"gid://shopify/Customer/{customer_id}"}

        data = self._graphql_request(query, variables)
        if not data:
            return None
        customer = data.get("customer")
        if not customer:
            # Deleted or unknown customer id.
            return None

        queue = (customer.get("queue") or {}).get("value")
        raw_priority = (customer.get("priority") or {}).get("value")
        try:
            priority = int(raw_priority)
        except (TypeError, ValueError):
            priority = None
        return {"queue": queue, "priority": priority}

    def set_customer_metafield(
        self, customer_id, key: str, value: str, mf_type: str
    ) -> Optional[dict]:
        """
        Set one `custom.*` metafield on a customer via metafieldsSet.

        Args:
            customer_id: Shopify customer ID (numeric, not GID)
            key: Metafield key (e.g., 'queue')
            value: Metafield value as a string (number_integer values are
                strings too, e.g. '80')
            mf_type: Shopify metafield type (e.g., 'single_line_text_field',
                'number_integer')

        Returns:
            The written metafield dict ({'id', 'value'}) on success, or None
            on any GraphQL error or userError.
        """
        mutation = """
        mutation setCustomerMetafield($metafields: [MetafieldsSetInput!]!) {
            metafieldsSet(metafields: $metafields) {
                metafields { id value }
                userErrors { field message }
            }
        }
        """
        variables = {
            "metafields": [{
                "ownerId": f"gid://shopify/Customer/{customer_id}",
                "namespace": "custom",
                "key": key,
                "type": mf_type,
                "value": str(value),
            }]
        }

        data = self._graphql_request(mutation, variables)
        if not data:
            return None

        result = data.get("metafieldsSet") or {}
        user_errors = result.get("userErrors") or []
        if user_errors:
            logger.error(
                f"Customer metafield set failed "
                f"(customer {customer_id}, custom.{key}): {user_errors}"
            )
            return None

        metafields = result.get("metafields") or []
        if metafields:
            logger.info(f"Set custom.{key} on customer {customer_id}")
            return metafields[0]
        return None

    def delete_customer_metafield(self, customer_id, key: str) -> bool:
        """
        Delete one `custom.*` metafield from a customer via metafieldsDelete
        (the only delete mutation in this API version — there is no singular
        metafieldDelete). Deleting a metafield that does not exist is fine:
        Shopify reports no userErrors, so this stays idempotent.

        Args:
            customer_id: Shopify customer ID (numeric, not GID)
            key: Metafield key (e.g., 'priority')

        Returns:
            True on success (including "was already absent"), False on any
            GraphQL error or userError.
        """
        mutation = """
        mutation deleteCustomerMetafield($metafields: [MetafieldIdentifierInput!]!) {
            metafieldsDelete(metafields: $metafields) {
                deletedMetafields { ownerId key }
                userErrors { field message }
            }
        }
        """
        variables = {
            "metafields": [{
                "ownerId": f"gid://shopify/Customer/{customer_id}",
                "namespace": "custom",
                "key": key,
            }]
        }

        data = self._graphql_request(mutation, variables)
        if not data:
            return False

        result = data.get("metafieldsDelete") or {}
        user_errors = result.get("userErrors") or []
        if user_errors:
            logger.error(
                f"Customer metafield delete failed "
                f"(customer {customer_id}, custom.{key}): {user_errors}"
            )
            return False

        logger.info(f"Deleted custom.{key} from customer {customer_id}")
        return True
