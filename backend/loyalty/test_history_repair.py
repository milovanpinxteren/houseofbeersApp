"""
Tests for update-in-place sync corrections and the repair_loyalty_history
command that fixes legacy correction rows and lifetime counters.
"""
from decimal import Decimal
from io import StringIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase

from loyalty.models import (
    PointsRule, Reward, PointsBalance, PointsTransaction,
    Redemption, ProcessedOrder
)
from loyalty.services import LoyaltyService

User = get_user_model()


def make_order(order_id, total, name=None):
    return {
        'id': order_id,
        'name': name or f'#{order_id}',
        'total_price': str(total),
        'financial_status': 'paid',
        'line_items': [],
        'created_at': '2026-01-15T12:00:00+00:00',
    }


class CheckAndCorrectTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user(
            username='corr@example.com', email='corr@example.com',
            password='SuperSecret123!'
        )
        self.rule = PointsRule.objects.create(
            name='1 punt per euro', rule_type='per_euro', points=1,
            multiplier=Decimal('1.00'),
        )
        self.service = LoyaltyService()

    def test_downward_correction_updates_earned_row_in_place(self):
        order = make_order(1001, '100.00')
        self.service.award_points_for_order(self.user, order)

        self.rule.multiplier = Decimal('0.50')
        self.rule.save()
        self.service.check_and_correct_points(self.user, [order])

        txns = PointsTransaction.objects.filter(user=self.user)
        self.assertEqual(txns.count(), 1)
        txn = txns.get()
        self.assertEqual(txn.transaction_type, 'earned')
        self.assertEqual(txn.points, 50)
        self.assertEqual(txn.balance_after, 50)
        self.assertEqual(txn.breakdown[0]['points'], 50)

        balance = PointsBalance.objects.get(user=self.user)
        self.assertEqual(balance.balance, 50)
        self.assertEqual(balance.lifetime_earned, 50)
        self.assertEqual(balance.lifetime_spent, 0)
        self.assertEqual(
            ProcessedOrder.objects.get(shopify_order_id='1001').points_awarded, 50
        )

    def test_correction_to_zero_deletes_the_earned_row(self):
        order = make_order(1002, '100.00')
        self.service.award_points_for_order(self.user, order)

        self.rule.is_active = False
        self.rule.save()
        self.service.check_and_correct_points(self.user, [order])

        self.assertEqual(PointsTransaction.objects.filter(user=self.user).count(), 0)
        balance = PointsBalance.objects.get(user=self.user)
        self.assertEqual(balance.balance, 0)
        self.assertEqual(balance.lifetime_earned, 0)
        self.assertEqual(balance.lifetime_spent, 0)

    def test_upward_correction_updates_earned_row_in_place(self):
        order = make_order(1003, '100.00')
        self.service.award_points_for_order(self.user, order)

        self.rule.multiplier = Decimal('2.00')
        self.rule.save()
        self.service.check_and_correct_points(self.user, [order])

        txn = PointsTransaction.objects.get(user=self.user)
        self.assertEqual(txn.points, 200)
        balance = PointsBalance.objects.get(user=self.user)
        self.assertEqual(balance.balance, 200)
        self.assertEqual(balance.lifetime_earned, 200)
        self.assertEqual(balance.lifetime_spent, 0)

    def test_award_stores_breakdown(self):
        order = make_order(1004, '30.00')
        self.service.award_points_for_order(self.user, order)

        txn = PointsTransaction.objects.get(user=self.user)
        self.assertEqual(len(txn.breakdown), 1)
        self.assertEqual(txn.breakdown[0]['rule_name'], '1 punt per euro')
        self.assertEqual(txn.breakdown[0]['rule_type'], 'per_euro')
        self.assertEqual(txn.breakdown[0]['points'], 30)


class FirstOrderBonusTests(TestCase):
    """The first_order bonus must survive a full (check-and-correct) sync."""

    SHOPIFY_TARGET = (
        'users.services.shopify.ShopifyService.get_all_customer_orders'
    )

    def setUp(self):
        self.user = User.objects.create_user(
            username='first@example.com', email='first@example.com',
            password='SuperSecret123!', shopify_customer_id='777',
        )
        PointsRule.objects.create(
            name='Welkomstbonus', rule_type='first_order', points=250,
        )
        self.service = LoyaltyService()

    def test_check_and_correct_keeps_first_order_bonus(self):
        order = make_order(3001, '40.00')
        self.assertEqual(self.service.award_points_for_order(self.user, order), 250)

        self.service.check_and_correct_points(self.user, [order])

        txn = PointsTransaction.objects.get(user=self.user)
        self.assertEqual(txn.points, 250)
        balance = PointsBalance.objects.get(user=self.user)
        self.assertEqual(balance.balance, 250)
        self.assertEqual(balance.lifetime_earned, 250)
        self.assertEqual(
            ProcessedOrder.objects.get(shopify_order_id='3001').points_awarded, 250
        )

    def test_full_sync_keeps_first_order_bonus(self):
        order = make_order(3002, '40.00')
        self.service.award_points_for_order(self.user, order)

        with patch(self.SHOPIFY_TARGET, return_value=[order]):
            result = self.service.full_sync_for_user(self.user)

        self.assertTrue(result['success'])
        self.assertEqual(result['new_balance'], 250)
        self.assertEqual(PointsBalance.objects.get(user=self.user).balance, 250)

    def test_second_order_gets_no_bonus(self):
        """The exclusion must not hand the bonus to every later order too."""
        self.service.award_points_for_order(self.user, make_order(3003, '40.00'))
        second = make_order(3004, '40.00')

        self.assertEqual(self.service.award_points_for_order(self.user, second), 0)
        self.service.check_and_correct_points(self.user, [second])
        self.assertFalse(
            PointsTransaction.objects.filter(shopify_order_id='3004').exists()
        )


class AdjustPointsTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user(
            username='adj@example.com', email='adj@example.com',
            password='SuperSecret123!'
        )
        self.service = LoyaltyService()

    def test_negative_adjustment_does_not_count_as_spent(self):
        self.service.adjust_points(self.user, 100, 'welcome bonus')
        self.service.adjust_points(self.user, -30, 'oops')

        balance = PointsBalance.objects.get(user=self.user)
        self.assertEqual(balance.balance, 70)
        self.assertEqual(balance.lifetime_earned, 70)
        self.assertEqual(balance.lifetime_spent, 0)


class RepairCommandTests(TestCase):
    """Simulate the legacy production state and verify the one-off repair."""

    def setUp(self):
        self.user = User.objects.create_user(
            username='legacy@example.com', email='legacy@example.com',
            password='SuperSecret123!'
        )

    def _legacy_revoked_order(self):
        """An order awarded 5289 points under an old rule, later corrected to 0.

        The old sync appended a negative adjustment and counted it as spent.
        """
        ProcessedOrder.objects.create(
            user=self.user, shopify_order_id='2001', shopify_order_name='#2001',
            order_total=Decimal('500.00'), points_awarded=0,
        )
        PointsTransaction.objects.create(
            user=self.user, transaction_type='earned', points=5289,
            balance_after=5289, description='Points earned from order #2001',
            shopify_order_id='2001', shopify_order_name='#2001',
        )
        PointsTransaction.objects.create(
            user=self.user, transaction_type='adjusted', points=-5289,
            balance_after=0,
            description='Points correction for order #2001 (5289 → 0)',
            shopify_order_id='2001', shopify_order_name='#2001',
        )
        PointsBalance.objects.create(
            user=self.user, balance=0, lifetime_earned=5289, lifetime_spent=5289,
        )

    def test_repair_clears_bogus_spent_and_folds_corrections(self):
        self._legacy_revoked_order()

        out = StringIO()
        call_command('repair_loyalty_history', '--apply', stdout=out)

        self.assertEqual(PointsTransaction.objects.filter(user=self.user).count(), 0)
        balance = PointsBalance.objects.get(user=self.user)
        self.assertEqual(balance.balance, 0)
        self.assertEqual(balance.lifetime_earned, 0)
        self.assertEqual(balance.lifetime_spent, 0)
        self.assertIn('Invariant balance == earned - spent holds', out.getvalue())

    def test_repair_partial_correction_folds_into_earned_row(self):
        """Order corrected 100 -> 40: one earned row of 40 should remain."""
        ProcessedOrder.objects.create(
            user=self.user, shopify_order_id='2002', shopify_order_name='#2002',
            order_total=Decimal('100.00'), points_awarded=40,
        )
        PointsTransaction.objects.create(
            user=self.user, transaction_type='earned', points=100,
            balance_after=100, description='Points earned from order #2002',
            shopify_order_id='2002', shopify_order_name='#2002',
        )
        PointsTransaction.objects.create(
            user=self.user, transaction_type='adjusted', points=-60,
            balance_after=40,
            description='Points correction for order #2002 (100 → 40)',
            shopify_order_id='2002', shopify_order_name='#2002',
        )
        PointsBalance.objects.create(
            user=self.user, balance=40, lifetime_earned=100, lifetime_spent=60,
        )

        call_command('repair_loyalty_history', '--apply', stdout=StringIO())

        txn = PointsTransaction.objects.get(user=self.user)
        self.assertEqual(txn.transaction_type, 'earned')
        self.assertEqual(txn.points, 40)
        self.assertEqual(txn.balance_after, 40)
        balance = PointsBalance.objects.get(user=self.user)
        self.assertEqual(balance.balance, 40)
        self.assertEqual(balance.lifetime_earned, 40)
        self.assertEqual(balance.lifetime_spent, 0)

    def test_repair_keeps_real_redemptions_in_spent(self):
        self._legacy_revoked_order()
        reward = Reward.objects.create(
            name='€5 korting', reward_type='fixed_discount', points_cost=50,
            discount_amount=Decimal('5.00'),
        )
        # A real redemption alongside the bogus correction
        PointsTransaction.objects.create(
            user=self.user, transaction_type='earned', points=80,
            balance_after=80, description='Points earned from order #2003',
            shopify_order_id='2003', shopify_order_name='#2003',
        )
        ProcessedOrder.objects.create(
            user=self.user, shopify_order_id='2003', shopify_order_name='#2003',
            order_total=Decimal('80.00'), points_awarded=80,
        )
        Redemption.objects.create(
            user=self.user, reward=reward, points_spent=50, status='completed',
        )
        PointsTransaction.objects.create(
            user=self.user, transaction_type='spent', points=-50,
            balance_after=30, description='Redeemed: €5 korting', reward=reward,
        )

        call_command('repair_loyalty_history', '--apply', stdout=StringIO())

        balance = PointsBalance.objects.get(user=self.user)
        self.assertEqual(balance.lifetime_spent, 50)
        self.assertEqual(balance.lifetime_earned, 80)
        self.assertEqual(balance.balance, 30)

    def test_repair_excludes_cancelled_redemptions_from_spent(self):
        reward = Reward.objects.create(
            name='€5 korting', reward_type='fixed_discount', points_cost=50,
            discount_amount=Decimal('5.00'),
        )
        PointsTransaction.objects.create(
            user=self.user, transaction_type='earned', points=100,
            balance_after=100, description='Points earned from order #2004',
            shopify_order_id='2004', shopify_order_name='#2004',
        )
        ProcessedOrder.objects.create(
            user=self.user, shopify_order_id='2004', shopify_order_name='#2004',
            order_total=Decimal('100.00'), points_awarded=100,
        )
        Redemption.objects.create(
            user=self.user, reward=reward, points_spent=50, status='cancelled',
        )
        PointsTransaction.objects.create(
            user=self.user, transaction_type='spent', points=-50,
            balance_after=50, description='Redeemed: €5 korting', reward=reward,
        )
        PointsTransaction.objects.create(
            user=self.user, transaction_type='adjusted', points=50,
            balance_after=100,
            description='Refund for cancelled redemption: €5 korting', reward=reward,
        )
        PointsBalance.objects.create(
            user=self.user, balance=100, lifetime_earned=100, lifetime_spent=0,
        )

        call_command('repair_loyalty_history', '--apply', stdout=StringIO())

        balance = PointsBalance.objects.get(user=self.user)
        self.assertEqual(balance.balance, 100)
        self.assertEqual(balance.lifetime_earned, 100)
        self.assertEqual(balance.lifetime_spent, 0)

    def test_dry_run_changes_nothing(self):
        self._legacy_revoked_order()

        out = StringIO()
        call_command('repair_loyalty_history', stdout=out)

        self.assertEqual(PointsTransaction.objects.filter(user=self.user).count(), 2)
        balance = PointsBalance.objects.get(user=self.user)
        self.assertEqual(balance.lifetime_spent, 5289)
        self.assertIn('Dry-run only', out.getvalue())
        # The report still shows what apply would do
        self.assertIn('5289', out.getvalue())
        self.assertIn('->', out.getvalue())
