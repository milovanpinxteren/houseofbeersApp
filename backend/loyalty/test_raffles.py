"""Raffle tests: draw correctness, fulfillment, notifications, reminders,
redemption detection and the frozen /api/loyalty/raffles/ shape. All Shopify
calls and notification transports are mocked - nothing leaves the process."""
from datetime import timedelta
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from loyalty.models import (
    Campaign, CampaignRaffle, CampaignRafflePrize, CampaignRaffleWinner,
    RaffleEntry,
)
from loyalty.services.raffles import (
    check_winner_redemptions, draw_raffle, send_raffle_reminders,
)
from loyalty.tasks import campaign_raffle_scheduler, draw_campaign_raffle

User = get_user_model()

NOTIFY_TARGET = 'notifications.services.send_notification'
DISCOUNT_TARGET = 'loyalty.services.discounts.create_discount_code'
USAGE_TARGET = 'users.services.shopify.ShopifyService.get_discount_code_usage'

# Every key of the frozen GET /api/loyalty/raffles/ shape (CAMPAIGN_CONTRACT.md).
FROZEN_FIELDS = {
    'id', 'campaign_id', 'title', 'rule_sentence',
    'prize_name', 'prize_description', 'prize_image_url',
    'prizes', 'my_prize_name', 'winner_prizes',
    'draw_at', 'status', 'entered', 'ticket_count', 'matched_products',
    'seen', 'result_seen', 'entrant_count',
    'entrant_first_names', 'winner_first_names',
    'did_win', 'my_code', 'my_code_expires_at', 'my_code_cart_url',
    'public_winner_names',
}


class RaffleTestCase(TestCase):

    def make_user(self, email='drinker@example.com', first_name=None):
        return User.objects.create_user(
            username=email,
            email=email,
            password='SuperSecret123!',
            first_name=email.split('@')[0].title() if first_name is None else first_name,
        )

    def make_raffle(self, campaign_status='active', num_winners=1,
                    fulfillment_type='manual', draw_at=None, **campaign_kwargs):
        now = timezone.now()
        defaults = {
            'name': 'Oktoberfest raffle',
            'status': campaign_status,
            'action_type': 'raffle',
            'window_start': now - timedelta(days=10),
            'window_end': now + timedelta(days=10),
            'rule_sentence': 'Iedereen die meedoet, loot mee.',
        }
        defaults.update(campaign_kwargs)
        campaign = Campaign.objects.create(**defaults)
        raffle = CampaignRaffle.objects.create(
            campaign=campaign,
            prize_name='Magnum fles',
            prize_description='Een magnum om te delen',
            num_winners=num_winners,
            fulfillment_type=fulfillment_type,
            draw_at=draw_at,
        )
        return campaign, raffle

    def add_prize(self, raffle, name, quantity=1, ordering=0, **kwargs):
        return CampaignRafflePrize.objects.create(
            raffle=raffle, name=name, quantity=quantity, ordering=ordering,
            **kwargs
        )

    def enter(self, raffle, user, tickets=1, **kwargs):
        return RaffleEntry.objects.create(
            raffle=raffle, user=user, ticket_count=tickets, **kwargs
        )

    def draw(self, raffle):
        """Draw with the notification transport mocked out."""
        with patch(NOTIFY_TARGET) as mock_notify:
            mock_notify.return_value = MagicMock(id=99)
            winners = draw_raffle(raffle)
        return winners, mock_notify


# ============ Draw semantics ============

class DrawTests(RaffleTestCase):

    def test_draw_flips_raffle_and_campaign_status(self):
        campaign, raffle = self.make_raffle()
        self.enter(raffle, self.make_user())

        winners, _ = self.draw(raffle)

        self.assertEqual(len(winners), 1)
        raffle.refresh_from_db()
        campaign.refresh_from_db()
        self.assertEqual(raffle.status, 'drawn')
        self.assertIsNotNone(raffle.drawn_at)
        self.assertEqual(campaign.status, 'completed')

    def test_winners_are_distinct_users(self):
        _, raffle = self.make_raffle(num_winners=5)
        for i in range(8):
            self.enter(raffle, self.make_user(f'user{i}@example.com'), tickets=i + 1)

        winners, _ = self.draw(raffle)

        self.assertEqual(len(winners), 5)
        user_ids = [w.user_id for w in winners]
        self.assertEqual(len(user_ids), len(set(user_ids)), 'no user may win twice')

    def test_num_winners_exceeding_entrants_draws_everyone_once(self):
        _, raffle = self.make_raffle(num_winners=5)
        users = [self.make_user(f'few{i}@example.com') for i in range(2)]
        for user in users:
            self.enter(raffle, user)

        winners, _ = self.draw(raffle)

        self.assertEqual(len(winners), 2)
        self.assertEqual(
            {w.user_id for w in winners}, {u.id for u in users},
        )

    def test_draw_with_zero_entrants(self):
        campaign, raffle = self.make_raffle()

        winners, mock_notify = self.draw(raffle)

        self.assertEqual(winners, [])
        mock_notify.assert_not_called()
        raffle.refresh_from_db()
        self.assertEqual(raffle.status, 'drawn')
        campaign.refresh_from_db()
        self.assertEqual(campaign.status, 'completed')

    def test_double_draw_returns_none_and_adds_no_winners(self):
        _, raffle = self.make_raffle()
        self.enter(raffle, self.make_user())

        first, _ = self.draw(raffle)
        second, mock_notify = self.draw(raffle)

        self.assertEqual(len(first), 1)
        self.assertIsNone(second)
        mock_notify.assert_not_called()
        self.assertEqual(CampaignRaffleWinner.objects.count(), 1)

    def test_pool_is_weighted_by_ticket_count(self):
        _, raffle = self.make_raffle(num_winners=2)
        entry_a = self.enter(raffle, self.make_user('a@example.com'), tickets=1)
        entry_b = self.enter(raffle, self.make_user('b@example.com'), tickets=5)
        entry_c = self.enter(raffle, self.make_user('c@example.com'), tickets=2)

        captured = []

        def fake_choices(pool, weights, k):
            # Copy: the service mutates the pool list between picks.
            captured.append((list(pool), list(weights)))
            return [pool[0]]

        with patch('loyalty.services.raffles.random') as mock_random:
            # Always pick the first pool element so the draw is deterministic
            # and we can inspect the weights that were offered.
            mock_random.choices.side_effect = fake_choices
            winners, _ = self.draw(raffle)

        self.assertEqual(len(captured), 2)
        first_pool, first_weights = captured[0]
        self.assertEqual(first_weights, [e.ticket_count for e in first_pool])
        self.assertEqual(first_weights, [1, 5, 2])
        # The first pick (entry_a) must be gone from the second pool:
        # sampling is WITHOUT replacement.
        second_pool, second_weights = captured[1]
        self.assertNotIn(entry_a, second_pool)
        self.assertEqual(second_weights, [5, 2])
        self.assertEqual(
            [w.user_id for w in winners],
            [entry_a.user_id, entry_b.user_id],
            'winners come back in draw order',
        )
        self.assertIsNotNone(entry_c)  # silence unused warning

    def test_draw_task_wraps_service(self):
        _, raffle = self.make_raffle()
        self.enter(raffle, self.make_user())

        with patch(NOTIFY_TARGET, return_value=MagicMock(id=1)):
            result = draw_campaign_raffle(raffle.id)
            again = draw_campaign_raffle(raffle.id)

        self.assertEqual(result, {'winners': 1})
        self.assertEqual(again, {'already_drawn': True})


# ============ Prize tiers ============

class PrizeTierDrawTests(RaffleTestCase):
    """Several DIFFERENT prizes out of one entrant pool."""

    def test_three_prizes_go_to_three_distinct_winners_in_order(self):
        _, raffle = self.make_raffle(num_winners=1)  # ignored once tiers exist
        shirt = self.add_prize(raffle, 'T-shirt', ordering=0)
        hoodie = self.add_prize(raffle, 'Hoodie', ordering=1)
        cap = self.add_prize(raffle, 'Pet', ordering=2)
        for i in range(10):
            self.enter(raffle, self.make_user(f'user{i}@example.com'))

        winners, _ = self.draw(raffle)

        self.assertEqual(len(winners), 3)
        self.assertEqual(
            [w.prize_id for w in winners], [shirt.id, hoodie.id, cap.id],
            'prizes are handed out in ordering order',
        )
        user_ids = [w.user_id for w in winners]
        self.assertEqual(len(set(user_ids)), 3, 'nobody wins two prizes')

    def test_quantity_expands_into_multiple_slots(self):
        _, raffle = self.make_raffle()
        shirt = self.add_prize(raffle, 'T-shirt', quantity=3, ordering=0)
        cap = self.add_prize(raffle, 'Pet', quantity=1, ordering=1)
        for i in range(6):
            self.enter(raffle, self.make_user(f'user{i}@example.com'))

        winners, _ = self.draw(raffle)

        self.assertEqual(
            [w.prize_id for w in winners],
            [shirt.id, shirt.id, shirt.id, cap.id],
        )
        self.assertEqual(len({w.user_id for w in winners}), 4)

    def test_fewer_entrants_than_slots_clamps(self):
        _, raffle = self.make_raffle()
        shirt = self.add_prize(raffle, 'T-shirt', ordering=0)
        self.add_prize(raffle, 'Hoodie', ordering=1)
        self.add_prize(raffle, 'Pet', quantity=5, ordering=2)
        only = self.make_user('only@example.com')
        self.enter(raffle, only)

        winners, _ = self.draw(raffle)

        self.assertEqual(len(winners), 1)
        self.assertEqual(winners[0].user_id, only.id)
        self.assertEqual(winners[0].prize_id, shirt.id, 'the first prize goes first')
        raffle.refresh_from_db()
        self.assertEqual(raffle.status, 'drawn')

    def test_legacy_raffle_without_prizes_draws_as_before(self):
        _, raffle = self.make_raffle(num_winners=2)
        for i in range(4):
            self.enter(raffle, self.make_user(f'user{i}@example.com'))

        winners, _ = self.draw(raffle)

        self.assertEqual(len(winners), 2)
        self.assertEqual([w.prize_id for w in winners], [None, None])

    def test_per_prize_free_product_codes_use_their_own_gid(self):
        _, raffle = self.make_raffle(
            fulfillment_type='shopify_code',
            discount_type='fixed_amount', discount_value=10,
        )
        self.add_prize(
            raffle, 'T-shirt', ordering=0, discount_type='free_product',
            discount_product_gid='gid://shopify/Product/111',
            discount_validity_days=14,
        )
        self.add_prize(
            raffle, 'Hoodie', ordering=1, discount_type='free_product',
            discount_product_gid='gid://shopify/Product/222',
        )
        for i in range(2):
            self.enter(raffle, self.make_user(f'user{i}@example.com'))

        with patch(DISCOUNT_TARGET) as mock_create:
            mock_create.return_value = {'code': 'WIN-X', 'discount_id': '1',
                                        'expires_at': None}
            winners, _ = self.draw(raffle)

        configs = [call.args[1] for call in mock_create.call_args_list]
        self.assertEqual(len(configs), 2)
        self.assertEqual(
            [c.discount_product_gid for c in configs],
            ['gid://shopify/Product/111', 'gid://shopify/Product/222'],
        )
        self.assertEqual([c.discount_type for c in configs],
                         ['free_product', 'free_product'])
        # Blank prize fields fall back to the campaign's config.
        self.assertEqual(configs[0].discount_validity_days, 14)
        self.assertEqual(configs[1].discount_validity_days, 30)
        self.assertEqual(len(winners), 2)

    def test_winner_notification_names_their_own_prize(self):
        _, raffle = self.make_raffle()
        self.add_prize(raffle, 'Hoodie', ordering=0)
        self.enter(raffle, self.make_user())

        _winners, mock_notify = self.draw(raffle)

        self.assertIn('Hoodie', mock_notify.call_args.kwargs['body'])


# ============ Fulfillment ============

class FulfillmentTests(RaffleTestCase):

    def make_code_raffle(self, **kwargs):
        return self.make_raffle(
            fulfillment_type='shopify_code',
            discount_type='fixed_amount',
            discount_value=10,
            discount_validity_days=30,
            **kwargs,
        )

    def test_shopify_code_issued(self):
        expires = timezone.now() + timedelta(days=30)
        _, raffle = self.make_code_raffle()
        self.enter(raffle, self.make_user())

        with patch(DISCOUNT_TARGET) as mock_create:
            mock_create.return_value = {
                'code': 'WIN-TESTCODE', 'discount_id': 'gid://shopify/D/1',
                'expires_at': expires,
            }
            winners, _ = self.draw(raffle)

        winner = winners[0]
        winner.refresh_from_db()
        self.assertEqual(winner.fulfillment_status, 'code_issued')
        self.assertEqual(winner.prize_code, 'WIN-TESTCODE')
        self.assertEqual(winner.shopify_discount_id, 'gid://shopify/D/1')
        self.assertEqual(winner.code_expires_at, expires)
        # The generated code carries the raffle prefix and the campaign is
        # the duck-typed discount config.
        (user_arg, config_arg, code_arg), _kwargs = mock_create.call_args
        self.assertEqual(user_arg, winner.user)
        self.assertEqual(config_arg, raffle.campaign)
        self.assertTrue(code_arg.startswith('WIN-'))

    def test_shopify_failure_leaves_pending_and_still_notifies(self):
        _, raffle = self.make_code_raffle()
        loser = self.make_user('loser@example.com')
        self.enter(raffle, self.make_user())
        self.enter(raffle, loser)

        with patch(DISCOUNT_TARGET, return_value=None):
            winners, mock_notify = self.draw(raffle)

        winner = winners[0]
        winner.refresh_from_db()
        self.assertEqual(winner.fulfillment_status, 'pending')
        self.assertEqual(winner.prize_code, '')
        # Draw completed and both entrants were notified regardless.
        raffle.refresh_from_db()
        self.assertEqual(raffle.status, 'drawn')
        self.assertEqual(mock_notify.call_count, 2)

    def test_manual_fulfillment_pending(self):
        _, raffle = self.make_raffle(fulfillment_type='manual')
        self.enter(raffle, self.make_user())

        with patch(DISCOUNT_TARGET) as mock_create:
            winners, _ = self.draw(raffle)

        mock_create.assert_not_called()
        winner = winners[0]
        winner.refresh_from_db()
        self.assertEqual(winner.fulfillment_status, 'manual_pending')


# ============ Notifications ============

class DrawNotificationTests(RaffleTestCase):

    def test_winner_and_loser_get_result_notifications(self):
        campaign, raffle = self.make_raffle()
        winner_user = self.make_user('winner@example.com')
        loser_user = self.make_user('loser@example.com')
        self.enter(raffle, winner_user)
        self.enter(raffle, loser_user)

        with patch(NOTIFY_TARGET) as mock_notify:
            mock_notify.return_value = MagicMock(id=123)
            winners = draw_raffle(raffle)

        won_id = winners[0].user_id
        self.assertEqual(mock_notify.call_count, 2)
        by_user = {call.args[0].id: call for call in mock_notify.call_args_list}
        for user_id, call in by_user.items():
            self.assertEqual(call.kwargs['kind'], 'raffle')
            self.assertEqual(
                call.kwargs['dedupe_key'],
                f'campaign:{campaign.id}:{user_id}:result',
            )
            self.assertEqual(call.kwargs['data'], {'url': f'/raffle/{raffle.id}'})
        # Winner row records its delivery for the funnel.
        winners[0].refresh_from_db()
        self.assertEqual(winners[0].result_delivery_id, 123)
        # Loser copy differs from winner copy.
        self.assertNotEqual(
            by_user[won_id].kwargs['title'],
            by_user[[u for u in by_user if u != won_id][0]].kwargs['title'],
        )

    def test_winner_with_code_forces_email(self):
        _, raffle = self.make_raffle(
            fulfillment_type='shopify_code',
            discount_type='percentage', discount_value=100,
        )
        winner_user = self.make_user('winner@example.com')
        self.enter(raffle, winner_user)

        with patch(DISCOUNT_TARGET) as mock_create, patch(NOTIFY_TARGET) as mock_notify:
            mock_create.return_value = {'code': 'WIN-ABC', 'discount_id': '1',
                                        'expires_at': None}
            mock_notify.return_value = MagicMock(id=1)
            draw_raffle(raffle)

        call = mock_notify.call_args
        self.assertEqual(call.kwargs['email_policy'], 'always')
        self.assertIn('WIN-ABC', call.kwargs['body'])

    def test_winner_without_code_keeps_default_policy(self):
        _, raffle = self.make_raffle(fulfillment_type='manual')
        self.enter(raffle, self.make_user())

        with patch(NOTIFY_TARGET) as mock_notify:
            mock_notify.return_value = MagicMock(id=1)
            draw_raffle(raffle)

        self.assertIsNone(mock_notify.call_args.kwargs.get('email_policy'))

    def test_notification_failure_does_not_break_the_fanout(self):
        _, raffle = self.make_raffle(num_winners=1)
        for i in range(3):
            self.enter(raffle, self.make_user(f'user{i}@example.com'))

        with patch(NOTIFY_TARGET) as mock_notify:
            mock_notify.side_effect = [RuntimeError('smtp down'),
                                       MagicMock(id=1), MagicMock(id=2)]
            winners = draw_raffle(raffle)

        self.assertEqual(len(winners), 1)
        self.assertEqual(mock_notify.call_count, 3)
        raffle.refresh_from_db()
        self.assertEqual(raffle.status, 'drawn')


class RaffleKindWiringTests(RaffleTestCase):
    """The 'raffle' kind flows through the real notifications service."""

    def test_kind_policy_and_category_registered(self):
        from notifications.services import KIND_CATEGORY, KIND_POLICY

        self.assertEqual(KIND_POLICY['raffle'], 'fallback')
        self.assertEqual(KIND_CATEGORY['raffle'], 'raffle')

    def test_kind_choices_include_raffle(self):
        from notifications.models import (NotificationDelivery,
                                          NotificationKindSetting)

        self.assertIn('raffle', dict(NotificationDelivery.KIND_CHOICES))
        self.assertIn('raffle', dict(NotificationKindSetting.KIND_CHOICES))

    def test_kind_setting_seeded(self):
        from notifications.models import NotificationKindSetting

        setting = NotificationKindSetting.objects.get(kind='raffle')
        self.assertTrue(setting.send_push)
        self.assertEqual(setting.email_policy, 'fallback')

    def test_raffle_category_opt_out_blocks_delivery(self):
        from notifications.models import NotificationPreference
        from notifications.services import send_notification

        user = self.make_user()
        preference = NotificationPreference.for_user(user)
        preference.raffle = False
        preference.email_enabled = True
        preference.save()

        delivery = send_notification(
            user, kind='raffle', title='t', body='b',
            dedupe_key='raffle-opt-out-test',
        )
        self.assertEqual(delivery.push_status, 'skipped')
        self.assertIn('opted out', delivery.push_error)
        self.assertEqual(delivery.email_status, 'skipped')

    def test_preference_serializer_exposes_raffle_category(self):
        from notifications.serializers import NotificationPreferenceSerializer

        self.assertIn('raffle', NotificationPreferenceSerializer.Meta.fields)


# ============ Reminders & scheduler ============

class ReminderTests(RaffleTestCase):

    def test_reminder_sent_inside_window(self):
        campaign, raffle = self.make_raffle(
            draw_at=timezone.now() + timedelta(hours=2),
        )
        user = self.make_user()
        self.enter(raffle, user, tickets=3)

        with patch(NOTIFY_TARGET) as mock_notify:
            mock_notify.return_value = MagicMock(id=1)
            reminded = send_raffle_reminders()

        self.assertEqual(reminded, 1)
        call = mock_notify.call_args
        self.assertEqual(call.kwargs['kind'], 'raffle')
        self.assertEqual(
            call.kwargs['dedupe_key'],
            f'campaign:{campaign.id}:{user.id}:reminder',
        )
        raffle.refresh_from_db()
        self.assertIsNotNone(raffle.reminder_sent_at)

    def test_reminder_not_repeated(self):
        _, raffle = self.make_raffle(draw_at=timezone.now() + timedelta(hours=2))
        self.enter(raffle, self.make_user())

        with patch(NOTIFY_TARGET, return_value=MagicMock(id=1)) as mock_notify:
            send_raffle_reminders()
            send_raffle_reminders()

        self.assertEqual(mock_notify.call_count, 1)

    def test_no_reminder_outside_window_or_when_disabled(self):
        _, far = self.make_raffle(draw_at=timezone.now() + timedelta(hours=5))
        self.enter(far, self.make_user('far@example.com'))
        _, off = self.make_raffle(draw_at=timezone.now() + timedelta(hours=1))
        off.send_reminder = False
        off.save(update_fields=['send_reminder'])
        self.enter(off, self.make_user('off@example.com'))

        with patch(NOTIFY_TARGET) as mock_notify:
            reminded = send_raffle_reminders()

        self.assertEqual(reminded, 0)
        mock_notify.assert_not_called()

    def test_scheduler_draws_past_due_raffles(self):
        _, due = self.make_raffle(draw_at=timezone.now() - timedelta(minutes=10))
        self.enter(due, self.make_user('due@example.com'))
        _, future = self.make_raffle(draw_at=timezone.now() + timedelta(days=1))
        self.enter(future, self.make_user('future@example.com'))
        _, manual = self.make_raffle(draw_at=None)
        self.enter(manual, self.make_user('manual@example.com'))

        with patch(NOTIFY_TARGET, return_value=MagicMock(id=1)):
            result = campaign_raffle_scheduler()

        self.assertEqual(result['drawn'], 1)
        due.refresh_from_db()
        future.refresh_from_db()
        manual.refresh_from_db()
        self.assertEqual(due.status, 'drawn')
        self.assertEqual(future.status, 'open')
        self.assertEqual(manual.status, 'open')


# ============ Redemption detection ============

class RedemptionTests(RaffleTestCase):

    def make_winner(self, raffle, email, status='code_issued', code='WIN-AAA'):
        return CampaignRaffleWinner.objects.create(
            raffle=raffle, user=self.make_user(email),
            fulfillment_status=status, prize_code=code,
        )

    def test_used_code_marks_redeemed(self):
        _, raffle = self.make_raffle()
        winner = self.make_winner(raffle, 'w1@example.com', code='WIN-USED')

        with patch(USAGE_TARGET, return_value=1):
            result = check_winner_redemptions()

        winner.refresh_from_db()
        self.assertIsNotNone(winner.redeemed_at)
        self.assertEqual(result, {'checked': 1, 'redeemed': 1})

    def test_unused_or_unknown_code_left_alone(self):
        _, raffle = self.make_raffle()
        unused = self.make_winner(raffle, 'w1@example.com', code='WIN-UNUSED')
        unknown = self.make_winner(raffle, 'w2@example.com', code='WIN-GONE')

        with patch(USAGE_TARGET, side_effect=[0, None]):
            result = check_winner_redemptions()

        unused.refresh_from_db()
        unknown.refresh_from_db()
        self.assertIsNone(unused.redeemed_at)
        self.assertIsNone(unknown.redeemed_at)
        self.assertEqual(result['redeemed'], 0)

    def test_shopify_error_skips_only_that_winner(self):
        _, raffle = self.make_raffle()
        broken = self.make_winner(raffle, 'w1@example.com', code='WIN-ERR')
        fine = self.make_winner(raffle, 'w2@example.com', code='WIN-OK')

        with patch(USAGE_TARGET, side_effect=[RuntimeError('boom'), 1]):
            result = check_winner_redemptions()

        broken.refresh_from_db()
        fine.refresh_from_db()
        self.assertIsNone(broken.redeemed_at)
        self.assertIsNotNone(fine.redeemed_at)
        self.assertEqual(result['redeemed'], 1)

    def test_manual_and_already_redeemed_winners_not_checked(self):
        _, raffle = self.make_raffle()
        self.make_winner(raffle, 'w1@example.com', status='manual_pending', code='')
        done = self.make_winner(raffle, 'w2@example.com', code='WIN-DONE')
        done.redeemed_at = timezone.now()
        done.save(update_fields=['redeemed_at'])

        with patch(USAGE_TARGET) as mock_usage:
            result = check_winner_redemptions()

        mock_usage.assert_not_called()
        self.assertEqual(result, {'checked': 0, 'redeemed': 0})


# ============ Mobile API ============

class RaffleApiTests(RaffleTestCase):

    def setUp(self):
        self.client = APIClient()
        self.user = self.make_user('caller@example.com', first_name='Caller')
        self.client.force_authenticate(user=self.user)

    def get_raffles(self):
        response = self.client.get('/api/loyalty/raffles/')
        self.assertEqual(response.status_code, 200)
        return response.data['raffles']

    def test_requires_auth(self):
        self.client.force_authenticate(user=None)
        response = self.client.get('/api/loyalty/raffles/')
        self.assertIn(response.status_code, (401, 403))

    def test_open_raffle_entrant_shape(self):
        _, raffle = self.make_raffle(draw_at=timezone.now() + timedelta(days=2))
        self.enter(raffle, self.user, tickets=3,
                   matched_products=['Beer A', 'Beer B'])
        self.enter(raffle, self.make_user('other@example.com'))

        raffles = self.get_raffles()
        self.assertEqual(len(raffles), 1)
        payload = raffles[0]
        self.assertEqual(set(payload.keys()), FROZEN_FIELDS)
        self.assertEqual(payload['id'], raffle.id)
        self.assertEqual(payload['campaign_id'], raffle.campaign_id)
        self.assertEqual(payload['title'], 'Oktoberfest raffle')
        self.assertEqual(payload['rule_sentence'], 'Iedereen die meedoet, loot mee.')
        self.assertEqual(payload['prize_name'], 'Magnum fles')
        self.assertEqual(payload['status'], 'open')
        self.assertTrue(payload['entered'])
        self.assertEqual(payload['ticket_count'], 3)
        self.assertEqual(payload['matched_products'], ['Beer A', 'Beer B'])
        self.assertFalse(payload['seen'])
        self.assertFalse(payload['result_seen'])
        self.assertEqual(payload['entrant_count'], 2)
        for null_field in ('entrant_first_names', 'winner_first_names',
                           'did_win', 'my_code', 'my_code_expires_at',
                           'public_winner_names'):
            self.assertIsNone(payload[null_field], null_field)

    def test_open_raffle_visible_to_non_entrant_as_teaser(self):
        self.make_raffle()

        payload = self.get_raffles()[0]
        self.assertFalse(payload['entered'])
        self.assertEqual(payload['ticket_count'], 0)
        self.assertEqual(payload['matched_products'], [])
        self.assertFalse(payload['seen'])

    def test_open_raffle_of_inactive_campaign_hidden(self):
        self.make_raffle(campaign_status='draft')
        self.assertEqual(self.get_raffles(), [])

    def test_drawn_raffle_for_loser(self):
        _, raffle = self.make_raffle()
        self.enter(raffle, self.user)
        winner_user = self.make_user('winner@example.com', first_name='Willem')
        self.enter(raffle, winner_user, tickets=100)
        nameless = self.make_user('kees.pils@example.com', first_name='')
        self.enter(raffle, nameless)

        with patch('loyalty.services.raffles.random') as mock_random:
            mock_random.choices.side_effect = (
                lambda pool, weights, k: [next(
                    e for e in pool if e.user_id == winner_user.id
                )]
            )
            winners, _ = self.draw(raffle)

        payload = self.get_raffles()[0]
        self.assertEqual(set(payload.keys()), FROZEN_FIELDS)
        self.assertEqual(payload['status'], 'drawn')
        self.assertFalse(payload['did_win'])
        self.assertEqual(payload['winner_first_names'], ['Willem'])
        self.assertEqual(payload['public_winner_names'], ['Willem'])
        self.assertIsNone(payload['my_code'])
        self.assertIsNone(payload['my_code_expires_at'])
        # All entrants appear; the blank-first-name user falls back to the
        # email prefix.
        self.assertEqual(
            sorted(payload['entrant_first_names']),
            sorted(['Caller', 'Willem', 'kees.pils']),
        )

    def test_drawn_raffle_for_winner_includes_code(self):
        expires = timezone.now() + timedelta(days=30)
        _, raffle = self.make_raffle(
            fulfillment_type='shopify_code',
            discount_type='fixed_amount', discount_value=25,
        )
        self.enter(raffle, self.user)

        with patch(DISCOUNT_TARGET) as mock_create:
            mock_create.return_value = {'code': 'WIN-MINE', 'discount_id': '1',
                                        'expires_at': expires}
            self.draw(raffle)

        payload = self.get_raffles()[0]
        self.assertTrue(payload['did_win'])
        self.assertEqual(payload['my_code'], 'WIN-MINE')
        self.assertIsNotNone(payload['my_code_expires_at'])

    def test_prize_tiers_in_payload_before_and_after_the_draw(self):
        _, raffle = self.make_raffle(draw_at=timezone.now() + timedelta(days=1))
        self.add_prize(raffle, 'T-shirt', quantity=2, ordering=0,
                       description='In jouw maat')
        self.add_prize(raffle, 'Hoodie', ordering=1)
        self.enter(raffle, self.user)
        other = self.make_user('other@example.com', first_name='Otto')
        self.enter(raffle, other)

        payload = self.get_raffles()[0]
        self.assertEqual(set(payload.keys()), FROZEN_FIELDS)
        self.assertEqual(
            [(p['name'], p['quantity'], p['ordering']) for p in payload['prizes']],
            [('T-shirt', 2, 0), ('Hoodie', 1, 1)],
        )
        self.assertEqual(payload['prizes'][0]['description'], 'In jouw maat')
        self.assertIsNone(payload['my_prize_name'], 'null before the draw')
        self.assertIsNone(payload['winner_prizes'])

        self.draw(raffle)

        payload = self.get_raffles()[0]
        # 3 slots, 2 entrants: both win, and the T-shirt (quantity 2) fills
        # both slots before the hoodie is reached.
        self.assertEqual(payload['winner_prizes'], ['T-shirt', 'T-shirt'])
        self.assertEqual(len(payload['winner_prizes']), len(payload['winner_first_names']))
        self.assertTrue(payload['did_win'])
        self.assertEqual(payload['my_prize_name'], 'T-shirt')

    def test_legacy_raffle_reports_empty_prize_fields(self):
        _, raffle = self.make_raffle()
        self.enter(raffle, self.user)
        self.draw(raffle)

        payload = self.get_raffles()[0]
        self.assertEqual(set(payload.keys()), FROZEN_FIELDS)
        self.assertEqual(payload['prizes'], [])
        self.assertIsNone(payload['my_prize_name'])
        self.assertIsNone(payload['winner_prizes'])
        self.assertEqual(payload['prize_name'], 'Magnum fles')

    def test_drawn_raffle_hidden_from_non_entrants(self):
        _, raffle = self.make_raffle()
        self.enter(raffle, self.make_user('someone@example.com'))
        self.draw(raffle)

        self.assertEqual(self.get_raffles(), [])

    def test_old_drawn_raffle_stays_visible_to_entrant(self):
        """Drawn raffles are the entrant's archive (Loyalty codes tab): no
        time cutoff, so a winner's code stays reachable while it's valid."""
        _, raffle = self.make_raffle()
        self.enter(raffle, self.user)
        self.draw(raffle)
        CampaignRaffle.objects.filter(pk=raffle.pk).update(
            drawn_at=timezone.now() - timedelta(days=45)
        )

        raffles = self.get_raffles()
        self.assertEqual([r['id'] for r in raffles], [raffle.id])

    def test_drawn_history_is_capped_and_newest_first(self):
        from loyalty.views import RafflesListView

        limit = RafflesListView.DRAWN_HISTORY_LIMIT
        ids = []
        for i in range(limit + 2):
            _, raffle = self.make_raffle(name=f'Actie {i}')
            self.enter(raffle, self.user)
            self.draw(raffle)
            CampaignRaffle.objects.filter(pk=raffle.pk).update(
                drawn_at=timezone.now() - timedelta(days=i)
            )
            ids.append(raffle.id)

        raffles = self.get_raffles()
        # Newest draws first; the 2 oldest fall off the end.
        self.assertEqual([r['id'] for r in raffles], ids[:limit])

    def test_open_raffles_sort_before_drawn(self):
        _, drawn = self.make_raffle(name='Oude actie')
        self.enter(drawn, self.user)
        self.draw(drawn)
        _, open_raffle = self.make_raffle(
            name='Nieuwe actie', draw_at=timezone.now() + timedelta(days=1),
        )
        self.enter(open_raffle, self.user)

        raffles = self.get_raffles()
        self.assertEqual([r['id'] for r in raffles],
                         [open_raffle.id, drawn.id])


class SeenEndpointTests(RaffleTestCase):

    def setUp(self):
        self.client = APIClient()
        self.user = self.make_user('caller@example.com')
        self.client.force_authenticate(user=self.user)

    def test_seen_sets_timestamp_once_and_returns_empty_204(self):
        _, raffle = self.make_raffle()
        entry = self.enter(raffle, self.user)

        response = self.client.post(f'/api/loyalty/raffles/{raffle.id}/seen/')
        self.assertEqual(response.status_code, 204)
        self.assertEqual(response.content, b'', '204 body must be empty')

        entry.refresh_from_db()
        first_seen = entry.seen_at
        self.assertIsNotNone(first_seen)

        response = self.client.post(f'/api/loyalty/raffles/{raffle.id}/seen/')
        self.assertEqual(response.status_code, 204)
        entry.refresh_from_db()
        self.assertEqual(entry.seen_at, first_seen, 'timestamp is set only once')

    def test_result_seen_sets_timestamp_and_returns_empty_204(self):
        _, raffle = self.make_raffle()
        entry = self.enter(raffle, self.user)

        response = self.client.post(
            f'/api/loyalty/raffles/{raffle.id}/result-seen/'
        )
        self.assertEqual(response.status_code, 204)
        self.assertEqual(response.content, b'')
        entry.refresh_from_db()
        self.assertIsNotNone(entry.result_seen_at)
        self.assertIsNone(entry.seen_at, 'seen and result-seen are independent')

    def test_no_entry_is_a_204_no_op(self):
        _, raffle = self.make_raffle()

        for suffix in ('seen', 'result-seen'):
            response = self.client.post(
                f'/api/loyalty/raffles/{raffle.id}/{suffix}/'
            )
            self.assertEqual(response.status_code, 204)
            self.assertEqual(response.content, b'')
        self.assertEqual(RaffleEntry.objects.count(), 0)

    def test_unknown_raffle_is_a_204_no_op(self):
        response = self.client.post('/api/loyalty/raffles/9999/seen/')
        self.assertEqual(response.status_code, 204)
