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
    """create_basic_discount accepts an optional expiry."""

    def _service(self):
        from users.services import ShopifyService
        return ShopifyService()

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


class ShopifyCombinesWithTests(APITestCase):
    """
    Every code we mint must be stackable with the other codes a member holds.

    Shopify defaults combinesWith to all-false, so omitting the field is the
    same as saying "this code stands alone" — which is what members were
    running into. These tests pin the field down at the payload level.
    """

    def _service(self):
        from users.services import ShopifyService
        return ShopifyService()

    def _basic_payload(self, mock_gql):
        return mock_gql.call_args.args[1]['basicCodeDiscount']

    def test_basic_discount_combines_with_everything_by_default(self):
        service = self._service()
        with patch.object(service, '_graphql_request', return_value=None) as mock_gql:
            service.create_basic_discount(
                code='HOB-X', title='t', discount_type='fixed_amount', value=5
            )

        self.assertEqual(
            self._basic_payload(mock_gql)['combinesWith'],
            {'orderDiscounts': True, 'productDiscounts': True, 'shippingDiscounts': True},
        )

    def test_free_product_discount_combines_with_everything(self):
        """Raffle prizes go through create_free_product_discount."""
        service = self._service()
        with patch.object(service, '_graphql_request', return_value=None) as mock_gql:
            service.create_free_product_discount(
                code='WIN-X', title='t', product_id='gid://shopify/Product/1'
            )

        self.assertEqual(
            self._basic_payload(mock_gql)['combinesWith'],
            {'orderDiscounts': True, 'productDiscounts': True, 'shippingDiscounts': True},
        )

    def test_free_shipping_discount_combines_with_everything(self):
        service = self._service()
        with patch.object(service, '_graphql_request', return_value=None) as mock_gql:
            service.create_free_shipping_discount(code='HOB-X', title='t')

        payload = mock_gql.call_args.args[1]['freeShippingCodeDiscount']
        self.assertEqual(
            payload['combinesWith'],
            {'orderDiscounts': True, 'productDiscounts': True, 'shippingDiscounts': True},
        )

    def test_combines_with_can_be_overridden(self):
        """An explicit {} mints a stand-alone code without touching the default."""
        service = self._service()
        with patch.object(service, '_graphql_request', return_value=None) as mock_gql:
            service.create_basic_discount(
                code='HOB-X', title='t', discount_type='percentage', value=10,
                combines_with={},
            )

        self.assertEqual(self._basic_payload(mock_gql)['combinesWith'], {})

    def test_customer_id_locks_the_code_to_one_customer(self):
        """The birthday gift relies on this; it used to be a REST prerequisite."""
        service = self._service()
        with patch.object(service, '_graphql_request', return_value=None) as mock_gql:
            service.create_basic_discount(
                code='BDAY-X', title='t', discount_type='fixed_amount', value=5,
                customer_id='123456',
            )

        self.assertEqual(
            self._basic_payload(mock_gql)['customerSelection'],
            {'customers': {'add': ['gid://shopify/Customer/123456']}},
        )

    def test_without_customer_id_the_code_is_open(self):
        service = self._service()
        with patch.object(service, '_graphql_request', return_value=None) as mock_gql:
            service.create_basic_discount(
                code='HOB-X', title='t', discount_type='fixed_amount', value=5
            )

        self.assertEqual(
            self._basic_payload(mock_gql)['customerSelection'], {'all': True}
        )


class ShopifySetCombinesWithTests(APITestCase):
    """Repairing codes that were already minted non-combinable."""

    def _service(self):
        from users.services import ShopifyService
        return ShopifyService()

    def _responses(self, typename, update_key, user_errors=None):
        """codeDiscountNodeByCode lookup, then the update mutation."""
        return [
            {'codeDiscountNodeByCode': {
                'id': 'gid://shopify/DiscountCodeNode/7',
                'codeDiscount': {'__typename': typename},
            }},
            {update_key: {'userErrors': user_errors or []}},
        ]

    def test_basic_code_is_updated_through_the_basic_mutation(self):
        service = self._service()
        with patch.object(service, '_graphql_request') as mock_gql:
            mock_gql.side_effect = self._responses(
                'DiscountCodeBasic', 'discountCodeBasicUpdate'
            )
            result = service.set_discount_combines_with('HOB-ABC12345')

        self.assertEqual(result, 'updated')
        mutation, variables = mock_gql.call_args.args
        self.assertIn('discountCodeBasicUpdate', mutation)
        self.assertIn('basicCodeDiscount', mutation)
        self.assertEqual(variables['id'], 'gid://shopify/DiscountCodeNode/7')
        self.assertEqual(
            variables['input']['combinesWith'],
            {'orderDiscounts': True, 'productDiscounts': True, 'shippingDiscounts': True},
        )

    def test_free_shipping_code_uses_its_own_mutation(self):
        """A DiscountCodeBasic input cannot update a free-shipping discount."""
        service = self._service()
        with patch.object(service, '_graphql_request') as mock_gql:
            mock_gql.side_effect = self._responses(
                'DiscountCodeFreeShipping', 'discountCodeFreeShippingUpdate'
            )
            result = service.set_discount_combines_with('HOB-SHIP1234')

        self.assertEqual(result, 'updated')
        mutation, _variables = mock_gql.call_args.args
        self.assertIn('discountCodeFreeShippingUpdate', mutation)
        self.assertIn('freeShippingCodeDiscount', mutation)

    def test_missing_code_reports_not_found_without_updating(self):
        """Deleted in the Shopify admin: nothing to repair, not a failure."""
        service = self._service()
        with patch.object(service, '_graphql_request') as mock_gql:
            mock_gql.return_value = {'codeDiscountNodeByCode': None}
            result = service.set_discount_combines_with('HOB-GONE0000')

        self.assertEqual(result, 'not_found')
        self.assertEqual(mock_gql.call_count, 1)

    def test_user_errors_report_failed(self):
        service = self._service()
        with patch.object(service, '_graphql_request') as mock_gql:
            mock_gql.side_effect = self._responses(
                'DiscountCodeBasic', 'discountCodeBasicUpdate',
                user_errors=[{'code': 'INVALID', 'message': 'nope'}],
            )
            result = service.set_discount_combines_with('HOB-ABC12345')

        self.assertEqual(result, 'failed')

    def test_shopify_silence_reports_failed(self):
        service = self._service()
        with patch.object(service, '_graphql_request', return_value=None):
            result = service.set_discount_combines_with('HOB-ABC12345')

        self.assertEqual(result, 'failed')


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


class SignupCodeTests(APITestCase):
    """Flyer QR -> registration -> welcome bonus."""

    def setUp(self):
        from users.models import SignupCode

        self.url = reverse('register')
        # RegisterView reaches out to Shopify; never in tests.
        patcher = patch('users.views.ShopifyService')
        self.mock_shopify = patcher.start()
        self.addCleanup(patcher.stop)
        self.mock_shopify.return_value.link_customer_to_user.return_value = False

        # The bonus notification goes over the real outbox; stub the delivery
        # so these tests assert points, not push infrastructure.
        notify_patcher = patch('notifications.services.send_notification')
        self.mock_notify = notify_patcher.start()
        self.addCleanup(notify_patcher.stop)

        self.code = SignupCode.objects.create(
            code='FLYER-UTRECHT', label='Flyer Utrecht september', points=100
        )

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

    def _register(self, **overrides):
        return self.client.post(self.url, self._payload(**overrides), format='json')

    # --- normalization ---------------------------------------------------

    def test_code_is_stored_uppercase(self):
        from users.models import SignupCode

        code = SignupCode.objects.create(code='  flyer-den-bosch ', label='DB')
        self.assertEqual(code.code, 'FLYER-DEN-BOSCH')

    def test_lowercase_typed_code_matches_uppercase_qr_code(self):
        """Someone typing 'flyer-utrecht' and a QR carrying it must agree."""
        response = self._register(signup_code='flyer-utrecht')

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        user = User.objects.get(email='newuser@example.com')
        self.assertEqual(user.signup_code, self.code)

    # --- awarding ---------------------------------------------------------

    def test_valid_code_awards_points_once(self):
        from loyalty.models import PointsBalance, PointsTransaction

        response = self._register(signup_code='FLYER-UTRECHT')

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['signup_bonus_points'], 100)

        user = User.objects.get(email='newuser@example.com')
        self.assertEqual(user.signup_code, self.code)
        self.assertEqual(user.signup_code_raw, 'FLYER-UTRECHT')
        self.assertEqual(PointsBalance.objects.get(user=user).balance, 100)
        self.assertEqual(PointsTransaction.objects.filter(user=user).count(), 1)

    def test_points_land_as_earned_without_a_shopify_order_id(self):
        """
        The shape the whole ledger agrees on: full sync's check-and-correct
        rewrites earned rows that carry a shopify_order_id.
        """
        from loyalty.models import PointsTransaction

        self._register(signup_code='FLYER-UTRECHT')
        user = User.objects.get(email='newuser@example.com')

        txn = PointsTransaction.objects.get(user=user)
        self.assertEqual(txn.transaction_type, 'earned')
        self.assertEqual(txn.points, 100)
        self.assertIsNone(txn.rule)
        self.assertFalse(txn.shopify_order_id)
        # The label reaches the app's history expander via the breakdown.
        self.assertIn('Flyer Utrecht september', txn.breakdown[0]['rule_name'])

    def test_bonus_cannot_be_awarded_twice_for_the_same_user(self):
        from loyalty.models import PointsBalance, PointsTransaction
        from users.services.signup_codes import award_signup_bonus

        self._register(signup_code='FLYER-UTRECHT')
        user = User.objects.get(email='newuser@example.com')
        self.assertIsNotNone(user.welcome_bonus_awarded_at)

        # A replayed request / retried registration must be a no-op.
        self.assertEqual(award_signup_bonus(user), 0)
        self.assertEqual(PointsBalance.objects.get(user=user).balance, 100)
        self.assertEqual(PointsTransaction.objects.filter(user=user).count(), 1)

    def test_calling_the_award_path_twice_awards_once(self):
        """The DB-level guard, exercised directly - no registration involved."""
        from loyalty.models import PointsBalance, PointsTransaction
        from users.services.signup_codes import award_signup_bonus

        user = User.objects.create_user(
            username='direct@example.com', email='direct@example.com',
            password='SuperSecret123!',
        )
        user.signup_code = self.code
        user.save(update_fields=['signup_code'])

        self.assertEqual(award_signup_bonus(user), 100)
        self.assertEqual(award_signup_bonus(user), 0)

        self.assertEqual(PointsTransaction.objects.filter(user=user).count(), 1)
        self.assertEqual(PointsBalance.objects.get(user=user).balance, 100)

    def test_the_marker_alone_stops_a_second_award(self):
        """
        Even with the grant row gone (an admin cleanup, a data migration), the
        marker must hold: the bonus is once per user, ever.
        """
        from loyalty.models import PointsBalance, ServiceGrant
        from users.services.signup_codes import award_signup_bonus

        self._register(signup_code='FLYER-UTRECHT')
        user = User.objects.get(email='newuser@example.com')
        ServiceGrant.objects.filter(dedupe_key=f'signup:{user.id}').delete()

        self.assertEqual(award_signup_bonus(user), 0)
        self.assertEqual(PointsBalance.objects.get(user=user).balance, 100)

    def test_registration_without_a_code_awards_nothing(self):
        from loyalty.models import PointsTransaction

        response = self._register()

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        user = User.objects.get(email='newuser@example.com')
        self.assertEqual(user.signup_code_raw, '')
        self.assertIsNone(user.signup_code)
        self.assertEqual(PointsTransaction.objects.filter(user=user).count(), 0)

    # --- invalid codes still create the account --------------------------

    def test_unknown_code_still_registers_and_records_the_raw_value(self):
        from loyalty.models import PointsTransaction

        response = self._register(signup_code='FLYER-TYPO')

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        user = User.objects.get(email='newuser@example.com')
        self.assertIsNone(user.signup_code)
        self.assertEqual(user.signup_code_raw, 'FLYER-TYPO')
        self.assertEqual(PointsTransaction.objects.filter(user=user).count(), 0)

    def test_expired_code_still_registers_and_records_the_raw_value(self):
        self.code.valid_until = timezone.now() - timedelta(days=1)
        self.code.save()

        response = self._register(signup_code='FLYER-UTRECHT')

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['signup_bonus_points'], 0)
        user = User.objects.get(email='newuser@example.com')
        self.assertIsNone(user.signup_code)
        self.assertEqual(user.signup_code_raw, 'FLYER-UTRECHT')

    def test_inactive_and_not_yet_valid_codes_are_unusable(self):
        self.code.valid_from = timezone.now() + timedelta(days=7)
        self.code.save()
        self.assertEqual(self.code.check_usable(), (False, 'not yet valid'))

        self.code.valid_from = None
        self.code.is_active = False
        self.code.save()
        self.assertEqual(self.code.check_usable(), (False, 'inactive'))

    def test_max_uses_is_enforced(self):
        self.code.max_uses = 1
        self.code.save()

        first = self._register(signup_code='FLYER-UTRECHT')
        self.assertEqual(first.data['signup_bonus_points'], 100)

        second = self._register(email='second@example.com',
                                signup_code='FLYER-UTRECHT')
        self.assertEqual(second.status_code, status.HTTP_201_CREATED)
        self.assertEqual(second.data['signup_bonus_points'], 0)

        other = User.objects.get(email='second@example.com')
        self.assertIsNone(other.signup_code)
        self.assertEqual(other.signup_code_raw, 'FLYER-UTRECHT')
        self.assertEqual(self.code.signup_count, 1)

    def test_existing_account_gets_one_clear_error_pointing_at_login(self):
        """
        The welcome bonus is for NEW accounts. Someone who already has one and
        registers again must get the email error and nothing else - the code
        must not add a second, confusing error on top.
        """
        User.objects.create_user(
            username='newuser@example.com', email='newuser@example.com',
            password='SuperSecret123!',
        )

        response = self._register(signup_code='FLYER-UTRECHT')

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(list(response.data.keys()), ['email'])
        self.assertIn('log in', str(response.data['email']).lower())
        # Nothing was recorded and nothing was paid out.
        existing = User.objects.get(email='newuser@example.com')
        self.assertEqual(existing.signup_code_raw, '')
        self.assertIsNone(existing.welcome_bonus_awarded_at)

    def test_a_broken_bonus_never_costs_the_account(self):
        """The whole point of the try/except around the award."""
        with patch('users.services.signup_codes.award_signup_bonus',
                   side_effect=RuntimeError('loyalty is down')):
            response = self._register(signup_code='FLYER-UTRECHT')

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(User.objects.filter(email='newuser@example.com').exists())

    # --- public lookup endpoint ------------------------------------------

    def test_lookup_returns_points_for_a_valid_code(self):
        response = self.client.get(
            reverse('signup_code_lookup', args=['flyer-utrecht'])
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data['valid'])
        self.assertEqual(response.data['points'], 100)
        self.assertEqual(response.data['label'], 'Flyer Utrecht september')

    def test_lookup_needs_no_authentication(self):
        """It runs before the account exists."""
        self.client.force_authenticate(user=None)
        response = self.client.get(reverse('signup_code_lookup', args=['NOPE']))
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_lookup_leaks_nothing_about_an_invalid_code(self):
        self.code.is_active = False
        self.code.save()

        unknown = self.client.get(
            reverse('signup_code_lookup', args=['NOPE'])
        ).data
        inactive = self.client.get(
            reverse('signup_code_lookup', args=['FLYER-UTRECHT'])
        ).data

        expected = {'valid': False, 'label': '', 'points': 0}
        self.assertEqual(dict(unknown), expected)
        # Identical to the unknown-code answer: an anonymous caller cannot
        # probe which codes exist.
        self.assertEqual(dict(inactive), expected)

    # --- admin deliverable ------------------------------------------------

    def test_qr_url_is_the_printable_deliverable(self):
        self.assertEqual(
            self.code.qr_url,
            'https://app.houseofbeers.nl/?ref=FLYER-UTRECHT',
        )
