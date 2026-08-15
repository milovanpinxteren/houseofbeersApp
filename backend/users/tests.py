from datetime import date, timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

User = get_user_model()


def years_ago(years: int, today: date = None) -> date:
    """A birthdate exactly `years` years ago (29 Feb falls back to 28 Feb)."""
    today = today or timezone.localdate()
    try:
        return today.replace(year=today.year - years)
    except ValueError:
        return today.replace(year=today.year - years, day=28)


class BirthdateRegistrationTests(APITestCase):
    """Under-18 is blocked at registration, birthdate stays optional."""

    def setUp(self):
        self.url = reverse('register')
        # RegisterView reaches out to Shopify; never in tests.
        patcher = patch('users.views.ShopifyService')
        self.mock_shopify = patcher.start()
        self.addCleanup(patcher.stop)
        self.mock_shopify.return_value.link_customer_to_user.return_value = False

    def _payload(self, **overrides):
        payload = {
            'email': 'newuser@example.com',
            'password': 'SuperSecret123!',
            'password_confirm': 'SuperSecret123!',
            'first_name': 'New',
            'last_name': 'User',
        }
        payload.update(overrides)
        return payload

    def test_registration_without_birthdate_still_works(self):
        """Existing clients that never send a birthdate must keep working."""
        response = self.client.post(self.url, self._payload(), format='json')

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        user = User.objects.get(email='newuser@example.com')
        self.assertIsNone(user.birthdate)
        self.assertIsNone(user.birthdate_set_at)

    def test_registration_with_valid_birthdate(self):
        birthdate = years_ago(30)
        response = self.client.post(
            self.url, self._payload(birthdate=birthdate.isoformat()), format='json'
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        user = User.objects.get(email='newuser@example.com')
        self.assertEqual(user.birthdate, birthdate)
        self.assertIsNotNone(user.birthdate_set_at)

    def test_registration_rejects_under_18(self):
        """We sell alcohol: an under-18 date fails validation outright."""
        response = self.client.post(
            self.url, self._payload(birthdate=years_ago(17).isoformat()), format='json'
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('birthdate', response.data)
        self.assertIn('18', str(response.data['birthdate']))
        self.assertFalse(User.objects.filter(email='newuser@example.com').exists())

    def test_registration_rejects_birthdate_one_day_short_of_18(self):
        almost_18 = years_ago(18) + timedelta(days=1)
        response = self.client.post(
            self.url, self._payload(birthdate=almost_18.isoformat()), format='json'
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(User.objects.filter(email='newuser@example.com').exists())

    def test_registration_accepts_exactly_18_today(self):
        response = self.client.post(
            self.url, self._payload(birthdate=years_ago(18).isoformat()), format='json'
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)


class BirthdateEndpointTests(APITestCase):
    """PATCH /api/users/me/birthdate/"""

    def setUp(self):
        self.user = User.objects.create_user(
            username='tester@example.com',
            email='tester@example.com',
            password='SuperSecret123!',
        )
        self.client.force_authenticate(user=self.user)
        self.url = reverse('user_birthdate')

    def test_requires_authentication(self):
        self.client.force_authenticate(user=None)
        response = self.client.patch(self.url, {'birthdate': '1990-01-01'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_sets_birthdate_and_timestamp(self):
        birthdate = years_ago(30)
        response = self.client.patch(
            self.url, {'birthdate': birthdate.isoformat()}, format='json'
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['birthdate'], birthdate.isoformat())
        # Set-once: the very act of setting it locks it.
        self.assertTrue(response.data['birthdate_locked'])

        self.user.refresh_from_db()
        self.assertEqual(self.user.birthdate, birthdate)
        self.assertIsNotNone(self.user.birthdate_set_at)

    def test_rejects_under_18(self):
        response = self.client.patch(
            self.url, {'birthdate': years_ago(17).isoformat()}, format='json'
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('18', str(response.data['birthdate']))
        self.user.refresh_from_db()
        self.assertIsNone(self.user.birthdate)

    def test_rejects_future_date(self):
        future = timezone.localdate() + timedelta(days=1)
        response = self.client.patch(self.url, {'birthdate': future.isoformat()}, format='json')

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('future', str(response.data['birthdate']).lower())

    def test_rejects_implausible_age(self):
        response = self.client.patch(
            self.url, {'birthdate': years_ago(130).isoformat()}, format='json'
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_rejects_unparseable_date(self):
        response = self.client.patch(self.url, {'birthdate': 'not-a-date'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_can_only_be_set_once(self):
        """Set-once: changes go through us (Django admin), not the app."""
        first, second = years_ago(30), years_ago(31)

        self.client.patch(self.url, {'birthdate': first.isoformat()}, format='json')
        response = self.client.patch(self.url, {'birthdate': second.isoformat()}, format='json')

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.user.refresh_from_db()
        self.assertEqual(self.user.birthdate, first)

    def test_locked_when_birthdate_arrived_via_registration(self):
        """A birthdate supplied at registration counts as the one set."""
        self.user.birthdate = years_ago(30)
        self.user.save(update_fields=['birthdate'])

        response = self.client.patch(
            self.url, {'birthdate': years_ago(40).isoformat()}, format='json'
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


class UserSerializerBirthdateTests(APITestCase):
    """birthdate/birthdate_locked exposure on /api/users/me/"""

    def setUp(self):
        self.user = User.objects.create_user(
            username='me@example.com',
            email='me@example.com',
            password='SuperSecret123!',
            birthdate=years_ago(30),
        )
        self.client.force_authenticate(user=self.user)
        self.url = reverse('user_me')

    def test_me_exposes_birthdate_and_lock_state(self):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['birthdate'], self.user.birthdate.isoformat())
        # Set-once: having a birthdate at all means it is locked.
        self.assertTrue(response.data['birthdate_locked'])

    def test_me_reports_unlocked_without_a_birthdate(self):
        self.user.birthdate = None
        self.user.save(update_fields=['birthdate'])

        response = self.client.get(self.url)
        self.assertFalse(response.data['birthdate_locked'])

    def test_me_patch_cannot_bypass_the_lock(self):
        """birthdate is read-only on /users/me/ so the lock cannot be sidestepped."""
        original = self.user.birthdate

        response = self.client.patch(
            self.url, {'birthdate': years_ago(40).isoformat()}, format='json'
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.user.refresh_from_db()
        self.assertEqual(self.user.birthdate, original)


class LastActiveTests(APITestCase):
    """last_active_at powers 'has not visited in N days' segments."""

    def setUp(self):
        self.user = User.objects.create_user(
            username='active@example.com',
            email='active@example.com',
            password='SuperSecret123!',
        )

    def test_starts_empty(self):
        self.assertIsNone(self.user.last_active_at)

    def test_touch_sets_it(self):
        wrote = self.user.touch_last_active()

        self.assertTrue(wrote)
        self.user.refresh_from_db()
        self.assertIsNotNone(self.user.last_active_at)

    def test_touch_is_throttled(self):
        """A chatty session must not cost one UPDATE per request."""
        self.user.touch_last_active()
        first = self.user.last_active_at

        wrote = self.user.touch_last_active()

        self.assertFalse(wrote)
        self.user.refresh_from_db()
        self.assertEqual(self.user.last_active_at, first)

    def test_touch_writes_again_once_the_window_has_passed(self):
        from users.models import LAST_ACTIVE_THROTTLE

        stale = timezone.now() - LAST_ACTIVE_THROTTLE - timedelta(minutes=1)
        User.objects.filter(pk=self.user.pk).update(last_active_at=stale)
        self.user.refresh_from_db()

        wrote = self.user.touch_last_active()

        self.assertTrue(wrote)
        self.user.refresh_from_db()
        self.assertGreater(self.user.last_active_at, stale)

    def test_touch_does_not_disturb_other_fields(self):
        """The UPDATE must touch exactly one column."""
        User.objects.filter(pk=self.user.pk).update(first_name='Written elsewhere')

        self.user.touch_last_active()

        self.user.refresh_from_db()
        self.assertEqual(self.user.first_name, 'Written elsewhere')

    def test_tracker_updates_last_active(self):
        from analytics.tracker import track

        track('orders_view', user=self.user)

        self.user.refresh_from_db()
        self.assertIsNotNone(self.user.last_active_at)

    def test_tracker_tolerates_no_user(self):
        from analytics.tracker import track

        track('login', user=None)  # must not raise

    def test_login_updates_last_active(self):
        """The end-to-end path: logging in marks the user active."""
        response = self.client.post(
            reverse('login'),
            {'email': 'active@example.com', 'password': 'SuperSecret123!'},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.user.refresh_from_db()
        self.assertIsNotNone(self.user.last_active_at)


class EmailCaseInsensitivityTests(APITestCase):
    """
    Phone keyboards auto-capitalize the email field, which used to strand
    users: login and password reset matched case-sensitively. Emails are now
    stored lowercase and looked up case-insensitively — but exact matches win,
    because legacy case-duplicate account pairs exist and both must stay
    reachable.
    """

    def setUp(self):
        self.user = User.objects.create_user(
            username='ruud@example.com',
            email='ruud@example.com',
            password='SuperSecret123!',
        )

    def test_login_ignores_email_case(self):
        response = self.client.post(
            reverse('login'),
            {'email': 'Ruud@Example.com', 'password': 'SuperSecret123!'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_password_reset_ignores_email_case(self):
        from django.core import mail

        response = self.client.post(
            reverse('password_reset'), {'email': 'Ruud@example.com'}, format='json'
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(mail.outbox), 1)

    def test_registration_stores_email_lowercase(self):
        with patch('users.views.ShopifyService') as mock_shopify:
            mock_shopify.return_value.link_customer_to_user.return_value = False
            response = self.client.post(
                reverse('register'),
                {
                    'email': 'New.User@Example.com',
                    'password': 'SuperSecret123!',
                    'password_confirm': 'SuperSecret123!',
                },
                format='json',
            )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        user = User.objects.get(email='new.user@example.com')
        self.assertEqual(user.username, 'new.user@example.com')

    def test_registration_rejects_case_variant_of_existing_email(self):
        """No new Foo@x.com / foo@x.com duplicate pairs."""
        response = self.client.post(
            reverse('register'),
            {
                'email': 'RUUD@example.com',
                'password': 'SuperSecret123!',
                'password_confirm': 'SuperSecret123!',
            },
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('email', response.data)
        self.assertEqual(User.objects.count(), 1)

    def test_exact_match_wins_over_case_insensitive(self):
        """Both halves of a legacy duplicate pair stay reachable."""
        twin = User.objects.create_user(
            username='Ruud@example.com',
            email='Ruud@example.com',
            password='OtherSecret123!',
        )

        self.assertEqual(
            User.objects.get_by_natural_key('Ruud@example.com').pk, twin.pk
        )
        self.assertEqual(
            User.objects.get_by_natural_key('ruud@example.com').pk, self.user.pk
        )

    def test_ambiguous_case_variant_of_duplicate_pair_does_not_crash(self):
        """A third casing matches neither exactly and two case-insensitively;
        it must raise DoesNotExist (auth failure), not MultipleObjectsReturned
        (a 500)."""
        User.objects.create_user(
            username='Ruud@example.com',
            email='Ruud@example.com',
            password='OtherSecret123!',
        )

        with self.assertRaises(User.DoesNotExist):
            User.objects.get_by_natural_key('RUUD@example.com')


class ShopifyEndsAtTests(APITestCase):
    """create_discount_code / create_basic_discount accept an optional expiry."""

    def _service(self):
        from users.services import ShopifyService
        return ShopifyService()

    def test_rest_discount_omits_ends_at_by_default(self):
        service = self._service()
        with patch.object(service, '_request', return_value=None) as mock_request:
            service.create_discount_code(code='X', discount_type='fixed_amount', value=5)

        payload = mock_request.call_args.kwargs['json']['price_rule']
        self.assertNotIn('ends_at', payload)

    def test_rest_discount_sends_ends_at(self):
        service = self._service()
        ends_at = timezone.now() + timedelta(days=30)
        with patch.object(service, '_request', return_value=None) as mock_request:
            service.create_discount_code(
                code='X', discount_type='fixed_amount', value=5, ends_at=ends_at
            )

        payload = mock_request.call_args.kwargs['json']['price_rule']
        self.assertEqual(payload['ends_at'], ends_at.isoformat())

    def test_graphql_discount_ends_at_is_optional(self):
        service = self._service()
        ends_at = timezone.now() + timedelta(days=30)

        with patch.object(service, '_graphql_request', return_value=None) as mock_gql:
            service.create_basic_discount(
                code='X', title='t', discount_type='percentage', value=10
            )
            self.assertNotIn('endsAt', mock_gql.call_args.args[1]['basicCodeDiscount'])

            service.create_basic_discount(
                code='X', title='t', discount_type='percentage', value=10, ends_at=ends_at
            )
            self.assertEqual(
                mock_gql.call_args.args[1]['basicCodeDiscount']['endsAt'],
                ends_at.isoformat(),
            )


class AdminActionTests(APITestCase):
    """
    The admin test-send and force-gift actions.

    These exist so the notification and birthday flows can be verified on a
    live site without waiting for a real birthday, so they need to work.
    """

    def setUp(self):
        from django.contrib.admin.sites import AdminSite
        from users.admin import UserAdmin

        self.admin = UserAdmin(User, AdminSite())
        self.user = User.objects.create_user(
            username='giftee', email='giftee@example.com', password='pw12345!',
            birthdate=date(1990, 6, 15),
        )
        self.user.birthdate_set_at = timezone.now() - timedelta(days=400)
        self.user.save(update_fields=['birthdate_set_at'])

        self.request = type('R', (), {})()
        self.messages = []
        self.admin.message_user = lambda req, msg, level=None: self.messages.append(msg)

    def test_send_test_notification_uses_the_real_pipeline(self):
        """It must go through send_notification, not push directly, so the
        result reflects what production would actually do."""
        self.admin.send_test_notification(
            self.request, User.objects.filter(pk=self.user.pk)
        )
        from notifications.models import NotificationDelivery
        delivery = NotificationDelivery.objects.get(user=self.user)
        self.assertEqual(delivery.kind, 'transactional')
        # No push subscription exists so push is skipped, and email is off by
        # default (users only get email after explicitly opting in).
        self.assertEqual(delivery.push_status, 'skipped')
        self.assertEqual(delivery.email_status, 'skipped')
        self.assertIn('push=skipped', self.messages[0])

    def test_test_notification_can_be_sent_repeatedly(self):
        """A timestamped dedupe key means the action is not one-shot.

        Note the timestamp has second granularity, so two clicks inside the
        same second deliberately collapse into one send — which is a useful
        guard against a double-click, not a defect.
        """
        from notifications.models import NotificationDelivery
        qs = User.objects.filter(pk=self.user.pk)

        self.admin.send_test_notification(self.request, qs)
        first = NotificationDelivery.objects.get(user=self.user)
        self.assertTrue(first.dedupe_key.startswith(f'admin-test:{self.user.id}:'))

        # Re-run with the clock moved on, as a later click would.
        with patch('users.admin.timezone') as mock_tz:
            mock_tz.now.return_value.strftime.return_value = '29991231235959'
            self.admin.send_test_notification(self.request, qs)

        self.assertEqual(
            NotificationDelivery.objects.filter(user=self.user).count(), 2
        )

    @patch('loyalty.tasks._issue_birthday_gift', return_value=True)
    def test_force_gift_issues_on_any_day(self, mock_issue):
        """The whole point: no waiting for the birthday or the send hour."""
        self.admin.issue_birthday_gift_now(
            self.request, User.objects.filter(pk=self.user.pk)
        )
        mock_issue.assert_called_once()
        self.assertIn('Issued 1', self.messages[0])

    @patch('loyalty.tasks._issue_birthday_gift', return_value=True)
    def test_force_gift_still_honours_one_per_year(self, mock_issue):
        """Forcing must not become a way to hand out unlimited gifts."""
        from loyalty.models import BirthdayReward
        BirthdayReward.objects.create(
            user=self.user, year=timezone.localtime().year,
            discount_code='EXISTING', expires_at=timezone.now() + timedelta(days=30),
        )
        self.admin.issue_birthday_gift_now(
            self.request, User.objects.filter(pk=self.user.pk)
        )
        mock_issue.assert_not_called()
        self.assertIn('already received one', ' '.join(self.messages))

    @patch('loyalty.tasks._issue_birthday_gift', return_value=True)
    def test_force_gift_skips_users_without_a_birthdate(self, mock_issue):
        other = User.objects.create_user(
            username='nobday', email='nobday@example.com', password='pw12345!')
        self.admin.issue_birthday_gift_now(
            self.request, User.objects.filter(pk=other.pk)
        )
        mock_issue.assert_not_called()
        self.assertIn('no birthdate set', ' '.join(self.messages))

    @patch('loyalty.tasks._issue_birthday_gift', side_effect=RuntimeError('Shopify down'))
    def test_force_gift_reports_failure_without_raising(self, mock_issue):
        """A Shopify outage must surface in the admin, not 500 the page."""
        self.admin.issue_birthday_gift_now(
            self.request, User.objects.filter(pk=self.user.pk)
        )
        self.assertIn('Shopify down', ' '.join(self.messages))
