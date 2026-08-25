"""
Tests for the service grant API (/api/service/loyalty/) and the pending
grant claim flow.
"""
import hashlib
import hmac
import json
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from loyalty.models import PointsBalance, PointsTransaction, ServiceGrant
from loyalty.services.grants import (
    GrantError,
    claim_pending_grants,
    create_grant,
    revoke_grant,
)

User = get_user_model()

SECRET = 'test-secret'
NOTIFY_TARGET = 'notifications.services.send_notification'


def sign(body: bytes, secret: str = SECRET) -> str:
    return 'sha256=' + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


class GrantServiceTest(TestCase):
    """create_grant / claim_pending_grants / revoke_grant service logic."""

    def setUp(self):
        self.user = User.objects.create_user(
            username='piet@example.com', email='piet@example.com', password='x',
            )
        self.user.shopify_customer_id = '12345'
        self.user.save(update_fields=['shopify_customer_id'])

    def _grant(self, **kwargs):
        defaults = dict(
            dedupe_key='hob:test:1', points=100,
            reason='Snelste reactie', phone='+31683253135',
        )
        defaults.update(kwargs)
        with patch(NOTIFY_TARGET) as mock_notify:
            mock_notify.return_value = MagicMock(id=42)
            return create_grant(**defaults)

    def test_grant_to_member_by_shopify_id(self):
        grant, created = self._grant(shopify_customer_id='12345')

        self.assertTrue(created)
        self.assertEqual(grant.status, 'granted')
        self.assertEqual(grant.user, self.user)

        balance = PointsBalance.objects.get(user=self.user)
        self.assertEqual(balance.balance, 100)
        self.assertEqual(balance.lifetime_earned, 100)
        self.assertEqual(balance.lifetime_spent, 0)

        txn = grant.transaction
        self.assertEqual(txn.transaction_type, 'earned')
        self.assertIsNone(txn.rule)
        self.assertEqual(txn.shopify_order_id, '')
        self.assertEqual(txn.description, 'Snelste reactie')
        self.assertEqual(txn.balance_after, 100)
        # rule_name is what the mobile breakdown expander renders
        self.assertEqual(txn.breakdown[0]['rule_name'], 'Snelste reactie')
        self.assertEqual(txn.breakdown[0]['points'], 100)

    def test_grant_to_member_by_email_case_insensitive(self):
        grant, created = self._grant(email='PIET@Example.com')
        self.assertEqual(grant.status, 'granted')
        self.assertEqual(grant.user, self.user)

    def test_grant_idempotent_on_dedupe_key(self):
        self._grant(shopify_customer_id='12345')
        grant2, created2 = self._grant(shopify_customer_id='12345')

        self.assertFalse(created2)
        self.assertEqual(ServiceGrant.objects.count(), 1)
        self.assertEqual(PointsBalance.objects.get(user=self.user).balance, 100)
        self.assertEqual(PointsTransaction.objects.count(), 1)

    def test_grant_unknown_identity_is_pending(self):
        grant, created = self._grant(phone='+31600000000')
        self.assertTrue(created)
        self.assertEqual(grant.status, 'pending')
        self.assertIsNone(grant.user)
        self.assertEqual(PointsTransaction.objects.count(), 0)

    def test_grant_ambiguous_shopify_id_fails_loudly(self):
        other = User.objects.create_user(
            username='dup@example.com', email='dup@example.com', password='x',
        )
        other.shopify_customer_id = '12345'
        other.save(update_fields=['shopify_customer_id'])

        with self.assertRaises(GrantError):
            self._grant(shopify_customer_id='12345')
        self.assertEqual(ServiceGrant.objects.count(), 0)

    def test_grant_validation(self):
        for bad in [dict(points=0), dict(points='100'), dict(points=200_000),
                    dict(reason=''), dict(dedupe_key='')]:
            with self.assertRaises(GrantError):
                self._grant(**bad)
        with self.assertRaises(GrantError):
            self._grant(phone='', email='', shopify_customer_id='')

    def test_claim_pending_by_email_on_join(self):
        self._grant(dedupe_key='hob:pending:1', email='nieuw@example.com',
                    phone='+31600000000')

        newcomer = User.objects.create_user(
            username='nieuw@example.com', email='Nieuw@Example.com', password='x',
        )
        with patch(NOTIFY_TARGET) as mock_notify:
            mock_notify.return_value = MagicMock(id=43)
            claimed = claim_pending_grants(newcomer)

        self.assertEqual(claimed, 1)
        grant = ServiceGrant.objects.get(dedupe_key='hob:pending:1')
        self.assertEqual(grant.status, 'granted')
        self.assertEqual(grant.user, newcomer)
        self.assertEqual(grant.notified_delivery_id, 43)
        self.assertEqual(PointsBalance.objects.get(user=newcomer).balance, 100)

    def test_claim_pending_by_shopify_id(self):
        self._grant(dedupe_key='hob:pending:2', shopify_customer_id='99999',
                    phone='+31600000000')
        newcomer = User.objects.create_user(
            username='x@example.com', email='x@example.com', password='x',
        )
        newcomer.shopify_customer_id = '99999'
        newcomer.save(update_fields=['shopify_customer_id'])

        with patch(NOTIFY_TARGET, return_value=MagicMock(id=1)):
            self.assertEqual(claim_pending_grants(newcomer), 1)
        self.assertEqual(PointsBalance.objects.get(user=newcomer).balance, 100)

    def test_claim_is_idempotent(self):
        self._grant(dedupe_key='hob:pending:3', email='nieuw@example.com')
        newcomer = User.objects.create_user(
            username='nieuw@example.com', email='nieuw@example.com', password='x',
        )
        with patch(NOTIFY_TARGET, return_value=MagicMock(id=1)):
            self.assertEqual(claim_pending_grants(newcomer), 1)
            self.assertEqual(claim_pending_grants(newcomer), 0)
        self.assertEqual(PointsBalance.objects.get(user=newcomer).balance, 100)

    def test_revoke_granted_creates_compensating_transaction(self):
        self._grant(shopify_customer_id='12345')
        grant = revoke_grant('hob:test:1', reason='verkeerde persoon')

        self.assertEqual(grant.status, 'revoked')
        balance = PointsBalance.objects.get(user=self.user)
        self.assertEqual(balance.balance, 0)
        self.assertEqual(balance.lifetime_earned, 0)
        reversal = PointsTransaction.objects.order_by('-id').first()
        self.assertEqual(reversal.points, -100)
        self.assertIn('Teruggedraaid', reversal.description)

        # Idempotent: revoking again changes nothing
        revoke_grant('hob:test:1')
        self.assertEqual(PointsBalance.objects.get(user=self.user).balance, 0)
        self.assertEqual(PointsTransaction.objects.count(), 2)

    def test_revoke_pending_never_claims(self):
        self._grant(dedupe_key='hob:pending:4', email='nieuw@example.com')
        revoke_grant('hob:pending:4')

        newcomer = User.objects.create_user(
            username='nieuw@example.com', email='nieuw@example.com', password='x',
        )
        with patch(NOTIFY_TARGET, return_value=MagicMock(id=1)):
            self.assertEqual(claim_pending_grants(newcomer), 0)
        self.assertFalse(PointsBalance.objects.filter(user=newcomer).exists())

    def test_notification_dedupe_key_and_delivery_id(self):
        with patch(NOTIFY_TARGET) as mock_notify:
            mock_notify.return_value = MagicMock(id=77)
            grant, _ = create_grant(
                dedupe_key='hob:test:notify', points=100,
                reason='Snelste reactie', shopify_customer_id='12345',
            )
        kwargs = mock_notify.call_args.kwargs
        self.assertEqual(kwargs['dedupe_key'], 'grant:hob:test:notify')
        self.assertEqual(kwargs['data'], {'url': '/loyalty'})
        self.assertEqual(grant.notified_delivery_id, 77)

    def test_notify_false_skips_notification(self):
        with patch(NOTIFY_TARGET) as mock_notify:
            create_grant(
                dedupe_key='hob:test:quiet', points=100,
                reason='Stil', shopify_customer_id='12345', notify=False,
            )
        mock_notify.assert_not_called()


@override_settings(SERVICE_API_HMAC_SECRET=SECRET)
class ServiceApiTest(TestCase):
    """HTTP layer: HMAC auth + the four endpoints."""

    def setUp(self):
        self.user = User.objects.create_user(
            username='piet@example.com', email='piet@example.com', password='x',
        )
        self.user.shopify_customer_id = '12345'
        self.user.save(update_fields=['shopify_customer_id'])

    def _post(self, path, data, secret=SECRET, signature=None):
        body = json.dumps(data).encode()
        return self.client.post(
            path, data=body, content_type='application/json',
            **{'HTTP_X_SIGNATURE': signature or sign(body, secret)},
        )

    def test_missing_signature_rejected(self):
        body = json.dumps({'dedupe_key': 'k'}).encode()
        response = self.client.post(
            '/api/service/loyalty/grant/', data=body,
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 403)

    def test_bad_signature_rejected(self):
        response = self._post(
            '/api/service/loyalty/grant/',
            {'dedupe_key': 'k'}, signature='sha256=deadbeef',
        )
        self.assertEqual(response.status_code, 403)

    @override_settings(SERVICE_API_HMAC_SECRET='')
    def test_unset_secret_disables_api(self):
        response = self._post('/api/service/loyalty/grant/', {'dedupe_key': 'k'})
        self.assertEqual(response.status_code, 503)

    def test_get_not_allowed(self):
        response = self.client.get('/api/service/loyalty/grant/')
        self.assertEqual(response.status_code, 405)

    def test_grant_endpoint_member(self):
        with patch(NOTIFY_TARGET, return_value=MagicMock(id=1)):
            response = self._post('/api/service/loyalty/grant/', {
                'dedupe_key': 'hob:api:1',
                'points': 100,
                'reason': 'Snelste reactie – sale 24 augustus',
                'phone': '+31683253135',
                'shopify_customer_id': '12345',
                'context': {'sale_id': 7},
            })

        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertEqual(data['status'], 'granted')
        self.assertTrue(data['created'])
        self.assertEqual(data['user']['email'], 'piet@example.com')
        self.assertEqual(data['user']['balance'], 100)

        # Replay returns the same grant, 200, no double award
        with patch(NOTIFY_TARGET, return_value=MagicMock(id=1)):
            replay = self._post('/api/service/loyalty/grant/', {
                'dedupe_key': 'hob:api:1', 'points': 100,
                'reason': 'Snelste reactie – sale 24 augustus',
                'shopify_customer_id': '12345',
            })
        self.assertEqual(replay.status_code, 200)
        self.assertFalse(replay.json()['created'])
        self.assertEqual(PointsBalance.objects.get(user=self.user).balance, 100)

    def test_grant_endpoint_pending_for_unknown_phone(self):
        response = self._post('/api/service/loyalty/grant/', {
            'dedupe_key': 'hob:api:2', 'points': 50,
            'reason': 'Actie', 'phone': '+31600000000',
        })
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()['status'], 'pending')

    def test_grant_endpoint_validation_error(self):
        response = self._post('/api/service/loyalty/grant/', {
            'dedupe_key': 'hob:api:3', 'points': 0,
            'reason': 'Actie', 'phone': '+31600000000',
        })
        self.assertEqual(response.status_code, 400)
        self.assertIn('points', response.json()['error'])

    def test_lookup_member_and_non_member(self):
        response = self._post('/api/service/loyalty/lookup/', {
            'shopify_customer_id': '12345',
        })
        data = response.json()
        self.assertTrue(data['found'])
        self.assertEqual(data['user']['email'], 'piet@example.com')

        with patch(NOTIFY_TARGET, return_value=MagicMock(id=1)):
            self._post('/api/service/loyalty/grant/', {
                'dedupe_key': 'hob:api:4', 'points': 100,
                'reason': 'Actie', 'phone': '+31600000000',
            })
        response = self._post('/api/service/loyalty/lookup/', {
            'phone': '+31600000000',
        })
        data = response.json()
        self.assertFalse(data['found'])
        self.assertEqual(data['pending_grants'], 1)
        self.assertEqual(data['pending_points'], 100)
        self.assertIn('note', data)

    def test_status_endpoint(self):
        with patch(NOTIFY_TARGET, return_value=MagicMock(id=1)):
            self._post('/api/service/loyalty/grant/', {
                'dedupe_key': 'hob:api:5', 'points': 100,
                'reason': 'Actie', 'shopify_customer_id': '12345',
            })

        response = self._post('/api/service/loyalty/status/', {
            'dedupe_key': 'hob:api:5',
        })
        self.assertEqual(response.json()['status'], 'granted')

        response = self._post('/api/service/loyalty/status/', {
            'source': 'hob', 'status': 'granted',
        })
        self.assertEqual(len(response.json()['grants']), 1)

        response = self._post('/api/service/loyalty/status/', {
            'dedupe_key': 'nope',
        })
        self.assertEqual(response.status_code, 404)

    def test_revoke_endpoint(self):
        with patch(NOTIFY_TARGET, return_value=MagicMock(id=1)):
            self._post('/api/service/loyalty/grant/', {
                'dedupe_key': 'hob:api:6', 'points': 100,
                'reason': 'Actie', 'shopify_customer_id': '12345',
            })
        response = self._post('/api/service/loyalty/revoke/', {
            'dedupe_key': 'hob:api:6', 'reason': 'foutje',
        })
        self.assertEqual(response.json()['status'], 'revoked')
        self.assertEqual(PointsBalance.objects.get(user=self.user).balance, 0)

        response = self._post('/api/service/loyalty/revoke/', {
            'dedupe_key': 'nope',
        })
        self.assertEqual(response.status_code, 404)


class RegistrationClaimHookTest(TestCase):
    """Registering with a pending grant claims it (email match, no Shopify)."""

    def test_register_claims_email_pending_grant(self):
        with patch(NOTIFY_TARGET, return_value=MagicMock(id=1)):
            create_grant(
                dedupe_key='hob:hook:1', points=100,
                reason='Snelste reactie', email='nieuw@example.com',
                phone='+31600000000',
            )

        with patch('users.views.ShopifyService') as mock_service, \
                patch(NOTIFY_TARGET, return_value=MagicMock(id=1)):
            mock_service.return_value.link_customer_to_user.return_value = False
            response = self.client.post('/api/auth/register/', {
                'email': 'nieuw@example.com',
                'password': 'Sterk-wachtwoord-1',
                'password_confirm': 'Sterk-wachtwoord-1',
            })

        self.assertEqual(response.status_code, 201)
        newcomer = User.objects.get(email='nieuw@example.com')
        grant = ServiceGrant.objects.get(dedupe_key='hob:hook:1')
        self.assertEqual(grant.status, 'granted')
        self.assertEqual(grant.user, newcomer)
        self.assertEqual(PointsBalance.objects.get(user=newcomer).balance, 100)
