from datetime import date, datetime, timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.test import TestCase

from loyalty.models import BirthdayReward, BirthdayRewardConfig
from loyalty.tasks import birthday_scan

User = get_user_model()

AMS = ZoneInfo('Europe/Amsterdam')

# Where the Shopify call and the notification send are patched. Both are
# imported inside the task, so patching the source module is what takes
# effect - and it means these tests run before notifications/ exists.
SHOPIFY_TARGET = 'users.services.shopify.ShopifyService.create_basic_discount'
NOTIFY_TARGET = 'notifications.services.send_notification'


class BirthdayScanTestCase(TestCase):
    """Shared fixtures: an active config and time-frozen scan runs."""

    def setUp(self):
        self.config = BirthdayRewardConfig.load()
        self.config.is_active = True
        self.config.discount_type = 'fixed_amount'
        self.config.discount_value = Decimal('5.00')
        self.config.validity_days = 30
        self.config.send_hour = 9
        self.config.save()

    def make_user(self, email, birthdate, set_at, shopify_customer_id='123456'):
        return User.objects.create_user(
            username=email,
            email=email,
            password='SuperSecret123!',
            first_name=email.split('@')[0].title(),
            birthdate=birthdate,
            birthdate_set_at=set_at,
            shopify_customer_id=shopify_customer_id,
        )

    def run_scan(self, now_local, shopify_result='ok', notify_return=None):
        """
        Run birthday_scan with `now` frozen to an Amsterdam-local datetime.
        Returns (result, mock_shopify, mock_notify).
        """
        if shopify_result == 'ok':
            shopify_result = {'discount_id': 'gid://shopify/DiscountCodeNode/1', 'code': 'X'}

        if notify_return is None:
            notify_return = MagicMock(id=99)

        with patch('django.utils.timezone.now', return_value=now_local), \
                patch(SHOPIFY_TARGET) as mock_shopify, \
                patch(NOTIFY_TARGET) as mock_notify:
            if callable(shopify_result) or isinstance(shopify_result, list):
                mock_shopify.side_effect = shopify_result
            else:
                mock_shopify.return_value = shopify_result
            mock_notify.return_value = notify_return

            result = birthday_scan()

        return result, mock_shopify, mock_notify


class BirthdayGiftIssuingTests(BirthdayScanTestCase):

    def test_gift_issued_on_the_birthday(self):
        now = datetime(2026, 7, 29, 9, 30, tzinfo=AMS)
        user = self.make_user(
            'bday@example.com',
            birthdate=date(1990, 7, 29),
            set_at=datetime(2025, 1, 1, 12, 0, tzinfo=AMS),
        )

        result, mock_shopify, mock_notify = self.run_scan(now)

        self.assertEqual(result['issued'], 1)

        reward = BirthdayReward.objects.get(user=user)
        self.assertEqual(reward.year, 2026)
        self.assertTrue(reward.discount_code.startswith('BDAY-'))
        self.assertEqual(reward.expires_at, now + timedelta(days=30))
        self.assertEqual(reward.delivery_id, 99)

        # Single-use, expiring, locked to the linked Shopify customer.
        kwargs = mock_shopify.call_args.kwargs
        self.assertEqual(kwargs['usage_limit'], 1)
        self.assertEqual(kwargs['customer_id'], '123456')
        self.assertEqual(kwargs['ends_at'], now + timedelta(days=30))
        self.assertEqual(kwargs['discount_type'], 'fixed_amount')
        self.assertEqual(kwargs['value'], 5.0)
        self.assertEqual(kwargs['code'], reward.discount_code)
        self.assertIn(user.email, kwargs['title'])
        # No combines_with override: the gift stacks like every other code.
        self.assertNotIn('combines_with', kwargs)

        notify_kwargs = mock_notify.call_args.kwargs
        self.assertEqual(notify_kwargs['kind'], 'birthday_gift')
        self.assertEqual(notify_kwargs['dedupe_key'], f'birthday:{user.id}:2026')
        self.assertEqual(notify_kwargs['data']['url'], '/loyalty')
        self.assertIn(reward.discount_code, notify_kwargs['body'])

    def test_user_without_shopify_customer_still_gets_a_code(self):
        """usage_limit=1 already bounds the cost, so no linked customer is fine."""
        now = datetime(2026, 7, 29, 9, 30, tzinfo=AMS)
        user = self.make_user(
            'nolink@example.com',
            birthdate=date(1990, 7, 29),
            set_at=datetime(2025, 1, 1, 12, 0, tzinfo=AMS),
            shopify_customer_id='',
        )

        result, mock_shopify, mock_notify = self.run_scan(now)

        self.assertEqual(result['issued'], 1)
        self.assertTrue(BirthdayReward.objects.filter(user=user).exists())
        self.assertIsNone(mock_shopify.call_args.kwargs['customer_id'])
        self.assertEqual(mock_shopify.call_args.kwargs['usage_limit'], 1)

    def test_no_gift_for_a_user_whose_birthday_is_not_today(self):
        now = datetime(2026, 7, 29, 9, 30, tzinfo=AMS)
        self.make_user(
            'other@example.com',
            birthdate=date(1990, 3, 14),
            set_at=datetime(2025, 1, 1, 12, 0, tzinfo=AMS),
        )

        result, mock_shopify, mock_notify = self.run_scan(now)

        self.assertEqual(result['issued'], 0)
        self.assertEqual(BirthdayReward.objects.count(), 0)
        mock_shopify.assert_not_called()


class BirthdayImmediateTests(BirthdayScanTestCase):
    """
    No lead time: a birthdate set today still gets today's gift. Set-once
    (User.birthdate_locked) is what prevents gift farming instead.
    """

    def test_gift_issued_when_birthdate_was_set_on_the_birthday_itself(self):
        now = datetime(2026, 7, 29, 9, 30, tzinfo=AMS)
        user = self.make_user(
            'lastminute@example.com',
            birthdate=date(1990, 7, 29),
            set_at=datetime(2026, 7, 29, 8, 0, tzinfo=AMS),  # 90 minutes ago
        )

        result, _, _ = self.run_scan(now)

        self.assertEqual(result['issued'], 1)
        self.assertTrue(BirthdayReward.objects.filter(user=user).exists())


class BirthdayOncePerYearTests(BirthdayScanTestCase):

    def test_running_the_scan_twice_issues_exactly_one_gift(self):
        now = datetime(2026, 7, 29, 9, 30, tzinfo=AMS)
        user = self.make_user(
            'twice@example.com',
            birthdate=date(1990, 7, 29),
            set_at=datetime(2025, 1, 1, 12, 0, tzinfo=AMS),
        )

        _, _, first_notify = self.run_scan(now)
        _, second_shopify, second_notify = self.run_scan(now)

        self.assertEqual(BirthdayReward.objects.filter(user=user).count(), 1)
        self.assertEqual(first_notify.call_count, 1)
        self.assertEqual(second_notify.call_count, 0)
        second_shopify.assert_not_called()

    def test_a_previous_year_reward_does_not_block_this_year(self):
        now = datetime(2026, 7, 29, 9, 30, tzinfo=AMS)
        user = self.make_user(
            'returning@example.com',
            birthdate=date(1990, 7, 29),
            set_at=datetime(2024, 1, 1, 12, 0, tzinfo=AMS),
        )
        BirthdayReward.objects.create(user=user, year=2025, discount_code='BDAY-LASTYEAR')

        result, _, _ = self.run_scan(now)

        self.assertEqual(result['issued'], 1)
        self.assertTrue(BirthdayReward.objects.filter(user=user, year=2026).exists())


class BirthdayCatchUpTests(BirthdayScanTestCase):
    """A birthday during an outage must not silently vanish."""

    def test_birthday_two_days_ago_still_gets_a_gift(self):
        now = datetime(2026, 7, 29, 9, 30, tzinfo=AMS)
        user = self.make_user(
            'missed@example.com',
            birthdate=date(1990, 7, 27),
            set_at=datetime(2025, 1, 1, 12, 0, tzinfo=AMS),
        )

        result, _, mock_notify = self.run_scan(now)

        self.assertEqual(result['issued'], 1)
        reward = BirthdayReward.objects.get(user=user)
        self.assertEqual(reward.year, 2026)
        self.assertEqual(
            mock_notify.call_args.kwargs['dedupe_key'], f'birthday:{user.id}:2026'
        )

    def test_birthday_outside_the_catch_up_window_gets_nothing(self):
        now = datetime(2026, 7, 29, 9, 30, tzinfo=AMS)
        user = self.make_user(
            'longgone@example.com',
            birthdate=date(1990, 7, 24),  # 5 days ago
            set_at=datetime(2025, 1, 1, 12, 0, tzinfo=AMS),
        )

        result, _, _ = self.run_scan(now)

        self.assertEqual(result['issued'], 0)
        self.assertFalse(BirthdayReward.objects.filter(user=user).exists())

    def test_catch_up_across_the_new_year_uses_the_birthday_year(self):
        """A 30 December birthday seen on 1 January belongs to the old year."""
        now = datetime(2026, 1, 1, 9, 30, tzinfo=AMS)
        user = self.make_user(
            'nye@example.com',
            birthdate=date(1990, 12, 30),
            set_at=datetime(2024, 1, 1, 12, 0, tzinfo=AMS),
        )

        result, _, mock_notify = self.run_scan(now)

        self.assertEqual(result['issued'], 1)
        reward = BirthdayReward.objects.get(user=user)
        self.assertEqual(reward.year, 2025)
        self.assertEqual(
            mock_notify.call_args.kwargs['dedupe_key'], f'birthday:{user.id}:2025'
        )


class BirthdayLeapDayTests(BirthdayScanTestCase):

    def test_29_february_is_celebrated_on_28_february_in_a_non_leap_year(self):
        now = datetime(2026, 2, 28, 9, 30, tzinfo=AMS)  # 2026 is not a leap year
        user = self.make_user(
            'leapling@example.com',
            birthdate=date(2000, 2, 29),
            set_at=datetime(2025, 1, 1, 12, 0, tzinfo=AMS),
        )

        result, _, _ = self.run_scan(now)

        self.assertEqual(result['issued'], 1)
        self.assertEqual(BirthdayReward.objects.get(user=user).year, 2026)

    def test_29_february_is_celebrated_on_29_february_in_a_leap_year(self):
        now = datetime(2028, 2, 29, 9, 30, tzinfo=AMS)  # 2028 is a leap year
        user = self.make_user(
            'leapling@example.com',
            birthdate=date(2000, 2, 29),
            set_at=datetime(2027, 1, 1, 12, 0, tzinfo=AMS),
        )

        result, _, _ = self.run_scan(now)

        self.assertEqual(result['issued'], 1)
        self.assertEqual(BirthdayReward.objects.get(user=user).year, 2028)

    def test_leapling_gets_only_one_gift_across_28_and_29_february(self):
        """In a leap year, 28 Feb must not also fire for a 29 Feb birthdate."""
        user = self.make_user(
            'leapling@example.com',
            birthdate=date(2000, 2, 29),
            set_at=datetime(2027, 1, 1, 12, 0, tzinfo=AMS),
        )

        self.run_scan(datetime(2028, 2, 28, 9, 30, tzinfo=AMS))
        self.run_scan(datetime(2028, 2, 29, 9, 30, tzinfo=AMS))

        self.assertEqual(BirthdayReward.objects.filter(user=user).count(), 1)


class BirthdayScanGatingTests(BirthdayScanTestCase):

    def test_scan_does_nothing_outside_the_send_hour(self):
        now = datetime(2026, 7, 29, 10, 5, tzinfo=AMS)  # send_hour is 9
        user = self.make_user(
            'earlybird@example.com',
            birthdate=date(1990, 7, 29),
            set_at=datetime(2025, 1, 1, 12, 0, tzinfo=AMS),
        )

        result, mock_shopify, mock_notify = self.run_scan(now)

        self.assertEqual(result, {'skipped': 'outside send hour'})
        self.assertFalse(BirthdayReward.objects.filter(user=user).exists())
        mock_shopify.assert_not_called()
        mock_notify.assert_not_called()

    def test_scan_respects_a_changed_send_hour(self):
        self.config.send_hour = 18
        self.config.save()
        now = datetime(2026, 7, 29, 18, 5, tzinfo=AMS)
        user = self.make_user(
            'evening@example.com',
            birthdate=date(1990, 7, 29),
            set_at=datetime(2025, 1, 1, 12, 0, tzinfo=AMS),
        )

        result, _, _ = self.run_scan(now)

        self.assertEqual(result['issued'], 1)
        self.assertTrue(BirthdayReward.objects.filter(user=user).exists())

    def test_scan_does_nothing_when_inactive(self):
        self.config.is_active = False
        self.config.save()
        now = datetime(2026, 7, 29, 9, 30, tzinfo=AMS)
        user = self.make_user(
            'inactive@example.com',
            birthdate=date(1990, 7, 29),
            set_at=datetime(2025, 1, 1, 12, 0, tzinfo=AMS),
        )

        result, mock_shopify, mock_notify = self.run_scan(now)

        self.assertEqual(result, {'skipped': 'inactive'})
        self.assertFalse(BirthdayReward.objects.filter(user=user).exists())
        mock_shopify.assert_not_called()
        mock_notify.assert_not_called()


class BirthdayFailureIsolationTests(BirthdayScanTestCase):

    def test_one_users_shopify_failure_does_not_block_the_others(self):
        now = datetime(2026, 7, 29, 9, 30, tzinfo=AMS)
        set_at = datetime(2025, 1, 1, 12, 0, tzinfo=AMS)
        doomed = self.make_user(
            'doomed@example.com', date(1990, 7, 29), set_at, shopify_customer_id='FAIL'
        )
        lucky = self.make_user(
            'lucky@example.com', date(1985, 7, 29), set_at, shopify_customer_id='OK'
        )

        def shopify_side_effect(**kwargs):
            if kwargs.get('customer_id') == 'FAIL':
                return None  # Shopify refused
            return {'price_rule_id': 1, 'discount_code_id': 2, 'code': kwargs['code']}

        result, mock_shopify, mock_notify = self.run_scan(
            now, shopify_result=shopify_side_effect
        )

        self.assertEqual(mock_shopify.call_count, 2)
        self.assertEqual(result['issued'], 1)
        self.assertEqual(result['failed'], 1)
        self.assertFalse(BirthdayReward.objects.filter(user=doomed).exists())
        self.assertTrue(BirthdayReward.objects.filter(user=lucky).exists())
        self.assertEqual(mock_notify.call_count, 1)

    def test_notification_failure_still_leaves_the_gift_issued(self):
        now = datetime(2026, 7, 29, 9, 30, tzinfo=AMS)
        user = self.make_user(
            'nonotify@example.com',
            birthdate=date(1990, 7, 29),
            set_at=datetime(2025, 1, 1, 12, 0, tzinfo=AMS),
        )

        with patch('django.utils.timezone.now', return_value=now), \
                patch(SHOPIFY_TARGET, return_value={'code': 'X'}), \
                patch(NOTIFY_TARGET, side_effect=RuntimeError('push service down')):
            result = birthday_scan()

        self.assertEqual(result['issued'], 1)
        reward = BirthdayReward.objects.get(user=user)
        self.assertIsNone(reward.delivery_id)


class BirthdayNotificationIntegrationTests(BirthdayScanTestCase):
    """
    The one test that does NOT mock send_notification, so the contract with
    the notifications app is checked for real. Shopify is still mocked.
    """

    def test_scan_creates_a_notification_delivery(self):
        from django.apps import apps

        if not apps.is_installed('notifications'):
            self.skipTest('notifications app is not installed')

        from notifications.models import NotificationDelivery

        now = datetime(2026, 7, 29, 9, 30, tzinfo=AMS)
        user = self.make_user(
            'real@example.com',
            birthdate=date(1990, 7, 29),
            set_at=datetime(2025, 1, 1, 12, 0, tzinfo=AMS),
        )

        with patch('django.utils.timezone.now', return_value=now), \
                patch(SHOPIFY_TARGET, return_value={'code': 'X'}):
            result = birthday_scan()

        self.assertEqual(result['issued'], 1)

        delivery = NotificationDelivery.objects.get(
            dedupe_key=f'birthday:{user.id}:2026'
        )
        self.assertEqual(delivery.kind, 'birthday_gift')
        self.assertEqual(delivery.user, user)

        reward = BirthdayReward.objects.get(user=user)
        self.assertEqual(reward.delivery_id, delivery.id)
        self.assertIn(reward.discount_code, delivery.body)


class BirthdayRewardConfigTests(TestCase):

    def test_load_creates_a_single_row_with_defaults(self):
        config = BirthdayRewardConfig.load()

        self.assertEqual(config.pk, 1)
        self.assertTrue(config.is_active)
        self.assertEqual(config.validity_days, 30)
        self.assertEqual(config.send_hour, 9)

    def test_config_is_a_singleton(self):
        BirthdayRewardConfig.load()
        BirthdayRewardConfig.objects.create(send_hour=11)

        self.assertEqual(BirthdayRewardConfig.objects.count(), 1)
        self.assertEqual(BirthdayRewardConfig.load().send_hour, 11)


class BirthdayRewardModelTests(TestCase):

    def test_one_reward_per_user_per_year(self):
        from django.db import IntegrityError, transaction

        user = User.objects.create_user(
            username='u@example.com', email='u@example.com', password='SuperSecret123!'
        )
        BirthdayReward.objects.create(user=user, year=2026, discount_code='BDAY-ONE')

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                BirthdayReward.objects.create(user=user, year=2026, discount_code='BDAY-TWO')
