"""
Tests for the client event endpoint: only whitelisted event types are
accepted, metadata is sanitized, and auth is required.
"""

from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase

from .models import UsageEvent

User = get_user_model()


class ClientEventTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='test@example.com',
            email='test@example.com',
            password='test1234',
        )
        self.client.force_authenticate(self.user)

    def test_screen_view_is_recorded(self):
        response = self.client.post('/api/analytics/event/', {
            'event_type': 'screen_view',
            'metadata': {'screen': '/ontdek'},
        }, format='json')
        self.assertEqual(response.status_code, 200)
        event = UsageEvent.objects.get()
        self.assertEqual(event.event_type, 'screen_view')
        self.assertEqual(event.user, self.user)
        self.assertEqual(event.metadata['screen'], '/ontdek')

    def test_unknown_event_type_rejected(self):
        response = self.client.post('/api/analytics/event/', {
            'event_type': 'login',  # server-side event, not client-reportable
        }, format='json')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(UsageEvent.objects.count(), 0)

    def test_oversized_metadata_is_clamped(self):
        response = self.client.post('/api/analytics/event/', {
            'event_type': 'app_shop_checkout',
            'metadata': {f'key{i}': 'x' * 500 for i in range(25)},
        }, format='json')
        self.assertEqual(response.status_code, 200)
        event = UsageEvent.objects.get()
        self.assertLessEqual(len(event.metadata), 10)
        for value in event.metadata.values():
            self.assertLessEqual(len(value), 200)

    def test_requires_authentication(self):
        self.client.force_authenticate(None)
        response = self.client.post('/api/analytics/event/', {
            'event_type': 'screen_view',
        }, format='json')
        self.assertEqual(response.status_code, 401)
        self.assertEqual(UsageEvent.objects.count(), 0)
