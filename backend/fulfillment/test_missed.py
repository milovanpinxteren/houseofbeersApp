"""
Tests for the missed-items service API (/api/service/fulfillment/missed/)
and the pending-record claim flow.
"""
import hashlib
import hmac
import json
from datetime import date
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from fulfillment.models import MissedItemsRecord
from fulfillment.services.missed import (
    MissedItemsError,
    claim_pending_missed,
    upsert_missed,
)

User = get_user_model()

SECRET = 'test-secret'


def sign(body: bytes, secret: str = SECRET) -> str:
    return 'sha256=' + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def payload(**overrides):
    base = {
        'dedupe_key': 'hob:missed:111:8123456789',
        'source': 'hob',
        'shopify_customer_id': '8123456789',
        'email': 'x@y.nl',
        'phone': '31612345678',
        'sale': {'id': 111, 'name': '26-10', 'date': '2026-10-26'},
        'draft_order_id': '123456',
        'draft_order_name': '#D6795',
        'shopify_order_id': None,
        'lines': [
            {'product_id': 9876543210, 'title': 'Brouwerij X – Beer Name',
             'requested': 3, 'received': 1, 'reason': 'out_of_stock'},
        ],
        'pushed_at': '2026-10-29T12:34:56+01:00',
    }
    base.update(overrides)
    return base


class UpsertMissedServiceTest(TestCase):
    """upsert_missed lifecycle + user resolution."""

    def setUp(self):
        self.user = User.objects.create_user(
            username='piet@example.com', email='piet@example.com', password='x',
        )
        self.user.shopify_customer_id = '8123456789'
        self.user.save(update_fields=['shopify_customer_id'])

    def test_create_attaches_to_member_by_shopify_id(self):
        record, created = upsert_missed(payload())

        self.assertTrue(created)
        self.assertEqual(record.status, 'attached')
        self.assertEqual(record.user, self.user)
        self.assertEqual(record.sale_id, 111)
        self.assertEqual(record.sale_name, '26-10')
        self.assertEqual(record.sale_date, date(2026, 10, 26))
        self.assertEqual(record.draft_order_id, '123456')
        self.assertEqual(record.shopify_order_id, '')
        self.assertEqual(len(record.lines), 1)
        self.assertIsNotNone(record.pushed_at)

    def test_create_falls_back_to_email(self):
        record, created = upsert_missed(payload(
            shopify_customer_id='999999', email='PIET@Example.com',
        ))
        self.assertTrue(created)
        self.assertEqual(record.status, 'attached')
        self.assertEqual(record.user, self.user)

    def test_non_member_stays_pending(self):
        record, created = upsert_missed(payload(
            shopify_customer_id='999999', email='nobody@example.com',
        ))
        self.assertTrue(created)
        self.assertEqual(record.status, 'pending')
        self.assertIsNone(record.user)

    def test_ambiguous_shopify_id_stays_pending_not_error(self):
        other = User.objects.create_user(
            username='dup@example.com', email='dup@example.com', password='x',
        )
        other.shopify_customer_id = '8123456789'
        other.save(update_fields=['shopify_customer_id'])

        # Unlike grants, ambiguity must NOT fail the push — the snapshot is
        # pure display and the record stays claimable after a cleanup.
        record, created = upsert_missed(payload(email='nobody@example.com'))
        self.assertTrue(created)
        self.assertEqual(record.status, 'pending')
        self.assertIsNone(record.user)

    def test_repush_replaces_lines_and_ids(self):
        upsert_missed(payload())
        record, created = upsert_missed(payload(
            lines=[{'product_id': 1, 'title': 'Other', 'requested': 2,
                    'received': 2, 'reason': 'out_of_stock'}],
            draft_order_id='777777',
            shopify_order_id='456789',
        ))

        self.assertFalse(created)
        self.assertEqual(MissedItemsRecord.objects.count(), 1)
        self.assertEqual(record.lines[0]['title'], 'Other')
        self.assertEqual(record.draft_order_id, '777777')
        self.assertEqual(record.shopify_order_id, '456789')
        self.assertEqual(record.status, 'attached')

    def test_empty_lines_clears_but_keeps_row_and_user(self):
        upsert_missed(payload())
        record, created = upsert_missed(payload(lines=[]))

        self.assertFalse(created)
        self.assertEqual(record.status, 'cleared')
        # The user link survives the clear (idempotency row, still theirs).
        self.assertEqual(record.user, self.user)
        self.assertEqual(record.lines, [])

    def test_repush_after_clear_reopens(self):
        upsert_missed(payload(lines=[]))
        record, created = upsert_missed(payload())
        self.assertFalse(created)
        self.assertEqual(record.status, 'attached')
        self.assertEqual(len(record.lines), 1)

    def test_create_with_empty_lines_is_cleared(self):
        record, created = upsert_missed(payload(lines=[]))
        self.assertTrue(created)
        self.assertEqual(record.status, 'cleared')

    def test_validation_errors(self):
        for bad in [
            payload(dedupe_key=''),
            payload(dedupe_key='x' * 121),
            payload(sale=None),
            payload(sale={'id': 'not-int', 'date': '2026-10-26'}),
            payload(sale={'id': 111, 'date': 'nonsense'}),
            payload(lines='not-a-list'),
            payload(lines=['not-a-dict']),
            payload(pushed_at='not-a-datetime'),
        ]:
            with self.assertRaises(MissedItemsError):
                upsert_missed(bad)
        self.assertEqual(MissedItemsRecord.objects.count(), 0)


class ClaimPendingMissedTest(TestCase):
    """claim_pending_missed + its registration and Shopify-link hooks."""

    def _pending(self, **overrides):
        record, _ = upsert_missed(payload(
            shopify_customer_id=overrides.pop('shopify_customer_id', '999999'),
            email=overrides.pop('email', 'nieuw@example.com'),
            **overrides,
        ))
        assert record.status == 'pending'
        return record

    def test_claim_by_email(self):
        self._pending()
        newcomer = User.objects.create_user(
            username='nieuw@example.com', email='Nieuw@Example.com', password='x',
        )
        self.assertEqual(claim_pending_missed(newcomer), 1)
        record = MissedItemsRecord.objects.get()
        self.assertEqual(record.status, 'attached')
        self.assertEqual(record.user, newcomer)

    def test_claim_by_shopify_id(self):
        self._pending(email='other@example.com')
        newcomer = User.objects.create_user(
            username='x@example.com', email='x@example.com', password='x',
        )
        newcomer.shopify_customer_id = '999999'
        newcomer.save(update_fields=['shopify_customer_id'])

        self.assertEqual(claim_pending_missed(newcomer), 1)
        self.assertEqual(MissedItemsRecord.objects.get().user, newcomer)

    def test_claim_is_idempotent_and_skips_cleared(self):
        self._pending()
        upsert_missed(payload(
            dedupe_key='hob:missed:112:999999', shopify_customer_id='999999',
            email='nieuw@example.com',
            sale={'id': 112, 'name': '27-10', 'date': '2026-10-27'},
            lines=[],
        ))  # cleared — must not be touched by the claim

        newcomer = User.objects.create_user(
            username='nieuw@example.com', email='nieuw@example.com', password='x',
        )
        self.assertEqual(claim_pending_missed(newcomer), 1)
        self.assertEqual(claim_pending_missed(newcomer), 0)
        cleared = MissedItemsRecord.objects.get(dedupe_key='hob:missed:112:999999')
        self.assertEqual(cleared.status, 'cleared')
        self.assertIsNone(cleared.user)

    def test_registration_hook_claims(self):
        """The hook in RegisterView, not just the service."""
        self._pending()

        with patch('users.views.ShopifyService') as mock_service:
            mock_service.return_value.link_customer_to_user.return_value = False
            response = self.client.post('/api/auth/register/', {
                'email': 'nieuw@example.com',
                'password': 'Sterk-wachtwoord-1',
                'password_confirm': 'Sterk-wachtwoord-1',
            })

        self.assertEqual(response.status_code, 201)
        newcomer = User.objects.get(email='nieuw@example.com')
        record = MissedItemsRecord.objects.get()
        self.assertEqual(record.status, 'attached')
        self.assertEqual(record.user, newcomer)

    def test_shopify_link_hook_claims(self):
        """The hook in link_customer_to_user's success path."""
        from users.services import ShopifyService

        self._pending(email='other@example.com')
        user = User.objects.create_user(
            username='link@example.com', email='link@example.com', password='x',
        )

        with patch.object(ShopifyService, 'find_customer_by_email',
                          return_value={'id': 999999}):
            linked = ShopifyService().link_customer_to_user(user)

        self.assertTrue(linked)
        record = MissedItemsRecord.objects.get()
        self.assertEqual(record.status, 'attached')
        self.assertEqual(record.user, user)


@override_settings(SERVICE_API_HMAC_SECRET=SECRET)
class MissedServiceApiTest(TestCase):
    """HTTP layer: HMAC auth + the upsert endpoint."""

    URL = '/api/service/fulfillment/missed/'

    def _post(self, data, secret=SECRET, signature=None):
        body = json.dumps(data).encode()
        return self.client.post(
            self.URL, data=body, content_type='application/json',
            **{'HTTP_X_SIGNATURE': signature or sign(body, secret)},
        )

    def test_valid_signature_creates_201(self):
        response = self._post(payload())
        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertEqual(data['status'], 'created')
        self.assertEqual(data['record_status'], 'pending')
        self.assertEqual(MissedItemsRecord.objects.count(), 1)

    def test_repush_returns_200_updated(self):
        self._post(payload())
        response = self._post(payload(lines=[]))
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['status'], 'updated')
        self.assertEqual(data['record_status'], 'cleared')

    def test_attached_record_status_reported(self):
        user = User.objects.create_user(
            username='piet@example.com', email='piet@example.com', password='x',
        )
        user.shopify_customer_id = '8123456789'
        user.save(update_fields=['shopify_customer_id'])

        response = self._post(payload())
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()['record_status'], 'attached')

    def test_bad_signature_rejected(self):
        response = self._post(payload(), signature='sha256=deadbeef')
        self.assertEqual(response.status_code, 403)
        self.assertEqual(MissedItemsRecord.objects.count(), 0)

    @override_settings(SERVICE_API_HMAC_SECRET='')
    def test_unset_secret_disables_api(self):
        response = self._post(payload())
        self.assertEqual(response.status_code, 503)

    def test_invalid_payload_is_400_never_500(self):
        for bad in [payload(dedupe_key=''), payload(sale=None),
                    payload(lines='nope')]:
            response = self._post(bad)
            self.assertEqual(response.status_code, 400)
            self.assertIn('error', response.json())

    def test_get_not_allowed(self):
        response = self.client.get(self.URL)
        self.assertEqual(response.status_code, 405)
