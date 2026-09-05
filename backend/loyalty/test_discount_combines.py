"""
Tests for the combines-with backfill command.

Shopify defaults combinesWith to all-false, so every code minted before we
started sending the field is stuck at "cannot be used with any other
discount". New codes are fixed at the source; this command repairs the ones
already handed out. What matters here is WHICH codes it picks up — a member
can only be helped by a code that is still redeemable, and every extra row
costs two Shopify calls.
"""
from datetime import timedelta
from io import StringIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from loyalty.models import BirthdayReward, Redemption, Reward

User = get_user_model()

SERVICE_TARGET = (
    'users.services.shopify.ShopifyService.set_discount_combines_with'
)


class BackfillCombinesTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user(
            username='combi@example.com',
            email='combi@example.com',
            password='SuperSecret123!',
        )
        self.reward = Reward.objects.create(
            name='5 euro korting',
            points_cost=500,
            reward_type='fixed_discount',
            discount_amount=5,
        )

    def _redemption(self, code, **kwargs):
        defaults = {
            'user': self.user,
            'reward': self.reward,
            'points_spent': 500,
            'discount_code': code,
        }
        defaults.update(kwargs)
        return Redemption.objects.create(**defaults)

    def _run(self, *args):
        out = StringIO()
        call_command('backfill_discount_combines', *args, stdout=out)
        return out.getvalue()

    def test_dry_run_lists_codes_and_calls_nothing(self):
        self._redemption('HOB-LIVE0001')

        with patch(SERVICE_TARGET) as mock_set:
            output = self._run()

        mock_set.assert_not_called()
        self.assertIn('HOB-LIVE0001', output)
        self.assertIn('Would update 1 code', output)

    def test_apply_sends_each_code_to_shopify(self):
        self._redemption('HOB-LIVE0001')
        BirthdayReward.objects.create(
            user=self.user, year=2026, discount_code='BDAY-LIVE0002',
            expires_at=timezone.now() + timedelta(days=10),
        )

        with patch(SERVICE_TARGET, return_value='updated') as mock_set:
            output = self._run('--apply')

        sent = {call.args[0] for call in mock_set.call_args_list}
        self.assertEqual(sent, {'HOB-LIVE0001', 'BDAY-LIVE0002'})
        self.assertIn('Updated 2 of 2', output)

    def test_used_and_expired_codes_are_skipped(self):
        """Repairing a dead code costs two Shopify calls and helps nobody."""
        self._redemption('HOB-USED0001', discount_code_used=True)
        self._redemption(
            'HOB-GONE0001', expires_at=timezone.now() - timedelta(days=1)
        )
        self._redemption(
            'HOB-LIVE0001', expires_at=timezone.now() + timedelta(days=1)
        )

        with patch(SERVICE_TARGET) as mock_set:
            output = self._run()

        mock_set.assert_not_called()
        self.assertIn('HOB-LIVE0001', output)
        self.assertNotIn('HOB-USED0001', output)
        self.assertNotIn('HOB-GONE0001', output)

    def test_redemption_without_a_code_is_ignored(self):
        """Non-discount rewards have no code to repair."""
        self._redemption('')

        with patch(SERVICE_TARGET) as mock_set:
            output = self._run()

        mock_set.assert_not_called()
        self.assertIn('No live codes', output)

    def test_failures_are_counted_not_raised(self):
        """One dead code must not abort the run for everyone behind it."""
        self._redemption('HOB-LIVE0001')
        self._redemption('HOB-LIVE0002')

        with patch(SERVICE_TARGET, side_effect=['updated', 'not_found']):
            output = self._run('--apply')

        self.assertIn('Updated 1 of 2', output)
        self.assertIn('1 not in Shopify', output)
