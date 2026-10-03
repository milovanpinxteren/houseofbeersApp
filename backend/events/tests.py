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
- Presence refresh on every poll + on (re)join (raffle eligibility)
- Winner outbox notifications (sent per winner, draw survives send failures)
- Viewer name fallback (no email prefixes on the raffle overlay)

NOTE on concurrency: the test DB is SQLite, where SELECT ... FOR UPDATE is a
no-op and true parallel transactions are unreliable. The atomicity tests
simulate the admin double-click race by invoking the draw path from two stale
model instances; the status re-check inside the locked transaction is what is
being exercised. True parallel row locking is only exercised on Postgres.
"""
import json
from datetime import timedelta
from urllib.parse import quote

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.db import connection
from django.utils import timezone
from rest_framework.test import APITestCase

from .models import (
    Event, EventViewer, EventMessage, Raffle, RaffleWinner, AuctionItem, Bid,
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
        # The recent viewer plus the polling user itself (every poll now
        # refreshes presence); the stale viewer stays outside the window.
        self.assertEqual(len(names), 2)

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
        # Pre-create the presence row so every measured poll takes the
        # steady-state update path instead of create-then-update.
        EventViewer.objects.create(event=self.event, user=self.user)

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
        # Sanity bound: event + presence update_or_create (in its own
        # savepoint) + messages + winner count (+ a little headroom)
        self.assertLessEqual(count_with_100, 10)

    def test_heartbeat_poll_query_count_does_not_scale(self):
        url = self.url + '&heartbeat=1'
        self.seed_messages(10)
        with CaptureQueriesContext(connection) as ctx:
            self.client.get(url)
        count_with_10 = len(ctx.captured_queries)

        self.seed_messages(90, offset=10)
        with CaptureQueriesContext(connection) as ctx:
            self.client.get(url)
        count_with_100 = len(ctx.captured_queries)

        self.assertEqual(count_with_10, count_with_100)


class PollPresenceTests(APITestCase):
    """Every poll must refresh presence (not just the ~60s heartbeat), so a
    single dropped heartbeat can't make an actively-polling viewer
    raffle-ineligible."""

    def setUp(self):
        self.user = make_user(0)
        self.client.force_authenticate(user=self.user)
        self.event = make_event()

    def test_non_heartbeat_poll_refreshes_presence(self):
        viewer = EventViewer.objects.create(event=self.event, user=self.user)
        set_last_seen(viewer, timezone.now() - timedelta(minutes=5))

        response = self.client.get(f'/api/events/{self.event.id}/poll/')
        self.assertEqual(response.status_code, 200)

        viewer.refresh_from_db()
        self.assertGreater(
            viewer.last_seen_at,
            timezone.now() - timedelta(seconds=PRESENCE_WINDOW_SECONDS),
        )
        self.assertEqual(self.event.active_viewer_count(), 1)

    def test_poll_creates_presence_row_for_new_viewer(self):
        self.client.get(f'/api/events/{self.event.id}/poll/')
        self.assertTrue(
            EventViewer.objects.filter(event=self.event, user=self.user).exists()
        )

    def test_rejoin_refreshes_presence(self):
        viewer = EventViewer.objects.create(event=self.event, user=self.user)
        set_last_seen(viewer, timezone.now() - timedelta(minutes=5))

        response = self.client.post(f'/api/events/{self.event.id}/join/')
        self.assertEqual(response.status_code, 200)

        viewer.refresh_from_db()
        self.assertGreater(
            viewer.last_seen_at,
            timezone.now() - timedelta(seconds=PRESENCE_WINDOW_SECONDS),
        )
        # Join reports the ACTIVE viewer count, and the joiner counts
        self.assertEqual(response.data['viewer_count'], 1)


class WinnerNotificationTests(TestCase):
    """Drawn winners get a durable outbox notification: the in-stream
    overlay is ephemeral and a locked phone misses it entirely."""

    def setUp(self):
        self.event = make_event()
        self.users = [make_user(i) for i in range(3)]
        for user in self.users:
            EventViewer.objects.create(event=self.event, user=user)

    def test_draw_sends_notification_per_winner(self):
        from notifications.models import NotificationDelivery

        raffle = Raffle.objects.create(
            event=self.event, prize_name='Bierpakket', num_winners=2,
        )
        winners = raffle.draw_winners()
        self.assertEqual(len(winners), 2)

        deliveries = NotificationDelivery.objects.filter(
            dedupe_key__startswith=f'event-raffle:{raffle.id}:'
        )
        self.assertEqual(deliveries.count(), 2)
        for winner in winners:
            delivery = deliveries.get(
                dedupe_key=f'event-raffle:{raffle.id}:{winner.user_id}:won'
            )
            self.assertEqual(delivery.user_id, winner.user_id)
            self.assertEqual(delivery.kind, 'raffle')
            self.assertIn('Bierpakket', delivery.body)
            self.assertEqual(
                delivery.data.get('url'), f'/livestream?eventId={self.event.id}'
            )

    def test_notification_failure_does_not_break_draw(self):
        from unittest.mock import patch

        raffle = Raffle.objects.create(
            event=self.event, prize_name='Bierpakket', num_winners=2,
        )
        with patch(
            'notifications.services.send_notification',
            side_effect=RuntimeError('push service down'),
        ):
            winners = raffle.draw_winners()

        # The draw itself committed despite every notification failing
        self.assertEqual(len(winners), 2)
        raffle.refresh_from_db()
        self.assertEqual(raffle.status, 'drawn')
        self.assertEqual(RaffleWinner.objects.filter(raffle=raffle).count(), 2)

    def test_no_notifications_without_eligible_viewers(self):
        from notifications.models import NotificationDelivery

        EventViewer.objects.all().delete()
        raffle = Raffle.objects.create(
            event=self.event, prize_name='Bierpakket', num_winners=1,
        )
        self.assertEqual(raffle.draw_winners(), [])
        self.assertFalse(
            NotificationDelivery.objects.filter(
                dedupe_key__startswith='event-raffle:'
            ).exists()
        )


class WinnersCsvExportTests(TestCase):
    """The winners CSV is the prize-fulfillment handover: it must carry the
    Shopify match key (email) and the already-linked customer id."""

    def setUp(self):
        self.event = make_event(title='Oktober Livestream')
        self.winner_user = make_user(1)
        self.winner_user.first_name = 'Koen'
        self.winner_user.last_name = 'de Vries'
        self.winner_user.shopify_customer_id = '556677'
        self.winner_user.save()
        EventViewer.objects.create(event=self.event, user=self.winner_user)
        self.raffle = Raffle.objects.create(
            event=self.event, prize_name='Bierpakket', num_winners=1,
        )
        (self.winner,) = self.raffle.draw_winners()

    def export_via_event_action(self):
        from django.contrib.admin.sites import AdminSite
        from .admin import EventAdmin

        event_admin = EventAdmin(Event, AdminSite())
        return event_admin.export_winners_csv(
            None, Event.objects.filter(pk=self.event.pk)
        )

    def test_event_action_exports_winner_row(self):
        response = self.export_via_event_action()
        content = response.content.decode('utf-8-sig')
        lines = content.strip().splitlines()

        self.assertEqual(
            lines[0].strip(),
            'Event,Prize,Email,First name,Last name,'
            'Shopify customer ID,Drawn at,Push status,Email status',
        )
        self.assertEqual(len(lines), 2)
        row = lines[1]
        self.assertIn('Oktober Livestream', row)
        self.assertIn('Bierpakket', row)
        self.assertIn(self.winner_user.email, row)
        self.assertIn('Koen', row)
        self.assertIn('de Vries', row)
        self.assertIn('556677', row)

    def test_notification_status_included(self):
        response = self.export_via_event_action()
        row = response.content.decode('utf-8-sig').strip().splitlines()[1]
        # draw_winners sent the outbox notification; locally push is skipped
        self.assertIn('skipped', row)

    def test_unlinked_winner_exports_blank_shopify_id(self):
        self.winner_user.shopify_customer_id = None
        self.winner_user.save()
        response = self.export_via_event_action()
        row = response.content.decode('utf-8-sig').strip().splitlines()[1]
        self.assertIn(f'{self.winner_user.email},Koen,de Vries,,', row)

    def test_event_without_winners_returns_message_not_csv(self):
        from django.contrib.admin.sites import AdminSite
        from unittest.mock import MagicMock
        from .admin import EventAdmin

        empty_event = make_event(title='Nog geen trekking')
        event_admin = EventAdmin(Event, AdminSite())
        event_admin.message_user = MagicMock()
        response = event_admin.export_winners_csv(
            None, Event.objects.filter(pk=empty_event.pk)
        )
        self.assertIsNone(response)
        event_admin.message_user.assert_called_once()


class WinnerPolicyTests(TestCase):
    """Per-raffle winner policy: inherit follows the event flag, exclude and
    allow override it in either direction."""

    def setUp(self):
        self.event = make_event(exclude_past_winners=True)
        self.users = [make_user(i) for i in range(5)]
        for user in self.users:
            EventViewer.objects.create(event=self.event, user=user)

    def draw(self, policy, num_winners=3):
        raffle = Raffle.objects.create(
            event=self.event, prize_name=f'Prize {policy}',
            num_winners=num_winners, winner_policy=policy,
        )
        return {w.user_id for w in raffle.draw_winners()}

    def test_inherit_follows_event_flag(self):
        first = self.draw('inherit')
        second = self.draw('inherit')
        self.assertEqual(first & second, set())

        self.event.exclude_past_winners = False
        self.event.save()
        # 5 viewers, 5 already won: with inherit->allow the pool is full again
        third = self.draw('inherit', num_winners=5)
        self.assertEqual(len(third), 5)

    def test_allow_overrides_event_exclusion(self):
        first = self.draw('exclude', num_winners=5)
        self.assertEqual(len(first), 5)
        # Every viewer already won, but this raffle lets everyone back in
        finale = self.draw('allow', num_winners=2)
        self.assertEqual(len(finale), 2)

    def test_exclude_overrides_event_inclusion(self):
        self.event.exclude_past_winners = False
        self.event.save()
        first = self.draw('exclude')
        second = self.draw('exclude')
        self.assertEqual(first & second, set())
        self.assertEqual(len(second), 2)  # only 2 of 5 left


class PointsAwardTests(TestCase):
    """A raffle with points_award credits each winner inside the draw, with
    the same sync-safe transaction shape as service grants."""

    def setUp(self):
        self.event = make_event()
        self.users = [make_user(i) for i in range(3)]
        for user in self.users:
            EventViewer.objects.create(event=self.event, user=user)

    def test_points_credited_to_each_winner(self):
        from loyalty.models import PointsBalance, PointsTransaction

        raffle = Raffle.objects.create(
            event=self.event, prize_name='2000 Punten',
            num_winners=2, points_award=2000,
        )
        winners = raffle.draw_winners()
        self.assertEqual(len(winners), 2)

        for winner in winners:
            balance = PointsBalance.objects.get(user=winner.user)
            self.assertEqual(balance.balance, 2000)
            self.assertEqual(balance.lifetime_earned, 2000)
            self.assertEqual(balance.lifetime_spent, 0)

            txn = PointsTransaction.objects.get(user=winner.user)
            self.assertEqual(txn.transaction_type, 'earned')
            self.assertEqual(txn.points, 2000)
            self.assertEqual(txn.balance_after, 2000)
            self.assertIsNone(txn.rule)
            self.assertFalse(txn.shopify_order_id)
            self.assertEqual(txn.description, 'Livestream prijs: 2000 Punten')
            self.assertEqual(txn.breakdown[0]['source'], 'livestream_raffle')
            self.assertEqual(txn.breakdown[0]['event_raffle_id'], raffle.pk)

    def test_points_added_on_top_of_existing_balance(self):
        from loyalty.models import PointsBalance, PointsTransaction

        user = self.users[0]
        PointsBalance.objects.create(
            user=user, balance=150, lifetime_earned=500, lifetime_spent=350,
        )
        # Only this user is an eligible viewer
        EventViewer.objects.exclude(user=user).delete()

        raffle = Raffle.objects.create(
            event=self.event, prize_name='500 Punten',
            num_winners=1, points_award=500,
        )
        raffle.draw_winners()

        balance = PointsBalance.objects.get(user=user)
        self.assertEqual(balance.balance, 650)
        self.assertEqual(balance.lifetime_earned, 1000)
        self.assertEqual(
            balance.balance, balance.lifetime_earned - balance.lifetime_spent)
        self.assertEqual(
            PointsTransaction.objects.get(user=user).balance_after, 650)

    def test_physical_prize_creates_no_transaction(self):
        from loyalty.models import PointsTransaction

        raffle = Raffle.objects.create(
            event=self.event, prize_name='Bierpakket', num_winners=2,
        )
        raffle.draw_winners()
        self.assertEqual(PointsTransaction.objects.count(), 0)

    def test_notification_body_mentions_points(self):
        from notifications.models import NotificationDelivery

        raffle = Raffle.objects.create(
            event=self.event, prize_name='1000 Punten',
            num_winners=1, points_award=1000,
        )
        (winner,) = raffle.draw_winners()
        delivery = NotificationDelivery.objects.get(
            dedupe_key=f'event-raffle:{raffle.pk}:{winner.user_id}:won'
        )
        self.assertIn('1000 punten zijn direct toegevoegd', delivery.body)
        self.assertNotIn('nemen contact met je op', delivery.body)

    def test_physical_notification_body_unchanged(self):
        from notifications.models import NotificationDelivery

        raffle = Raffle.objects.create(
            event=self.event, prize_name='Bierpakket', num_winners=1,
        )
        (winner,) = raffle.draw_winners()
        delivery = NotificationDelivery.objects.get(
            dedupe_key=f'event-raffle:{raffle.pk}:{winner.user_id}:won'
        )
        self.assertIn('We nemen contact met je op', delivery.body)


# The production manifest storage needs collectstatic output; plain storage
# lets the admin-based regie template render inside tests (same as test_studio).
@override_settings(STORAGES={
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
})
class RegieViewTests(TestCase):
    """The livestream regie page: staff-only control room with per-raffle
    draw buttons and live policy switching."""

    def setUp(self):
        self.admin = User.objects.create_superuser(
            username='admin', email='admin@test.com', password='adminpass123',
        )
        self.event = make_event(title='Oktober Stream')
        self.viewer_user = make_user(1)
        EventViewer.objects.create(event=self.event, user=self.viewer_user)
        self.raffle = Raffle.objects.create(
            event=self.event, prize_name='Bierpakket', num_winners=1,
        )
        self.url = f'/admin/events/event/{self.event.pk}/regie/'

    def test_requires_staff(self):
        self.client.force_login(make_user(2))  # not staff
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertIn('/admin/login/', response.url)

    def test_page_renders_rundown(self):
        self.client.force_login(self.admin)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Oktober Stream')
        self.assertContains(response, 'Bierpakket')
        self.assertContains(response, 'Trek nu')

    def test_draw_post_draws_and_redirects(self):
        self.client.force_login(self.admin)
        response = self.client.post(f'{self.url}draw/{self.raffle.pk}/')
        self.assertRedirects(response, self.url)
        self.raffle.refresh_from_db()
        self.assertEqual(self.raffle.status, 'drawn')
        self.assertEqual(self.raffle.winners.count(), 1)

    def test_draw_get_rejected(self):
        self.client.force_login(self.admin)
        response = self.client.get(f'{self.url}draw/{self.raffle.pk}/')
        self.assertEqual(response.status_code, 405)
        self.raffle.refresh_from_db()
        self.assertEqual(self.raffle.status, 'pending')

    def test_draw_raffle_of_other_event_is_404(self):
        other_event = make_event(title='Ander event')
        other_raffle = Raffle.objects.create(
            event=other_event, prize_name='Prijs', num_winners=1,
        )
        self.client.force_login(self.admin)
        response = self.client.post(f'{self.url}draw/{other_raffle.pk}/')
        self.assertEqual(response.status_code, 404)

    def test_policy_post_updates_pending_raffle(self):
        self.client.force_login(self.admin)
        response = self.client.post(
            f'{self.url}policy/{self.raffle.pk}/', {'winner_policy': 'allow'},
        )
        self.assertRedirects(response, self.url)
        self.raffle.refresh_from_db()
        self.assertEqual(self.raffle.winner_policy, 'allow')

    def test_policy_rejected_on_drawn_raffle(self):
        self.raffle.draw_winners()
        self.client.force_login(self.admin)
        self.client.post(
            f'{self.url}policy/{self.raffle.pk}/', {'winner_policy': 'allow'},
        )
        self.raffle.refresh_from_db()
        self.assertEqual(self.raffle.winner_policy, 'inherit')

    def test_invalid_policy_rejected(self):
        self.client.force_login(self.admin)
        self.client.post(
            f'{self.url}policy/{self.raffle.pk}/', {'winner_policy': 'bogus'},
        )
        self.raffle.refresh_from_db()
        self.assertEqual(self.raffle.winner_policy, 'inherit')

    def test_stats_endpoint(self):
        self.client.force_login(self.admin)
        response = self.client.get(f'{self.url}stats/')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['active_viewer_count'], 1)
        self.assertEqual(data['winner_count'], 0)


class ImportRafflesCommandTests(TestCase):
    def setUp(self):
        self.event = make_event()

    def run_command(self, *args, **kwargs):
        import io
        from django.core.management import call_command

        out = io.StringIO()
        call_command('import_raffles', *args, stdout=out, **kwargs)
        return out.getvalue()

    def test_dry_run_creates_nothing(self):
        output = self.run_command(
            '--event', str(self.event.pk),
            '--json', '[{"prize": "Pet", "winners": 2}]',
        )
        self.assertIn('DRY-RUN', output)
        self.assertEqual(self.event.raffles.count(), 0)

    def test_apply_creates_in_list_order(self):
        import base64
        payload = json.dumps([
            {'prize': '2000 Punten', 'points': 2000},
            {'prize': 'Bourbon County Pet', 'winners': 5},
            {'prize': 'King Henry II', 'policy': 'allow'},
        ])
        self.run_command(
            '--event', str(self.event.pk),
            '--json-b64', base64.b64encode(payload.encode()).decode(),
            '--apply',
        )
        raffles = list(self.event.raffles.order_by('id'))
        self.assertEqual(
            [r.prize_name for r in raffles],
            ['2000 Punten', 'Bourbon County Pet', 'King Henry II'],
        )
        self.assertEqual(raffles[0].points_award, 2000)
        self.assertEqual(raffles[1].num_winners, 5)
        self.assertEqual(raffles[2].winner_policy, 'allow')

    def test_rerun_skips_existing_prizes(self):
        payload = '[{"prize": "Pet"}, {"prize": "Muts"}]'
        self.run_command('--event', str(self.event.pk), '--json', payload, '--apply')
        output = self.run_command(
            '--event', str(self.event.pk),
            '--json', '[{"prize": "Pet"}, {"prize": "Glas"}]', '--apply',
        )
        self.assertIn('overgeslagen', output)
        self.assertEqual(self.event.raffles.count(), 3)

    def test_invalid_policy_rejected(self):
        from django.core.management.base import CommandError

        with self.assertRaises(CommandError):
            self.run_command(
                '--event', str(self.event.pk),
                '--json', '[{"prize": "Pet", "policy": "nope"}]',
            )
        self.assertEqual(self.event.raffles.count(), 0)

    def test_unknown_event_rejected(self):
        from django.core.management.base import CommandError

        with self.assertRaises(CommandError):
            self.run_command('--event', '99999', '--json', '[{"prize": "Pet"}]')


class ViewerNameFallbackTests(APITestCase):
    """Viewers without a display name or first name must never leak their
    email prefix onto the raffle overlay."""

    def setUp(self):
        self.user = make_user(0)
        self.client.force_authenticate(user=self.user)
        self.event = make_event()

    def test_nameless_viewer_shows_generic_fallback(self):
        nameless = make_user(1)  # no first_name, no community profile
        EventViewer.objects.create(event=self.event, user=nameless)
        EventViewer.objects.create(event=self.event, user=self.user)

        response = self.client.get(f'/api/events/{self.event.id}/viewers/')
        names = [v['display_name'] for v in response.data['viewers']]
        self.assertIn('Member', names)
        for name in names:
            self.assertNotIn('user1', name)


class PartialDrawTests(TestCase):
    """draw_winners(count=N) fills slots in batches; the raffle only flips
    to 'drawn' once every num_winners slot is filled ("Trek 1" on regie)."""

    def setUp(self):
        self.event = make_event()
        self.users = [make_user(i) for i in range(6)]
        for user in self.users:
            EventViewer.objects.create(event=self.event, user=user)

    def test_single_draw_leaves_raffle_pending(self):
        raffle = Raffle.objects.create(
            event=self.event, prize_name='Taster', num_winners=4,
        )
        winners = raffle.draw_winners(count=1)
        self.assertEqual(len(winners), 1)
        raffle.refresh_from_db()
        self.assertEqual(raffle.status, 'pending')
        self.assertIsNone(raffle.drawn_at)

    def test_batches_accumulate_until_drawn(self):
        raffle = Raffle.objects.create(
            event=self.event, prize_name='Taster', num_winners=3,
        )
        self.assertEqual(len(raffle.draw_winners(count=1)), 1)
        self.assertEqual(len(raffle.draw_winners(count=1)), 1)
        raffle.refresh_from_db()
        self.assertEqual(raffle.status, 'pending')

        final = raffle.draw_winners(count=1)
        self.assertEqual(len(final), 1)
        raffle.refresh_from_db()
        self.assertEqual(raffle.status, 'drawn')
        self.assertIsNotNone(raffle.drawn_at)
        self.assertEqual(raffle.winners.count(), 3)
        # Fully drawn: another call is the already-drawn no-op
        self.assertIsNone(raffle.draw_winners())

    def test_count_clamped_to_remaining_slots(self):
        raffle = Raffle.objects.create(
            event=self.event, prize_name='Taster', num_winners=2,
        )
        winners = raffle.draw_winners(count=99)
        self.assertEqual(len(winners), 2)
        raffle.refresh_from_db()
        self.assertEqual(raffle.status, 'drawn')

    def test_no_count_draws_all_remaining(self):
        raffle = Raffle.objects.create(
            event=self.event, prize_name='Taster', num_winners=4,
        )
        raffle.draw_winners(count=1)
        rest = raffle.draw_winners()
        self.assertEqual(len(rest), 3)
        raffle.refresh_from_db()
        self.assertEqual(raffle.status, 'drawn')

    def test_same_raffle_winner_never_redrawn_even_with_allow_policy(self):
        """'allow' lets event-wide past winners back in, but a winner of an
        earlier batch of THIS raffle must never be drawn again (unique
        constraint)."""
        raffle = Raffle.objects.create(
            event=self.event, prize_name='Taster', num_winners=6,
            winner_policy='allow',
        )
        seen = set()
        for _ in range(6):
            (winner,) = raffle.draw_winners(count=1)
            self.assertNotIn(winner.user_id, seen)
            seen.add(winner.user_id)
        self.assertEqual(len(seen), 6)

    def test_insufficient_viewers_keeps_raffle_open(self):
        """A full draw with fewer eligible viewers than slots fills what it
        can and stays pending, so the rest can be drawn once more viewers
        arrive (previously the raffle closed short)."""
        raffle = Raffle.objects.create(
            event=self.event, prize_name='Taster', num_winners=10,
        )
        winners = raffle.draw_winners()
        self.assertEqual(len(winners), 6)
        raffle.refresh_from_db()
        self.assertEqual(raffle.status, 'pending')

        late_user = make_user(50)
        EventViewer.objects.create(event=self.event, user=late_user)
        raffle.winner_policy = 'allow'
        raffle.save()
        more = raffle.draw_winners()
        self.assertEqual({w.user_id for w in more}, {late_user.id})

    def test_points_awarded_per_batch(self):
        from loyalty.models import PointsTransaction

        raffle = Raffle.objects.create(
            event=self.event, prize_name='500 Punten',
            num_winners=2, points_award=500,
        )
        (first,) = raffle.draw_winners(count=1)
        self.assertEqual(
            PointsTransaction.objects.filter(user=first.user).count(), 1)
        (second,) = raffle.draw_winners(count=1)
        self.assertEqual(
            PointsTransaction.objects.filter(user=second.user).count(), 1)
        self.assertEqual(PointsTransaction.objects.count(), 2)


class ExcludedUserTests(APITestCase):
    """Event.excluded_users (presenting staff): never drawn, never on the
    name reel, but still an honest part of the viewer count."""

    def setUp(self):
        self.user = make_user(0)
        self.client.force_authenticate(user=self.user)
        self.event = make_event()
        self.host = make_user(1)
        self.host.first_name = 'Mart'
        self.host.save()
        self.event.excluded_users.add(self.host)
        self.regular = make_user(2)
        for user in [self.host, self.regular]:
            EventViewer.objects.create(event=self.event, user=user)

    def test_excluded_user_never_drawn(self):
        raffle = Raffle.objects.create(
            event=self.event, prize_name='Prijs', num_winners=5,
        )
        winners = raffle.draw_winners()
        winner_ids = {w.user_id for w in winners}
        self.assertNotIn(self.host.id, winner_ids)
        self.assertIn(self.regular.id, winner_ids)

    def test_excluded_user_not_in_poll_viewer_names(self):
        raffle = Raffle.objects.create(
            event=self.event, prize_name='Prijs', num_winners=1,
            status='drawn', drawn_at=timezone.now(),
        )
        RaffleWinner.objects.create(raffle=raffle, user=self.regular)
        response = self.client.get(
            f'/api/events/{self.event.id}/poll/?known_winner_count=0'
        )
        names = [v['display_name'] for v in response.data['viewer_names']]
        self.assertNotIn('Mart', names)

    def test_excluded_user_not_in_viewers_endpoint(self):
        response = self.client.get(f'/api/events/{self.event.id}/viewers/')
        names = [v['display_name'] for v in response.data['viewers']]
        self.assertNotIn('Mart', names)

    def test_excluded_user_still_counts_as_viewer(self):
        self.assertEqual(self.event.active_viewer_count(), 2)


class AuctionBidTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.user = make_user(0)
        self.client.force_authenticate(user=self.user)
        # Deliberately livestream-typed: raffles and auctions share an event
        self.event = make_event(status='live')
        self.item = AuctionItem.objects.create(
            event=self.event, title='BCBS 2015', starting_price='50.00',
            min_increment=5, status='active',
        )
        self.url = f'/api/events/{self.event.id}/auction/bid/'

    def tearDown(self):
        cache.clear()

    def bid(self, amount):
        return self.client.post(self.url, {'amount': amount}, format='json')

    def test_first_bid_at_starting_price_accepted(self):
        response = self.bid(50)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data['ok'])
        self.assertEqual(response.data['current_bid'], 50)
        self.assertEqual(Bid.objects.count(), 1)

    def test_first_bid_below_starting_price_rejected(self):
        response = self.bid(49)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data['error'], 'too_low')
        self.assertEqual(response.data['minimum'], 50)
        self.assertEqual(Bid.objects.count(), 0)

    def test_bid_below_current_plus_increment_rejected(self):
        other = make_user(1)
        Bid.objects.create(item=self.item, user=other, amount=60)
        response = self.bid(64)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data['error'], 'too_low')
        self.assertEqual(response.data['minimum'], 65)

    def test_bid_at_current_plus_increment_accepted(self):
        other = make_user(1)
        Bid.objects.create(item=self.item, user=other, amount=60)
        response = self.bid(65)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['current_bid'], 65)

    def test_non_integer_amount_rejected(self):
        for value in ['abc', '50.5', '', None, [50]]:
            response = self.bid(value)
            self.assertEqual(response.status_code, 400, f'amount={value!r}')
            self.assertEqual(response.data['error'], 'invalid_amount')
        self.assertEqual(Bid.objects.count(), 0)

    def test_no_active_item_rejected(self):
        self.item.status = 'pending'
        self.item.save()
        response = self.bid(50)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data['error'], 'no_active_item')

    def test_not_live_rejected(self):
        self.event.status = 'ended'
        self.event.save()
        response = self.bid(50)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data['error'], 'not_live')

    def test_bid_refreshes_presence(self):
        self.bid(50)
        viewer = EventViewer.objects.get(event=self.event, user=self.user)
        self.assertGreater(
            viewer.last_seen_at,
            timezone.now() - timedelta(seconds=PRESENCE_WINDOW_SECONDS),
        )

    def test_tie_goes_to_earliest_bidder(self):
        other = make_user(1)
        other.first_name = 'Eerste'
        other.save()
        Bid.objects.create(item=self.item, user=other, amount=50)
        # Same amount arriving later (race): stored, but not the leader
        Bid.objects.create(item=self.item, user=self.user, amount=50)
        self.assertEqual(self.item.bids.first().user_id, other.id)


class PollPayloadTests(APITestCase):
    def setUp(self):
        self.user = make_user(0)
        self.client.force_authenticate(user=self.user)
        self.event = make_event(
            youtube_url='https://www.youtube.com/live/abc123',
        )
        self.url = f'/api/events/{self.event.id}/poll/'

    def test_event_block_always_present(self):
        response = self.client.get(self.url)
        self.assertEqual(response.data['event'], {
            'status': 'live',
            'youtube_url': 'https://www.youtube.com/live/abc123',
        })

    def test_event_block_reflects_mid_stream_url_fix(self):
        self.client.get(self.url)
        self.event.youtube_url = 'https://www.youtube.com/live/NEWID'
        self.event.status = 'ended'
        self.event.save()
        response = self.client.get(self.url)
        self.assertEqual(response.data['event']['status'], 'ended')
        self.assertEqual(
            response.data['event']['youtube_url'],
            'https://www.youtube.com/live/NEWID',
        )

    def test_livestream_event_with_items_includes_auction_block(self):
        """Raffles + auction now run in ONE livestream-typed event; the
        auction payload must not require event_type == 'auction'."""
        item = AuctionItem.objects.create(
            event=self.event, title='BCBS', brewery='Goose Island',
            size='75cl', untappd_rating='4.55', starting_price='50.00',
            min_increment=10, status='active',
        )
        Bid.objects.create(item=item, user=make_user(1), amount=80)
        response = self.client.get(self.url)
        data = response.data['auction_item']
        self.assertEqual(data['id'], item.id)
        self.assertEqual(data['brewery'], 'Goose Island')
        self.assertEqual(data['size'], '75cl')
        self.assertEqual(data['min_increment'], 10)
        self.assertEqual(data['current_bid'], 80)
        self.assertEqual(data['bid_count'], 1)
        self.assertIsNotNone(data['leader_name'])

    def test_livestream_event_without_items_omits_auction_block(self):
        response = self.client.get(self.url)
        self.assertNotIn('auction_item', response.data)


class NameDisambiguationTests(APITestCase):
    """Three Ivos won on 2026-10-02 and nobody knew which one — winner and
    viewer names now carry the last-name initial."""

    def setUp(self):
        self.user = make_user(0)
        self.client.force_authenticate(user=self.user)
        self.event = make_event()

        self.ivo_b = make_user(1)
        self.ivo_b.first_name, self.ivo_b.last_name = 'Ivo', 'Bakker'
        self.ivo_b.save()
        self.ivo_s = make_user(2)
        self.ivo_s.first_name, self.ivo_s.last_name = 'Ivo', 'Smit'
        self.ivo_s.save()

        self.raffle = Raffle.objects.create(
            event=self.event, prize_name='Glas', num_winners=2,
            status='drawn', drawn_at=timezone.now(),
        )
        RaffleWinner.objects.create(raffle=self.raffle, user=self.ivo_b)
        RaffleWinner.objects.create(raffle=self.raffle, user=self.ivo_s)

    def winners_payload(self):
        response = self.client.get(
            f'/api/events/{self.event.id}/poll/?known_winner_count=0'
        )
        return response.data['winners']

    def test_winner_names_carry_last_initial(self):
        names = {w['user']['display_name'] for w in self.winners_payload()}
        self.assertEqual(names, {'Ivo B.', 'Ivo S.'})

    def test_winner_rows_carry_raffle_id(self):
        for winner in self.winners_payload():
            self.assertEqual(winner['raffle_id'], self.raffle.id)

    def test_community_display_name_wins_over_initial(self):
        from community.models import CommunityProfile

        # A profile row may already exist (created on registration)
        CommunityProfile.objects.update_or_create(
            user=self.ivo_b, defaults={'display_name': 'BierIvo'})
        names = {w['user']['display_name'] for w in self.winners_payload()}
        self.assertIn('BierIvo', names)

    def test_viewer_reel_names_carry_last_initial(self):
        EventViewer.objects.create(event=self.event, user=self.ivo_b)
        response = self.client.get(f'/api/events/{self.event.id}/viewers/')
        names = [v['display_name'] for v in response.data['viewers']]
        self.assertIn('Ivo B.', names)

    def test_no_email_leak_for_nameless_winner(self):
        nameless = make_user(3)
        raffle = Raffle.objects.create(
            event=self.event, prize_name='Pet', num_winners=1,
            status='drawn', drawn_at=timezone.now(),
        )
        RaffleWinner.objects.create(raffle=raffle, user=nameless)
        names = {w['user']['display_name'] for w in self.winners_payload()}
        self.assertIn('Member', names)
        for name in names:
            self.assertNotIn('user3', name)


class FulfillmentTypeMigrationTests(TestCase):
    """The 0007 data migration marks points raffles as points-fulfilled."""

    def test_forward_sets_points_type(self):
        import importlib
        from django.apps import apps as live_apps

        event = make_event()
        points_raffle = Raffle.objects.create(
            event=event, prize_name='2000 Punten', points_award=2000,
            fulfillment_type='manual',
        )
        physical_raffle = Raffle.objects.create(
            event=event, prize_name='Glas',
        )
        migration = importlib.import_module(
            'events.migrations.0007_raffle_fulfillment_type_points')
        migration.set_points_fulfillment(live_apps, None)

        points_raffle.refresh_from_db()
        physical_raffle.refresh_from_db()
        self.assertEqual(points_raffle.fulfillment_type, 'points')
        self.assertEqual(physical_raffle.fulfillment_type, 'manual')


@override_settings(STORAGES={
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
})
class RegieControlTests(TestCase):
    """New regie controls: partial draws, auction management, exclusions."""

    def setUp(self):
        self.admin = User.objects.create_superuser(
            username='admin', email='admin@test.com', password='adminpass123',
        )
        self.client.force_login(self.admin)
        self.event = make_event(title='Najaar Stream')
        self.viewers = [make_user(i) for i in range(4)]
        for user in self.viewers:
            EventViewer.objects.create(event=self.event, user=user)
        self.url = f'/admin/events/event/{self.event.pk}/regie/'

    def test_draw_count_one_draws_single_winner(self):
        raffle = Raffle.objects.create(
            event=self.event, prize_name='Taster', num_winners=3,
        )
        response = self.client.post(
            f'{self.url}draw/{raffle.pk}/', {'draw_count': '1'},
        )
        self.assertRedirects(response, self.url)
        raffle.refresh_from_db()
        self.assertEqual(raffle.winners.count(), 1)
        self.assertEqual(raffle.status, 'pending')

    def test_draw_without_count_fills_all_slots(self):
        raffle = Raffle.objects.create(
            event=self.event, prize_name='Taster', num_winners=3,
        )
        self.client.post(f'{self.url}draw/{raffle.pk}/')
        raffle.refresh_from_db()
        self.assertEqual(raffle.winners.count(), 3)
        self.assertEqual(raffle.status, 'drawn')

    def test_regie_page_shows_partial_draw_buttons(self):
        Raffle.objects.create(
            event=self.event, prize_name='Taster', num_winners=4,
        )
        response = self.client.get(self.url)
        self.assertContains(response, 'Trek 1')
        self.assertContains(response, 'Trek alle (4)')

    def test_auction_create_activate_bid_close_cycle(self):
        # Create via the regie form
        response = self.client.post(f'{self.url}auction/save/', {
            'title': 'King Henry II', 'brewery': 'Goose Island',
            'size': '50cl', 'untappd_rating': '4.8',
            'starting_price': '100.00', 'min_increment': '10',
            'description': 'Barrel aged', 'image_url': '',
        })
        self.assertRedirects(response, self.url)
        item = AuctionItem.objects.get(event=self.event)
        self.assertEqual(item.status, 'pending')
        self.assertEqual(item.min_increment, 10)

        # Activate deactivates any other active item
        other = AuctionItem.objects.create(
            event=self.event, title='Ander item', starting_price='10.00',
            status='active',
        )
        self.client.post(f'{self.url}auction/{item.pk}/activate/')
        item.refresh_from_db()
        other.refresh_from_db()
        self.assertEqual(item.status, 'active')
        self.assertEqual(other.status, 'pending')

        # Close: highest bidder wins at their amount
        Bid.objects.create(item=item, user=self.viewers[0], amount=120)
        Bid.objects.create(item=item, user=self.viewers[1], amount=150)
        self.client.post(f'{self.url}auction/{item.pk}/close/')
        item.refresh_from_db()
        self.assertEqual(item.status, 'sold')
        self.assertEqual(item.winner_id, self.viewers[1].id)
        self.assertEqual(item.final_price, 150)

    def test_auction_close_without_bids_returns_to_pending(self):
        item = AuctionItem.objects.create(
            event=self.event, title='Stil item', starting_price='10.00',
            status='active',
        )
        self.client.post(f'{self.url}auction/{item.pk}/close/')
        item.refresh_from_db()
        self.assertEqual(item.status, 'pending')
        self.assertIsNone(item.winner)

    def test_exclude_add_by_email_and_remove(self):
        member = self.viewers[0]
        response = self.client.post(
            f'{self.url}exclude/add/', {'q': member.email},
        )
        self.assertRedirects(response, self.url)
        self.assertIn(member, self.event.excluded_users.all())

        response = self.client.post(
            f'{self.url}exclude/remove/', {'user_id': member.pk},
        )
        self.assertRedirects(response, self.url)
        self.assertNotIn(member, self.event.excluded_users.all())

    def test_exclude_add_ambiguous_query_adds_nobody(self):
        for user in self.viewers[:2]:
            user.first_name = 'Jeroen'
            user.save()
        self.client.post(f'{self.url}exclude/add/', {'q': 'Jeroen'})
        self.assertEqual(self.event.excluded_users.count(), 0)


class ChatCsvExportTests(TestCase):
    def setUp(self):
        self.event = make_event(title='Export Stream')
        self.user = make_user(1)
        self.user.first_name = 'Kees'
        self.user.save()
        EventMessage.objects.create(
            event=self.event, user=self.user, message='Proost; allemaal',
        )

    def export(self, queryset):
        from django.contrib.admin.sites import AdminSite
        from unittest.mock import MagicMock
        from .admin import EventAdmin

        event_admin = EventAdmin(Event, AdminSite())
        event_admin.message_user = MagicMock()
        return event_admin, event_admin.export_chat_csv(None, queryset)

    def test_exports_semicolon_csv_with_bom(self):
        _, response = self.export(Event.objects.filter(pk=self.event.pk))
        raw = response.content.decode('utf-8-sig')
        lines = raw.strip().splitlines()
        self.assertEqual(lines[0], 'tijd;naam;email;bericht')
        self.assertIn('Kees', lines[1])
        self.assertIn(self.user.email, lines[1])
        # The ; inside the message must be quoted, not split
        self.assertIn('"Proost; allemaal"', lines[1])
        self.assertIn(
            f'chat-{self.event.pk}-', response['Content-Disposition'])

    def test_multiple_events_selected_is_rejected(self):
        make_event(title='Tweede')
        event_admin, response = self.export(Event.objects.all())
        self.assertIsNone(response)
        event_admin.message_user.assert_called_once()
