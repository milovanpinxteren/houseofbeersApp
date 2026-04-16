import logging
import requests
from typing import Optional
from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)


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

    def create_discount_code(
        self,
        code: str,
        discount_type: str,
        value: float,
        usage_limit: int = 1,
        customer_id: str = None,
    ) -> Optional[dict]:
        """
        Create a discount code in Shopify.

        Args:
            code: The discount code string
            discount_type: 'fixed_amount' or 'percentage'
            value: Discount value (amount in currency or percentage)
            usage_limit: Number of times the code can be used
            customer_id: Limit to specific customer (optional)

        Returns:
            Price rule data or None if failed
        """
        # First create a price rule
        price_rule_data = {
            'price_rule': {
                'title': f'Loyalty Reward - {code}',
                'target_type': 'line_item',
                'target_selection': 'all',
                'allocation_method': 'across',
                'value_type': discount_type,
                'value': str(-abs(value)),  # Shopify expects negative value
                'customer_selection': 'prerequisite' if customer_id else 'all',
                'usage_limit': usage_limit,
                'once_per_customer': True,
                'starts_at': timezone.now().isoformat(),
            }
        }

        # Add customer prerequisite if specified
        if customer_id:
            price_rule_data['price_rule']['prerequisite_customer_ids'] = [int(customer_id)]

        result = self._request('POST', 'price_rules.json', json=price_rule_data)
        if not result or 'price_rule' not in result:
            logger.error(f"Failed to create price rule for {code}")
            return None

        price_rule_id = result['price_rule']['id']

        # Now create the discount code
        discount_data = {
            'discount_code': {
                'code': code,
            }
        }

        discount_result = self._request(
            'POST',
            f'price_rules/{price_rule_id}/discount_codes.json',
            json=discount_data
        )

        if discount_result and 'discount_code' in discount_result:
            logger.info(f"Created Shopify discount code: {code}")
            return {
                'price_rule_id': price_rule_id,
                'discount_code_id': discount_result['discount_code']['id'],
                'code': code,
            }

        logger.error(f"Failed to create discount code {code}")
        return None

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

    def create_basic_discount(
        self,
        code: str,
        title: str,
        discount_type: str,
        value: float,
        usage_limit: int = 1,
        product_ids: list = None,
        applies_once_per_customer: bool = True,
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

        variables = {
            "basicCodeDiscount": {
                "title": title,
                "code": code,
                "startsAt": timezone.now().isoformat(),
                "usageLimit": usage_limit,
                "appliesOncePerCustomer": applies_once_per_customer,
                "customerSelection": {"all": True},
                "customerGets": {
                    "value": customer_gets_value,
                    "items": items
                }
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
    ) -> Optional[dict]:
        """Create a free shipping discount code."""

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
