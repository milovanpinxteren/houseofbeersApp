"""Tests for the pickup RSVP feature: day generation, RSVP/cancel flows,
the outbound hob sync client, and the sync task."""
import hashlib
import hmac
import json
from datetime import date, datetime, time
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from fulfillment.models import (
    PickupActionLog, PickupClosure, PickupRSVP, PickupSchedule,
)
from fulfillment.services import hob_sync
from fulfillment.tasks import sync_pickup_action
from fulfillment.views import get_offered_days

User = get_user_model()

# A Wednesday morning. With a Friday + Saturday schedule the next 14 days
# (Sep 16-29) offer Fri 18, Sat 19, Fri 25, Sat 26.
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

    def test_offers_schedule_days_within_14_days(self):
        with freeze_now(WEDNESDAY_9AM):
            days = [d['date'] for d in get_offered_days()]
        self.assertEqual(days, [
            date(2026, 9, 18), date(2026, 9, 19),
            date(2026, 9, 25), date(2026, 9, 26),
        ])

    def test_inactive_schedule_is_ignored(self):
        self.saturday.active = False
        self.saturday.save()
        with freeze_now(WEDNESDAY_9AM):
            days = [d['date'] for d in get_offered_days()]
        self.assertEqual(days, [date(2026, 9, 18), date(2026, 9, 25)])

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


HOB_SETTINGS = {
    'HOB_SERVICE_URL': 'https://hob.example.com',
    'HOB_SERVICE_HMAC_SECRET': 'topsecret',
}


class HobSyncClientTest(PickupBaseTest):

    def make_log(self, action='rsvp'):
        rsvp = PickupRSVP.objects.create(user=self.user, date=date(2026, 9, 18))
        return PickupActionLog.objects.create(
            user=self.user, rsvp=rsvp, action=action,
            pickup_date=date(2026, 9, 18),
        )

    def mock_response(self, status_code=200, body='{"success": true}'):
        response = MagicMock()
        response.status_code = status_code
        response.text = body
        if body:
            try:
                response.json.return_value = json.loads(body)
            except ValueError:
                response.json.side_effect = ValueError('no json')
        else:
            response.json.side_effect = ValueError('no json')
        return response

    def test_skipped_when_unconfigured(self):
        log = self.make_log()
        for url, secret in [('', ''), ('https://hob.example.com', ''), ('', 's')]:
            with override_settings(HOB_SERVICE_URL=url, HOB_SERVICE_HMAC_SECRET=secret):
                with patch('fulfillment.services.hob_sync.requests.post') as mock_post:
                    status, _ = hob_sync.push_pickup_action(log)
            self.assertEqual(status, 'skipped')
            mock_post.assert_not_called()

    @override_settings(**HOB_SETTINGS)
    def test_success_call_url_signature_and_payload(self):
        log = self.make_log()
        with patch('fulfillment.services.hob_sync.requests.post') as mock_post:
            mock_post.return_value = self.mock_response()
            status, response_text = hob_sync.push_pickup_action(log)

        self.assertEqual(status, 'success')
        self.assertEqual(response_text, '{"success": true}')
        args, kwargs = mock_post.call_args
        self.assertEqual(
            args[0], 'https://hob.example.com/api/service/app/pickup-rsvp/',
        )
        self.assertEqual(kwargs['timeout'], 10)

        body = kwargs['data']
        self.assertEqual(json.loads(body.decode('utf-8')), {
            'action': 'rsvp',
            'shopify_customer_id': 123456789,
            'email': 'piet@example.com',
            'first_name': 'Piet',
            'last_name': 'Bier',
            'pickup_date': '2026-09-18',
        })
        # Recompute the HMAC over the exact bytes that were sent.
        expected = 'sha256=' + hmac.new(
            b'topsecret', body, hashlib.sha256,
        ).hexdigest()
        self.assertEqual(kwargs['headers']['X-Signature'], expected)
        self.assertEqual(kwargs['headers']['Content-Type'], 'application/json')

    @override_settings(**HOB_SETTINGS)
    def test_unlinked_user_sends_null_customer_id(self):
        self.user.shopify_customer_id = None
        self.user.save()
        log = self.make_log(action='cancel')
        with patch('fulfillment.services.hob_sync.requests.post') as mock_post:
            mock_post.return_value = self.mock_response()
            hob_sync.push_pickup_action(log)
        payload = json.loads(mock_post.call_args.kwargs['data'].decode('utf-8'))
        self.assertIsNone(payload['shopify_customer_id'])
        self.assertEqual(payload['action'], 'cancel')

    @override_settings(**HOB_SETTINGS)
    def test_2xx_without_success_flag_is_failure(self):
        log = self.make_log()
        with patch('fulfillment.services.hob_sync.requests.post') as mock_post:
            mock_post.return_value = self.mock_response(body='{"success": false, "error": "unknown customer"}')
            status, response_text = hob_sync.push_pickup_action(log)
        self.assertEqual(status, 'failed')
        self.assertIn('unknown customer', response_text)

    @override_settings(**HOB_SETTINGS)
    def test_http_error_is_failure_with_status_and_snippet(self):
        log = self.make_log()
        with patch('fulfillment.services.hob_sync.requests.post') as mock_post:
            mock_post.return_value = self.mock_response(
                status_code=500, body='boom' * 2000,
            )
            status, response_text = hob_sync.push_pickup_action(log)
        self.assertEqual(status, 'failed')
        self.assertIn('HTTP 500', response_text)
        self.assertLessEqual(len(response_text), hob_sync.MAX_RESPONSE_CHARS)

    @override_settings(**HOB_SETTINGS)
    def test_network_error_is_failure_not_raise(self):
        import requests as requests_lib
        log = self.make_log()
        with patch('fulfillment.services.hob_sync.requests.post') as mock_post:
            mock_post.side_effect = requests_lib.ConnectionError('refused')
            status, response_text = hob_sync.push_pickup_action(log)
        self.assertEqual(status, 'failed')
        self.assertIn('refused', response_text)


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
            'fulfillment.services.hob_sync.push_pickup_action',
            return_value=('success', '{"success": true}'),
        ):
            sync_pickup_action(log.id)
        log.refresh_from_db()
        self.assertEqual(log.sync_status, 'success')
        self.assertEqual(log.sync_attempts, 1)
        self.assertEqual(log.sync_response, '{"success": true}')

    def test_skipped_does_not_count_an_attempt(self):
        log = self.make_log()
        with override_settings(HOB_SERVICE_URL='', HOB_SERVICE_HMAC_SECRET=''):
            sync_pickup_action(log.id)
        log.refresh_from_db()
        self.assertEqual(log.sync_status, 'skipped')
        self.assertEqual(log.sync_attempts, 0)
        self.assertIn('not configured', log.sync_response)

    def test_failure_updates_log_row_and_raises_for_retry(self):
        log = self.make_log()
        with patch(
            'fulfillment.services.hob_sync.push_pickup_action',
            return_value=('failed', 'HTTP 500: boom'),
        ):
            # Called directly (no worker), so retry() re-raises the exc.
            with self.assertRaises(Exception):
                sync_pickup_action(log.id)
        log.refresh_from_db()
        self.assertEqual(log.sync_status, 'failed')
        self.assertEqual(log.sync_attempts, 1)
        self.assertEqual(log.sync_response, 'HTTP 500: boom')

    def test_missing_log_row_is_a_noop(self):
        sync_pickup_action(999999)  # must not raise
