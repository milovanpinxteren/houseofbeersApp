"""Campaign engine tests: evaluator, actions, backfill, sentence builder,
sync-hook isolation. All Shopify calls and notification sends are mocked."""
from datetime import datetime, timezone as dt_timezone
from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.test import TestCase

from loyalty.models import (
    Campaign, CampaignAward, CampaignPreview, CampaignProgress,
    CampaignRaffle, PointsBalance, PointsRule, PointsTransaction,
    RaffleEntry,
)
from loyalty.services import LoyaltyService
from loyalty.services.campaigns import (
    apply_order_to_campaigns, build_rule_sentence, resolve_product_matchers,
    run_backfill,
)
from loyalty.tasks import campaign_backfill, refresh_campaign_snapshots

User = get_user_model()

UTC = dt_timezone.utc

WINDOW_START = datetime(2026, 9, 1, 0, 0, tzinfo=UTC)
WINDOW_END = datetime(2026, 9, 30, 20, 0, tzinfo=UTC)  # Sep 30 22:00 Amsterdam

NOTIFY_TARGET = 'notifications.services.send_notification'
DISCOUNT_TARGET = 'loyalty.services.discounts.create_discount_code'
SHOP_ORDERS_TARGET = 'users.services.shopify.ShopifyService.get_shop_orders_in_window'
TAG_TARGET = 'users.services.shopify.ShopifyService.get_product_ids_by_tag'


def item(sku='A', title=None, quantity=1, product_id=None):
    return {
        'sku': sku,
        'title': title or f'Beer {sku}',
        'quantity': quantity,
        'product_id': product_id or 1000,
    }


def order(order_id, created_at='2026-09-05T12:00:00+00:00', items=None,
          total='25.00', financial_status='paid', customer_id=None):
    result = {
        'id': order_id,
        'name': f'#{order_id}',
        'created_at': created_at,
        'financial_status': financial_status,
        'total_price': total,
        'line_items': items if items is not None else [item()],
    }
    if customer_id is not None:
        result['customer'] = {'id': customer_id}
    return result


class CampaignTestCase(TestCase):

    def make_user(self, email='drinker@example.com', shopify_customer_id='111'):
        return User.objects.create_user(
            username=email,
            email=email,
            password='SuperSecret123!',
            first_name=email.split('@')[0].title(),
            shopify_customer_id=shopify_customer_id,
        )

    def make_campaign(self, **kwargs):
        defaults = {
            'name': 'Septemberactie',
            'status': 'active',
            'action_type': 'points',
            'points_amount': 100,
            'window_start': WINDOW_START,
            'window_end': WINDOW_END,
        }
        defaults.update(kwargs)
        return Campaign.objects.create(**defaults)

    def make_raffle_campaign(self, entry_mode='single', **kwargs):
        kwargs.setdefault('action_type', 'raffle')
        kwargs.pop('points_amount', None)
        campaign = self.make_campaign(points_amount=None, **kwargs)
        raffle = CampaignRaffle.objects.create(
            campaign=campaign,
            prize_name='Magnum fles',
            entry_mode=entry_mode,
        )
        return campaign, raffle

    def apply(self, user, *orders):
        with patch(NOTIFY_TARGET) as mock_notify:
            mock_notify.return_value = MagicMock(id=42)
            for o in orders:
                apply_order_to_campaigns(user, o)
        return mock_notify


class RuleSentenceTests(CampaignTestCase):

    def test_k_of_n_raffle_sentence(self):
        campaign, _ = self.make_raffle_campaign(
            entry_mode='per_item',
            product_matchers=[
                {'type': 'sku', 'value': 'A'},
                {'type': 'sku', 'value': 'B'},
                {'type': 'sku', 'value': 'C'},
            ],
            min_distinct_products=2,
        )
        sentence = build_rule_sentence(campaign)
        self.assertIn('tussen 1 en 30 september', sentence)
        self.assertIn('minstens 2 van deze 3 bieren koopt', sentence)
        self.assertIn('doet mee in de loting', sentence)
        self.assertIn('(1 lot per gekocht item)', sentence)

    def test_fixed_points_sentence(self):
        campaign = self.make_campaign(points_amount=100)
        self.assertIn('krijgt 100 punten', build_rule_sentence(campaign))

    def test_per_item_points_sentence(self):
        campaign = self.make_campaign(points_amount=10, points_mode='per_item')
        self.assertIn('krijgt 10 punten per gekocht item', build_rule_sentence(campaign))

    def test_discount_percentage_sentence(self):
        campaign = self.make_campaign(
            action_type='discount_code', points_amount=None,
            discount_type='percentage', discount_value=Decimal('10.00'),
        )
        self.assertIn('kortingscode van 10%', build_rule_sentence(campaign))

    def test_spend_sentence(self):
        campaign = self.make_campaign(min_total_spend=Decimal('100.00'))
        sentence = build_rule_sentence(campaign)
        self.assertIn('minstens €100 besteedt', sentence)


class EvaluatorTests(CampaignTestCase):

    def test_k_of_n_qualifies_across_orders(self):
        campaign, raffle = self.make_raffle_campaign(
            product_matchers=[
                {'type': 'sku', 'value': 'A'},
                {'type': 'sku', 'value': 'B'},
                {'type': 'sku', 'value': 'C'},
            ],
            min_distinct_products=2,
        )
        user = self.make_user()

        mock_notify = self.apply(user, order(1, items=[item('A')]))
        progress = CampaignProgress.objects.get(campaign=campaign, user=user)
        self.assertIsNone(progress.qualified_at)
        mock_notify.assert_not_called()

        mock_notify = self.apply(user, order(2, items=[item('B')]))
        progress.refresh_from_db()
        self.assertIsNotNone(progress.qualified_at)

        entry = RaffleEntry.objects.get(raffle=raffle, user=user)
        self.assertEqual(entry.ticket_count, 1)
        self.assertEqual(entry.matched_products, ['Beer A', 'Beer B'])

        award = CampaignAward.objects.get(campaign=campaign, user=user)
        self.assertEqual(award.notified_delivery_id, 42)
        kwargs = mock_notify.call_args.kwargs
        self.assertEqual(kwargs['kind'], 'raffle')
        self.assertEqual(kwargs['dedupe_key'], f'campaign:{campaign.id}:{user.id}:qualified')
        self.assertEqual(kwargs['data']['url'], f'/raffle/{raffle.id}')

    def test_idempotent_reprocessing(self):
        campaign, raffle = self.make_raffle_campaign(
            entry_mode='per_item',
            product_matchers=[{'type': 'sku', 'value': 'A'}],
            min_total_quantity=2,
        )
        user = self.make_user()
        same_order = order(1, items=[item('A', quantity=2)])

        self.apply(user, same_order, same_order)
        self.apply(user, same_order)

        progress = CampaignProgress.objects.get(campaign=campaign, user=user)
        self.assertEqual(progress.data['order_count'], 1)
        self.assertEqual(progress.data['matcher_qty'], {'0': 2})
        entry = RaffleEntry.objects.get(raffle=raffle, user=user)
        self.assertEqual(entry.ticket_count, 2)

    def test_per_item_tickets_accumulate_after_qualification(self):
        campaign, raffle = self.make_raffle_campaign(
            entry_mode='per_item',
            product_matchers=[{'type': 'sku', 'value': 'A'}],
        )
        user = self.make_user()

        self.apply(user, order(1, items=[item('A', quantity=2)]))
        entry = RaffleEntry.objects.get(raffle=raffle, user=user)
        self.assertEqual(entry.ticket_count, 2)

        self.apply(user, order(2, items=[item('A', quantity=3)]))
        entry.refresh_from_db()
        self.assertEqual(entry.ticket_count, 5)

    def test_per_order_tickets(self):
        campaign, raffle = self.make_raffle_campaign(
            entry_mode='per_order',
            product_matchers=[{'type': 'sku', 'value': 'A'}],
        )
        user = self.make_user()
        self.apply(
            user,
            order(1, items=[item('A')]),
            order(2, items=[item('A')]),
            order(3, items=[item('B')]),  # does not match
        )
        entry = RaffleEntry.objects.get(raffle=raffle, user=user)
        self.assertEqual(entry.ticket_count, 2)

    def test_order_outside_window_ignored(self):
        campaign = self.make_campaign()
        user = self.make_user()
        self.apply(user, order(1, created_at='2026-08-15T12:00:00+00:00'))
        self.assertFalse(CampaignProgress.objects.filter(campaign=campaign).exists())

    def test_unpaid_order_ignored(self):
        campaign = self.make_campaign()
        user = self.make_user()
        self.apply(user, order(1, financial_status='pending'))
        self.assertFalse(CampaignProgress.objects.filter(campaign=campaign).exists())

    def test_only_after_registration(self):
        campaign = self.make_campaign(only_after_registration=True)
        user = self.make_user()
        user.date_joined = datetime(2026, 9, 10, tzinfo=UTC)
        user.save(update_fields=['date_joined'])

        self.apply(user, order(1, created_at='2026-09-05T12:00:00+00:00'))
        progress = CampaignProgress.objects.get(campaign=campaign, user=user)
        self.assertIsNone(progress.qualified_at)
        self.assertEqual(progress.data['order_count'], 0)
        # The skipped order is still recorded for idempotency
        self.assertEqual(progress.data['processed_order_ids'], ['1'])

        self.apply(user, order(2, created_at='2026-09-15T12:00:00+00:00'))
        progress.refresh_from_db()
        self.assertIsNotNone(progress.qualified_at)

    def test_registered_after_condition(self):
        campaign = self.make_campaign(
            registered_after=datetime(2026, 9, 1, tzinfo=UTC)
        )
        early_user = self.make_user('early@example.com')
        early_user.date_joined = datetime(2026, 8, 1, tzinfo=UTC)
        early_user.save(update_fields=['date_joined'])
        late_user = self.make_user('late@example.com', shopify_customer_id='222')
        late_user.date_joined = datetime(2026, 9, 2, tzinfo=UTC)
        late_user.save(update_fields=['date_joined'])

        self.apply(early_user, order(1))
        self.apply(late_user, order(2))

        self.assertIsNone(
            CampaignProgress.objects.get(campaign=campaign, user=early_user).qualified_at
        )
        self.assertIsNotNone(
            CampaignProgress.objects.get(campaign=campaign, user=late_user).qualified_at
        )

    def test_requires_untappd(self):
        from recommendations.models import UntappdProfile

        campaign = self.make_campaign(requires_untappd=True)
        linked = self.make_user('linked@example.com')
        UntappdProfile.objects.create(user=linked, username='linked')
        unlinked = self.make_user('unlinked@example.com', shopify_customer_id='222')

        self.apply(linked, order(1))
        self.apply(unlinked, order(2))

        self.assertIsNotNone(
            CampaignProgress.objects.get(campaign=campaign, user=linked).qualified_at
        )
        self.assertIsNone(
            CampaignProgress.objects.get(campaign=campaign, user=unlinked).qualified_at
        )

    def test_min_points_balance(self):
        campaign = self.make_campaign(min_points_balance=50)
        user = self.make_user()

        self.apply(user, order(1))
        self.assertIsNone(
            CampaignProgress.objects.get(campaign=campaign, user=user).qualified_at
        )

        PointsBalance.objects.create(user=user, balance=100, lifetime_earned=100)
        self.apply(user, order(2))
        self.assertIsNotNone(
            CampaignProgress.objects.get(campaign=campaign, user=user).qualified_at
        )

    def test_min_total_spend_cumulative(self):
        campaign = self.make_campaign(min_total_spend=Decimal('100.00'))
        user = self.make_user()

        self.apply(user, order(1, total='60.00'))
        progress = CampaignProgress.objects.get(campaign=campaign, user=user)
        self.assertIsNone(progress.qualified_at)
        self.assertEqual(progress.data['spend'], '60.00')

        self.apply(user, order(2, total='50.00'))
        progress.refresh_from_db()
        self.assertIsNotNone(progress.qualified_at)
        self.assertEqual(progress.data['spend'], '110.00')

    def test_min_order_value(self):
        campaign = self.make_campaign(min_order_value=Decimal('50.00'))
        user = self.make_user()

        self.apply(user, order(1, total='30.00'))
        self.assertIsNone(
            CampaignProgress.objects.get(campaign=campaign, user=user).qualified_at
        )
        self.apply(user, order(2, total='60.00'))
        self.assertIsNotNone(
            CampaignProgress.objects.get(campaign=campaign, user=user).qualified_at
        )

    def test_min_order_count(self):
        campaign = self.make_campaign(min_order_count=2)
        user = self.make_user()

        self.apply(user, order(1))
        self.assertIsNone(
            CampaignProgress.objects.get(campaign=campaign, user=user).qualified_at
        )
        self.apply(user, order(2))
        self.assertIsNotNone(
            CampaignProgress.objects.get(campaign=campaign, user=user).qualified_at
        )


class ActionTests(CampaignTestCase):

    def test_fixed_points_awarded_once(self):
        campaign = self.make_campaign(
            points_amount=100,
            product_matchers=[{'type': 'sku', 'value': 'A'}],
        )
        user = self.make_user()

        mock_notify = self.apply(
            user,
            order(1, items=[item('A')]),
            order(2, items=[item('A')]),
        )

        balance = PointsBalance.objects.get(user=user)
        self.assertEqual(balance.balance, 100)
        self.assertEqual(balance.lifetime_earned, 100)

        txn = PointsTransaction.objects.get(user=user)
        self.assertEqual(txn.transaction_type, 'earned')
        self.assertEqual(txn.points, 100)
        self.assertIsNone(txn.rule)
        self.assertEqual(txn.description, campaign.name)
        self.assertEqual(txn.breakdown, [{
            'campaign_id': campaign.id,
            'campaign_name': campaign.name,
            'points': 100,
        }])

        award = CampaignAward.objects.get(campaign=campaign, user=user)
        self.assertEqual(award.points_awarded, 100)
        self.assertEqual(award.points_transaction_id, txn.id)
        self.assertEqual(mock_notify.call_count, 1)
        self.assertEqual(mock_notify.call_args.kwargs['kind'], 'announcement')

    def test_per_item_points_incremental(self):
        campaign = self.make_campaign(
            points_amount=10, points_mode='per_item',
            product_matchers=[{'type': 'sku', 'value': 'A'}],
        )
        user = self.make_user()

        self.apply(user, order(1, items=[item('A', quantity=2)]))
        self.assertEqual(PointsBalance.objects.get(user=user).balance, 20)

        self.apply(user, order(2, items=[item('A', quantity=3)]))
        balance = PointsBalance.objects.get(user=user)
        self.assertEqual(balance.balance, 50)

        award = CampaignAward.objects.get(campaign=campaign, user=user)
        self.assertEqual(award.points_awarded, 50)
        self.assertEqual(PointsTransaction.objects.filter(user=user).count(), 2)

    def test_discount_action_creates_code(self):
        campaign = self.make_campaign(
            action_type='discount_code', points_amount=None,
            discount_type='percentage', discount_value=Decimal('10.00'),
        )
        user = self.make_user()

        with patch(DISCOUNT_TARGET) as mock_discount, \
                patch(NOTIFY_TARGET) as mock_notify:
            mock_discount.return_value = {
                'discount_id': 'gid://shopify/DiscountCodeNode/9', 'code': 'X',
            }
            mock_notify.return_value = MagicMock(id=7)
            apply_order_to_campaigns(user, order(1))

        award = CampaignAward.objects.get(campaign=campaign, user=user)
        self.assertTrue(award.discount_code.startswith('HOB-'))
        self.assertEqual(award.shopify_discount_id, 'gid://shopify/DiscountCodeNode/9')

        config_arg = mock_discount.call_args.args[1]
        self.assertEqual(config_arg, campaign)
        # Default NL body carries the code
        self.assertIn(award.discount_code, mock_notify.call_args.kwargs['body'])


class SyncHookTests(CampaignTestCase):

    def test_campaign_error_never_breaks_points_sync(self):
        PointsRule.objects.create(
            name='Order bonus', rule_type='per_order', points=10,
        )
        user = self.make_user()

        with patch(
            'loyalty.services.campaigns.apply_order_to_campaigns',
            side_effect=RuntimeError('campaign exploded'),
        ):
            result = LoyaltyService().process_all_orders_for_user(
                user, [order(1)]
            )

        self.assertEqual(result['total_awarded'], 10)
        self.assertEqual(PointsBalance.objects.get(user=user).balance, 10)

    def test_hook_called_for_every_paid_order(self):
        user = self.make_user()
        orders = [
            order(1),
            order(2, financial_status='pending'),
            order(3),
        ]
        with patch('loyalty.services.campaigns.apply_order_to_campaigns') as mock_apply:
            LoyaltyService().process_all_orders_for_user(user, orders)

        self.assertEqual(mock_apply.call_count, 2)
        called_ids = [call.args[1]['id'] for call in mock_apply.call_args_list]
        self.assertEqual(called_ids, [1, 3])


class MatcherResolutionTests(CampaignTestCase):

    def test_tag_matcher_resolves_and_matches(self):
        campaign, raffle = self.make_raffle_campaign(
            product_matchers=[{'type': 'tag', 'value': 'oktoberfest'}],
        )
        with patch(TAG_TARGET, return_value=[555, 556]) as mock_tag:
            resolve_product_matchers(campaign)
        mock_tag.assert_called_once_with('oktoberfest')

        campaign.refresh_from_db()
        self.assertEqual(campaign.resolved_product_ids, {'0': [555, 556]})
        self.assertIsNotNone(campaign.resolved_at)

        user = self.make_user()
        self.apply(user, order(1, items=[
            item('X', title='Tagged beer', product_id=555),
        ]))
        self.assertIsNotNone(
            CampaignProgress.objects.get(campaign=campaign, user=user).qualified_at
        )

    def test_failed_resolution_keeps_previous_snapshot(self):
        """Shopify down during a snapshot refresh must retain the old
        resolved ids, not wipe them (get_product_ids_by_tag raises instead
        of silently returning [])."""
        campaign, _ = self.make_raffle_campaign(
            product_matchers=[{'type': 'tag', 'value': 'oktoberfest'}],
        )
        with patch(TAG_TARGET, return_value=[555, 556]):
            resolve_product_matchers(campaign)
        campaign.refresh_from_db()
        self.assertEqual(campaign.resolved_product_ids, {'0': [555, 556]})

        with patch(TAG_TARGET, side_effect=RuntimeError('shopify down')):
            resolve_product_matchers(campaign)
        campaign.refresh_from_db()
        self.assertEqual(campaign.resolved_product_ids, {'0': [555, 556]})

    def test_no_dynamic_matchers_is_a_noop_without_shopify(self):
        campaign = self.make_campaign(
            product_matchers=[{'type': 'sku', 'value': 'A'}],
        )
        with patch(TAG_TARGET) as mock_tag:
            resolve_product_matchers(campaign)
        mock_tag.assert_not_called()
        campaign.refresh_from_db()
        self.assertIsNotNone(campaign.resolved_at)


class BackfillTests(CampaignTestCase):

    def setUp(self):
        self.campaign, self.raffle = self.make_raffle_campaign(
            entry_mode='per_item',
            product_matchers=[
                {'type': 'sku', 'value': 'A'},
                {'type': 'sku', 'value': 'B'},
            ],
            min_distinct_products=2,
        )
        self.alice = self.make_user('alice@example.com', shopify_customer_id='111')
        self.bob = self.make_user('bob@example.com', shopify_customer_id='222')
        self.shop_orders = [
            # Newest-first, as Shopify returns them
            order(4, created_at='2026-09-20T10:00:00+00:00',
                  items=[item('B')], customer_id=111),
            order(3, created_at='2026-09-15T10:00:00+00:00',
                  items=[item('A')], customer_id=222),
            order(2, created_at='2026-09-10T10:00:00+00:00',
                  items=[item('A')], customer_id=111),
            order(1, created_at='2026-09-05T10:00:00+00:00',
                  items=[item('A')], customer_id=999),  # not an app user
        ]

    def test_dry_run_reports_without_writing(self):
        with patch(SHOP_ORDERS_TARGET, return_value=self.shop_orders), \
                patch(NOTIFY_TARGET) as mock_notify:
            result = run_backfill(self.campaign, dry_run=True)

        self.assertEqual(result['orders_scanned'], 4)
        self.assertEqual(result['qualified_count'], 1)
        self.assertEqual(result['near_miss_count'], 1)

        [qualified] = result['users']
        self.assertEqual(qualified['user_id'], self.alice.id)
        self.assertEqual(qualified['email'], 'alice@example.com')
        self.assertEqual(qualified['first_name'], 'Alice')
        self.assertEqual(qualified['tickets'], 2)
        self.assertEqual(qualified['matched'], ['Beer A', 'Beer B'])

        [near_miss] = result['near_miss_users']
        self.assertEqual(near_miss['user_id'], self.bob.id)

        # Dry run writes nothing and notifies nobody
        self.assertFalse(CampaignProgress.objects.exists())
        self.assertFalse(RaffleEntry.objects.exists())
        mock_notify.assert_not_called()

    def test_live_run_writes_and_notifies(self):
        with patch(SHOP_ORDERS_TARGET, return_value=self.shop_orders), \
                patch(NOTIFY_TARGET) as mock_notify:
            mock_notify.return_value = MagicMock(id=5)
            result = run_backfill(self.campaign, dry_run=False)

        self.assertEqual(result['qualified_count'], 1)
        self.assertEqual(result['orders_scanned'], 4)

        alice_progress = CampaignProgress.objects.get(
            campaign=self.campaign, user=self.alice
        )
        self.assertIsNotNone(alice_progress.qualified_at)
        bob_progress = CampaignProgress.objects.get(
            campaign=self.campaign, user=self.bob
        )
        self.assertIsNone(bob_progress.qualified_at)

        entry = RaffleEntry.objects.get(raffle=self.raffle, user=self.alice)
        self.assertEqual(entry.ticket_count, 2)
        self.assertEqual(mock_notify.call_count, 1)

    def test_live_run_is_idempotent_with_sync_hook(self):
        """Backfill then the same order arriving via sync must not double-count."""
        with patch(SHOP_ORDERS_TARGET, return_value=self.shop_orders), \
                patch(NOTIFY_TARGET, return_value=MagicMock(id=5)):
            run_backfill(self.campaign, dry_run=False)

        self.apply(self.alice, self.shop_orders[0])

        entry = RaffleEntry.objects.get(raffle=self.raffle, user=self.alice)
        self.assertEqual(entry.ticket_count, 2)


class TaskTests(CampaignTestCase):

    def test_campaign_backfill_preview_task(self):
        campaign = self.make_campaign(status='draft')
        preview = CampaignPreview.objects.create(campaign=campaign)

        with patch(SHOP_ORDERS_TARGET, return_value=[]):
            campaign_backfill(campaign.id, preview.id)

        preview.refresh_from_db()
        self.assertEqual(preview.status, 'done')
        self.assertIsNotNone(preview.finished_at)
        self.assertEqual(preview.result['qualified_count'], 0)
        self.assertEqual(preview.result['orders_scanned'], 0)

        campaign.refresh_from_db()
        self.assertFalse(campaign.preview_stale)
        self.assertEqual(campaign.status, 'previewed')

    def test_campaign_backfill_preview_failure_recorded(self):
        campaign = self.make_campaign(status='draft')
        preview = CampaignPreview.objects.create(campaign=campaign)

        with patch(SHOP_ORDERS_TARGET, side_effect=RuntimeError('shopify down')):
            campaign_backfill(campaign.id, preview.id)

        preview.refresh_from_db()
        self.assertEqual(preview.status, 'failed')
        self.assertIn('shopify down', preview.error)
        campaign.refresh_from_db()
        self.assertTrue(campaign.preview_stale)

    def test_refresh_completes_ended_non_raffle_campaigns(self):
        ended_points = self.make_campaign(
            name='Ended points',
            window_start=datetime(2026, 6, 1, tzinfo=UTC),
            window_end=datetime(2026, 6, 30, tzinfo=UTC),
        )
        ended_raffle, _ = self.make_raffle_campaign(
            name='Ended raffle',
            window_start=datetime(2026, 6, 1, tzinfo=UTC),
            window_end=datetime(2026, 6, 30, tzinfo=UTC),
        )
        running = self.make_campaign(
            name='Running',
            window_start=datetime(2026, 6, 1, tzinfo=UTC),
            window_end=datetime(2036, 6, 30, tzinfo=UTC),
        )

        result = refresh_campaign_snapshots()

        ended_points.refresh_from_db()
        ended_raffle.refresh_from_db()
        running.refresh_from_db()
        self.assertEqual(ended_points.status, 'completed')
        # Raffle campaigns complete on draw, not window end
        self.assertEqual(ended_raffle.status, 'active')
        self.assertEqual(running.status, 'active')
        self.assertEqual(result['completed'], 1)


class PreviewStaleTests(CampaignTestCase):

    def test_condition_edit_marks_preview_stale(self):
        campaign = self.make_campaign(status='draft')
        Campaign.objects.filter(pk=campaign.pk).update(preview_stale=False)
        campaign.refresh_from_db()

        campaign.min_order_count = 3
        campaign.save()
        self.assertTrue(campaign.preview_stale)

    def test_cosmetic_edit_keeps_preview_fresh(self):
        campaign = self.make_campaign(status='draft')
        Campaign.objects.filter(pk=campaign.pk).update(preview_stale=False)
        campaign.refresh_from_db()

        campaign.description = 'New description'
        campaign.save()
        self.assertFalse(campaign.preview_stale)

    def test_active_campaign_saves_do_not_go_stale(self):
        campaign = self.make_campaign(status='active')
        Campaign.objects.filter(pk=campaign.pk).update(preview_stale=False)
        campaign.refresh_from_db()

        campaign.min_order_count = 3
        campaign.save()
        self.assertFalse(campaign.preview_stale)
