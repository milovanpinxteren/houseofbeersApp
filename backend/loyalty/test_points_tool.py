"""Puntentool tests: access control, the two write shapes (earned grant vs
adjusted correction), the ledger invariant, the euro<->points conversion and
the refusals.

Notification sends are mocked — the tool must never depend on push working.
"""
from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.contrib.admin.models import LogEntry
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from loyalty.models import PointsBalance, PointsTransaction, Reward, ServiceGrant
from loyalty.services import points_tool as tool
from loyalty.services.points_value import (
    FALLBACK_EURO_PER_POINT, euro_to_points, points_to_euro, rate_info,
)

User = get_user_model()

NOTIFY_TARGET = 'notifications.services.send_notification'


def notify_patch():
    """Outbox mock returning a delivery-shaped object (same idiom as
    test_service_grants) — grants stores `delivery.id` on the grant row."""
    return patch(NOTIFY_TARGET, return_value=MagicMock(id=1))


# The production manifest storage needs collectstatic output; plain storage
# lets the admin-based templates render inside tests (same as test_studio).
@override_settings(STORAGES={
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
})
class PointsToolTestCase(TestCase):

    def setUp(self):
        self.staff = User.objects.create_user(
            username='admin@houseofbeers.nl',
            email='admin@houseofbeers.nl',
            password='SuperSecret123!',
            is_staff=True,
        )
        self.member = User.objects.create_user(
            username='drinker@example.com',
            email='drinker@example.com',
            password='SuperSecret123!',
            first_name='Jan',
            last_name='Jansen',
        )
        self.client.force_login(self.staff)

    def make_reward(self, name='€5 korting', amount='5.00', cost=100, **kwargs):
        defaults = {
            'name': name,
            'reward_type': 'fixed_discount',
            'discount_amount': Decimal(amount),
            'points_cost': cost,
            'is_active': True,
        }
        defaults.update(kwargs)
        return Reward.objects.create(**defaults)

    def set_balance(self, points, earned=None, spent=0):
        balance, _ = PointsBalance.objects.get_or_create(user=self.member)
        balance.balance = points
        balance.lifetime_earned = points + spent if earned is None else earned
        balance.lifetime_spent = spent
        balance.save()
        return balance

    def member_url(self):
        return reverse('points_tool:member', args=[self.member.pk])

    def post_form(self, step='confirm', **overrides):
        data = {
            'step': step,
            'mode': 'add',
            'points': '100',
            'euro': '',
            'target_balance': '',
            'reason': 'Instagram post',
            'notify': 'on',
            'token': 'testtoken1234',
        }
        data.update(overrides)
        return self.client.post(self.member_url(), data)

    def assert_invariant(self):
        balance = PointsBalance.objects.get(user=self.member)
        self.assertEqual(
            balance.balance,
            balance.lifetime_earned - balance.lifetime_spent,
            'balance == lifetime_earned - lifetime_spent must always hold',
        )
        return balance


class PointsToolAccessTests(PointsToolTestCase):

    def test_anonymous_is_redirected_to_login(self):
        self.client.logout()
        response = self.client.get(reverse('points_tool:index'))
        self.assertEqual(response.status_code, 302)
        self.assertIn('login', response.url)

    def test_non_staff_is_bounced(self):
        self.client.force_login(self.member)
        for url in (reverse('points_tool:index'), self.member_url()):
            response = self.client.get(url)
            self.assertEqual(response.status_code, 302, url)
            self.assertIn('login', response.url)

    def test_non_staff_cannot_award_points(self):
        self.client.force_login(self.member)
        with notify_patch():
            response = self.post_form(step='execute')
        self.assertEqual(response.status_code, 302)
        self.assertFalse(PointsTransaction.objects.exists())

    def test_staff_sees_the_member_page(self):
        self.set_balance(250)
        response = self.client.get(self.member_url())
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'drinker@example.com')
        self.assertContains(response, '250')


class PointsToolAddModeTests(PointsToolTestCase):

    def test_confirm_step_does_not_write_anything(self):
        response = self.post_form(step='confirm')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Kloppen deze punten?')
        self.assertFalse(PointsTransaction.objects.exists())
        self.assertFalse(ServiceGrant.objects.exists())

    def test_add_writes_a_member_visible_earned_transaction(self):
        self.set_balance(40)
        with notify_patch() as send:
            response = self.post_form(step='execute')
        self.assertEqual(response.status_code, 302)

        txn = PointsTransaction.objects.get()
        self.assertEqual(txn.transaction_type, 'earned')
        self.assertEqual(txn.points, 100)
        self.assertIsNone(txn.rule_id)
        # A full sync deletes earned rows carrying an order id it cannot
        # reproduce — a manual award must never carry one.
        self.assertEqual(txn.shopify_order_id, '')
        self.assertEqual(txn.description, 'Instagram post')
        # The app's history expander renders rule_name from the breakdown.
        self.assertEqual(txn.breakdown[0]['rule_name'], 'Instagram post')
        self.assertEqual(txn.breakdown[0]['points'], 100)

        balance = self.assert_invariant()
        self.assertEqual(balance.balance, 140)
        self.assertEqual(balance.lifetime_spent, 0)
        self.assertTrue(send.called)

    def test_add_goes_through_the_grant_path(self):
        with notify_patch():
            self.post_form(step='execute')
        grant = ServiceGrant.objects.get()
        self.assertEqual(grant.source, 'staff_tool')
        self.assertEqual(grant.status, 'granted')
        self.assertEqual(grant.user, self.member)
        self.assertEqual(grant.dedupe_key, 'pointstool:testtoken1234')
        self.assertEqual(grant.context['staff_user_id'], self.staff.pk)

    def test_add_records_who_did_it(self):
        with notify_patch():
            self.post_form(step='execute')
        entry = LogEntry.objects.get()
        self.assertEqual(entry.user, self.staff)
        self.assertEqual(entry.object_id, str(self.member.pk))
        self.assertTrue(entry.change_message.startswith(tool.LOG_PREFIX))
        self.assertIn('Instagram post', entry.change_message)
        # The member-facing text stays clean of staff names.
        self.assertNotIn(self.staff.email, PointsTransaction.objects.get().description)

    def test_notify_off_sends_nothing(self):
        with notify_patch() as send:
            self.post_form(step='execute', notify='')
        self.assertFalse(send.called)
        self.assertEqual(PointsTransaction.objects.count(), 1)

    def test_resubmitting_the_same_token_awards_once(self):
        with notify_patch():
            self.post_form(step='execute')
            self.post_form(step='execute')
        self.assertEqual(PointsTransaction.objects.count(), 1)
        self.assertEqual(PointsBalance.objects.get(user=self.member).balance, 100)

    def test_reason_is_required(self):
        response = self.post_form(step='execute', reason='')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Vul een reden in')
        self.assertFalse(PointsTransaction.objects.exists())

    def test_zero_points_is_refused(self):
        response = self.post_form(step='execute', points='0')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'minstens 1')
        self.assertFalse(PointsTransaction.objects.exists())

    def test_large_award_warns_but_does_not_block(self):
        self.make_reward()
        response = self.post_form(step='confirm', points='2500')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'grote correctie')
        # …and confirming still works.
        with notify_patch():
            self.post_form(step='execute', points='2500')
        self.assertEqual(PointsBalance.objects.get(user=self.member).balance, 2500)


class PointsToolSetModeTests(PointsToolTestCase):

    def set_mode(self, target, step='execute', **overrides):
        data = {
            'mode': 'set',
            'points': '',
            'target_balance': str(target),
            'reason': 'Dubbele toekenning teruggedraaid',
            'notify': '',
        }
        data.update(overrides)
        return self.post_form(step=step, **data)

    def test_set_writes_an_adjusted_transaction_with_the_right_delta(self):
        self.set_balance(850)
        response = self.set_mode(1000)
        self.assertEqual(response.status_code, 302)

        txn = PointsTransaction.objects.get()
        self.assertEqual(txn.transaction_type, 'adjusted')
        self.assertEqual(txn.points, 150)
        self.assertEqual(txn.balance_after, 1000)
        self.assertIn('Dubbele toekenning', txn.description)

        balance = self.assert_invariant()
        self.assertEqual(balance.balance, 1000)

    def test_set_downwards_preserves_the_invariant_and_lifetime_spent(self):
        # 900 earned, 100 spent on a redemption -> balance 800.
        self.set_balance(800, earned=900, spent=100)
        self.set_mode(500)

        txn = PointsTransaction.objects.get()
        self.assertEqual(txn.points, -300)
        balance = self.assert_invariant()
        self.assertEqual(balance.balance, 500)
        # Corrections never touch "spent" — that stays reserved for redemptions.
        self.assertEqual(balance.lifetime_spent, 100)
        self.assertEqual(balance.lifetime_earned, 600)

    def test_negative_target_is_refused_in_dutch(self):
        self.set_balance(100)
        response = self.set_mode(-50)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'kan niet negatief zijn')
        self.assertFalse(PointsTransaction.objects.exists())
        self.assertEqual(PointsBalance.objects.get(user=self.member).balance, 100)

    def test_service_refuses_a_negative_target(self):
        self.set_balance(100)
        with self.assertRaises(tool.PointsToolError) as ctx:
            tool.set_balance(
                member=self.member, target=-1, reason='oeps',
                staff_user=self.staff,
            )
        self.assertIn('negatief', str(ctx.exception))

    def test_unchanged_balance_is_refused(self):
        self.set_balance(300)
        response = self.set_mode(300, step='confirm')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'niets te wijzigen')
        self.assertFalse(PointsTransaction.objects.exists())

    def test_set_mode_can_notify(self):
        self.set_balance(100)
        with notify_patch() as send:
            self.set_mode(200, notify='on')
        self.assertTrue(send.called)


class EuroConversionTests(PointsToolTestCase):

    def test_rate_is_derived_from_an_active_fixed_discount_reward(self):
        self.make_reward(amount='5.00', cost=100)
        info = rate_info()
        self.assertTrue(info['derived'])
        self.assertEqual(info['rate'], Decimal('0.05'))
        self.assertEqual(points_to_euro(100), Decimal('5.00'))
        self.assertEqual(points_to_euro(250), Decimal('12.50'))
        self.assertEqual(euro_to_points(10), 200)
        self.assertIn('€5,00 voor 100 punten', info['label'])

    def test_rate_follows_a_repriced_reward(self):
        self.make_reward(amount='5.00', cost=50)  # €0,10 per punt
        self.assertEqual(rate_info()['rate'], Decimal('0.10'))
        self.assertEqual(euro_to_points(10), 100)

    def test_inactive_and_non_fixed_rewards_are_ignored(self):
        self.make_reward(amount='5.00', cost=50, is_active=False)
        Reward.objects.create(
            name='10% korting', reward_type='percentage_discount',
            discount_percentage=Decimal('10'), points_cost=100,
        )
        info = rate_info()
        self.assertFalse(info['derived'])
        self.assertEqual(info['rate'], FALLBACK_EURO_PER_POINT)

    def test_falls_back_sanely_with_no_rewards(self):
        info = rate_info()
        self.assertFalse(info['derived'])
        self.assertEqual(info['rate'], Decimal('0.05'))
        self.assertEqual(points_to_euro(100), Decimal('5.00'))
        self.assertEqual(euro_to_points(10), 200)
        self.assertIn('standaardtarief', info['label'])

    def test_median_rate_ignores_an_outlier(self):
        self.make_reward(name='A', amount='5.00', cost=100)   # 0.05
        self.make_reward(name='B', amount='10.00', cost=200)  # 0.05
        self.make_reward(name='C', amount='50.00', cost=100)  # 0.50 outlier
        self.assertEqual(rate_info()['rate'], Decimal('0.05'))

    def test_member_page_shows_the_rate(self):
        self.make_reward()
        response = self.client.get(self.member_url())
        self.assertContains(response, '€0,05')
        self.assertContains(response, '€5,00 voor 100 punten')


class PointsToolIndexTests(PointsToolTestCase):

    def test_index_lists_recent_tool_actions(self):
        with notify_patch():
            self.post_form(step='execute')
        response = self.client.get(reverse('points_tool:index'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'drinker@example.com')
        self.assertContains(response, 'Instagram post')

    def test_admin_index_entry_redirects_to_the_tool(self):
        # The Puntentool proxy model is how staff reach the tool from the
        # admin index; its changelist is a redirect.
        response = self.client.get(reverse('admin:loyalty_puntentool_changelist'))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('points_tool:index'))

    def test_member_search_is_the_studio_endpoint(self):
        response = self.client.get(
            reverse('points_tool:user_search'), {'q': 'jansen'}
        )
        self.assertEqual(response.status_code, 200)
        emails = [row['email'] for row in response.json()['users']]
        self.assertIn('drinker@example.com', emails)
