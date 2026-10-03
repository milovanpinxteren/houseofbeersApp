"""
Tests for the prize-fulfillment Shopify primitives (livestream raffles &
auctions): unlisted product creation, draft-order attach, order editing.
All Shopify traffic is mocked at the `_graphql_request` boundary, same as
the discount tests in users/tests.py.
"""
from unittest.mock import MagicMock, patch

import requests
from django.test import SimpleTestCase, override_settings

from users.services.shopify import ShopifyService


def _search_empty():
    return {'products': {'edges': []}}


def _search_match(title='Prijs X', tags=None):
    return {'products': {'edges': [{'node': {
        'id': 'gid://shopify/Product/11',
        'title': title,
        'tags': tags if tags is not None else ['livestream-prize'],
        'variants': {'nodes': [{
            'id': 'gid://shopify/ProductVariant/21',
            'inventoryItem': {'id': 'gid://shopify/InventoryItem/31'},
        }]},
    }}]}}


def _product_create():
    return {'productCreate': {
        'product': {
            'id': 'gid://shopify/Product/12',
            'variants': {'nodes': [{
                'id': 'gid://shopify/ProductVariant/22',
                'inventoryItem': {'id': 'gid://shopify/InventoryItem/32'},
            }]},
        },
        'userErrors': [],
    }}


def _bulk_update(variant_gid='gid://shopify/ProductVariant/22',
                 inventory_item_gid='gid://shopify/InventoryItem/32'):
    return {'productVariantsBulkUpdate': {
        'productVariants': [{
            'id': variant_gid,
            'inventoryItem': {'id': inventory_item_gid},
        }],
        'userErrors': [],
    }}


def _inventory_ok():
    return {'inventorySetQuantities': {
        'inventoryAdjustmentGroup': {'reason': 'correction'},
        'userErrors': [],
    }}


def _publications():
    return {'publications': {'edges': [
        {'node': {'id': 'gid://shopify/Publication/1', 'name': 'Online Store'}},
        {'node': {'id': 'gid://shopify/Publication/2', 'name': 'POS'}},
    ]}}


def _publish_ok():
    return {'publishablePublish': {'userErrors': []}}


def _media_ok():
    return {'productCreateMedia': {'media': [], 'mediaUserErrors': []}}


@override_settings(SHOPIFY_LOCATION_ID='123')
class CreateUnlistedProductTests(SimpleTestCase):

    def test_happy_path_creates_configures_publishes_and_attaches_image(self):
        service = ShopifyService()
        with patch.object(service, '_graphql_request') as mock_gql:
            mock_gql.side_effect = [
                _search_empty(),      # idempotency search
                _product_create(),    # productCreate
                _bulk_update(),       # price/taxable/tracked
                _inventory_ok(),      # inventorySetQuantities
                _publications(),      # publications lookup (cached after)
                _publish_ok(),        # publishablePublish
                _media_ok(),          # productCreateMedia (fresh create only)
            ]
            result = service.create_unlisted_product(
                'Prijs X', price=210, quantity=3,
                image_url='https://img.example/x.jpg',
            )

        self.assertEqual(result['product_gid'], 'gid://shopify/Product/12')
        self.assertEqual(result['variant_gid'], 'gid://shopify/ProductVariant/22')
        self.assertEqual(result['inventory_item_gid'], 'gid://shopify/InventoryItem/32')
        self.assertFalse(result['reused'])
        self.assertTrue(result['published'])
        self.assertEqual(mock_gql.call_count, 7)

        create_input = mock_gql.call_args_list[1].args[1]['product']
        self.assertEqual(create_input['status'], 'UNLISTED')
        self.assertIn('livestream-prize', create_input['tags'])

        bulk_vars = mock_gql.call_args_list[2].args[1]
        self.assertEqual(bulk_vars['variants'][0]['price'], '210')
        self.assertTrue(bulk_vars['variants'][0]['taxable'])
        self.assertTrue(bulk_vars['variants'][0]['inventoryItem']['tracked'])

        inv_vars = mock_gql.call_args_list[3].args[1]
        quantities = inv_vars['input']['quantities'][0]
        # Bare numeric setting must be normalised to a Location GID
        self.assertEqual(quantities['locationId'], 'gid://shopify/Location/123')
        self.assertEqual(quantities['quantity'], 3)
        self.assertTrue(inv_vars['idempotencyKey'])

        media_vars = mock_gql.call_args_list[6].args[1]
        self.assertEqual(media_vars['media'][0]['originalSource'],
                         'https://img.example/x.jpg')

    def test_existing_title_is_reused_and_reconfigured(self):
        service = ShopifyService()
        with patch.object(service, '_graphql_request') as mock_gql:
            mock_gql.side_effect = [
                _search_match('Prijs X'),
                _bulk_update('gid://shopify/ProductVariant/21',
                             'gid://shopify/InventoryItem/31'),
                _inventory_ok(),
                _publications(),
                _publish_ok(),
            ]
            result = service.create_unlisted_product(
                'Prijs X', price=0, quantity=1,
                image_url='https://img.example/x.jpg',
            )

        self.assertTrue(result['reused'])
        self.assertEqual(result['product_gid'], 'gid://shopify/Product/11')
        # No productCreate and — crucially — no second image attach
        self.assertEqual(mock_gql.call_count, 5)
        queries = [call.args[0] for call in mock_gql.call_args_list]
        self.assertFalse(any('productCreate(' in q for q in queries))
        self.assertFalse(any('productCreateMedia' in q for q in queries))

    def test_title_match_without_prize_tag_is_not_reused(self):
        service = ShopifyService()
        with patch.object(service, '_graphql_request') as mock_gql:
            mock_gql.side_effect = [
                _search_match('Prijs X', tags=['something-else']),
                _product_create(),
                _bulk_update(),
                _inventory_ok(),
                _publications(),
                _publish_ok(),
            ]
            result = service.create_unlisted_product('Prijs X', price=5, quantity=1)

        self.assertFalse(result['reused'])
        self.assertEqual(result['product_gid'], 'gid://shopify/Product/12')

    def test_failed_search_aborts_without_creating(self):
        service = ShopifyService()
        with patch.object(service, '_graphql_request', return_value=None) as mock_gql:
            result = service.create_unlisted_product('Prijs X', price=5, quantity=1)
        self.assertIsNone(result)
        self.assertEqual(mock_gql.call_count, 1)

    @override_settings(SHOPIFY_LOCATION_ID='')
    def test_without_location_variant_is_untracked_and_inventory_skipped(self):
        service = ShopifyService()
        with patch.object(service, '_graphql_request') as mock_gql:
            mock_gql.side_effect = [
                _search_empty(),
                _product_create(),
                _bulk_update(),
                _publications(),
                _publish_ok(),
            ]
            result = service.create_unlisted_product('Prijs X', price=5, quantity=1)

        self.assertIsNotNone(result)
        bulk_vars = mock_gql.call_args_list[2].args[1]
        self.assertFalse(bulk_vars['variants'][0]['inventoryItem']['tracked'])
        queries = [call.args[0] for call in mock_gql.call_args_list]
        self.assertFalse(any('inventorySetQuantities' in q for q in queries))

    def test_variant_update_failure_returns_none(self):
        service = ShopifyService()
        with patch.object(service, '_graphql_request') as mock_gql:
            mock_gql.side_effect = [
                _search_empty(),
                _product_create(),
                {'productVariantsBulkUpdate': {
                    'productVariants': [],
                    'userErrors': [{'field': 'price', 'message': 'nope'}],
                }},
            ]
            result = service.create_unlisted_product('Prijs X', price=5, quantity=1)
        self.assertIsNone(result)


def _draft_lines_response(lines):
    return {'node': {
        'id': 'gid://shopify/DraftOrder/51',
        'status': 'OPEN',
        'lineItems': {'edges': [{'node': line} for line in lines]},
    }}


def _draft_update_ok():
    return {'draftOrderUpdate': {
        'draftOrder': {'id': 'gid://shopify/DraftOrder/51',
                       'invoiceUrl': 'https://pay.example/51'},
        'userErrors': [],
    }}


class DraftOrderTests(SimpleTestCase):

    VARIANT_A = 'gid://shopify/ProductVariant/100'
    VARIANT_B = 'gid://shopify/ProductVariant/200'

    def _existing_lines(self):
        return [
            {'quantity': 1, 'title': 'Beer A',
             'originalUnitPriceSet': {'shopMoney': {'amount': '12.50'}},
             'variant': {'id': self.VARIANT_A}},
            {'quantity': 2, 'title': 'Handwritten line',
             'originalUnitPriceSet': {'shopMoney': {'amount': '5.00'}},
             'variant': None},
        ]

    def test_adding_existing_variant_bumps_quantity_and_keeps_custom_lines(self):
        service = ShopifyService()
        with patch.object(service, '_graphql_request') as mock_gql:
            mock_gql.side_effect = [
                _draft_lines_response(self._existing_lines()),
                _draft_update_ok(),
            ]
            result = service.add_to_draft_order(
                'gid://shopify/DraftOrder/51', self.VARIANT_A, 1
            )

        self.assertEqual(result['draft_gid'], 'gid://shopify/DraftOrder/51')
        sent = mock_gql.call_args_list[1].args[1]['input']['lineItems']
        self.assertEqual(sent, [
            {'variantId': self.VARIANT_A, 'quantity': 2},
            {'title': 'Handwritten line', 'originalUnitPrice': '5.00',
             'quantity': 2},
        ])

    def test_adding_new_variant_appends_line(self):
        service = ShopifyService()
        with patch.object(service, '_graphql_request') as mock_gql:
            mock_gql.side_effect = [
                _draft_lines_response(self._existing_lines()),
                _draft_update_ok(),
            ]
            service.add_to_draft_order(
                'gid://shopify/DraftOrder/51', self.VARIANT_B, 1
            )

        sent = mock_gql.call_args_list[1].args[1]['input']['lineItems']
        self.assertIn({'variantId': self.VARIANT_A, 'quantity': 1}, sent)
        self.assertIn({'variantId': self.VARIANT_B, 'quantity': 1}, sent)

    def test_find_open_draft_skips_completed_and_returns_open(self):
        service = ShopifyService()
        response = {'draftOrders': {'edges': [
            {'node': {'id': 'gid://shopify/DraftOrder/90', 'status': 'COMPLETED',
                      'invoiceUrl': None, 'lineItems': {'edges': []}}},
            {'node': {'id': 'gid://shopify/DraftOrder/91', 'status': 'INVOICE_SENT',
                      'invoiceUrl': 'https://pay.example/91',
                      'lineItems': {'edges': [
                          {'node': {'quantity': 1,
                                    'variant': {'id': self.VARIANT_A}}},
                          {'node': {'quantity': 1, 'variant': None}},
                      ]}}},
        ]}}
        with patch.object(service, '_graphql_request', return_value=response):
            found = service.find_open_draft_order(777)

        self.assertEqual(found['draft_gid'], 'gid://shopify/DraftOrder/91')
        self.assertEqual(found['status'], 'INVOICE_SENT')
        # Custom (variant-less) lines are omitted from the summary
        self.assertEqual(found['line_items'],
                         [{'variant_gid': self.VARIANT_A, 'quantity': 1}])

    def test_find_open_draft_reports_lookup_failure_as_error(self):
        service = ShopifyService()
        with patch.object(service, '_graphql_request', return_value=None):
            found = service.find_open_draft_order(777)
        self.assertEqual(found, {'error': 'draft order lookup failed'})

    def test_find_open_draft_none_when_no_open_drafts(self):
        service = ShopifyService()
        with patch.object(service, '_graphql_request',
                          return_value={'draftOrders': {'edges': []}}):
            self.assertIsNone(service.find_open_draft_order(777))

    def test_create_draft_order_builds_input(self):
        service = ShopifyService()
        response = {'draftOrderCreate': {
            'draftOrder': {'id': 'gid://shopify/DraftOrder/60',
                           'invoiceUrl': 'https://pay.example/60',
                           'status': 'OPEN'},
            'userErrors': [],
        }}
        with patch.object(service, '_graphql_request',
                          return_value=response) as mock_gql:
            created = service.create_draft_order(
                777, [{'variant_gid': self.VARIANT_A, 'quantity': 2}],
                note='Livestream prijs',
            )

        self.assertEqual(created, {'draft_gid': 'gid://shopify/DraftOrder/60',
                                   'invoice_url': 'https://pay.example/60'})
        sent = mock_gql.call_args.args[1]['input']
        self.assertEqual(sent['customerId'], 'gid://shopify/Customer/777')
        self.assertEqual(sent['lineItems'],
                         [{'variantId': self.VARIANT_A, 'quantity': 2}])
        self.assertTrue(sent['allowDiscountCodesInCheckout'])
        self.assertEqual(sent['note'], 'Livestream prijs')


class OrderEditTests(SimpleTestCase):

    VARIANT = 'gid://shopify/ProductVariant/100'

    def _begin_response(self, lines):
        return {'orderEditBegin': {
            'calculatedOrder': {
                'id': 'gid://shopify/CalculatedOrder/5',
                'lineItems': {'edges': [{'node': line} for line in lines]},
            },
            'userErrors': [],
        }}

    def _commit_ok(self):
        return {'orderEditCommit': {
            'order': {'id': 'gid://shopify/Order/900'},
            'userErrors': [],
        }}

    def test_new_variant_uses_add_variant(self):
        service = ShopifyService()
        with patch.object(service, '_graphql_request') as mock_gql:
            mock_gql.side_effect = [
                self._begin_response([]),
                {'orderEditAddVariant': {
                    'calculatedOrder': {'id': 'gid://shopify/CalculatedOrder/5'},
                    'userErrors': [],
                }},
                self._commit_ok(),
            ]
            result = service.edit_order_add_variant(900, self.VARIANT, 1)

        self.assertEqual(result, {'order_gid': 'gid://shopify/Order/900',
                                  'action': 'added'})
        add_vars = mock_gql.call_args_list[1].args[1]
        self.assertEqual(add_vars['variantId'], self.VARIANT)
        self.assertEqual(add_vars['quantity'], 1)
        commit_query = mock_gql.call_args_list[2].args[0]
        self.assertIn('notifyCustomer: false', commit_query)

    def test_existing_variant_uses_set_quantity(self):
        service = ShopifyService()
        existing_line = {
            'id': 'gid://shopify/CalculatedLineItem/7',
            'quantity': 2,
            'variant': {'id': self.VARIANT},
        }
        with patch.object(service, '_graphql_request') as mock_gql:
            mock_gql.side_effect = [
                self._begin_response([existing_line]),
                {'orderEditSetQuantity': {
                    'calculatedOrder': {'id': 'gid://shopify/CalculatedOrder/5'},
                    'userErrors': [],
                }},
                self._commit_ok(),
            ]
            result = service.edit_order_add_variant(900, self.VARIANT, 1)

        self.assertEqual(result['action'], 'quantity_set')
        set_vars = mock_gql.call_args_list[1].args[1]
        self.assertEqual(set_vars['lineItemId'],
                         'gid://shopify/CalculatedLineItem/7')
        self.assertEqual(set_vars['quantity'], 3)  # 2 existing + 1 added

    def test_mid_flow_failure_reports_calculated_order(self):
        service = ShopifyService()
        with patch.object(service, '_graphql_request') as mock_gql:
            mock_gql.side_effect = [
                self._begin_response([]),
                {'orderEditAddVariant': {
                    'calculatedOrder': None,
                    'userErrors': [{'field': 'variantId', 'message': 'gone'}],
                }},
            ]
            result = service.edit_order_add_variant(900, self.VARIANT, 1)

        self.assertEqual(result['error'], 'orderEditAddVariant failed')
        self.assertEqual(result['calculated_order_gid'],
                         'gid://shopify/CalculatedOrder/5')
        self.assertEqual(mock_gql.call_count, 2)  # no commit attempted

    def test_begin_failure(self):
        service = ShopifyService()
        with patch.object(service, '_graphql_request', return_value=None):
            result = service.edit_order_add_variant(900, self.VARIANT, 1)
        self.assertEqual(result, {'error': 'orderEditBegin failed'})


class AttachRouterTests(SimpleTestCase):

    VARIANT = 'gid://shopify/ProductVariant/100'

    def test_open_draft_routes_to_update(self):
        service = ShopifyService()
        with patch.object(service, 'find_open_draft_order', return_value={
            'draft_gid': 'gid://shopify/DraftOrder/51', 'status': 'OPEN',
            'invoice_url': 'https://pay.example/51', 'line_items': [],
        }), patch.object(service, 'add_to_draft_order', return_value={
            'draft_gid': 'gid://shopify/DraftOrder/51',
            'invoice_url': 'https://pay.example/51',
        }) as mock_add, patch.object(
            service, 'create_draft_order'
        ) as mock_create:
            result = service.attach_variant_to_customer(777, self.VARIANT)

        self.assertEqual(result['action'], 'draft_updated')
        self.assertEqual(result['draft_gid'], 'gid://shopify/DraftOrder/51')
        mock_add.assert_called_once_with('gid://shopify/DraftOrder/51',
                                         self.VARIANT, 1)
        mock_create.assert_not_called()

    def test_no_draft_routes_to_create(self):
        service = ShopifyService()
        with patch.object(service, 'find_open_draft_order', return_value=None), \
             patch.object(service, 'create_draft_order', return_value={
                 'draft_gid': 'gid://shopify/DraftOrder/60',
                 'invoice_url': 'https://pay.example/60',
             }) as mock_create:
            result = service.attach_variant_to_customer(777, self.VARIANT, 2)

        self.assertEqual(result['action'], 'draft_created')
        mock_create.assert_called_once_with(
            777, [{'variant_gid': self.VARIANT, 'quantity': 2}]
        )

    def test_lookup_failure_aborts_instead_of_creating_duplicate(self):
        service = ShopifyService()
        with patch.object(service, 'find_open_draft_order',
                          return_value={'error': 'draft order lookup failed'}), \
             patch.object(service, 'create_draft_order') as mock_create:
            result = service.attach_variant_to_customer(777, self.VARIANT)

        self.assertEqual(result, {'error': 'draft order lookup failed'})
        mock_create.assert_not_called()


class ThrottleRetryTests(SimpleTestCase):

    def _response(self, status_code=200, payload=None):
        response = MagicMock()
        response.status_code = status_code
        if status_code >= 400:
            response.raise_for_status.side_effect = (
                requests.exceptions.HTTPError(response=response)
            )
            response.text = 'throttled'
        else:
            response.raise_for_status.return_value = None
            response.json.return_value = payload
        return response

    @patch('users.services.shopify.time.sleep')
    @patch('users.services.shopify.requests.post')
    def test_429_is_retried_when_retries_allowed(self, mock_post, mock_sleep):
        service = ShopifyService()
        mock_post.side_effect = [
            self._response(429),
            self._response(200, {'data': {'ok': True}}),
        ]
        result = service._graphql_request('query {}', retries=3)
        self.assertEqual(result, {'ok': True})
        self.assertEqual(mock_post.call_count, 2)
        mock_sleep.assert_called_once()

    @patch('users.services.shopify.time.sleep')
    @patch('users.services.shopify.requests.post')
    def test_throttled_graphql_error_is_retried(self, mock_post, mock_sleep):
        service = ShopifyService()
        mock_post.side_effect = [
            self._response(200, {'errors': [
                {'message': 'Throttled',
                 'extensions': {'code': 'THROTTLED'}},
            ]}),
            self._response(200, {'data': {'ok': True}}),
        ]
        result = service._graphql_request('query {}', retries=3)
        self.assertEqual(result, {'ok': True})
        self.assertEqual(mock_post.call_count, 2)

    @patch('users.services.shopify.time.sleep')
    @patch('users.services.shopify.requests.post')
    def test_429_without_retries_returns_none(self, mock_post, mock_sleep):
        service = ShopifyService()
        mock_post.side_effect = [self._response(429)]
        result = service._graphql_request('query {}')
        self.assertIsNone(result)
        self.assertEqual(mock_post.call_count, 1)

    @patch('users.services.shopify.requests.post')
    def test_api_version_override_changes_url(self, mock_post):
        service = ShopifyService()
        mock_post.side_effect = [
            self._response(200, {'data': {}}),
            self._response(200, {'data': {}}),
        ]
        service._graphql_request('query {}')
        default_url = mock_post.call_args.args[0]
        self.assertIn('/2024-01/', default_url)

        service._graphql_request('query {}', api_version='2026-04')
        override_url = mock_post.call_args.args[0]
        self.assertIn('/2026-04/', override_url)
