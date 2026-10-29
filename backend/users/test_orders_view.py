"""
Tests for the orders-screen overhaul: line-item state derivation, the
chunked multi-key metafield fetch, and the UserOrdersView response contract
(orders + drafts + missed).
"""
import re
from datetime import date, timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APITestCase

from users.services.order_state import derive_line_state, display_title
from users.services.shopify import ShopifyService

User = get_user_model()

TODAY = date(2026, 10, 29)


class StateDerivationTests(TestCase):
    """Table test for the pure helper — the five states, both inputs."""

    def _state(self, **kwargs):
        defaults = dict(
            product_id='987', raw_eta=None, unresolved_ids=set(),
            today=TODAY, fulfillment_status=None,
        )
        defaults.update(kwargs)
        return derive_line_state(**defaults)

    def test_fulfilled_is_shipped(self):
        self.assertEqual(
            self._state(fulfillment_status='fulfilled'),
            ('shipped', None),
        )

    def test_partial_is_partial(self):
        self.assertEqual(
            self._state(fulfillment_status='partial'), ('partial', None),
        )

    def test_shipped_still_normalizes_eta(self):
        self.assertEqual(
            self._state(fulfillment_status='fulfilled', raw_eta='2026-11-05'),
            ('shipped', '2026-11-05'),
        )

    def test_no_eta_means_in_warehouse(self):
        self.assertEqual(self._state(raw_eta=None), ('in_warehouse', None))
        self.assertEqual(self._state(raw_eta='  '), ('in_warehouse', None))

    def test_past_eta_is_in_warehouse(self):
        self.assertEqual(
            self._state(raw_eta='2026-10-01'),
            ('in_warehouse', '2026-10-01'),
        )

    def test_eta_today_counts_as_arrived(self):
        # Matches hob's graduation rule: the ETA day itself = in warehouse.
        self.assertEqual(
            self._state(raw_eta=TODAY.isoformat()),
            ('in_warehouse', TODAY.isoformat()),
        )

    def test_future_eta_is_incoming(self):
        self.assertEqual(
            self._state(raw_eta='2026-11-15'),
            ('incoming', '2026-11-15'),
        )

    def test_datetime_prefix_is_accepted(self):
        # Defensive [:10] slice: a datetime-shaped value still parses.
        self.assertEqual(
            self._state(raw_eta='2026-11-15T00:00:00'),
            ('incoming', '2026-11-15'),
        )

    def test_garbage_value_is_unknown_and_warns(self):
        with self.assertLogs('users.services.order_state', level='WARNING') as logs:
            result = self._state(raw_eta='volgende week')
        self.assertEqual(result, ('unknown', None))
        self.assertIn('987', logs.output[0])
        self.assertIn('volgende week', logs.output[0])

    def test_unresolved_product_is_unknown(self):
        self.assertEqual(
            self._state(unresolved_ids={'987'}, raw_eta='2026-11-15'),
            ('unknown', None),
        )

    def test_unresolved_loses_to_fulfillment_status(self):
        # A shipped line is shipped no matter what the metafield fetch did.
        self.assertEqual(
            self._state(unresolved_ids={'987'}, fulfillment_status='fulfilled'),
            ('shipped', None),
        )

    def test_custom_line_without_product_is_in_warehouse(self):
        self.assertEqual(
            self._state(product_id=None), ('in_warehouse', None),
        )

    def test_display_title_prefers_app_title(self):
        self.assertEqual(
            display_title('24-10 - K - Beer', {'app_title': 'Clean Beer'}),
            'Clean Beer',
        )
        self.assertEqual(display_title('Raw Title', {}), 'Raw Title')
        self.assertEqual(display_title('Raw Title', {'app_title': '  '}),
                         'Raw Title')


class BulkMetafieldTests(TestCase):
    """get_products_metafields_bulk: chunking, retry, unresolved ids."""

    GID_RE = re.compile(r'(product_\d+): product\(id: "gid://shopify/Product/(\d+)"')

    def _service(self):
        return ShopifyService()

    def _fake_response(self, query):
        """Answer every aliased product in the query with an ETA metafield."""
        data = {}
        for alias, pid in self.GID_RE.findall(query):
            data[alias] = {
                'id': f'gid://shopify/Product/{pid}',
                'estimated_delivery_date': {'value': '2026-11-15'},
                'app_title': None,
            }
        return data

    def test_over_250_ids_chunk_into_multiple_calls(self):
        ids = [str(i) for i in range(1, 301)]
        with patch.object(ShopifyService, '_graphql_request',
                          side_effect=lambda q, *a, **kw: self._fake_response(q)) as mock_gql:
            values, unresolved = self._service().get_products_metafields_bulk(
                ids, 'custom', ['estimated_delivery_date', 'app_title'],
            )

        self.assertEqual(mock_gql.call_count, 2)
        self.assertEqual(unresolved, set())
        self.assertEqual(len(values), 300)
        self.assertEqual(
            values['42'], {'estimated_delivery_date': '2026-11-15'},
        )

    def test_failed_chunk_lands_in_unresolved(self):
        ids = [str(i) for i in range(1, 301)]
        with patch.object(ShopifyService, '_graphql_request',
                          return_value=None) as mock_gql:
            values, unresolved = self._service().get_products_metafields_bulk(
                ids, 'custom', ['estimated_delivery_date'],
            )

        # 2 chunks x (1 call + 1 retry)
        self.assertEqual(mock_gql.call_count, 4)
        self.assertEqual(values, {})
        self.assertEqual(unresolved, set(ids))

    def test_retry_once_rescues_a_blip(self):
        calls = []

        def flaky(query, *args, **kwargs):
            calls.append(query)
            if len(calls) == 1:
                return None  # first attempt fails, retry succeeds
            return self._fake_response(query)

        with patch.object(ShopifyService, '_graphql_request', side_effect=flaky):
            values, unresolved = self._service().get_products_metafields_bulk(
                ['1', '2'], 'custom', ['estimated_delivery_date'],
            )

        self.assertEqual(len(calls), 2)
        self.assertEqual(unresolved, set())
        self.assertEqual(set(values), {'1', '2'})

    def test_duplicate_ids_are_deduped(self):
        with patch.object(ShopifyService, '_graphql_request',
                          side_effect=lambda q, *a, **kw: self._fake_response(q)) as mock_gql:
            values, _ = self._service().get_products_metafields_bulk(
                ['7', 7, '7'], 'custom', ['estimated_delivery_date'],
            )
        self.assertEqual(mock_gql.call_count, 1)
        self.assertEqual(list(values), ['7'])


class UserOrdersViewTests(APITestCase):
    """The full response contract: orders + drafts + missed."""

    URL = '/api/users/me/orders/'

    def setUp(self):
        self.user = User.objects.create_user(
            username='piet@example.com', email='piet@example.com', password='x',
        )
        self.user.shopify_customer_id = '555'
        self.user.save(update_fields=['shopify_customer_id'])
        self.client.force_authenticate(user=self.user)

        self.today = date.today()
        self.future = (self.today + timedelta(days=7)).isoformat()

        self.orders = [{
            'id': 123, 'order_number': 1001, 'name': '#1001',
            'created_at': '2026-10-20T10:00:00+02:00',
            'financial_status': 'paid', 'fulfillment_status': None,
            'total_price': '86.40', 'currency': 'EUR',
            'line_items': [
                {'id': 1, 'title': 'Shipped Beer', 'variant_title': 'Sale',
                 'quantity': 2, 'price': '12.95', 'sku': None,
                 'product_id': 1, 'fulfillment_status': 'fulfilled'},
                {'id': 2, 'title': '24-10 - K - Beer', 'variant_title': 'Sale',
                 'quantity': 1, 'price': '9.95', 'sku': None,
                 'product_id': 2, 'fulfillment_status': None},
                {'id': 3, 'title': 'Shelf Beer', 'variant_title': None,
                 'quantity': 1, 'price': '4.50', 'sku': 'SKU3',
                 'product_id': 3, 'fulfillment_status': None},
            ],
        }]
        self.drafts = [{
            'id': '123456', 'name': '#D6795', 'status': 'OPEN',
            'created_at': '2026-10-27T20:00:00+02:00',
            'invoice_url': 'https://shopify.example/invoice',
            'total_price': '43.80', 'currency': 'EUR',
            'line_items': [
                {'title': '24-10 - K - Beer', 'variant_title': 'Sale',
                 'quantity': 1, 'price': '12.95', 'product_id': '2'},
                # Custom line: no variant, no product — must be kept.
                {'title': 'Verzendkosten', 'variant_title': None,
                 'quantity': 1, 'price': '7.50', 'product_id': None},
            ],
        }]
        self.metafields = (
            {'2': {'estimated_delivery_date': self.future,
                   'app_title': 'Clean Beer Name'}},
            set(),
        )

    def _get(self):
        with patch('users.views.ShopifyService') as mock_service:
            instance = mock_service.return_value
            instance.get_customer_orders.return_value = self.orders
            instance.get_customer_draft_orders.return_value = self.drafts
            instance.get_products_metafields_bulk.return_value = self.metafields
            response = self.client.get(self.URL)
        return response, instance

    def test_full_contract(self):
        from fulfillment.models import MissedItemsRecord

        # In window + attached -> shown.
        MissedItemsRecord.objects.create(
            dedupe_key='hob:missed:111:555', shopify_customer_id='555',
            sale_id=111, sale_name='26-10',
            sale_date=self.today - timedelta(days=3),
            draft_order_id='123456', status='attached', user=self.user,
            lines=[{'product_id': 2, 'title': 'Clean Beer Name',
                    'requested': 3, 'received': 1, 'reason': 'out_of_stock'}],
        )
        # Cleared -> hidden.
        MissedItemsRecord.objects.create(
            dedupe_key='hob:missed:112:555', shopify_customer_id='555',
            sale_id=112, sale_date=self.today - timedelta(days=2),
            status='cleared', user=self.user, lines=[],
        )
        # Older than 30 days -> hidden.
        MissedItemsRecord.objects.create(
            dedupe_key='hob:missed:90:555', shopify_customer_id='555',
            sale_id=90, sale_date=self.today - timedelta(days=40),
            status='attached', user=self.user,
            lines=[{'product_id': 9, 'title': 'Old', 'requested': 1,
                    'received': 0, 'reason': 'out_of_stock'}],
        )

        response, instance = self._get()
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(set(data), {'orders', 'drafts', 'missed'})

        # Orders: states + display_title + normalized ETA.
        items = data['orders'][0]['line_items']
        self.assertEqual(items[0]['state'], 'shipped')
        self.assertEqual(items[0]['display_title'], 'Shipped Beer')
        self.assertEqual(items[1]['state'], 'incoming')
        self.assertEqual(items[1]['display_title'], 'Clean Beer Name')
        self.assertEqual(items[1]['estimated_delivery_date'], self.future)
        self.assertEqual(items[2]['state'], 'in_warehouse')
        self.assertIsNone(items[2]['estimated_delivery_date'])
        # Pre-existing fields survive.
        self.assertEqual(items[0]['sku'], None)
        self.assertEqual(items[2]['sku'], 'SKU3')

        # Drafts: contract shape, custom line kept.
        draft = data['drafts'][0]
        self.assertEqual(draft['id'], '123456')
        self.assertEqual(draft['invoice_url'], 'https://shopify.example/invoice')
        self.assertEqual(draft['line_items'][0]['state'], 'incoming')
        self.assertEqual(draft['line_items'][0]['display_title'],
                         'Clean Beer Name')
        custom = draft['line_items'][1]
        self.assertIsNone(custom['product_id'])
        self.assertEqual(custom['state'], 'in_warehouse')
        self.assertEqual(custom['display_title'], 'Verzendkosten')
        self.assertEqual(custom['price'], '7.50')

        # Missed: only the in-window attached record, newest first.
        self.assertEqual(len(data['missed']), 1)
        missed = data['missed'][0]
        self.assertEqual(missed['sale_id'], 111)
        self.assertEqual(missed['sale_name'], '26-10')
        self.assertEqual(missed['draft_order_id'], '123456')
        self.assertIsNone(missed['shopify_order_id'])
        self.assertEqual(missed['lines'][0]['requested'], 3)

        # Product ids pooled from BOTH orders and drafts into ONE call.
        instance.get_products_metafields_bulk.assert_called_once()
        pooled_ids, namespace, keys = \
            instance.get_products_metafields_bulk.call_args.args
        self.assertEqual(set(pooled_ids), {'1', '2', '3'})
        self.assertEqual(namespace, 'custom')
        self.assertEqual(set(keys), {'estimated_delivery_date', 'app_title'})

    def test_pending_record_is_claimed_on_view(self):
        from fulfillment.models import MissedItemsRecord

        MissedItemsRecord.objects.create(
            dedupe_key='hob:missed:113:555', shopify_customer_id='555',
            sale_id=113, sale_date=self.today - timedelta(days=1),
            status='pending',
            lines=[{'product_id': 2, 'title': 'X', 'requested': 1,
                    'received': 0, 'reason': 'max_per_customer'}],
        )
        response, _ = self._get()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()['missed']), 1)
        record = MissedItemsRecord.objects.get(dedupe_key='hob:missed:113:555')
        self.assertEqual(record.status, 'attached')
        self.assertEqual(record.user, self.user)

    def test_unresolved_products_become_unknown(self):
        self.metafields = ({}, {'2', '3'})
        response, _ = self._get()
        items = response.json()['orders'][0]['line_items']
        self.assertEqual(items[0]['state'], 'shipped')  # status wins
        self.assertEqual(items[1]['state'], 'unknown')
        self.assertEqual(items[2]['state'], 'unknown')
        self.assertIsNone(items[1]['estimated_delivery_date'])

    def test_no_shopify_id_is_400(self):
        self.user.shopify_customer_id = None
        self.user.save(update_fields=['shopify_customer_id'])
        response, _ = self._get()
        self.assertEqual(response.status_code, 400)

    def test_shopify_failure_is_500(self):
        with patch('users.views.ShopifyService') as mock_service:
            mock_service.return_value.get_customer_orders.side_effect = \
                RuntimeError('boom')
            response = self.client.get(self.URL)
        self.assertEqual(response.status_code, 500)
        self.assertIn('error', response.json())
