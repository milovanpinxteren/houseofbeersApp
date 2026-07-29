"""
Integration tests for the livestream/events feature.

Covers the fixes for:
- Raffle draw atomicity (double-click / concurrent draw protection)
- Poll endpoint query param validation (no 500s on malformed input)
- Sold auction item contract in the poll payload
- Winner delta protocol (winners only sent when known count differs)
- Chat: live-only posting + per-user throttle
- Unified 90s presence window (viewer count + raffle eligibility)
- Poll query count guard (must not scale with message volume)

NOTE on concurrency: the test DB is SQLite, where SELECT ... FOR UPDATE is a
no-op and true parallel transactions are unreliable. The atomicity tests
simulate the admin double-click race by invoking the draw path from two stale
model instances; the status re-check inside the locked transaction is what is
being exercised. True parallel row locking is only exercised on Postgres.
"""
from datetime import timedelta
from urllib.parse import quote

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.db import connection
from django.utils import timezone
from rest_framework.test import APITestCase

from .models import (
    Event, EventViewer, EventMessage, Raffle, RaffleWinner, AuctionItem,
    PRESENCE_WINDOW_SECONDS,
)

User = get_user_model()


def make_user(n):
    return User.objects.create_user(
        username=f'user{n}',
        email=f'user{n}@test.com',
        password='testpass123',
    )


def make_event(**kwargs):
    defaults = {
        'title': 'Test Livestream',
        'event_type': 'livestream',
        'scheduled_at': timezone.now(),
        'status': 'live',
    }
    defaults.update(kwargs)
    return Event.objects.create(**defaults)


def set_last_seen(viewer, when):
    """last_seen_at has auto_now, so bypass save() to control it."""
    EventViewer.objects.filter(pk=viewer.pk).update(last_seen_at=when)


class RaffleAtomicityTests(TestCase):
    def setUp(self):
        self.event = make_event()
        self.users = [make_user(i) for i in range(5)]
        now = timezone.now()
        for user in self.users:
            viewer = EventViewer.objects.create(event=self.event, user=user)
            set_last_seen(viewer, now)

    def test_draw_creates_exactly_num_winners(self):
        raffle = Raffle.objects.create(
            event=self.event, prize_name='Beer Pack', num_winners=2,
        )
        winners = raffle.draw_winners()

        self.assertIsNotNone(winners)
        self.assertEqual(len(winners), 2)
        self.assertEqual(RaffleWinner.objects.filter(raffle=raffle).count(), 2)
        raffle.refresh_from_db()
        self.assertEqual(raffle.status, 'drawn')
        self.assertIsNotNone(raffle.drawn_at)

    def test_double_draw_simulated_race_does_not_duplicate_winners(self):
        """Simulates an admin double click: two requests each load the raffle
        while status is still 'pending', then both call draw_winners(). The
        re-check inside the locked transaction must make the second a no-op."""
        raffle = Raffle.objects.create(
            event=self.event, prize_name='Beer Pack', num_winners=2,
        )
        # Both "requests" load the raffle before either draw runs
        instance_a = Raffle.objects.get(pk=raffle.pk)
        instance_b = Raffle.objects.get(pk=raffle.pk)
        self.assertEqual(instance_a.status, 'pending')
        self.assertEqual(instance_b.status, 'pending')

        first = instance_a.draw_winners()
        second = instance_b.draw_winners()  # in-memory status is stale 'pending'

        self.assertEqual(len(first), 2)
        self.assertIsNone(second, "Second draw must return the already-drawn signal")
        self.assertEqual(
            RaffleWinner.objects.filter(raffle=raffle).count(), 2,
            "Winner count must be exactly num_winners, never doubled",
        )

    def test_draw_on_already_drawn_raffle_returns_none(self):
        raffle = Raffle.objects.create(
            event=self.event, prize_name='Beer Pack', num_winners=1,
        )
        self.assertEqual(len(raffle.draw_winners()), 1)
        self.assertIsNone(raffle.draw_winners())
        self.assertEqual(RaffleWinner.objects.filter(raffle=raffle).count(), 1)

    def test_draw_with_no_eligible_viewers_returns_empty_and_stays_pending(self):
        empty_event = make_event(title='Empty Event')
        raffle = Raffle.objects.create(
            event=empty_event, prize_name='Beer Pack', num_winners=1,
        )
        self.assertEqual(raffle.draw_winners(), [])
        raffle.refresh_from_db()
        self.assertEqual(raffle.status, 'pending')
        self.assertEqual(RaffleWinner.objects.count(), 0)

    def test_exclude_past_winners(self):
        self.event.exclude_past_winners = True
        self.event.save()
        raffle1 = Raffle.objects.create(
            event=self.event, prize_name='Prize 1', num_winners=3,
        )
        raffle2 = Raffle.objects.create(
            event=self.event, prize_name='Prize 2', num_winners=3,
        )
        first_winner_ids = {w.user_id for w in raffle1.draw_winners()}
        second_winner_ids = {w.user_id for w in raffle2.draw_winners()}
        self.assertEqual(len(first_winner_ids), 3)
        # Only 2 of 5 viewers remain eligible
        self.assertEqual(len(second_winner_ids), 2)
        self.assertEqual(first_winner_ids & second_winner_ids, set())


class PollParamValidationTests(APITestCase):
    def setUp(self):
        self.user = make_user(0)
        self.client.force_authenticate(user=self.user)
        self.event = make_event()
        self.url = f'/api/events/{self.event.id}/poll/'

    def assert_not_500(self, url):
        response = self.client.get(url)
        self.assertLess(
            response.status_code, 500,
            f"{url} returned {response.status_code}",
        )
        return response

    def test_malformed_known_winner_count_does_not_500(self):
        for value in ['abc', '', '[1,2]', '1.5', 'None', '  ']:
            response = self.assert_not_500(
                f'{self.url}?known_winner_count={value}'
            )
            self.assertEqual(response.status_code, 200)

    def test_repeated_known_winner_count_param_does_not_500(self):
        response = self.assert_not_500(
            f'{self.url}?known_winner_count=1&known_winner_count=abc'
        )
        self.assertEqual(response.status_code, 200)

    def test_malformed_after_does_not_500(self):
        for value in ['garbage', '', 'not-a-date', '[]', '2026-99-99']:
            response = self.assert_not_500(f'{self.url}?after={value}')
            self.assertEqual(response.status_code, 200)
            # Malformed cursor falls back to the last-100 branch
            self.assertIn('messages', response.data)

    def test_valid_after_still_filters(self):
        EventMessage.objects.create(
            event=self.event, user=self.user, message='old message',
        )
        # URL-encode: an unencoded '+' in a timezone offset decodes to a space
        # (the mobile client encodes via URLSearchParams)
        future = quote((timezone.now() + timedelta(hours=1)).isoformat())
        response = self.client.get(f'{self.url}?after={future}')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['messages'], [])

    def test_malformed_after_on_chat_endpoint_does_not_500(self):
        response = self.client.get(
            f'/api/events/{self.event.id}/chat/?after=garbage'
        )
        self.assertEqual(response.status_code, 200)


class SoldAuctionContractTests(APITestCase):
    def setUp(self):
        self.user = make_user(0)
        self.client.force_authenticate(user=self.user)
        self.event = make_event(event_type='auction')
        self.url = f'/api/events/{self.event.id}/poll/'

    def test_no_items_returns_null(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.data['auction_item'])

    def test_active_item_returned(self):
        item = AuctionItem.objects.create(
            event=self.event, title='Rare Beer', starting_price='50.00',
            status='active',
        )
        response = self.client.get(self.url)
        self.assertEqual(response.data['auction_item']['id'], item.id)
        self.assertEqual(response.data['auction_item']['status'], 'active')

    def test_sold_item_returned_when_nothing_active(self):
        """The client detects the active->sold transition from this payload;
        it must be the sold item, not null."""
        item = AuctionItem.objects.create(
            event=self.event, title='Rare Beer', starting_price='50.00',
            status='active',
        )
        item.status = 'sold'
        item.final_price = '120.00'
        item.winner = self.user
        item.save()

        response = self.client.get(self.url)
        self.assertIsNotNone(response.data['auction_item'])
        self.assertEqual(response.data['auction_item']['id'], item.id)
        self.assertEqual(response.data['auction_item']['status'], 'sold')
        self.assertEqual(response.data['auction_item']['final_price'], '120.00')
        self.assertIsNotNone(response.data['auction_item']['winner_name'])

    def test_most_recently_sold_item_wins(self):
        older = AuctionItem.objects.create(
            event=self.event, title='First Item', starting_price='10.00',
            status='sold',
        )
        newer = AuctionItem.objects.create(
            event=self.event, title='Second Item', starting_price='20.00',
            status='sold',
        )
        # newer was updated last (auto_now); touch it to be explicit
        newer.save()
        response = self.client.get(self.url)
        self.assertEqual(response.data['auction_item']['id'], newer.id)

    def test_active_item_takes_precedence_over_sold(self):
        AuctionItem.objects.create(
            event=self.event, title='Sold Item', starting_price='10.00',
            status='sold',
        )
        active = AuctionItem.objects.create(
            event=self.event, title='Active Item', starting_price='20.00',
            status='active',
        )
        response = self.client.get(self.url)
        self.assertEqual(response.data['auction_item']['id'], active.id)
        self.assertEqual(response.data['auction_item']['status'], 'active')

    def test_non_auction_event_omits_auction_item(self):
        livestream = make_event(title='Plain Stream')
        response = self.client.get(f'/api/events/{livestream.id}/poll/')
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('auction_item', response.data)


class WinnerDeltaProtocolTests(APITestCase):
    def setUp(self):
        self.user = make_user(0)
        self.client.force_authenticate(user=self.user)
        self.event = make_event()
        self.url = f'/api/events/{self.event.id}/poll/'

        self.raffle = Raffle.objects.create(
            event=self.event, prize_name='Beer Pack', num_winners=2,
            status='drawn', drawn_at=timezone.now(),
        )
        self.winner_users = [make_user(1), make_user(2)]
        for user in self.winner_users:
            RaffleWinner.objects.create(raffle=self.raffle, user=user)

    def test_matching_count_omits_winners(self):
        response = self.client.get(f'{self.url}?known_winner_count=2')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['winner_count'], 2)
        self.assertNotIn('winners', response.data)
        self.assertNotIn('viewer_names', response.data)

    def test_lower_count_includes_full_winners_list(self):
        response = self.client.get(f'{self.url}?known_winner_count=0')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['winner_count'], 2)
        self.assertIn('winners', response.data)
        self.assertEqual(len(response.data['winners']), 2)
        self.assertIn('viewer_names', response.data)
        winner = response.data['winners'][0]
        self.assertIn('prize_name', winner)
        self.assertIn('user', winner)
        self.assertIn('display_name', winner['user'])

    def test_higher_count_includes_winners_after_admin_reset(self):
        """Client knew 5 winners, admin reset them to 2 — the client must
        receive the corrected list."""
        response = self.client.get(f'{self.url}?known_winner_count=5')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['winner_count'], 2)
        self.assertIn('winners', response.data)
        self.assertEqual(len(response.data['winners']), 2)

    def test_omitted_param_omits_winners(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['winner_count'], 2)
        self.assertNotIn('winners', response.data)


class ChatTests(APITestCase):
    def setUp(self):
        cache.clear()  # throttle state
        self.user = make_user(0)
        self.client.force_authenticate(user=self.user)

    def tearDown(self):
        cache.clear()

    def chat_url(self, event):
        return f'/api/events/{event.id}/chat/'

    def test_post_to_scheduled_event_rejected(self):
        event = make_event(status='scheduled')
        response = self.client.post(
            self.chat_url(event), {'message': 'hello'}, format='json',
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(EventMessage.objects.count(), 0)

    def test_post_to_ended_event_rejected(self):
        event = make_event(status='ended')
        response = self.client.post(
            self.chat_url(event), {'message': 'hello'}, format='json',
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(EventMessage.objects.count(), 0)

    def test_post_to_live_event_created(self):
        event = make_event(status='live')
        response = self.client.post(
            self.chat_url(event), {'message': 'hello stream'}, format='json',
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['message'], 'hello stream')
        self.assertEqual(
            EventMessage.objects.filter(event=event, user=self.user).count(), 1,
        )

    def test_empty_message_rejected(self):
        event = make_event(status='live')
        response = self.client.post(
            self.chat_url(event), {'message': '   '}, format='json',
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(EventMessage.objects.count(), 0)


class ChatThrottleTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.user = make_user(0)
        self.client.force_authenticate(user=self.user)
        self.event = make_event(status='live')
        self.url = f'/api/events/{self.event.id}/chat/'

    def tearDown(self):
        cache.clear()

    def test_throttle_engages_after_limit(self):
        for i in range(15):
            response = self.client.post(
                self.url, {'message': f'msg {i}'}, format='json',
            )
            self.assertEqual(
                response.status_code, 201,
                f"Post {i + 1} within the limit should succeed",
            )
        response = self.client.post(
            self.url, {'message': 'one too many'}, format='json',
        )
        self.assertEqual(response.status_code, 429)
        self.assertEqual(EventMessage.objects.count(), 15)

    def test_throttle_does_not_affect_chat_reads(self):
        for i in range(16):
            self.client.post(self.url, {'message': f'msg {i}'}, format='json')
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)

    def test_throttle_does_not_affect_poll(self):
        for i in range(16):
            self.client.post(self.url, {'message': f'msg {i}'}, format='json')
        response = self.client.get(f'/api/events/{self.event.id}/poll/')
        self.assertEqual(response.status_code, 200)


class PresenceWindowTests(APITestCase):
    def setUp(self):
        self.user = make_user(0)
        self.client.force_authenticate(user=self.user)
        self.event = make_event()

        now = timezone.now()
        self.recent_user = make_user(1)   # seen 30s ago -> active + eligible
        self.stale_user = make_user(2)    # seen 2min ago -> neither
        recent = EventViewer.objects.create(event=self.event, user=self.recent_user)
        stale = EventViewer.objects.create(event=self.event, user=self.stale_user)
        set_last_seen(recent, now - timedelta(seconds=30))
        set_last_seen(stale, now - timedelta(minutes=2))

    def test_presence_window_constant_is_90_seconds(self):
        self.assertEqual(PRESENCE_WINDOW_SECONDS, 90)

    def test_active_viewer_count_uses_window(self):
        self.assertEqual(self.event.active_viewer_count(), 1)

    def test_raffle_eligibility_uses_same_window(self):
        raffle = Raffle.objects.create(
            event=self.event, prize_name='Beer Pack', num_winners=5,
        )
        winners = raffle.draw_winners()
        self.assertEqual(len(winners), 1)
        self.assertEqual(winners[0].user_id, self.recent_user.id)

    def test_viewer_names_in_poll_use_same_window(self):
        # Force the winner-diff branch so viewer_names are included
        raffle = Raffle.objects.create(
            event=self.event, prize_name='Beer Pack', num_winners=1,
            status='drawn', drawn_at=timezone.now(),
        )
        RaffleWinner.objects.create(raffle=raffle, user=self.recent_user)
        response = self.client.get(
            f'/api/events/{self.event.id}/poll/?known_winner_count=0'
        )
        names = [v['display_name'] for v in response.data['viewer_names']]
        self.assertEqual(len(names), 1)

    def test_viewers_endpoint_uses_same_window(self):
        response = self.client.get(f'/api/events/{self.event.id}/viewers/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data['viewers']), 1)


class PollQueryCountTests(APITestCase):
    """Regression guard for the livestream load target (~100 polls/sec at
    300 viewers): the poll query count must not scale with message volume."""

    def setUp(self):
        self.user = make_user(0)
        self.client.force_authenticate(user=self.user)
        self.event = make_event()
        self.url = f'/api/events/{self.event.id}/poll/?known_winner_count=0'

    def seed_messages(self, count, offset=0):
        EventMessage.objects.bulk_create([
            EventMessage(event=self.event, user=self.user, message=f'msg {i}')
            for i in range(offset, offset + count)
        ])

    def poll_query_count(self):
        with CaptureQueriesContext(connection) as ctx:
            response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        return len(ctx.captured_queries)

    def test_query_count_does_not_scale_with_messages(self):
        self.seed_messages(10)
        count_with_10 = self.poll_query_count()

        self.seed_messages(90, offset=10)  # 100 total
        count_with_100 = self.poll_query_count()

        self.assertEqual(
            count_with_10, count_with_100,
            "Poll query count must be identical regardless of message volume",
        )
        # Sanity bound: event + messages + winner count (+ a little headroom)
        self.assertLessEqual(count_with_100, 6)

    def test_heartbeat_poll_query_count_does_not_scale(self):
        url = self.url + '&heartbeat=1'
        # Pre-create the presence row so both measured heartbeats take the
        # (steady-state) update path instead of create-then-update.
        EventViewer.objects.create(event=self.event, user=self.user)
        self.seed_messages(10)
        with CaptureQueriesContext(connection) as ctx:
            self.client.get(url)
        count_with_10 = len(ctx.captured_queries)

        self.seed_messages(90, offset=10)
        with CaptureQueriesContext(connection) as ctx:
            self.client.get(url)
        count_with_100 = len(ctx.captured_queries)

        self.assertEqual(count_with_10, count_with_100)
