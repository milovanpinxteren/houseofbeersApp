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

from users.services.order_state import (
    derive_delivery_method,
    derive_line_state,
    derive_order_outcome,
    display_title,
    merged_into_order_name,
    shipping_method_title,
)
from users.services.shopify import ShopifyService

User = get_user_model()

TODAY = date(2026, 10, 29)


class StateDerivationTests(TestCase):
    """Table test for the pure helper — the five states, both inputs."""

    def _state(self, **kwargs):
        defaults = dict(
            product_id='987', raw_eta=None, unresolved_ids=set(),
            today=TODAY, fulfillment_status=None, order_outcome=None,
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

    def test_cancelled_order_outranks_everything(self):
        # Nothing is owed, so not the ETA logic, not even a line that was
        # fulfilled before the cancellation put the stock back.
        self.assertEqual(self._state(order_outcome='cancelled'),
                         ('cancelled', None))
        self.assertEqual(
            self._state(order_outcome='cancelled', raw_eta='2026-11-15'),
            ('cancelled', None),
        )
        self.assertEqual(
            self._state(order_outcome='cancelled',
                        fulfillment_status='fulfilled'),
            ('cancelled', None),
        )
        self.assertEqual(
            self._state(order_outcome='cancelled', unresolved_ids={'987'}),
            ('cancelled', None),
        )

    def test_archived_unfulfilled_line_is_handled(self):
        self.assertEqual(self._state(order_outcome='handled'),
                         ('handled', None))

    def test_handled_beats_eta_and_unresolved_but_not_fulfilment(self):
        # An ETA means nothing once the order is closed...
        self.assertEqual(
            self._state(order_outcome='handled', raw_eta='2026-11-15'),
            ('handled', None),
        )
        # ...and 'handled' is a better answer than 'unknown'.
        self.assertEqual(
            self._state(order_outcome='handled', unresolved_ids={'987'}),
            ('handled', None),
        )
        # But a line Shopify actually shipped stays shipped: archiving an
        # order must not downgrade "Verzonden" to the vaguer wording.
        self.assertEqual(
            self._state(order_outcome='handled',
                        fulfillment_status='fulfilled'),
            ('shipped', None),
        )
        self.assertEqual(
            self._state(order_outcome='handled',
                        fulfillment_status='partial'),
            ('partial', None),
        )

    def test_display_title_prefers_app_title(self):
        self.assertEqual(
            display_title('24-10 - K - Beer', {'app_title': 'Clean Beer'}),
            'Clean Beer',
        )
        self.assertEqual(display_title('Raw Title', {}), 'Raw Title')
        self.assertEqual(display_title('Raw Title', {'app_title': '  '}),
                         'Raw Title')


class DeliveryMethodTests(TestCase):
    """
    Pickup vs shipping. The expensive mistake is a FALSE pickup: a customer
    who paid €9,50 for shipping being told to come and collect. So every
    unrecognised and every missing title must land on shipping/unknown.
    """

    def test_our_pickup_rate_is_pickup(self):
        self.assertEqual(derive_delivery_method('House of Beers'), 'pickup')

    def test_pickup_keywords_are_pickup(self):
        self.assertEqual(derive_delivery_method('Ophalen in de winkel'), 'pickup')
        self.assertEqual(derive_delivery_method('Afhalen'), 'pickup')

    def test_unexpected_casing_still_matches(self):
        self.assertEqual(derive_delivery_method('HOUSE OF BEERS'), 'pickup')
        self.assertEqual(derive_delivery_method('  house of beers  '), 'pickup')
        self.assertEqual(derive_delivery_method('AFHALEN IN UDEN'), 'pickup')

    def test_weight_band_is_shipping(self):
        self.assertEqual(derive_delivery_method('0-20 KG'), 'shipping')
        self.assertEqual(derive_delivery_method('Verzending NL'), 'shipping')

    def test_empty_is_unknown_not_pickup(self):
        # ~1,000 orders since 01-09-2026 have no shipping line (POS/in-store).
        self.assertEqual(derive_delivery_method(''), 'unknown')
        self.assertEqual(derive_delivery_method('   '), 'unknown')
        self.assertEqual(derive_delivery_method(None), 'unknown')

    def test_title_from_shipping_lines(self):
        self.assertEqual(
            shipping_method_title({'shipping_lines': [{'title': '0-20 KG'}]}),
            '0-20 KG',
        )

    def test_missing_shipping_lines_key_entirely(self):
        self.assertEqual(shipping_method_title({}), '')
        self.assertEqual(shipping_method_title({'shipping_lines': None}), '')
        self.assertEqual(shipping_method_title({'shipping_lines': []}), '')
        self.assertEqual(shipping_method_title(None), '')

    def test_blank_or_null_title_is_skipped(self):
        self.assertEqual(
            shipping_method_title({'shipping_lines': [
                {'title': None}, {'title': '  '}, {'title': 'House of Beers'},
            ]}),
            'House of Beers',
        )

    def test_end_to_end_missing_line_never_promises_pickup(self):
        order = {'id': 1}
        self.assertEqual(
            derive_delivery_method(shipping_method_title(order)), 'unknown',
        )


class OrderOutcomeTests(TestCase):
    """
    Is this order finished? Shopify never fulfils a merged-away or
    counter-handover order, so without these signals every such line falls
    through to in_warehouse and the app promises beer that is long gone.
    """

    # The order that triggered this: merged into HoB8556, then cancelled and
    # restocked. 13 lines, all with fulfillment_status null.
    HOB9027 = {
        'id': 7185536876882, 'name': 'HoB9027',
        'created_at': '2025-12-03T18:07:33+01:00',
        'closed_at': '2025-12-09T11:14:03+01:00',
        'cancelled_at': '2025-12-09T14:20:00+01:00',
        'financial_status': 'paid', 'fulfillment_status': 'restocked',
        'tags': 'merged, merged-into-HoB8556',
    }

    def test_the_reported_order_is_cancelled(self):
        self.assertEqual(derive_order_outcome(self.HOB9027), 'cancelled')
        self.assertEqual(merged_into_order_name(self.HOB9027), 'HoB8556')

    def test_restocked_without_cancelled_at_is_still_cancelled(self):
        self.assertEqual(
            derive_order_outcome({'fulfillment_status': 'restocked'}),
            'cancelled',
        )

    def test_archived_is_handled(self):
        self.assertEqual(
            derive_order_outcome({'closed_at': '2026-09-29T10:00:00+02:00'}),
            'handled',
        )

    def test_cancelled_wins_over_archived(self):
        # Cancellations archive the order too; "geannuleerd" is the truth.
        self.assertEqual(
            derive_order_outcome({
                'closed_at': '2025-12-09T11:14:03+01:00',
                'cancelled_at': '2025-12-09T14:20:00+01:00',
            }),
            'cancelled',
        )

    def test_live_order_has_no_outcome(self):
        self.assertIsNone(derive_order_outcome({
            'closed_at': None, 'cancelled_at': None,
            'fulfillment_status': None,
        }))
        self.assertIsNone(derive_order_outcome({}))
        self.assertIsNone(derive_order_outcome(None))

    def test_fulfilled_order_is_not_an_outcome_by_itself(self):
        # Fulfilment is a LINE fact; a fulfilled-but-open order keeps its
        # per-line states.
        self.assertIsNone(derive_order_outcome({
            'fulfillment_status': 'fulfilled',
        }))

    def test_merged_tag_parsing(self):
        self.assertEqual(merged_into_order_name(
            {'tags': 'merged-into-HoB8556'}), 'HoB8556')
        # Prefix matched case-insensitively, the name's own casing kept.
        self.assertEqual(merged_into_order_name(
            {'tags': 'chicago, MERGED-INTO-HoB123, vip'}), 'HoB123')
        self.assertEqual(merged_into_order_name(
            {'tags': ' merged , merged-into-HoB8556 '}), 'HoB8556')

    def test_no_merge_tag(self):
        self.assertEqual(merged_into_order_name({'tags': 'merged'}), '')
        self.assertEqual(merged_into_order_name({'tags': 'merged-into-'}), '')
        self.assertEqual(merged_into_order_name({'tags': ''}), '')
        self.assertEqual(merged_into_order_name({'tags': None}), '')
        self.assertEqual(merged_into_order_name({}), '')
        self.assertEqual(merged_into_order_name(None), '')


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
            'shipping_lines': [{'title': '0-20 KG'}],
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

        # Orders: delivery method rides on the order, not the line.
        self.assertEqual(data['orders'][0]['shipping_method'], '0-20 KG')
        self.assertEqual(data['orders'][0]['delivery_method'], 'shipping')

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

    def test_pickup_order_reports_pickup(self):
        self.orders[0]['shipping_lines'] = [{'title': 'House of Beers'}]
        response, _ = self._get()
        order = response.json()['orders'][0]
        self.assertEqual(order['shipping_method'], 'House of Beers')
        self.assertEqual(order['delivery_method'], 'pickup')

    def test_order_without_shipping_lines_is_unknown(self):
        # The POS/in-store case: say nothing rather than promise pickup.
        del self.orders[0]['shipping_lines']
        response, _ = self._get()
        order = response.json()['orders'][0]
        self.assertEqual(order['shipping_method'], '')
        self.assertEqual(order['delivery_method'], 'unknown')

    def test_live_order_carries_no_outcome_fields(self):
        order = self._get()[0].json()['orders'][0]
        self.assertIsNone(order['cancelled_at'])
        self.assertEqual(order['merged_into'], '')

    def test_cancelled_merged_order_stops_promising_beer(self):
        """
        The HoB9027 regression: merged into another order, cancelled and
        restocked, 13 lines Shopify never fulfilled. Every line used to read
        "Ligt bij ons klaar" a year later.
        """
        self.orders[0].update({
            'cancelled_at': '2025-12-09T14:20:00+01:00',
            'closed_at': '2025-12-09T11:14:03+01:00',
            'fulfillment_status': 'restocked',
            'tags': 'merged, merged-into-HoB8556',
        })
        order = self._get()[0].json()['orders'][0]

        self.assertEqual(
            [item['state'] for item in order['line_items']],
            ['cancelled', 'cancelled', 'cancelled'],
        )
        # Nothing is pending, so no ETA is forwarded either.
        self.assertEqual(
            [item['estimated_delivery_date'] for item in order['line_items']],
            [None, None, None],
        )
        # ...and the card can say WHY instead of going quiet.
        self.assertEqual(order['cancelled_at'], '2025-12-09T14:20:00+01:00')
        self.assertEqual(order['merged_into'], 'HoB8556')

    def test_archived_order_reports_handled_but_keeps_shipped_lines(self):
        self.orders[0]['closed_at'] = '2026-10-16T10:22:25+02:00'
        order = self._get()[0].json()['orders'][0]
        self.assertEqual(
            [item['state'] for item in order['line_items']],
            # line 0 was fulfilled; lines 1-2 (incoming ETA / bare shelf
            # item) are finished business we cannot route any more precisely.
            ['shipped', 'handled', 'handled'],
        )
        self.assertIsNone(order['cancelled_at'])

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
