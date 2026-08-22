"""
Integration tests for the notification delivery system.

pywebpush is mocked throughout - we never hit a real push service - but
everything else is real: real model rows, real preference checks, real
django.core.mail outbox assertions.

Covers:
- dedupe_key idempotency (the core reliability primitive)
- 404/410 from the push service retiring a subscription
- email fallback when there is no working push channel
- the four per-kind email policies
- per-channel and per-category opt-outs
- partial push success still counting as sent
- the exact payload shape mobile/public/service-worker.js reads
- subscribe / unsubscribe / preferences endpoints
- the defaults: push on, email off (opt-in), and the 0006 data migration

Email is opt-in since migration 0006, so tests exercising the email channel
call `enable_email(user)` to model a user who explicitly turned it on.
"""
import json
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from pywebpush import WebPushException
from rest_framework.test import APITestCase

from .models import NotificationDelivery, NotificationPreference, PushSubscription
from .services import send_notification
from .tasks import prune_push_subscriptions

User = get_user_model()

VAPID_SETTINGS = dict(
    VAPID_PUBLIC_KEY='test-public-key',
    VAPID_PRIVATE_KEY='test-private-key',
    VAPID_SUBJECT='mailto:test@houseofbeers.nl',
)


class FakeResponse:
    """Stand-in for the requests.Response that pywebpush attaches."""

    def __init__(self, status_code):
        self.status_code = status_code
        self.text = f'status {status_code}'


def gone(status_code=410):
    return WebPushException(f'push service said {status_code}',
                            response=FakeResponse(status_code))


def server_error(status_code=500):
    return WebPushException(f'push service said {status_code}',
                            response=FakeResponse(status_code))


def make_user(n=1, email=None):
    return User.objects.create_user(
        username=f'user{n}',
        email=email or f'user{n}@test.com',
        password='testpass123',
    )


def make_subscription(user, n=1, **kwargs):
    defaults = {
        'endpoint': f'https://push.example.com/sub/{user.id}/{n}',
        'p256dh': f'p256dh-key-{n}',
        'auth': f'auth-key-{n}',
        'device_label': f'Device {n}',
    }
    defaults.update(kwargs)
    return PushSubscription.objects.create(user=user, **defaults)


def enable_email(user):
    """Opt a user into the email channel.

    Email is opt-in (email_enabled defaults to False), so tests that exercise
    email delivery or the email fallback policies must model a user who
    explicitly enabled it.
    """
    preference = NotificationPreference.for_user(user)
    preference.email_enabled = True
    preference.save(update_fields=['email_enabled'])
    return preference


@override_settings(**VAPID_SETTINGS)
class DedupeTests(TestCase):
    def setUp(self):
        self.user = make_user()
        make_subscription(self.user)
        enable_email(self.user)
        mail.outbox = []

    @patch('notifications.services.webpush')
    def test_same_dedupe_key_sends_once(self, mock_webpush):
        first = send_notification(
            self.user, kind='birthday_gift', title='Happy birthday',
            body='Here is your gift', dedupe_key='birthday:1:2026',
        )
        second = send_notification(
            self.user, kind='birthday_gift', title='Happy birthday',
            body='Here is your gift', dedupe_key='birthday:1:2026',
        )

        self.assertEqual(first.pk, second.pk)
        self.assertEqual(NotificationDelivery.objects.count(), 1)
        self.assertEqual(mock_webpush.call_count, 1, 'push must not be re-sent')
        self.assertEqual(len(mail.outbox), 1, 'email must not be re-sent')

    @patch('notifications.services.webpush')
    def test_second_call_returns_row_unchanged(self, mock_webpush):
        first = send_notification(
            self.user, kind='announcement', title='News', body='Body',
            dedupe_key='announce:1',
        )
        original_sent_at = first.sent_at

        second = send_notification(
            self.user, kind='announcement', title='Different title',
            body='Different body', dedupe_key='announce:1',
        )

        self.assertEqual(second.title, 'News')
        self.assertEqual(second.sent_at, original_sent_at)

    @patch('notifications.services.webpush')
    def test_different_dedupe_keys_both_send(self, mock_webpush):
        send_notification(self.user, kind='announcement', title='A', body='a',
                          dedupe_key='announce:a')
        send_notification(self.user, kind='announcement', title='B', body='b',
                          dedupe_key='announce:b')

        self.assertEqual(NotificationDelivery.objects.count(), 2)
        self.assertEqual(mock_webpush.call_count, 2)


@override_settings(**VAPID_SETTINGS)
class PushDeliveryTests(TestCase):
    def setUp(self):
        self.user = make_user()
        enable_email(self.user)
        mail.outbox = []

    @patch('notifications.services.webpush')
    def test_payload_matches_service_worker_contract(self, mock_webpush):
        make_subscription(self.user)

        send_notification(
            self.user, kind='announcement', title='New release',
            body='Tripel is back in stock',
            data={'url': '/shop/tripel', 'discount_code': 'IGNORED'},
            dedupe_key='announce:sw',
        )

        payload = json.loads(mock_webpush.call_args.kwargs['data'])
        # service-worker.js reads data.title, data.body, data.url and
        # data.tag - exactly.
        self.assertEqual(set(payload.keys()), {'title', 'body', 'url', 'tag'})
        self.assertEqual(payload['title'], 'New release')
        self.assertEqual(payload['body'], 'Tripel is back in stock')
        self.assertEqual(payload['url'], '/shop/tripel')
        self.assertEqual(payload['tag'], 'announce:sw')

    @patch('notifications.services.webpush')
    def test_payload_tag_defaults_to_dedupe_key(self, mock_webpush):
        """A retried send reuses the tag, so the browser replaces the earlier
        notification instead of stacking a duplicate."""
        make_subscription(self.user)

        send_notification(self.user, kind='announcement', title='T', body='B',
                          dedupe_key='announce:tagged')

        payload = json.loads(mock_webpush.call_args.kwargs['data'])
        self.assertEqual(payload['tag'], 'announce:tagged')

    @patch('notifications.services.webpush')
    def test_payload_tag_can_be_overridden_via_data(self, mock_webpush):
        make_subscription(self.user)

        send_notification(self.user, kind='announcement', title='T', body='B',
                          data={'tag': 'custom-tag'},
                          dedupe_key='announce:customtag')

        payload = json.loads(mock_webpush.call_args.kwargs['data'])
        self.assertEqual(payload['tag'], 'custom-tag')

    @patch('notifications.services.webpush')
    def test_payload_url_defaults_to_root(self, mock_webpush):
        make_subscription(self.user)

        send_notification(self.user, kind='announcement', title='T', body='B',
                          dedupe_key='announce:nourl')

        payload = json.loads(mock_webpush.call_args.kwargs['data'])
        self.assertEqual(payload['url'], '/')

    @patch('notifications.services.webpush')
    def test_subscription_info_uses_stored_keys(self, mock_webpush):
        subscription = make_subscription(self.user)

        send_notification(self.user, kind='announcement', title='T', body='B',
                          dedupe_key='announce:keys')

        info = mock_webpush.call_args.kwargs['subscription_info']
        self.assertEqual(info['endpoint'], subscription.endpoint)
        self.assertEqual(info['keys'], {
            'p256dh': subscription.p256dh, 'auth': subscription.auth,
        })

    @patch('notifications.services.webpush')
    def test_410_deactivates_subscription(self, mock_webpush):
        subscription = make_subscription(self.user)
        mock_webpush.side_effect = gone(410)

        delivery = send_notification(
            self.user, kind='announcement', title='T', body='B',
            dedupe_key='announce:410',
        )

        subscription.refresh_from_db()
        self.assertFalse(subscription.is_active)
        self.assertIsNotNone(subscription.deactivated_at)
        self.assertEqual(delivery.push_status, 'failed')

    @patch('notifications.services.webpush')
    def test_404_deactivates_subscription(self, mock_webpush):
        subscription = make_subscription(self.user)
        mock_webpush.side_effect = gone(404)

        send_notification(self.user, kind='announcement', title='T', body='B',
                          dedupe_key='announce:404')

        subscription.refresh_from_db()
        self.assertFalse(subscription.is_active)

    @patch('notifications.services.webpush')
    def test_500_increments_failure_count_but_keeps_subscription(self, mock_webpush):
        subscription = make_subscription(self.user)
        mock_webpush.side_effect = server_error(500)

        send_notification(self.user, kind='announcement', title='T', body='B',
                          dedupe_key='announce:500')

        subscription.refresh_from_db()
        self.assertTrue(subscription.is_active)
        self.assertEqual(subscription.failure_count, 1)

    @patch('notifications.services.webpush')
    def test_one_of_two_subscriptions_succeeding_counts_as_sent(self, mock_webpush):
        dead = make_subscription(self.user, n=1)
        alive = make_subscription(self.user, n=2)

        # Keyed on endpoint rather than call order. Subscriptions are fetched
        # in '-created_at' order, and two rows created microseconds apart in
        # one test may or may not tie on that timestamp - a positional
        # side_effect list made this test fail intermittently.
        def push(subscription_info=None, **kwargs):
            if subscription_info['endpoint'] == dead.endpoint:
                raise gone(410)
            return None

        mock_webpush.side_effect = push

        delivery = send_notification(
            self.user, kind='announcement', title='T', body='B',
            dedupe_key='announce:partial',
        )

        self.assertEqual(delivery.push_status, 'sent')
        dead.refresh_from_db()
        alive.refresh_from_db()
        self.assertFalse(dead.is_active)
        self.assertTrue(alive.is_active)
        self.assertIsNotNone(alive.last_success_at)
        # push worked, so the announcement fallback email must not fire
        self.assertEqual(len(mail.outbox), 0)

    @patch('notifications.services.webpush')
    def test_success_resets_failure_count(self, mock_webpush):
        subscription = make_subscription(self.user, failure_count=3)

        send_notification(self.user, kind='announcement', title='T', body='B',
                          dedupe_key='announce:reset')

        subscription.refresh_from_db()
        self.assertEqual(subscription.failure_count, 0)

    @patch('notifications.services.webpush')
    def test_inactive_subscription_is_not_pushed_to(self, mock_webpush):
        make_subscription(self.user, is_active=False)

        delivery = send_notification(
            self.user, kind='announcement', title='T', body='B',
            dedupe_key='announce:inactive',
        )

        mock_webpush.assert_not_called()
        self.assertEqual(delivery.push_status, 'skipped')

    @patch('notifications.services.webpush')
    def test_arbitrary_exception_does_not_escape(self, mock_webpush):
        subscription = make_subscription(self.user)
        mock_webpush.side_effect = ConnectionError('DNS failure')

        delivery = send_notification(
            self.user, kind='announcement', title='T', body='B',
            dedupe_key='announce:boom',
        )

        self.assertEqual(delivery.push_status, 'failed')
        subscription.refresh_from_db()
        self.assertEqual(subscription.failure_count, 1)

    @override_settings(VAPID_PRIVATE_KEY='', VAPID_PUBLIC_KEY='')
    @patch('notifications.services.webpush')
    def test_missing_vapid_keys_skips_push_instead_of_crashing(self, mock_webpush):
        make_subscription(self.user)

        delivery = send_notification(
            self.user, kind='announcement', title='T', body='B',
            dedupe_key='announce:novapid',
        )

        mock_webpush.assert_not_called()
        self.assertEqual(delivery.push_status, 'skipped')
        # no push channel, so the announcement falls back to email
        self.assertEqual(delivery.email_status, 'sent')


@override_settings(**VAPID_SETTINGS)
class EmailPolicyTests(TestCase):
    """The four kind policies from the design doc."""

    def setUp(self):
        self.user = make_user()
        enable_email(self.user)
        mail.outbox = []

    @patch('notifications.services.webpush')
    def test_birthday_gift_emails_even_when_push_succeeds(self, mock_webpush):
        make_subscription(self.user)

        delivery = send_notification(
            self.user, kind='birthday_gift', title='Happy birthday',
            body='Code: HB2026', data={'discount_code': 'HB2026'},
            dedupe_key='birthday:1:2026',
        )

        self.assertEqual(delivery.push_status, 'sent')
        self.assertEqual(delivery.email_status, 'sent')
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, [self.user.email])

    @patch('notifications.services.webpush')
    def test_transactional_emails_even_when_push_succeeds(self, mock_webpush):
        make_subscription(self.user)

        delivery = send_notification(
            self.user, kind='transactional', title='Order shipped',
            body='Your order is on its way', dedupe_key='order:99',
        )

        self.assertEqual(delivery.push_status, 'sent')
        self.assertEqual(delivery.email_status, 'sent')
        self.assertEqual(len(mail.outbox), 1)

    @patch('notifications.services.webpush')
    def test_announcement_skips_email_when_push_succeeds(self, mock_webpush):
        make_subscription(self.user)

        delivery = send_notification(
            self.user, kind='announcement', title='News', body='Body',
            dedupe_key='announce:pushok',
        )

        self.assertEqual(delivery.push_status, 'sent')
        self.assertEqual(delivery.email_status, 'skipped')
        self.assertEqual(len(mail.outbox), 0)

    @patch('notifications.services.webpush')
    def test_announcement_emails_when_push_fails(self, mock_webpush):
        make_subscription(self.user)
        mock_webpush.side_effect = gone(410)

        delivery = send_notification(
            self.user, kind='announcement', title='News', body='Body',
            dedupe_key='announce:pushfail',
        )

        self.assertEqual(delivery.push_status, 'failed')
        self.assertEqual(delivery.email_status, 'sent')
        self.assertEqual(len(mail.outbox), 1)

    @patch('notifications.services.webpush')
    def test_recommendations_never_emails(self, mock_webpush):
        # no subscription at all: push cannot succeed, and still no email
        delivery = send_notification(
            self.user, kind='recommendations', title='Picks for you',
            body='Three beers we think you will like',
            dedupe_key='recs:1:2026-07',
        )

        self.assertEqual(delivery.push_status, 'skipped')
        self.assertEqual(delivery.email_status, 'skipped')
        self.assertEqual(len(mail.outbox), 0)

    @patch('notifications.services.webpush')
    def test_no_active_subscription_falls_back_to_email(self, mock_webpush):
        delivery = send_notification(
            self.user, kind='announcement', title='News', body='Body',
            dedupe_key='announce:nosubs',
        )

        mock_webpush.assert_not_called()
        self.assertEqual(delivery.push_status, 'skipped')
        self.assertEqual(delivery.email_status, 'sent')
        self.assertEqual(len(mail.outbox), 1)

    @patch('notifications.services.webpush')
    def test_unknown_kind_uses_announcement_policy(self, mock_webpush):
        make_subscription(self.user)

        delivery = send_notification(
            self.user, kind='some_future_kind', title='T', body='B',
            dedupe_key='future:1',
        )

        self.assertEqual(delivery.email_status, 'skipped')
        self.assertEqual(len(mail.outbox), 0)

    @patch('notifications.services.webpush')
    def test_custom_email_subject_and_body_are_used(self, mock_webpush):
        send_notification(
            self.user, kind='birthday_gift', title='Push title',
            body='Push body', dedupe_key='birthday:custom',
            email_subject='Your birthday gift from House of Beers',
            email_body='Long form email with the code and how to use it.',
        )

        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].subject,
                         'Your birthday gift from House of Beers')
        self.assertIn('Long form email', mail.outbox[0].body)

    @patch('notifications.services.webpush')
    def test_email_failure_is_recorded_not_raised(self, mock_webpush):
        with patch('notifications.services.send_mail',
                   side_effect=Exception('SMTP down')):
            delivery = send_notification(
                self.user, kind='birthday_gift', title='T', body='B',
                dedupe_key='birthday:smtpdown',
            )

        self.assertEqual(delivery.email_status, 'failed')
        self.assertIn('SMTP down', delivery.email_error)


@override_settings(**VAPID_SETTINGS)
class PerMessageEmailPolicyTests(TestCase):
    """`email_policy` overrides the kind default for a single message."""

    def setUp(self):
        self.user = make_user()
        enable_email(self.user)
        mail.outbox = []

    @patch('notifications.services.webpush')
    def test_never_suppresses_email_that_the_kind_would_always_send(self, mock_webpush):
        make_subscription(self.user)

        delivery = send_notification(
            self.user, kind='birthday_gift', title='T', body='B',
            dedupe_key='birthday:nomail', email_policy='never',
        )

        self.assertEqual(delivery.push_status, 'sent')
        self.assertEqual(delivery.email_status, 'skipped')
        self.assertEqual(len(mail.outbox), 0)

    @patch('notifications.services.webpush')
    def test_never_suppresses_email_even_when_push_fails(self, mock_webpush):
        """'never' means never - not 'unless push failed'."""
        make_subscription(self.user)
        mock_webpush.side_effect = server_error(500)

        delivery = send_notification(
            self.user, kind='announcement', title='T', body='B',
            dedupe_key='announce:nomail', email_policy='never',
        )

        self.assertEqual(delivery.push_status, 'failed')
        self.assertEqual(delivery.email_status, 'skipped')
        self.assertEqual(len(mail.outbox), 0)

    @patch('notifications.services.webpush')
    def test_always_emails_a_kind_that_normally_would_not(self, mock_webpush):
        make_subscription(self.user)

        delivery = send_notification(
            self.user, kind='recommendations', title='Picks', body='B',
            dedupe_key='recs:forcemail', email_policy='always',
        )

        self.assertEqual(delivery.push_status, 'sent')
        self.assertEqual(delivery.email_status, 'sent')
        self.assertEqual(len(mail.outbox), 1)

    @patch('notifications.services.webpush')
    def test_fallback_downgrades_an_always_kind(self, mock_webpush):
        make_subscription(self.user)

        delivery = send_notification(
            self.user, kind='birthday_gift', title='T', body='B',
            dedupe_key='birthday:fallbackonly', email_policy='fallback',
        )

        self.assertEqual(delivery.push_status, 'sent')
        self.assertEqual(delivery.email_status, 'skipped')
        self.assertEqual(len(mail.outbox), 0)

    @patch('notifications.services.webpush')
    def test_omitting_the_override_keeps_the_kind_default(self, mock_webpush):
        """Every existing caller must be unaffected."""
        make_subscription(self.user)

        delivery = send_notification(
            self.user, kind='birthday_gift', title='T', body='B',
            dedupe_key='birthday:default',
        )

        self.assertEqual(delivery.email_status, 'sent')
        self.assertEqual(delivery.email_policy, '')
        self.assertEqual(len(mail.outbox), 1)

    @patch('notifications.services.webpush')
    def test_policy_is_recorded_on_the_delivery_row(self, mock_webpush):
        make_subscription(self.user)

        send_notification(
            self.user, kind='announcement', title='T', body='B',
            dedupe_key='announce:recorded', email_policy='never',
        )

        delivery = NotificationDelivery.objects.get(dedupe_key='announce:recorded')
        self.assertEqual(delivery.email_policy, 'never')

    def test_unknown_policy_is_rejected(self):
        with self.assertRaises(ValueError):
            send_notification(
                self.user, kind='announcement', title='T', body='B',
                dedupe_key='announce:bogus', email_policy='sometimes',
            )

    @patch('notifications.services.webpush')
    def test_an_override_cannot_defeat_a_user_opt_out(self, mock_webpush):
        """'always' is an operator preference, not a consent override."""
        preference = NotificationPreference.for_user(self.user)
        preference.email_enabled = False
        preference.save()

        delivery = send_notification(
            self.user, kind='announcement', title='T', body='B',
            dedupe_key='announce:optedout', email_policy='always',
        )

        self.assertEqual(delivery.email_status, 'skipped')
        self.assertEqual(len(mail.outbox), 0)


@override_settings(**VAPID_SETTINGS)
class PreferenceTests(TestCase):
    def setUp(self):
        self.user = make_user()
        enable_email(self.user)
        mail.outbox = []

    @patch('notifications.services.webpush')
    def test_push_disabled_skips_push(self, mock_webpush):
        make_subscription(self.user)
        preference = NotificationPreference.for_user(self.user)
        preference.push_enabled = False
        preference.save()

        delivery = send_notification(
            self.user, kind='announcement', title='T', body='B',
            dedupe_key='announce:nopush',
        )

        mock_webpush.assert_not_called()
        self.assertEqual(delivery.push_status, 'skipped')
        # push is unavailable, so the announcement still reaches them by email
        self.assertEqual(delivery.email_status, 'sent')

    @patch('notifications.services.webpush')
    def test_email_disabled_skips_email(self, mock_webpush):
        preference = NotificationPreference.for_user(self.user)
        preference.email_enabled = False
        preference.save()

        delivery = send_notification(
            self.user, kind='birthday_gift', title='T', body='B',
            dedupe_key='birthday:noemail',
        )

        self.assertEqual(delivery.email_status, 'skipped')
        self.assertEqual(len(mail.outbox), 0)

    @patch('notifications.services.webpush')
    def test_category_opt_out_skips_both_channels(self, mock_webpush):
        make_subscription(self.user)
        preference = NotificationPreference.for_user(self.user)
        preference.birthday = False
        preference.save()

        delivery = send_notification(
            self.user, kind='birthday_gift', title='T', body='B',
            dedupe_key='birthday:optout',
        )

        mock_webpush.assert_not_called()
        self.assertEqual(delivery.push_status, 'skipped')
        self.assertEqual(delivery.email_status, 'skipped')
        self.assertEqual(len(mail.outbox), 0)

    @patch('notifications.services.webpush')
    def test_transactional_ignores_category_opt_outs(self, mock_webpush):
        make_subscription(self.user)
        preference = NotificationPreference.for_user(self.user)
        preference.announcements = False
        preference.birthday = False
        preference.recommendations = False
        preference.save()

        delivery = send_notification(
            self.user, kind='transactional', title='Order shipped', body='B',
            dedupe_key='order:100',
        )

        self.assertEqual(delivery.push_status, 'sent')
        self.assertEqual(delivery.email_status, 'sent')

    def test_for_user_is_idempotent(self):
        first = NotificationPreference.for_user(self.user)
        second = NotificationPreference.for_user(self.user)
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(NotificationPreference.objects.count(), 1)


@override_settings(**VAPID_SETTINGS)
class DefaultPreferenceTests(TestCase):
    """The owner's defaults: push on, email off, unless the user chose otherwise."""

    def setUp(self):
        self.user = make_user()
        mail.outbox = []

    def test_new_preference_row_defaults(self):
        preference = NotificationPreference.for_user(self.user)

        self.assertTrue(preference.push_enabled, 'push must be on by default')
        self.assertFalse(preference.email_enabled, 'email must be off by default')
        # Category opt-outs stay on by default - they gate what, not how.
        self.assertTrue(preference.birthday)
        self.assertTrue(preference.announcements)
        self.assertTrue(preference.recommendations)

    @patch('notifications.services.webpush')
    def test_default_user_gets_push(self, mock_webpush):
        make_subscription(self.user)

        delivery = send_notification(
            self.user, kind='announcement', title='T', body='B',
            dedupe_key='defaults:push',
        )

        self.assertEqual(delivery.push_status, 'sent')
        self.assertEqual(mock_webpush.call_count, 1)

    @patch('notifications.services.webpush')
    def test_default_user_is_never_emailed_even_for_always_kinds(self, mock_webpush):
        """Nothing emails by default - not even an EMAIL_ALWAYS kind."""
        make_subscription(self.user)

        delivery = send_notification(
            self.user, kind='birthday_gift', title='Happy birthday',
            body='Here is your gift', dedupe_key='defaults:noemail',
        )

        self.assertEqual(delivery.push_status, 'sent')
        self.assertEqual(delivery.email_status, 'skipped')
        self.assertEqual(len(mail.outbox), 0)

    @patch('notifications.services.webpush')
    def test_default_user_gets_no_email_fallback_when_push_cannot_land(self, mock_webpush):
        # No subscription: push is skipped, and the announcement fallback
        # must NOT email a user who never opted into email.
        delivery = send_notification(
            self.user, kind='announcement', title='T', body='B',
            dedupe_key='defaults:nofallback',
        )

        self.assertEqual(delivery.push_status, 'skipped')
        self.assertEqual(delivery.email_status, 'skipped')
        self.assertEqual(len(mail.outbox), 0)

    @patch('notifications.services.webpush')
    def test_explicit_email_opt_in_still_gets_email(self, mock_webpush):
        make_subscription(self.user)
        enable_email(self.user)

        delivery = send_notification(
            self.user, kind='birthday_gift', title='T', body='B',
            dedupe_key='defaults:optin',
        )

        self.assertEqual(delivery.email_status, 'sent')
        self.assertEqual(len(mail.outbox), 1)


class DefaultsMigrationTests(TestCase):
    """The data half of migration 0006: old-default rows move to the new
    defaults; rows that differ from the old defaults are an explicit choice
    and stay untouched."""

    @staticmethod
    def _flip():
        from importlib import import_module

        from django.apps import apps
        migration = import_module(
            'notifications.migrations.0006_alter_notificationpreference_email_enabled'
        )
        migration.flip_old_default_rows(apps, None)

    def test_old_default_rows_are_flipped_to_email_off(self):
        user = make_user(1)
        NotificationPreference.objects.create(
            user=user, push_enabled=True, email_enabled=True,
        )

        self._flip()

        preference = NotificationPreference.objects.get(user=user)
        self.assertTrue(preference.push_enabled)
        self.assertFalse(preference.email_enabled)

    def test_push_opted_out_rows_keep_their_email_channel(self):
        """push off + email on differs from the old defaults: the user turned
        push off, and email is the only channel they have left."""
        user = make_user(2)
        NotificationPreference.objects.create(
            user=user, push_enabled=False, email_enabled=True,
        )

        self._flip()

        preference = NotificationPreference.objects.get(user=user)
        self.assertFalse(preference.push_enabled)
        self.assertTrue(preference.email_enabled)

    def test_category_choices_do_not_shield_a_row_from_the_flip(self):
        """Category toggles are independent of the channel defaults; the row
        still moves to email-off and the category choice is preserved."""
        user = make_user(3)
        NotificationPreference.objects.create(
            user=user, push_enabled=True, email_enabled=True,
            recommendations=False,
        )

        self._flip()

        preference = NotificationPreference.objects.get(user=user)
        self.assertFalse(preference.email_enabled)
        self.assertFalse(preference.recommendations)


class PruneTaskTests(TestCase):
    def setUp(self):
        self.user = make_user()

    def test_deactivates_subscriptions_past_the_failure_threshold(self):
        doomed = make_subscription(self.user, n=1, failure_count=5)
        healthy = make_subscription(self.user, n=2, failure_count=2)

        result = prune_push_subscriptions()

        doomed.refresh_from_db()
        healthy.refresh_from_db()
        self.assertFalse(doomed.is_active)
        self.assertTrue(healthy.is_active)
        self.assertEqual(result['deactivated'], 1)

    def test_deletes_long_retired_subscriptions(self):
        old = make_subscription(self.user, n=1, is_active=False)
        PushSubscription.objects.filter(pk=old.pk).update(
            deactivated_at=timezone.now() - timezone.timedelta(days=31),
        )
        recent = make_subscription(self.user, n=2, is_active=False)
        PushSubscription.objects.filter(pk=recent.pk).update(
            deactivated_at=timezone.now() - timezone.timedelta(days=2),
        )

        result = prune_push_subscriptions()

        self.assertFalse(PushSubscription.objects.filter(pk=old.pk).exists())
        self.assertTrue(PushSubscription.objects.filter(pk=recent.pk).exists())
        self.assertEqual(result['deleted'], 1)


class SubscribeEndpointTests(APITestCase):
    def setUp(self):
        self.user = make_user(1)
        self.other = make_user(2)
        self.url = reverse('notifications-subscribe')
        self.payload = {
            'endpoint': 'https://push.example.com/sub/abc',
            'keys': {'p256dh': 'p256dh-value', 'auth': 'auth-value'},
            'device_label': 'iPhone Safari',
        }

    def test_requires_authentication(self):
        response = self.client.post(self.url, self.payload, format='json')
        self.assertEqual(response.status_code, 401)

    def test_creates_subscription(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.post(self.url, self.payload, format='json')

        self.assertEqual(response.status_code, 201)
        subscription = PushSubscription.objects.get(endpoint=self.payload['endpoint'])
        self.assertEqual(subscription.user, self.user)
        self.assertEqual(subscription.p256dh, 'p256dh-value')
        self.assertEqual(subscription.device_label, 'iPhone Safari')
        self.assertTrue(subscription.is_active)

    def test_resubscribe_upserts_by_endpoint(self):
        self.client.force_authenticate(user=self.user)
        self.client.post(self.url, self.payload, format='json')

        refreshed = dict(self.payload)
        refreshed['keys'] = {'p256dh': 'new-p256dh', 'auth': 'new-auth'}
        response = self.client.post(self.url, refreshed, format='json')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(PushSubscription.objects.count(), 1)
        subscription = PushSubscription.objects.get()
        self.assertEqual(subscription.p256dh, 'new-p256dh')

    def test_resubscribe_reactivates_and_resets_failures(self):
        subscription = PushSubscription.objects.create(
            user=self.user, endpoint=self.payload['endpoint'],
            p256dh='old', auth='old', is_active=False, failure_count=7,
            deactivated_at=timezone.now(),
        )

        self.client.force_authenticate(user=self.user)
        self.client.post(self.url, self.payload, format='json')

        subscription.refresh_from_db()
        self.assertTrue(subscription.is_active)
        self.assertEqual(subscription.failure_count, 0)
        self.assertIsNone(subscription.deactivated_at)

    def test_shared_device_moves_to_the_requesting_user(self):
        PushSubscription.objects.create(
            user=self.other, endpoint=self.payload['endpoint'],
            p256dh='old', auth='old',
        )

        self.client.force_authenticate(user=self.user)
        response = self.client.post(self.url, self.payload, format='json')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(PushSubscription.objects.count(), 1)
        self.assertEqual(PushSubscription.objects.get().user, self.user)

    def test_missing_body_returns_400(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.post(self.url, {}, format='json')
        self.assertEqual(response.status_code, 400)

    def test_malformed_keys_returns_400(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.post(
            self.url,
            {'endpoint': 'https://push.example.com/x', 'keys': 'not-an-object'},
            format='json',
        )
        self.assertEqual(response.status_code, 400)

    def test_partial_keys_returns_400(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.post(
            self.url,
            {'endpoint': 'https://push.example.com/x', 'keys': {'p256dh': 'only'}},
            format='json',
        )
        self.assertEqual(response.status_code, 400)

    def test_device_label_is_optional(self):
        self.client.force_authenticate(user=self.user)
        payload = {k: v for k, v in self.payload.items() if k != 'device_label'}
        response = self.client.post(self.url, payload, format='json')
        self.assertEqual(response.status_code, 201)


class UnsubscribeEndpointTests(APITestCase):
    def setUp(self):
        self.user = make_user(1)
        self.other = make_user(2)
        self.url = reverse('notifications-unsubscribe')

    def test_requires_authentication(self):
        response = self.client.post(self.url, {'endpoint': 'x'}, format='json')
        self.assertEqual(response.status_code, 401)

    def test_deactivates_own_subscription(self):
        subscription = make_subscription(self.user)
        self.client.force_authenticate(user=self.user)

        response = self.client.post(
            self.url, {'endpoint': subscription.endpoint}, format='json',
        )

        self.assertEqual(response.status_code, 200)
        subscription.refresh_from_db()
        self.assertFalse(subscription.is_active)
        self.assertIsNotNone(subscription.deactivated_at)

    def test_unknown_endpoint_is_idempotent(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.post(
            self.url, {'endpoint': 'https://push.example.com/never-seen'},
            format='json',
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data['found'])

    def test_cannot_deactivate_another_users_subscription(self):
        subscription = make_subscription(self.other)
        self.client.force_authenticate(user=self.user)

        response = self.client.post(
            self.url, {'endpoint': subscription.endpoint}, format='json',
        )

        self.assertEqual(response.status_code, 200)
        subscription.refresh_from_db()
        self.assertTrue(subscription.is_active)

    def test_missing_endpoint_returns_400(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.post(self.url, {}, format='json')
        self.assertEqual(response.status_code, 400)


class PreferencesEndpointTests(APITestCase):
    def setUp(self):
        self.user = make_user()
        self.url = reverse('notifications-preferences')

    def test_requires_authentication(self):
        self.assertEqual(self.client.get(self.url).status_code, 401)
        self.assertEqual(self.client.patch(self.url, {}, format='json').status_code, 401)

    def test_get_creates_defaults(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data['push_enabled'])
        self.assertFalse(response.data['email_enabled'],
                         'email must be opt-in, not on by default')
        self.assertTrue(response.data['birthday'])
        self.assertEqual(NotificationPreference.objects.filter(user=self.user).count(), 1)

    def test_patch_partial_update(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.patch(
            self.url, {'recommendations': False}, format='json',
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data['recommendations'])
        self.assertTrue(response.data['announcements'])

        preference = NotificationPreference.objects.get(user=self.user)
        self.assertFalse(preference.recommendations)
        self.assertTrue(preference.announcements)

    def test_patch_rejects_malformed_value(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.patch(
            self.url, {'push_enabled': 'not-a-boolean'}, format='json',
        )
        self.assertEqual(response.status_code, 400)


class VapidPublicKeyEndpointTests(APITestCase):
    @override_settings(VAPID_PUBLIC_KEY='the-public-key')
    def test_available_without_authentication(self):
        response = self.client.get(reverse('notifications-vapid-public-key'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, {'public_key': 'the-public-key'})


class KindSettingTests(TestCase):
    """The admin checkboxes that control whether email follows a push."""

    def setUp(self):
        from django.core.cache import cache
        cache.clear()
        self.user = User.objects.create_user(
            username='ks', email='ks@example.com', password='pw12345!')
        enable_email(self.user)

    def tearDown(self):
        from django.core.cache import cache
        cache.clear()

    def _setting(self, kind, **kwargs):
        from notifications.models import NotificationKindSetting
        from notifications.services import invalidate_kind_settings_cache
        obj, _ = NotificationKindSetting.objects.update_or_create(
            kind=kind, defaults=kwargs)
        invalidate_kind_settings_cache()
        return obj

    def test_defaults_are_seeded_by_migration(self):
        from notifications.models import NotificationKindSetting
        kinds = set(NotificationKindSetting.objects.values_list('kind', flat=True))
        self.assertEqual(
            kinds,
            {'birthday_gift', 'announcement', 'recommendations',
             'transactional', 'raffle'},
        )

    def test_seeded_defaults_match_the_code_defaults(self):
        """Seeding must not silently change behaviour."""
        from notifications.models import NotificationKindSetting
        from notifications.services import KIND_POLICY
        for row in NotificationKindSetting.objects.all():
            self.assertEqual(
                row.email_policy, KIND_POLICY[row.kind],
                f"{row.kind} seeded as {row.email_policy}, code says {KIND_POLICY[row.kind]}",
            )

    def test_unticking_send_email_stops_the_fallback(self):
        """The headline case: push only, no email even when push cannot land."""
        self._setting('announcement', send_push=True, send_email=False,
                      email_only_if_push_failed=True)
        mail.outbox = []
        delivery = send_notification(
            self.user, kind='announcement', title='T', body='B',
            dedupe_key='ks:no-email')
        # No subscription exists, so push is skipped - previously this would
        # have fallen back to email.
        self.assertEqual(delivery.push_status, 'skipped')
        self.assertEqual(delivery.email_status, 'skipped')
        self.assertEqual(len(mail.outbox), 0)

    def test_unticking_only_if_failed_emails_alongside_push(self):
        self._setting('announcement', send_push=True, send_email=True,
                      email_only_if_push_failed=False)
        mail.outbox = []
        delivery = send_notification(
            self.user, kind='announcement', title='T', body='B',
            dedupe_key='ks:always')
        self.assertEqual(delivery.email_status, 'sent')
        self.assertEqual(len(mail.outbox), 1)

    def test_switching_push_off_for_a_kind(self):
        self._setting('recommendations', send_push=False, send_email=False,
                      email_only_if_push_failed=True)
        delivery = send_notification(
            self.user, kind='recommendations', title='T', body='B',
            dedupe_key='ks:nopush')
        self.assertEqual(delivery.push_status, 'skipped')
        self.assertIn('switched off', delivery.push_error)

    def test_per_message_override_beats_the_admin_setting(self):
        """An explicit call argument still wins, so code can force an email."""
        self._setting('announcement', send_push=True, send_email=False,
                      email_only_if_push_failed=True)
        mail.outbox = []
        delivery = send_notification(
            self.user, kind='announcement', title='T', body='B',
            dedupe_key='ks:override', email_policy='always')
        self.assertEqual(delivery.email_status, 'sent')
        self.assertEqual(len(mail.outbox), 1)

    def test_admin_setting_cannot_override_a_user_opt_out(self):
        """Operator preference must never defeat consent."""
        from notifications.models import NotificationPreference
        pref = NotificationPreference.for_user(self.user)
        pref.email_enabled = False
        pref.save()
        self._setting('announcement', send_push=True, send_email=True,
                      email_only_if_push_failed=False)
        mail.outbox = []
        delivery = send_notification(
            self.user, kind='announcement', title='T', body='B',
            dedupe_key='ks:consent')
        self.assertEqual(delivery.email_status, 'skipped')
        self.assertEqual(len(mail.outbox), 0)

    def test_missing_row_falls_back_to_the_code_default(self):
        from notifications.models import NotificationKindSetting
        from notifications.services import invalidate_kind_settings_cache
        NotificationKindSetting.objects.filter(kind='birthday_gift').delete()
        invalidate_kind_settings_cache()
        mail.outbox = []
        delivery = send_notification(
            self.user, kind='birthday_gift', title='T', body='B',
            dedupe_key='ks:missing')
        # birthday_gift is EMAIL_ALWAYS in code.
        self.assertEqual(delivery.email_status, 'sent')


class BroadcastTests(TestCase):
    """Admin-authored messages fanned out to an audience."""

    def setUp(self):
        from django.core.cache import cache
        cache.clear()
        self.a = User.objects.create_user(
            username='ba', email='ba@example.com', password='pw12345!')
        self.b = User.objects.create_user(
            username='bb', email='bb@example.com', password='pw12345!')
        self.inactive = User.objects.create_user(
            username='bc', email='bc@example.com', password='pw12345!',
            is_active=False)
        # Email is opt-in; these tests model users who enabled it, so the
        # push-only audience assertions actually prove the override works.
        enable_email(self.a)
        enable_email(self.b)
        mail.outbox = []

    def _broadcast(self, **kwargs):
        from .models import Broadcast
        kwargs.setdefault('title', 'New drop')
        kwargs.setdefault('body', 'Fresh beers just landed.')
        kwargs.setdefault('url', '/loyalty')
        return Broadcast.objects.create(**kwargs)

    def test_everyone_audience_excludes_inactive_accounts(self):
        from .models import Broadcast
        b = self._broadcast(audience=Broadcast.AUDIENCE_ALL,
                            status=Broadcast.STATUS_SCHEDULED)
        emails = {u.email for u in b.resolve_recipients()}
        self.assertEqual(emails, {'ba@example.com', 'bb@example.com'})

    def test_selected_audience_only_reaches_the_chosen_users(self):
        from .models import Broadcast
        b = self._broadcast(audience=Broadcast.AUDIENCE_SELECTED,
                            status=Broadcast.STATUS_SCHEDULED)
        b.recipients.add(self.a)
        self.assertEqual([u.pk for u in b.resolve_recipients()], [self.a.pk])

    def test_push_only_audience_excludes_users_without_a_subscription(self):
        from .models import Broadcast, PushSubscription
        PushSubscription.objects.create(
            user=self.a, endpoint='https://push.example/a',
            p256dh='x', auth='y', is_active=True)
        b = self._broadcast(audience=Broadcast.AUDIENCE_PUSH_ONLY,
                            status=Broadcast.STATUS_SCHEDULED)
        self.assertEqual([u.pk for u in b.resolve_recipients()], [self.a.pk])

    def test_send_creates_one_delivery_per_recipient(self):
        from .models import Broadcast
        from .tasks import send_broadcast
        b = self._broadcast(status=Broadcast.STATUS_SCHEDULED)
        send_broadcast(b.pk)

        b.refresh_from_db()
        self.assertEqual(b.status, Broadcast.STATUS_SENT)
        self.assertEqual(b.recipient_count, 2)
        self.assertEqual(
            NotificationDelivery.objects.filter(
                dedupe_key__startswith=f'broadcast:{b.pk}:').count(),
            2,
        )

    def test_resending_does_not_duplicate(self):
        """The claim plus per-recipient dedupe keys make a re-run safe."""
        from .models import Broadcast
        from .tasks import send_broadcast
        b = self._broadcast(status=Broadcast.STATUS_SCHEDULED)
        send_broadcast(b.pk)
        before = len(mail.outbox)

        # A retry, or the scheduler firing while a manual send ran.
        result = send_broadcast(b.pk)
        self.assertEqual(result, {'skipped': 'not claimable'})
        self.assertEqual(len(mail.outbox), before)
        self.assertEqual(
            NotificationDelivery.objects.filter(
                dedupe_key__startswith=f'broadcast:{b.pk}:').count(),
            2,
        )

    def test_push_only_audience_never_emails(self):
        """Choosing push-only must override the kind's email policy."""
        from .models import Broadcast, PushSubscription
        from .tasks import send_broadcast
        PushSubscription.objects.create(
            user=self.a, endpoint='https://push.example/a',
            p256dh='x', auth='y', is_active=True)
        b = self._broadcast(audience=Broadcast.AUDIENCE_PUSH_ONLY,
                            kind='transactional',  # normally EMAIL_ALWAYS
                            status=Broadcast.STATUS_SCHEDULED)
        send_broadcast(b.pk)
        self.assertEqual(len(mail.outbox), 0)

    def test_one_bad_recipient_does_not_abandon_the_rest(self):
        from .models import Broadcast
        from .tasks import send_broadcast
        b = self._broadcast(status=Broadcast.STATUS_SCHEDULED)

        real = send_notification
        calls = {'n': 0}

        def flaky(user, **kwargs):
            calls['n'] += 1
            if calls['n'] == 1:
                raise RuntimeError('boom')
            return real(user, **kwargs)

        # tasks.py imports send_notification inside the function, so patch it
        # where it is defined rather than where it is used.
        with patch('notifications.services.send_notification', side_effect=flaky):
            send_broadcast(b.pk)

        b.refresh_from_db()
        self.assertEqual(b.status, Broadcast.STATUS_SENT)
        # The second recipient still got theirs.
        self.assertEqual(
            NotificationDelivery.objects.filter(
                dedupe_key__startswith=f'broadcast:{b.pk}:').count(),
            1,
        )

    def test_scheduler_only_queues_messages_that_are_due(self):
        from .models import Broadcast
        from .tasks import process_scheduled_broadcasts
        due = self._broadcast(
            status=Broadcast.STATUS_SCHEDULED,
            scheduled_for=timezone.now() - timezone.timedelta(minutes=1))
        self._broadcast(
            status=Broadcast.STATUS_SCHEDULED,
            scheduled_for=timezone.now() + timezone.timedelta(hours=2))
        self._broadcast(status=Broadcast.STATUS_DRAFT)

        with patch('notifications.tasks.send_broadcast.delay') as mock_delay:
            result = process_scheduled_broadcasts()

        self.assertEqual(result, {'queued': 1})
        mock_delay.assert_called_once_with(due.pk)

    def test_a_sent_message_cannot_be_resent_by_the_admin_action(self):
        from .models import Broadcast
        b = self._broadcast(status=Broadcast.STATUS_SENT)
        self.assertFalse(b.is_editable)
