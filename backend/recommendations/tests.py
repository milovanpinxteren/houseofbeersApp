from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import override_settings
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from users.services.shopify import ShopifyService
from .views import PRODUCT_CACHE_KEY

User = get_user_model()


def _product(**overrides):
    product = {
        'id': 1,
        'title': 'Test IPA',
        'product_type': 'IPA',
        'tags': ['hoppy', 'new'],
        'price': '4.50',
        'image_url': 'https://cdn.shopify.com/ipa.jpg',
        'handle': 'test-ipa',
    }
    product.update(overrides)
    return product


PRODUCTS = [
    _product(id=1, title='Test IPA', product_type='IPA', tags=['hoppy'],
             price='4.50', handle='test-ipa'),
    _product(id=2, title='Dark Stout', product_type='Stout', tags=['dark', 'roasty'],
             price='6.95', handle='dark-stout'),
    _product(id=3, title='Sour Ale', product_type='Sour', tags=['fruity'],
             price='12.00', handle='sour-ale'),
    _product(id=4, title='Mystery Beer', product_type='', tags=['ipa'],
             price=None, handle='mystery-beer'),
]


@override_settings(CACHES={
    'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}
})
class RandomBeerViewTests(APITestCase):
    """GET /api/recommendations/random-beer/ — filtering, empty case, cache."""

    def setUp(self):
        self.url = reverse('random-beer')
        self.user = User.objects.create_user(
            username='beerfan', email='beerfan@example.com', password='SuperSecret123!'
        )
        self.client.force_authenticate(user=self.user)
        cache.delete(PRODUCT_CACHE_KEY)

        patcher = patch('recommendations.views.ShopifyService')
        self.mock_shopify_cls = patcher.start()
        self.addCleanup(patcher.stop)
        self.mock_service = self.mock_shopify_cls.return_value
        self.mock_service.get_active_products.return_value = list(PRODUCTS)

    def test_requires_authentication(self):
        self.client.force_authenticate(user=None)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_returns_random_beer_with_shop_url_and_styles(self):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data['found'])
        beer = response.data['beer']
        self.assertIn(beer['id'], [p['id'] for p in PRODUCTS])
        self.assertEqual(
            beer['shop_url'],
            f"https://houseofbeers.nl/products/{beer['handle']}"
        )
        # Distinct, non-empty product types, sorted (product 4 has none)
        self.assertEqual(response.data['styles'], ['IPA', 'Sour', 'Stout'])

    def test_style_filter_matches_product_type_case_insensitive(self):
        response = self.client.get(self.url, {'style': 'stout'})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data['found'])
        self.assertEqual(response.data['beer']['id'], 2)

    def test_style_filter_matches_tags(self):
        # 'hoppy' is only a tag, never a product_type
        response = self.client.get(self.url, {'style': 'HOPPY'})

        self.assertTrue(response.data['found'])
        self.assertEqual(response.data['beer']['id'], 1)

    def test_style_filter_matches_type_or_tag(self):
        # 'ipa' matches product 1 (type) and product 4 (tag)
        response = self.client.get(self.url, {'style': 'ipa'})

        self.assertTrue(response.data['found'])
        self.assertIn(response.data['beer']['id'], [1, 4])

    def test_max_price_filter(self):
        response = self.client.get(self.url, {'max_price': '5.00'})

        self.assertTrue(response.data['found'])
        # Only product 1 (4.50) is <= 5.00; products without a price are excluded
        self.assertEqual(response.data['beer']['id'], 1)

    def test_combined_filters(self):
        response = self.client.get(self.url, {'style': 'stout', 'max_price': '7.00'})

        self.assertTrue(response.data['found'])
        self.assertEqual(response.data['beer']['id'], 2)

    def test_no_match_returns_found_false_with_styles(self):
        response = self.client.get(self.url, {'style': 'stout', 'max_price': '1.00'})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(response.data['found'])
        self.assertNotIn('beer', response.data)
        # Styles still included so the client can offer looser filters
        self.assertEqual(response.data['styles'], ['IPA', 'Sour', 'Stout'])

    def test_unknown_style_returns_found_false(self):
        response = self.client.get(self.url, {'style': 'Barleywine'})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(response.data['found'])

    def test_empty_product_list_returns_found_false(self):
        self.mock_service.get_active_products.return_value = []

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(response.data['found'])
        self.assertEqual(response.data['styles'], [])

    def test_styles_only_returns_styles_without_a_beer(self):
        response = self.client.get(self.url, {'styles_only': '1'})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, {'styles': ['IPA', 'Sour', 'Stout']})

    def test_invalid_max_price_rejected(self):
        response = self.client.get(self.url, {'max_price': 'abc'})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_product_list_is_cached_between_spins(self):
        self.client.get(self.url)
        self.client.get(self.url)

        self.assertEqual(self.mock_service.get_active_products.call_count, 1)

    def test_empty_product_list_is_not_cached(self):
        """A failed/empty Shopify fetch must not pin an empty list for 15 min."""
        self.mock_service.get_active_products.return_value = []
        self.client.get(self.url)

        self.mock_service.get_active_products.return_value = list(PRODUCTS)
        response = self.client.get(self.url)

        self.assertTrue(response.data['found'])
        self.assertEqual(self.mock_service.get_active_products.call_count, 2)


class GetActiveProductsTests(APITestCase):
    """ShopifyService.get_active_products — parsing and stock filtering."""

    def _raw_product(self, **overrides):
        product = {
            'id': 10,
            'title': 'Raw IPA',
            'product_type': 'IPA',
            'tags': 'hoppy, new ',
            'handle': 'raw-ipa',
            'created_at': '2026-08-01T12:00:00+02:00',
            'image': {'src': 'https://cdn.shopify.com/raw.jpg'},
            'variants': [{
                'id': 501,
                'price': '5.25',
                'inventory_management': 'shopify',
                'inventory_policy': 'deny',
                'inventory_quantity': 3,
            }],
        }
        product.update(overrides)
        return product

    @patch.object(ShopifyService, '_paginated_request')
    def test_parses_product_fields(self, mock_request):
        mock_request.return_value = [self._raw_product()]

        products = ShopifyService().get_active_products()

        mock_request.assert_called_once_with(
            'products.json?limit=250&status=active', data_key='products'
        )
        self.assertEqual(len(products), 1)
        self.assertEqual(products[0], {
            'id': 10,
            'title': 'Raw IPA',
            'product_type': 'IPA',
            'tags': ['hoppy', 'new'],
            'price': '5.25',
            'variant_id': '501',
            'image_url': 'https://cdn.shopify.com/raw.jpg',
            'handle': 'raw-ipa',
            'created_at': '2026-08-01T12:00:00+02:00',
        })

    @patch.object(ShopifyService, '_paginated_request')
    def test_excludes_out_of_stock_products(self, mock_request):
        out_of_stock = self._raw_product(id=11, variants=[{
            'price': '5.25',
            'inventory_management': 'shopify',
            'inventory_policy': 'deny',
            'inventory_quantity': 0,
        }])
        mock_request.return_value = [self._raw_product(), out_of_stock]

        products = ShopifyService().get_active_products()

        self.assertEqual([p['id'] for p in products], [10])

    @patch.object(ShopifyService, '_paginated_request')
    def test_untracked_inventory_counts_as_in_stock(self, mock_request):
        untracked = self._raw_product(id=12, variants=[{
            'price': '3.00',
            'inventory_management': None,
            'inventory_quantity': 0,
        }])
        mock_request.return_value = [untracked]

        products = ShopifyService().get_active_products()

        self.assertEqual([p['id'] for p in products], [12])

    @patch.object(ShopifyService, '_paginated_request')
    def test_continue_policy_counts_as_in_stock(self, mock_request):
        oversellable = self._raw_product(id=13, variants=[{
            'price': '3.00',
            'inventory_management': 'shopify',
            'inventory_policy': 'continue',
            'inventory_quantity': 0,
        }])
        mock_request.return_value = [oversellable]

        products = ShopifyService().get_active_products()

        self.assertEqual([p['id'] for p in products], [13])

    @patch.object(ShopifyService, '_paginated_request')
    def test_product_without_variants_is_excluded(self, mock_request):
        mock_request.return_value = [self._raw_product(id=14, variants=[])]

        products = ShopifyService().get_active_products()

        self.assertEqual(products, [])


def _app_only_node(**overrides):
    """Raw GraphQL node for an app-only product (Sale + App variant)."""
    node = {
        'id': 'gid://shopify/Product/100',
        'legacyResourceId': '100',
        'title': 'Sale X - A - Test Gueuze',
        'handle': 'sale-x-a-test-gueuze',
        'status': 'UNLISTED',
        'tags': ['app-only'],
        'createdAt': '2026-08-01T10:00:00Z',
        'description': 'A test beer.',
        'featuredImage': None,
        'variants': {'edges': [
            {'node': {
                'id': 'gid://shopify/ProductVariant/11', 'legacyResourceId': '11',
                'price': '10.00', 'inventoryQuantity': 3,
                'selectedOptions': [{'name': 'Editie', 'value': 'Sale'}],
            }},
            {'node': {
                'id': 'gid://shopify/ProductVariant/22', 'legacyResourceId': '22',
                'price': '12.50', 'inventoryQuantity': 7,
                'selectedOptions': [{'name': 'Editie', 'value': 'App'}],
            }},
        ]},
        'metafields': {'edges': [
            {'node': {'key': 'app_title', 'value': 'Test Gueuze', 'type': 'single_line_text_field'}},
        ]},
    }
    node.update(overrides)
    return node


def _set_app_inventory(node, quantity):
    node['variants']['edges'][1]['node']['inventoryQuantity'] = quantity
    return node


class ParseAppOnlyProductTests(APITestCase):
    """
    ShopifyService._parse_app_only_product — buyability rules.

    Archived products (tag app-archived, App variant zeroed by the hob
    pipeline when a newer sale arrives) stay visible as the gemist wall;
    non-archived products with zero inventory are simply sold out and drop.
    """

    def test_buyable_product_has_both_prices(self):
        parsed = ShopifyService._parse_app_only_product(_app_only_node())
        self.assertTrue(parsed['buyable'])
        self.assertEqual(parsed['price'], '12.50')       # App variant
        self.assertEqual(parsed['sale_price'], '10.00')  # WhatsApp deal price
        self.assertEqual(parsed['variant_id'], '22')     # never variants[0]
        self.assertEqual(parsed['inventory'], 7)

    def test_archived_zero_inventory_is_kept_as_not_buyable(self):
        node = _set_app_inventory(
            _app_only_node(tags=['app-only', 'app-archived']), 0)
        parsed = ShopifyService._parse_app_only_product(node)
        self.assertIsNotNone(parsed)
        self.assertFalse(parsed['buyable'])
        self.assertEqual(parsed['sale_price'], '10.00')

    def test_archived_with_leftover_inventory_is_still_not_buyable(self):
        # Belt-and-braces: the tag alone closes the window, even if zeroing
        # the variant failed or lagged.
        node = _app_only_node(tags=['app-only', 'app-archived'])
        parsed = ShopifyService._parse_app_only_product(node)
        self.assertFalse(parsed['buyable'])

    def test_sold_out_without_archive_tag_is_dropped(self):
        node = _set_app_inventory(_app_only_node(), 0)
        self.assertIsNone(ShopifyService._parse_app_only_product(node))

    def test_product_without_app_variant_is_dropped(self):
        node = _app_only_node()
        node['variants']['edges'] = node['variants']['edges'][:1]  # Sale only
        self.assertIsNone(ShopifyService._parse_app_only_product(node))

    def _node_with_eta(self, value):
        node = _app_only_node()
        node['metafields']['edges'].append({'node': {
            'key': 'estimated_delivery_date', 'value': value, 'type': 'date'}})
        return node

    def test_future_eta_marks_the_product_as_preorder(self):
        # Pre-order beer (sold before the brewery delivery arrives) stays
        # buyable in the app — deliberately — but must carry its ETA so the
        # UI can say so.
        from datetime import date, timedelta
        eta = (date.today() + timedelta(days=5)).isoformat()
        parsed = ShopifyService._parse_app_only_product(self._node_with_eta(eta))
        self.assertEqual(parsed['estimated_delivery_date'], eta)
        self.assertTrue(parsed['buyable'])

    def test_past_eta_is_dropped(self):
        # hob pushes ETAs forward when shipments slip, so a passed date means
        # the beer arrived — showing it would read as stale.
        from datetime import date, timedelta
        eta = (date.today() - timedelta(days=1)).isoformat()
        parsed = ShopifyService._parse_app_only_product(self._node_with_eta(eta))
        self.assertIsNone(parsed['estimated_delivery_date'])

    def test_unparseable_eta_is_dropped_not_crashed(self):
        parsed = ShopifyService._parse_app_only_product(
            self._node_with_eta('soon™'))
        self.assertIsNone(parsed['estimated_delivery_date'])

    def test_no_eta_metafield_means_none(self):
        parsed = ShopifyService._parse_app_only_product(_app_only_node())
        self.assertIsNone(parsed['estimated_delivery_date'])

    @patch.object(ShopifyService, '_graphql_request')
    def test_sorted_buyable_first_then_newest(self, mock_graphql):
        def make(pid, created_at, tags=('app-only',)):
            node = _app_only_node(
                id=f'gid://shopify/Product/{pid}', legacyResourceId=str(pid),
                createdAt=created_at, tags=list(tags))
            if 'app-archived' in tags:
                _set_app_inventory(node, 0)
            return {'node': node}

        mock_graphql.return_value = {'products': {
            'pageInfo': {'hasNextPage': False, 'endCursor': None},
            'edges': [
                make(1, '2026-08-01T10:00:00Z'),
                make(2, '2026-07-01T10:00:00Z', ('app-only', 'app-archived')),
                make(3, '2026-08-15T10:00:00Z'),
                make(4, '2026-07-20T10:00:00Z', ('app-only', 'app-archived')),
            ],
        }}

        products = ShopifyService().get_app_only_products()

        self.assertEqual([p['id'] for p in products], ['3', '1', '4', '2'])


def _presale_node(**overrides):
    """Raw GraphQL node for a presale leftover product (single variant,
    no Editie option — unlike app-only products)."""
    node = {
        'id': 'gid://shopify/Product/200',
        'legacyResourceId': '200',
        'title': 'Presale Run 5 - Test Tripel',
        'handle': 'presale-run-5-test-tripel',
        'status': 'ACTIVE',
        'tags': ['presale', 'presale-run-5'],
        'createdAt': '2026-11-01T10:00:00Z',
        'description': 'A presale beer.',
        'featuredImage': None,
        'variants': {'edges': [
            {'node': {
                'id': 'gid://shopify/ProductVariant/55', 'legacyResourceId': '55',
                'price': '9.00', 'inventoryQuantity': 48,
                'selectedOptions': [],
            }},
        ]},
        'metafields': {'edges': []},
    }
    node.update(overrides)
    return node


def _set_presale_inventory(node, quantity):
    node['variants']['edges'][0]['node']['inventoryQuantity'] = quantity
    return node


class ParsePresaleProductTests(APITestCase):
    """
    ShopifyService._parse_presale_product — single-variant presale items.

    Deliberately NOT the same rules as app-only in most respects: no
    app-archived concept, and a past ETA is never dropped (the management
    system pulls the `presale` tag server-side instead). It DOES reuse the
    app-only Editie-variant guard, for the case where a product was hand-
    tagged `presale` while still carrying a Sale/App Editie option.
    """

    def test_buyable_presale_item_has_price_and_variant(self):
        parsed = ShopifyService._parse_presale_product(_presale_node())
        self.assertTrue(parsed['buyable'])
        self.assertEqual(parsed['price'], '9.00')
        self.assertEqual(parsed['sale_price'], '9.00')  # no separate WhatsApp price
        self.assertEqual(parsed['variant_id'], '55')
        self.assertEqual(parsed['inventory'], 48)
        self.assertTrue(parsed['is_presale'])

    def test_sold_out_presale_item_is_dropped_not_kept_as_not_buyable(self):
        # A sold-out presale is NOT a missed deal (no archive concept here):
        # keeping it with buyable=False would make the PWA render it on the
        # not-buyable branch, which is the "gemist" missed-deal card
        # (struck-through double prices, "sale voorbij" copy) — wrong for a
        # still-running presale. It must be dropped outright instead.
        node = _set_presale_inventory(_presale_node(), 0)
        self.assertIsNone(ShopifyService._parse_presale_product(node))

    def test_negative_inventory_is_also_dropped(self):
        node = _set_presale_inventory(_presale_node(), -1)
        self.assertIsNone(ShopifyService._parse_presale_product(node))

    def test_product_without_variants_is_dropped(self):
        node = _presale_node()
        node['variants']['edges'] = []
        self.assertIsNone(ShopifyService._parse_presale_product(node))

    def test_editie_tagged_product_uses_app_variant_not_variants_zero(self):
        # A human could hand-tag a regular two-variant (Editie Sale/App)
        # product `presale` in Shopify admin. variants[0] must never win
        # here — it would expose the Sale variant's WhatsApp price and full
        # sale inventory in the app.
        node = _presale_node()
        node['variants']['edges'] = [
            {'node': {
                'id': 'gid://shopify/ProductVariant/11', 'legacyResourceId': '11',
                'price': '10.00', 'inventoryQuantity': 3,
                'selectedOptions': [{'name': 'Editie', 'value': 'Sale'}],
            }},
            {'node': {
                'id': 'gid://shopify/ProductVariant/22', 'legacyResourceId': '22',
                'price': '12.50', 'inventoryQuantity': 7,
                'selectedOptions': [{'name': 'Editie', 'value': 'App'}],
            }},
        ]
        parsed = ShopifyService._parse_presale_product(node)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed['variant_id'], '22')
        self.assertEqual(parsed['price'], '12.50')
        self.assertEqual(parsed['inventory'], 7)

    def test_editie_tagged_product_without_app_variant_is_skipped(self):
        # Only a Sale variant exists (no App variant at all) — there is no
        # safe variant to expose, so the product is skipped entirely rather
        # than falling back to variants[0] (which would be the Sale variant).
        node = _presale_node()
        node['variants']['edges'] = [
            {'node': {
                'id': 'gid://shopify/ProductVariant/11', 'legacyResourceId': '11',
                'price': '10.00', 'inventoryQuantity': 3,
                'selectedOptions': [{'name': 'Editie', 'value': 'Sale'}],
            }},
        ]
        self.assertIsNone(ShopifyService._parse_presale_product(node))

    def _node_with_eta(self, value):
        node = _presale_node()
        node['metafields']['edges'].append({'node': {
            'key': 'estimated_delivery_date', 'value': value, 'type': 'date'}})
        return node

    def test_future_eta_is_kept(self):
        from datetime import date, timedelta
        eta = (date.today() + timedelta(days=10)).isoformat()
        parsed = ShopifyService._parse_presale_product(self._node_with_eta(eta))
        self.assertEqual(parsed['estimated_delivery_date'], eta)

    def test_past_eta_is_NOT_dropped(self):
        # Unlike app-only leftovers: a past ETA on a presale item is the
        # normal end state right up until the management system pulls the
        # `presale` tag — dropping it client-side would hide a still-live
        # presale that merely hasn't had its ETA bumped yet.
        from datetime import date, timedelta
        eta = (date.today() - timedelta(days=2)).isoformat()
        parsed = ShopifyService._parse_presale_product(self._node_with_eta(eta))
        self.assertEqual(parsed['estimated_delivery_date'], eta)

    def test_no_eta_metafield_means_none(self):
        parsed = ShopifyService._parse_presale_product(_presale_node())
        self.assertIsNone(parsed['estimated_delivery_date'])


class ParsePresaleProductTagFilterTests(APITestCase):
    """
    `_parse_presale_product`'s exact-tag filter, added after discovering
    (live data, 2026-11-15) that the GraphQL `tag:'presale'` search clause
    in get_presale_products() is only a coarse prefilter: Shopify tokenizes
    `tag:` on hyphens, so that search also returns products merely tagged
    e.g. `chicago-2025-presale` or `21-02-presale` that have never carried
    the real `presale` tag. 351 products matched the loose search; only 26
    carried the exact `presale` tag together with a `presale-run-<id>` tag.
    Two of the other 325 were still ACTIVE 2025-campaign leftovers with no
    `estimated_delivery_date` at all — exactly the shape that would have
    been served to the app as a "current" pre-order. Hence: require EXACT
    membership of `presale` in the node's tags AND at least one
    `presale-run-` prefixed tag, not just a substring/search match.
    """

    def test_node_without_exact_presale_tag_is_dropped(self):
        # Simulates a node the loose `tag:'presale'` search would return via
        # hyphen tokenization (e.g. `chicago-2025-presale`) without ever
        # carrying the real, exact `presale` tag.
        node = _presale_node(tags=['chicago-2025-presale', 'whatsapp-import'])
        self.assertIsNone(ShopifyService._parse_presale_product(node))

    def test_exact_presale_tag_without_run_tag_is_dropped(self):
        # Simulates the 143 stale WhatsApp-import products found live: the
        # exact `presale` tag IS present, but with no `presale-run-<id>`
        # tag there is no current run to attribute the listing to.
        node = _presale_node(tags=['presale', 'whatsapp-import', 'chicago'])
        self.assertIsNone(ShopifyService._parse_presale_product(node))

    def test_exact_presale_tag_with_run_tag_is_kept(self):
        node = _presale_node(tags=['presale', 'presale-run-113', 'awaiting-delivery'])
        parsed = ShopifyService._parse_presale_product(node)
        self.assertIsNotNone(parsed)
        self.assertTrue(parsed['is_presale'])

    def test_run_tag_without_exact_presale_tag_is_dropped(self):
        # A `presale-run-` tag alone (no exact `presale` tag) should never
        # happen from the hob pipeline, but the filter requires BOTH, not
        # either — belt and suspenders.
        node = _presale_node(tags=['presale-run-113', 'chicago'])
        self.assertIsNone(ShopifyService._parse_presale_product(node))


class PresaleMergeTests(APITestCase):
    """
    ShopifyService.get_app_only_products() — merging in presale leftovers
    (tag `presale`, ACTIVE status) ahead of the app-only batch.
    """

    @staticmethod
    def _graphql_side_effect(presale_edges, app_only_edges):
        def side_effect(query, variables=None, *args, **kwargs):
            if "presale" in query:
                edges = presale_edges
            else:
                edges = app_only_edges
            return {'products': {
                'pageInfo': {'hasNextPage': False, 'endCursor': None},
                'edges': edges,
            }}
        return side_effect

    @patch.object(ShopifyService, '_graphql_request')
    def test_presale_query_filters_status_active(self, mock_graphql):
        # The Admin API's product search does not implicitly filter by
        # status (see search_products's own explicit status:active) — a
        # presale flipped to DRAFT when stopped must disappear automatically,
        # so this term is load-bearing, not decorative.
        mock_graphql.side_effect = self._graphql_side_effect([], [])
        ShopifyService().get_app_only_products()
        presale_call = next(
            c for c in mock_graphql.call_args_list if "presale" in c.args[0]
        )
        self.assertIn("status:active", presale_call.args[0])

    @patch.object(ShopifyService, '_graphql_request')
    def test_presale_item_is_buyable_with_cart_url_and_sorted_first(self, mock_graphql):
        mock_graphql.side_effect = self._graphql_side_effect(
            [{'node': _presale_node()}], [{'node': _app_only_node()}],
        )
        products = ShopifyService().get_app_only_products()

        self.assertEqual(products[0]['id'], '200')
        self.assertTrue(products[0]['is_presale'])
        self.assertTrue(products[0]['buyable'])
        self.assertEqual(products[0]['variant_id'], '55')
        self.assertEqual(products[1]['id'], '100')  # the app-only batch follows

    @patch.object(ShopifyService, '_graphql_request')
    def test_draft_presale_item_is_absent(self, mock_graphql):
        # A stopped presale (DRAFT) never appears in the GraphQL response at
        # all because of the status:active term — nothing left to filter
        # client-side.
        mock_graphql.side_effect = self._graphql_side_effect([], [])
        products = ShopifyService().get_app_only_products()
        self.assertEqual(products, [])

    @patch.object(ShopifyService, '_graphql_request')
    def test_past_eta_presale_item_not_dropped_in_full_feed(self, mock_graphql):
        from datetime import date, timedelta
        eta = (date.today() - timedelta(days=3)).isoformat()
        node = _presale_node()
        node['metafields']['edges'].append({'node': {
            'key': 'estimated_delivery_date', 'value': eta, 'type': 'date'}})
        mock_graphql.side_effect = self._graphql_side_effect([{'node': node}], [])

        products = ShopifyService().get_app_only_products()

        self.assertEqual(len(products), 1)
        self.assertEqual(products[0]['estimated_delivery_date'], eta)

    @patch.object(ShopifyService, '_graphql_request')
    def test_dedupe_presale_wins_over_app_only(self, mock_graphql):
        # A product that somehow carries both tags turns up in both GraphQL
        # result sets under the same id — the presale parse must win and the
        # app-only duplicate must not also appear.
        shared_id = '100'
        presale_node = _presale_node(
            legacyResourceId=shared_id, id='gid://shopify/Product/100')
        app_only_node = _app_only_node()  # legacyResourceId '100' by default
        mock_graphql.side_effect = self._graphql_side_effect(
            [{'node': presale_node}], [{'node': app_only_node}],
        )

        products = ShopifyService().get_app_only_products()

        self.assertEqual(len(products), 1)
        self.assertEqual(products[0]['id'], '100')
        self.assertTrue(products[0]['is_presale'])

    def test_cache_key_bumped_to_v3(self):
        # The payload composition changed (presale merge) — the cache key
        # must have moved past v2 so a stale cached list can't hide the new
        # presale items behind the old TTL.
        from .views import APP_SHOP_CACHE_KEY
        self.assertTrue(APP_SHOP_CACHE_KEY.endswith(':v3'))
        self.assertNotEqual(APP_SHOP_CACHE_KEY, 'recommendations:app_only_products:v2')

    @patch.object(ShopifyService, '_graphql_request')
    def test_presale_fetch_failure_falls_back_to_app_only_only(self, mock_graphql):
        # The presale GraphQL call fails outright (None, as if the request
        # errored); the app-only batch must still come through untouched.
        def side_effect(query, variables=None, *args, **kwargs):
            if "presale" in query:
                return None
            return {'products': {
                'pageInfo': {'hasNextPage': False, 'endCursor': None},
                'edges': [{'node': _app_only_node()}],
            }}
        mock_graphql.side_effect = side_effect

        service = ShopifyService()
        products = service.get_app_only_products()

        self.assertEqual([p['id'] for p in products], ['100'])
        self.assertTrue(service.presale_fetch_failed)

    @patch.object(ShopifyService, '_graphql_request')
    def test_successful_empty_presale_does_not_set_failure_flag(self, mock_graphql):
        mock_graphql.side_effect = self._graphql_side_effect([], [])
        service = ShopifyService()
        service.get_app_only_products()
        self.assertFalse(service.presale_fetch_failed)


class GetPresaleProductsTests(APITestCase):
    """
    ShopifyService.get_presale_products — distinguishing a failed fetch
    (None) from a genuinely empty result ([]), so callers never cache a
    transient outage as "no presale items" for the long TTL.
    """

    @patch.object(ShopifyService, '_graphql_request')
    def test_first_page_failure_returns_none_not_empty_list(self, mock_graphql):
        mock_graphql.return_value = None
        self.assertIsNone(ShopifyService().get_presale_products())

    @patch.object(ShopifyService, '_graphql_request')
    def test_successful_fetch_with_no_items_returns_empty_list(self, mock_graphql):
        mock_graphql.return_value = {'products': {
            'pageInfo': {'hasNextPage': False, 'endCursor': None},
            'edges': [],
        }}
        self.assertEqual(ShopifyService().get_presale_products(), [])

    @patch.object(ShopifyService, '_graphql_request')
    def test_failure_on_a_later_page_returns_partial_results(self, mock_graphql):
        # A failure AFTER at least one successful page is a different case
        # (mid-pagination hiccup): keep what was already fetched, matching
        # _paginated_request's raise_on_error=False behavior elsewhere.
        mock_graphql.side_effect = [
            {'products': {
                'pageInfo': {'hasNextPage': True, 'endCursor': 'cursor1'},
                'edges': [{'node': _presale_node()}],
            }},
            None,
        ]
        products = ShopifyService().get_presale_products()
        self.assertEqual(len(products), 1)


@override_settings(CACHES={
    'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}
})
class AppShopCacheTtlTests(APITestCase):
    """
    _app_shop_cache_ttl / the app-shop view's cache write — a presale fetch
    failure must get the SHORT TTL even when the merged list (app-only
    leftovers included) is non-empty, so a transient presale outage is
    retried soon instead of being hidden for the long TTL.
    """

    def setUp(self):
        from .views import APP_SHOP_CACHE_KEY
        self.cache_key = APP_SHOP_CACHE_KEY
        cache.delete(self.cache_key)
        self.url = reverse('app-shop')
        self.user = User.objects.create_user(
            username='beerfan3', email='beerfan3@example.com', password='SuperSecret123!'
        )
        self.client.force_authenticate(user=self.user)

    def test_ttl_helper_uses_short_ttl_on_presale_failure_even_if_nonempty(self):
        from .views import _app_shop_cache_ttl, APP_SHOP_CACHE_TTL

        class _FakeService:
            presale_fetch_failed = True

        ttl = _app_shop_cache_ttl(_FakeService(), [{'id': '1'}])
        self.assertEqual(ttl, 300)
        self.assertNotEqual(ttl, APP_SHOP_CACHE_TTL)

    def test_ttl_helper_uses_long_ttl_when_presale_ok_and_nonempty(self):
        from .views import _app_shop_cache_ttl, APP_SHOP_CACHE_TTL

        class _FakeService:
            presale_fetch_failed = False

        self.assertEqual(_app_shop_cache_ttl(_FakeService(), [{'id': '1'}]), APP_SHOP_CACHE_TTL)

    def test_ttl_helper_defaults_to_long_ttl_when_flag_missing(self):
        # Callers that never ran get_app_only_products (e.g. a bare mock in
        # other tests) must not be treated as a presale failure.
        from .views import _app_shop_cache_ttl, APP_SHOP_CACHE_TTL

        class _FakeServiceNoFlag:
            pass

        self.assertEqual(
            _app_shop_cache_ttl(_FakeServiceNoFlag(), [{'id': '1'}]), APP_SHOP_CACHE_TTL
        )

    @patch('recommendations.views.cache.set')
    @patch('recommendations.views.ShopifyService')
    def test_view_caches_short_ttl_when_presale_fetch_failed(
        self, mock_service_cls, mock_cache_set
    ):
        from .views import APP_SHOP_CACHE_TTL

        mock_service = mock_service_cls.return_value
        mock_service.get_app_only_products.return_value = [
            {'id': '1', 'title': 'App-only leftover', 'variant_id': '22',
             'price': '12.50', 'sale_price': '10.00', 'buyable': True, 'inventory': 7},
        ]
        mock_service.presale_fetch_failed = True

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['products']), 1)
        mock_cache_set.assert_called_once()
        cached_ttl = mock_cache_set.call_args.args[2]
        self.assertEqual(cached_ttl, 300)
        self.assertNotEqual(cached_ttl, APP_SHOP_CACHE_TTL)

    @patch('recommendations.views.cache.set')
    @patch('recommendations.views.ShopifyService')
    def test_view_caches_long_ttl_when_presale_fetch_succeeds(
        self, mock_service_cls, mock_cache_set
    ):
        from .views import APP_SHOP_CACHE_TTL

        mock_service = mock_service_cls.return_value
        mock_service.get_app_only_products.return_value = [
            {'id': '1', 'title': 'App-only leftover', 'variant_id': '22',
             'price': '12.50', 'sale_price': '10.00', 'buyable': True, 'inventory': 7},
        ]
        mock_service.presale_fetch_failed = False

        self.client.get(self.url)

        cached_ttl = mock_cache_set.call_args.args[2]
        self.assertEqual(cached_ttl, APP_SHOP_CACHE_TTL)


@override_settings(CACHES={
    'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}
})
class AppShopViewTests(APITestCase):
    """GET /api/recommendations/app-shop/ — cart_url only for buyable items."""

    def setUp(self):
        from .views import APP_SHOP_CACHE_KEY
        self.url = reverse('app-shop')
        self.user = User.objects.create_user(
            username='beerfan2', email='beerfan2@example.com', password='SuperSecret123!'
        )
        self.client.force_authenticate(user=self.user)
        cache.delete(APP_SHOP_CACHE_KEY)

        patcher = patch('recommendations.views.ShopifyService')
        self.mock_service = patcher.start().return_value
        self.addCleanup(patcher.stop)

    def test_archived_products_get_no_cart_url(self):
        self.mock_service.get_app_only_products.return_value = [
            {'id': '1', 'title': 'Buyable', 'variant_id': '22',
             'price': '12.50', 'sale_price': '10.00', 'buyable': True, 'inventory': 7},
            {'id': '2', 'title': 'Gemist', 'variant_id': '33',
             'price': '13.50', 'sale_price': '11.00', 'buyable': False, 'inventory': 0},
        ]
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        products = {p['id']: p for p in response.data['products']}
        self.assertIn('/cart/22:1', products['1']['cart_url'])
        self.assertIsNone(products['2']['cart_url'])
