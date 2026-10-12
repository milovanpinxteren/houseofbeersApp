"""
Tests for the service events API (/api/service/events/) — the hob
"Push naar app" surface: HMAC auth, the upcoming-events picker feed and
the idempotent auction-item upsert.
"""
import hashlib
import hmac
import json
from decimal import Decimal

from django.test import TestCase, override_settings
from django.utils import timezone

from .models import AuctionItem, Event

SECRET = 'test-secret'

UPCOMING_URL = '/api/service/events/upcoming-events/'
UPSERT_URL = '/api/service/events/auction-items/upsert/'


def sign(body: bytes, secret: str = SECRET) -> str:
    return 'sha256=' + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def make_event(**kwargs):
    defaults = {
        'title': 'Oktober livestream',
        'event_type': 'livestream',
        'scheduled_at': timezone.now() + timezone.timedelta(days=7),
        'status': 'scheduled',
    }
    defaults.update(kwargs)
    return Event.objects.create(**defaults)


def upsert_payload(event, **overrides):
    payload = {
        'dedupe_key': 'hob:auction:12:345',
        'event_id': event.id,
        'title': 'Westvleteren 12 2015',
        'description': 'Verticale, perfect bewaard',
        'brewery': 'Westvleteren',
        'size': '33cl',
        'untappd_rating': 4.42,
        'image_url': 'https://cdn.example.com/west12.jpg',
        'starting_price': '50.00',
        'min_increment': 10,
    }
    payload.update(overrides)
    return payload


@override_settings(SERVICE_API_HMAC_SECRET=SECRET)
class ServiceEventsApiTests(TestCase):
    def _post(self, url, payload, secret=SECRET):
        body = json.dumps(payload).encode()
        return self.client.post(
            url, body, content_type='application/json',
            **{'HTTP_X_SIGNATURE': sign(body, secret)},
        )

    # --- auth plumbing (shared decorator, sanity checks only) ----------

    def test_bad_signature_rejected(self):
        response = self._post(UPCOMING_URL, {}, secret='wrong')
        self.assertEqual(response.status_code, 403)

    @override_settings(SERVICE_API_HMAC_SECRET='')
    def test_unconfigured_api_disabled(self):
        response = self._post(UPCOMING_URL, {})
        self.assertEqual(response.status_code, 503)

    # --- upcoming events ----------------------------------------------

    def test_upcoming_events_lists_scheduled_and_live_only(self):
        later = make_event(title='Later',
                           scheduled_at=timezone.now() + timezone.timedelta(days=14))
        live = make_event(title='Nu live', status='live',
                          scheduled_at=timezone.now())
        make_event(title='Voorbij', status='ended')

        response = self._post(UPCOMING_URL, {})
        self.assertEqual(response.status_code, 200)
        events = response.json()['events']
        self.assertEqual([e['id'] for e in events], [live.id, later.id])
        self.assertEqual(events[0]['status'], 'live')
        self.assertIn('scheduled_at', events[0])
        self.assertEqual(events[1]['event_type'], 'livestream')

    # --- upsert: create ------------------------------------------------

    def test_create(self):
        event = make_event()
        response = self._post(UPSERT_URL, upsert_payload(event))
        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertTrue(data['created'])
        self.assertEqual(data['status'], 'pending')
        self.assertEqual(data['event_id'], event.id)

        item = AuctionItem.objects.get(pk=data['id'])
        self.assertEqual(item.source_key, 'hob:auction:12:345')
        self.assertEqual(item.title, 'Westvleteren 12 2015')
        self.assertEqual(item.brewery, 'Westvleteren')
        self.assertEqual(item.size, '33cl')
        self.assertEqual(item.starting_price, Decimal('50.00'))
        self.assertEqual(item.min_increment, 10)
        self.assertEqual(item.untappd_rating, Decimal('4.42'))
        self.assertEqual(item.status, 'pending')

    def test_minimal_payload_defaults(self):
        event = make_event()
        response = self._post(UPSERT_URL, {
            'dedupe_key': 'hob:auction:1:2',
            'event_id': event.id,
            'title': 'Zeer oud bier',
            'starting_price': 25,
        })
        self.assertEqual(response.status_code, 201)
        item = AuctionItem.objects.get(pk=response.json()['id'])
        self.assertEqual(item.min_increment, 5)
        self.assertIsNone(item.untappd_rating)
        self.assertEqual(item.description, '')

    # --- upsert: update ------------------------------------------------

    def test_repush_updates_pending_item(self):
        event = make_event()
        other_event = make_event(title='Andere stream')
        created = self._post(UPSERT_URL, upsert_payload(event)).json()

        response = self._post(UPSERT_URL, upsert_payload(
            other_event, title='Westvleteren 12 2016',
            starting_price='60.00'))
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertFalse(data['created'])
        self.assertEqual(data['id'], created['id'])

        item = AuctionItem.objects.get(pk=created['id'])
        self.assertEqual(item.title, 'Westvleteren 12 2016')
        self.assertEqual(item.starting_price, Decimal('60.00'))
        self.assertEqual(item.event, other_event)
        self.assertEqual(AuctionItem.objects.count(), 1)

    def test_repush_refused_once_item_started(self):
        event = make_event()
        created = self._post(UPSERT_URL, upsert_payload(event)).json()
        AuctionItem.objects.filter(pk=created['id']).update(status='sold')

        response = self._post(UPSERT_URL, upsert_payload(
            event, title='Nieuwe titel'))
        self.assertEqual(response.status_code, 409)
        data = response.json()
        self.assertEqual(data['status'], 'sold')
        self.assertEqual(data['id'], created['id'])
        item = AuctionItem.objects.get(pk=created['id'])
        self.assertEqual(item.title, 'Westvleteren 12 2015')  # unchanged

    # --- upsert: validation --------------------------------------------

    def test_validation_errors(self):
        event = make_event()
        cases = [
            ({'title': ''}, 'title'),
            ({'dedupe_key': ''}, 'dedupe_key'),
            ({'starting_price': 'veel'}, 'starting_price'),
            ({'starting_price': -5}, 'starting_price'),
            ({'min_increment': 0}, 'min_increment'),
            ({'untappd_rating': 7}, 'untappd_rating'),
            ({'event_id': None}, 'event_id'),
            ({'event_id': 99999}, 'event_id'),
        ]
        for overrides, needle in cases:
            with self.subTest(**overrides):
                response = self._post(
                    UPSERT_URL, upsert_payload(event, **overrides))
                self.assertEqual(response.status_code, 400)
                self.assertIn(needle, response.json()['error'])
        self.assertEqual(AuctionItem.objects.count(), 0)

    def test_ended_event_refused(self):
        event = make_event(status='ended')
        response = self._post(UPSERT_URL, upsert_payload(event))
        self.assertEqual(response.status_code, 400)
        self.assertIn('ended', response.json()['error'])
