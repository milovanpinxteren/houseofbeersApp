"""Tests for the pickup RSVP feature: day generation, RSVP/cancel flows,
the direct Shopify metafield sync, and the sync task."""
from datetime import date, datetime, time, timedelta
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from fulfillment.models import (
    PickupActionLog, PickupClosure, PickupRSVP, PickupSchedule,
)
from fulfillment.services import shopify_sync
from fulfillment.tasks import sync_pickup_action
from fulfillment.views import get_offered_days
from users.services.shopify import ShopifyService

User = get_user_model()

# A Wednesday morning. With a Friday + Saturday schedule the next 21 days
# (Sep 16 - Oct 6) offer Fri 18, Sat 19, Fri 25, Sat 26, Fri Oct 2, Sat Oct 3.
WEDNESDAY_9AM = datetime(2026, 9, 16, 9, 0)


def freeze_now(dt):
    return patch('fulfillment.views._local_now', return_value=dt)


class PickupBaseTest(TestCase):

    def setUp(self):
        # The seed migration adds Friday/Saturday; wipe and recreate so the
        # tests own the schedule explicitly.
        PickupSchedule.objects.all().delete()
        self.friday = PickupSchedule.objects.create(
            weekday=4, open_time=time(10, 0), close_time=time(20, 0),
        )
        self.saturday = PickupSchedule.objects.create(
            weekday=5, open_time=time(10, 0), close_time=time(17, 0),
        )
        self.user = User.objects.create_user(
            username='piet', email='piet@example.com', password='x',
            first_name='Piet', last_name='Bier',
        )
        self.user.shopify_customer_id = '123456789'
        self.user.save()
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)


class OfferedDaysTest(PickupBaseTest):

    def test_offers_schedule_days_within_21_days(self):
        with freeze_now(WEDNESDAY_9AM):
            days = [d['date'] for d in get_offered_days()]
        self.assertEqual(days, [
            date(2026, 9, 18), date(2026, 9, 19),
            date(2026, 9, 25), date(2026, 9, 26),
            date(2026, 10, 2), date(2026, 10, 3),
        ])

    def test_inactive_schedule_is_ignored(self):
        self.saturday.active = False
        self.saturday.save()
        with freeze_now(WEDNESDAY_9AM):
            days = [d['date'] for d in get_offered_days()]
        self.assertEqual(
            days, [date(2026, 9, 18), date(2026, 9, 25), date(2026, 10, 2)]
        )

    def test_closure_removes_the_date(self):
        PickupClosure.objects.create(date=date(2026, 9, 19), reason='Feestdag')
        with freeze_now(WEDNESDAY_9AM):
            days = [d['date'] for d in get_offered_days()]
        self.assertNotIn(date(2026, 9, 19), days)
        self.assertIn(date(2026, 9, 26), days)

    def test_today_offered_before_close_time(self):
        # Friday 2026-09-18, store closes 20:00.
        with freeze_now(datetime(2026, 9, 18, 19, 59)):
            days = [d['date'] for d in get_offered_days()]
        self.assertIn(date(2026, 9, 18), days)

    def test_today_dropped_at_close_time(self):
        with freeze_now(datetime(2026, 9, 18, 20, 0)):
            days = [d['date'] for d in get_offered_days()]
        self.assertNotIn(date(2026, 9, 18), days)
        # The next Friday is still offered.
        self.assertIn(date(2026, 9, 25), days)

    def test_days_endpoint_shape_and_rsvp_flag(self):
        PickupRSVP.objects.create(user=self.user, date=date(2026, 9, 19))
        with freeze_now(WEDNESDAY_9AM):
            data = self.client.get('/api/pickup/days/').json()
        self.assertEqual(data['days'][0], {
            'date': '2026-09-18', 'open_time': '10:00',
            'close_time': '20:00', 'rsvp': False,
        })
        by_date = {d['date']: d for d in data['days']}
        self.assertTrue(by_date['2026-09-19']['rsvp'])
        self.assertEqual(by_date['2026-09-19']['close_time'], '17:00')

    def test_cancelled_rsvp_does_not_set_flag(self):
        PickupRSVP.objects.create(
            user=self.user, date=date(2026, 9, 19), status='cancelled',
        )
        with freeze_now(WEDNESDAY_9AM):
            data = self.client.get('/api/pickup/days/').json()
        by_date = {d['date']: d for d in data['days']}
        self.assertFalse(by_date['2026-09-19']['rsvp'])

    def test_requires_auth(self):
        self.client.force_authenticate(user=None)
        self.assertEqual(self.client.get('/api/pickup/days/').status_code, 401)


@patch('fulfillment.views._dispatch_sync')
class RSVPFlowTest(PickupBaseTest):

    def rsvp(self, date_str):
        with freeze_now(WEDNESDAY_9AM):
            return self.client.post(
                '/api/pickup/rsvp/', {'date': date_str}, format='json',
            )

    def cancel(self, date_str):
        with freeze_now(WEDNESDAY_9AM):
            return self.client.post(
                '/api/pickup/rsvp/cancel/', {'date': date_str}, format='json',
            )

    def test_rsvp_creates_row_and_log_and_dispatches_sync(self, mock_dispatch):
        response = self.rsvp('2026-09-18')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'date': '2026-09-18', 'rsvp': True})

        rsvp = PickupRSVP.objects.get(user=self.user, date=date(2026, 9, 18))
        self.assertEqual(rsvp.status, 'active')
        log = PickupActionLog.objects.get()
        self.assertEqual(log.action, 'rsvp')
        self.assertEqual(log.rsvp_id, rsvp.id)
        self.assertEqual(log.pickup_date, date(2026, 9, 18))
        self.assertEqual(log.sync_status, 'pending')
        mock_dispatch.assert_called_once_with(log)

    def test_rsvp_rejects_non_offered_day(self, mock_dispatch):
        response = self.rsvp('2026-09-17')  # a Thursday
        self.assertEqual(response.status_code, 400)
        self.assertIn('error', response.json())
        self.assertEqual(PickupRSVP.objects.count(), 0)
        mock_dispatch.assert_not_called()

    def test_rsvp_rejects_closure_date(self, mock_dispatch):
        PickupClosure.objects.create(date=date(2026, 9, 18))
        self.assertEqual(self.rsvp('2026-09-18').status_code, 400)

    def test_rsvp_rejects_malformed_date(self, mock_dispatch):
        self.assertEqual(self.rsvp('vrijdag').status_code, 400)
        with freeze_now(WEDNESDAY_9AM):
            response = self.client.post('/api/pickup/rsvp/', {}, format='json')
        self.assertEqual(response.status_code, 400)

    def test_re_rsvp_is_idempotent_no_new_log(self, mock_dispatch):
        self.rsvp('2026-09-18')
        response = self.rsvp('2026-09-18')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'date': '2026-09-18', 'rsvp': True})
        self.assertEqual(PickupRSVP.objects.count(), 1)
        self.assertEqual(PickupActionLog.objects.count(), 1)
        self.assertEqual(mock_dispatch.call_count, 1)

    def test_cancel_flips_status_and_logs(self, mock_dispatch):
        self.rsvp('2026-09-18')
        response = self.cancel('2026-09-18')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'date': '2026-09-18', 'rsvp': False})

        rsvp = PickupRSVP.objects.get()
        self.assertEqual(rsvp.status, 'cancelled')
        self.assertIsNotNone(rsvp.cancelled_at)
        self.assertEqual(
            list(PickupActionLog.objects.order_by('id').values_list('action', flat=True)),
            ['rsvp', 'cancel'],
        )
        self.assertEqual(mock_dispatch.call_count, 2)

    def test_cancel_without_active_rsvp_is_400(self, mock_dispatch):
        self.assertEqual(self.cancel('2026-09-18').status_code, 400)
        self.rsvp('2026-09-18')
        self.cancel('2026-09-18')
        self.assertEqual(self.cancel('2026-09-18').status_code, 400)

    def test_re_rsvp_after_cancel_reactivates_same_row(self, mock_dispatch):
        self.rsvp('2026-09-18')
        original = PickupRSVP.objects.get()
        self.cancel('2026-09-18')
        response = self.rsvp('2026-09-18')
        self.assertEqual(response.status_code, 200)

        self.assertEqual(PickupRSVP.objects.count(), 1)
        rsvp = PickupRSVP.objects.get()
        self.assertEqual(rsvp.id, original.id)
        self.assertEqual(rsvp.status, 'active')
        self.assertIsNone(rsvp.cancelled_at)
        # rsvp, cancel, rsvp = three log rows.
        self.assertEqual(PickupActionLog.objects.count(), 3)


CUSTOMER_GID = 'gid://shopify/Customer/123456789'


@patch.object(ShopifyService, '_graphql_request')
class CustomerMetafieldMethodsTest(TestCase):
    """The three ShopifyService customer-metafield methods (GraphQL mocked)."""

    def setUp(self):
        self.service = ShopifyService()

    # ---- get_customer_queue_priority ----

    def test_get_queue_priority_reads_both_metafields(self, mock_gql):
        mock_gql.return_value = {
            'customer': {
                'queue': {'value': 'Afhalen'},
                'priority': {'value': '80'},
            }
        }
        result = self.service.get_customer_queue_priority(123456789)
        self.assertEqual(result, {'queue': 'Afhalen', 'priority': 80})

        query, variables = mock_gql.call_args.args
        self.assertEqual(variables, {'id': CUSTOMER_GID})
        self.assertIn('metafield(namespace: "custom", key: "queue")', query)
        self.assertIn('metafield(namespace: "custom", key: "priority")', query)

    def test_get_queue_priority_absent_metafields_are_none(self, mock_gql):
        mock_gql.return_value = {'customer': {'queue': None, 'priority': None}}
        result = self.service.get_customer_queue_priority(123456789)
        self.assertEqual(result, {'queue': None, 'priority': None})

    def test_get_queue_priority_non_int_priority_is_none(self, mock_gql):
        mock_gql.return_value = {
            'customer': {
                'queue': {'value': 'Spoed'},
                'priority': {'value': 'hoog'},
            }
        }
        result = self.service.get_customer_queue_priority(123456789)
        self.assertEqual(result, {'queue': 'Spoed', 'priority': None})

    def test_get_queue_priority_unknown_customer_is_none(self, mock_gql):
        mock_gql.return_value = {'customer': None}
        self.assertIsNone(self.service.get_customer_queue_priority(123456789))

    def test_get_queue_priority_graphql_error_is_none(self, mock_gql):
        mock_gql.return_value = None
        self.assertIsNone(self.service.get_customer_queue_priority(123456789))

    # ---- set_customer_metafield ----

    def test_set_metafield_success(self, mock_gql):
        mock_gql.return_value = {
            'metafieldsSet': {
                'metafields': [{'id': 'gid://shopify/Metafield/1', 'value': 'Afhalen'}],
                'userErrors': [],
            }
        }
        result = self.service.set_customer_metafield(
            123456789, 'queue', 'Afhalen', 'single_line_text_field',
        )
        self.assertEqual(
            result, {'id': 'gid://shopify/Metafield/1', 'value': 'Afhalen'},
        )

        query, variables = mock_gql.call_args.args
        self.assertIn('metafieldsSet(metafields: $metafields)', query)
        self.assertEqual(variables, {
            'metafields': [{
                'ownerId': CUSTOMER_GID,
                'namespace': 'custom',
                'key': 'queue',
                'type': 'single_line_text_field',
                'value': 'Afhalen',
            }]
        })

    def test_set_metafield_integer_is_sent_as_string(self, mock_gql):
        mock_gql.return_value = {
            'metafieldsSet': {
                'metafields': [{'id': 'gid://shopify/Metafield/2', 'value': '80'}],
                'userErrors': [],
            }
        }
        self.service.set_customer_metafield(
            123456789, 'priority', '80', 'number_integer',
        )
        variables = mock_gql.call_args.args[1]
        self.assertEqual(variables['metafields'][0]['value'], '80')
        self.assertEqual(variables['metafields'][0]['type'], 'number_integer')

    def test_set_metafield_user_errors_is_none(self, mock_gql):
        mock_gql.return_value = {
            'metafieldsSet': {
                'metafields': [],
                'userErrors': [{'field': ['value'], 'message': 'not a valid choice'}],
            }
        }
        self.assertIsNone(self.service.set_customer_metafield(
            123456789, 'queue', 'Nonsense', 'single_line_text_field',
        ))

    def test_set_metafield_graphql_error_is_none(self, mock_gql):
        mock_gql.return_value = None
        self.assertIsNone(self.service.set_customer_metafield(
            123456789, 'queue', 'Afhalen', 'single_line_text_field',
        ))

    # ---- delete_customer_metafield ----

    def test_delete_metafield_success(self, mock_gql):
        mock_gql.return_value = {
            'metafieldsDelete': {
                'deletedMetafields': [{'ownerId': CUSTOMER_GID, 'key': 'queue'}],
                'userErrors': [],
            }
        }
        self.assertTrue(
            self.service.delete_customer_metafield(123456789, 'queue')
        )

        query, variables = mock_gql.call_args.args
        self.assertIn('metafieldsDelete(metafields: $metafields)', query)
        self.assertIn('$metafields: [MetafieldIdentifierInput!]!', query)
        self.assertEqual(variables, {
            'metafields': [{
                'ownerId': CUSTOMER_GID,
                'namespace': 'custom',
                'key': 'queue',
            }]
        })

    def test_delete_nonexistent_metafield_is_success(self, mock_gql):
        # Shopify reports no userErrors for an already-absent metafield.
        mock_gql.return_value = {
            'metafieldsDelete': {'deletedMetafields': [], 'userErrors': []}
        }
        self.assertTrue(
            self.service.delete_customer_metafield(123456789, 'priority')
        )

    def test_delete_metafield_user_errors_is_false(self, mock_gql):
        mock_gql.return_value = {
            'metafieldsDelete': {
                'deletedMetafields': [],
                'userErrors': [{'field': None, 'message': 'boom'}],
            }
        }
        self.assertFalse(
            self.service.delete_customer_metafield(123456789, 'queue')
        )

    def test_delete_metafield_graphql_error_is_false(self, mock_gql):
        mock_gql.return_value = None
        self.assertFalse(
            self.service.delete_customer_metafield(123456789, 'queue')
        )


class ShopifySyncPushTest(PickupBaseTest):
    """push_pickup_action semantics: read-modify-write, idempotent, never
    lowering a priority, never touching staff-set values."""

    def make_log(self, action='rsvp'):
        # Mirror production: the view flips the RSVP row to 'cancelled'
        # BEFORE dispatching a cancel sync, so the guard against other
        # active RSVPs never counts the row being cancelled itself.
        rsvp = PickupRSVP.objects.create(
            user=self.user, date=date(2026, 9, 18),
            status='cancelled' if action == 'cancel' else 'active',
        )
        return PickupActionLog.objects.create(
            user=self.user, rsvp=rsvp, action=action,
            pickup_date=date(2026, 9, 18),
        )

    def mock_service(self, queue=None, priority=None, current=Ellipsis):
        """A ShopifyService mock with a canned read and successful writes."""
        service = MagicMock()
        if current is Ellipsis:
            current = {'queue': queue, 'priority': priority}
        service.get_customer_queue_priority.return_value = current
        service.set_customer_metafield.return_value = {'id': 'x', 'value': 'y'}
        service.delete_customer_metafield.return_value = True
        return service

    def push(self, log, service):
        with patch(
            'fulfillment.services.shopify_sync.ShopifyService',
            return_value=service,
        ) as mock_cls:
            result = shopify_sync.push_pickup_action(log)
        return result, mock_cls

    def test_skipped_without_customer_id(self):
        for raw in [None, '', 'not-a-number']:
            self.user.shopify_customer_id = raw
            self.user.save()
            log = self.make_log()
            (status, text), mock_cls = self.push(log, self.mock_service())
            self.assertEqual(status, 'skipped')
            self.assertIn('No linked Shopify customer', text)
            mock_cls.assert_not_called()  # zero Shopify calls
            PickupRSVP.objects.all().delete()

    def test_rsvp_writes_queue_and_priority(self):
        log = self.make_log()
        service = self.mock_service(queue=None, priority=None)
        (status, text), _ = self.push(log, service)

        self.assertEqual(status, 'success')
        service.get_customer_queue_priority.assert_called_once_with(123456789)
        service.set_customer_metafield.assert_any_call(
            123456789, 'queue', 'Afhalen', 'single_line_text_field',
        )
        service.set_customer_metafield.assert_any_call(
            123456789, 'priority', '80', 'number_integer',
        )
        self.assertEqual(service.set_customer_metafield.call_count, 2)
        service.delete_customer_metafield.assert_not_called()
        self.assertIn("queue None -> 'Afhalen'", text)
        self.assertIn('priority None -> 80', text)

    def test_rsvp_never_lowers_existing_priority(self):
        log = self.make_log()
        service = self.mock_service(queue='Spoed', priority=90)
        (status, _), _ = self.push(log, service)

        self.assertEqual(status, 'success')
        # Queue is rewritten, but priority 90 stays (max(90, 80) == 90).
        service.set_customer_metafield.assert_called_once_with(
            123456789, 'queue', 'Afhalen', 'single_line_text_field',
        )

    def test_rsvp_raises_low_priority_to_80(self):
        log = self.make_log()
        service = self.mock_service(queue='Afhalen', priority=30)
        (status, _), _ = self.push(log, service)

        self.assertEqual(status, 'success')
        service.set_customer_metafield.assert_called_once_with(
            123456789, 'priority', '80', 'number_integer',
        )

    def test_rsvp_already_in_sync_makes_zero_writes(self):
        log = self.make_log()
        service = self.mock_service(queue='Afhalen', priority=80)
        (status, text), _ = self.push(log, service)

        self.assertEqual(status, 'success')
        service.set_customer_metafield.assert_not_called()
        service.delete_customer_metafield.assert_not_called()
        self.assertIn('already in sync', text)

    def test_cancel_deletes_own_queue_and_priority(self):
        log = self.make_log(action='cancel')
        service = self.mock_service(queue='Afhalen', priority=80)
        (status, text), _ = self.push(log, service)

        self.assertEqual(status, 'success')
        service.delete_customer_metafield.assert_any_call(123456789, 'queue')
        service.delete_customer_metafield.assert_any_call(123456789, 'priority')
        self.assertEqual(service.delete_customer_metafield.call_count, 2)
        service.set_customer_metafield.assert_not_called()

    def test_cancel_leaves_staff_values_untouched(self):
        log = self.make_log(action='cancel')
        # Staff moved the customer to 'Spoed' with priority 65: not ours,
        # so cancel must not revert anything.
        service = self.mock_service(queue='Spoed', priority=65)
        (status, text), _ = self.push(log, service)

        self.assertEqual(status, 'success')
        service.delete_customer_metafield.assert_not_called()
        service.set_customer_metafield.assert_not_called()
        self.assertIn('already in sync', text)

    def test_cancel_deletes_queue_but_keeps_staff_priority(self):
        log = self.make_log(action='cancel')
        service = self.mock_service(queue='Afhalen', priority=95)
        (status, _), _ = self.push(log, service)

        self.assertEqual(status, 'success')
        service.delete_customer_metafield.assert_called_once_with(
            123456789, 'queue',
        )

    def test_cancel_with_other_active_rsvp_leaves_shopify_untouched(self):
        # Coming Friday AND Saturday; de-selecting Friday must keep the
        # customer in the queue for Saturday: zero Shopify calls.
        log = self.make_log(action='cancel')
        upcoming = timezone.localdate() + timedelta(days=1)
        PickupRSVP.objects.create(user=self.user, date=upcoming)
        service = self.mock_service(queue='Afhalen', priority=80)
        (status, text), mock_cls = self.push(log, service)

        self.assertEqual(status, 'success')
        self.assertIn('other active RSVPs remain', text)
        mock_cls.assert_not_called()

    def test_cancel_with_only_past_active_rsvp_still_reverts(self):
        # A spent RSVP (date passed, never cancelled) must not block the
        # revert: its queue entry is staff's to clear during pickup.
        log = self.make_log(action='cancel')
        past = timezone.localdate() - timedelta(days=7)
        PickupRSVP.objects.create(user=self.user, date=past)
        service = self.mock_service(queue='Afhalen', priority=80)
        (status, _), _ = self.push(log, service)

        self.assertEqual(status, 'success')
        self.assertEqual(service.delete_customer_metafield.call_count, 2)

    def test_customer_not_found_is_failed_for_retry(self):
        log = self.make_log()
        service = self.mock_service(current=None)
        (status, text), _ = self.push(log, service)

        self.assertEqual(status, 'failed')
        self.assertIn('Could not read queue/priority', text)
        service.set_customer_metafield.assert_not_called()

    def test_write_error_is_failed(self):
        log = self.make_log()
        service = self.mock_service(queue=None, priority=None)
        service.set_customer_metafield.return_value = None
        (status, text), _ = self.push(log, service)

        self.assertEqual(status, 'failed')
        self.assertIn('failed', text)

    def test_delete_error_is_failed(self):
        log = self.make_log(action='cancel')
        service = self.mock_service(queue='Afhalen', priority=80)
        service.delete_customer_metafield.return_value = False
        (status, text), _ = self.push(log, service)

        self.assertEqual(status, 'failed')

    def test_unexpected_exception_is_failed_not_raise(self):
        log = self.make_log()
        service = self.mock_service()
        service.get_customer_queue_priority.side_effect = RuntimeError('boom')
        (status, text), _ = self.push(log, service)

        self.assertEqual(status, 'failed')
        self.assertIn('boom', text)


class SyncTaskTest(PickupBaseTest):

    def make_log(self):
        rsvp = PickupRSVP.objects.create(user=self.user, date=date(2026, 9, 18))
        return PickupActionLog.objects.create(
            user=self.user, rsvp=rsvp, action='rsvp',
            pickup_date=date(2026, 9, 18),
        )

    def test_success_updates_log_row(self):
        log = self.make_log()
        with patch(
            'fulfillment.services.shopify_sync.push_pickup_action',
            return_value=('success', 'Customer 123456789: queue set'),
        ):
            sync_pickup_action(log.id)
        log.refresh_from_db()
        self.assertEqual(log.sync_status, 'success')
        self.assertEqual(log.sync_attempts, 1)
        self.assertEqual(log.sync_response, 'Customer 123456789: queue set')

    def test_skipped_does_not_count_an_attempt(self):
        # An unlinked user is the real skip case: no Shopify customer to
        # write to, and no Shopify calls at all.
        self.user.shopify_customer_id = None
        self.user.save()
        log = self.make_log()
        sync_pickup_action(log.id)
        log.refresh_from_db()
        self.assertEqual(log.sync_status, 'skipped')
        self.assertEqual(log.sync_attempts, 0)
        self.assertIn('No linked Shopify customer', log.sync_response)

    def test_failure_updates_log_row_and_raises_for_retry(self):
        log = self.make_log()
        with patch(
            'fulfillment.services.shopify_sync.push_pickup_action',
            return_value=('failed', 'Shopify error: boom'),
        ):
            # Called directly (no worker), so retry() re-raises the exc.
            with self.assertRaises(Exception):
                sync_pickup_action(log.id)
        log.refresh_from_db()
        self.assertEqual(log.sync_status, 'failed')
        self.assertEqual(log.sync_attempts, 1)
        self.assertEqual(log.sync_response, 'Shopify error: boom')

    def test_missing_log_row_is_a_noop(self):
        sync_pickup_action(999999)  # must not raise
