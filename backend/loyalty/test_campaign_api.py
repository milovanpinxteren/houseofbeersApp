"""Tests for the in-app campaign surface (/api/loyalty/campaigns/), the
qualify-email fallback for members without push, and the ended-window
activation guard."""
from datetime import timedelta
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from loyalty.models import Campaign, CampaignAward, CampaignProgress
from loyalty.test_campaigns import (
    NOTIFY_TARGET, CampaignTestCase, order,
)

User = get_user_model()


class CampaignsListViewTest(CampaignTestCase):

    def setUp(self):
        self.user = self.make_user()
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def get(self):
        return self.client.get('/api/loyalty/campaigns/')

    def qualify(self, campaign, user, points=0, code=''):
        progress = CampaignProgress.objects.create(
            campaign=campaign, user=user, qualified_at=timezone.now(),
        )
        award = CampaignAward.objects.create(
            campaign=campaign, user=user,
            points_awarded=points, discount_code=code,
        )
        return progress, award

    def test_requires_auth(self):
        self.client.force_authenticate(user=None)
        self.assertEqual(self.get().status_code, 401)

    def test_active_points_campaign_shows_as_teaser(self):
        campaign = self.make_campaign(rule_sentence='Koop bier, krijg punten.')
        data = self.get().json()
        self.assertEqual(len(data['campaigns']), 1)
        row = data['campaigns'][0]
        self.assertEqual(row['id'], campaign.id)
        self.assertEqual(row['action_type'], 'points')
        self.assertFalse(row['qualified'])
        self.assertEqual(row['points_awarded'], 0)
        self.assertIsNone(row['discount_code'])
        self.assertEqual(row['rule_sentence'], 'Koop bier, krijg punten.')

    def test_qualified_state_carries_award(self):
        campaign = self.make_campaign()
        self.qualify(campaign, self.user, points=100)
        row = self.get().json()['campaigns'][0]
        self.assertTrue(row['qualified'])
        self.assertEqual(row['points_awarded'], 100)

    def test_raffle_campaigns_excluded(self):
        self.make_raffle_campaign()
        self.assertEqual(self.get().json()['campaigns'], [])

    def test_draft_and_completed_hidden_without_award(self):
        self.make_campaign(status='draft')
        self.make_campaign(status='completed')
        self.assertEqual(self.get().json()['campaigns'], [])

    def test_completed_campaign_with_my_code_stays_visible(self):
        campaign = self.make_campaign(
            status='completed', action_type='discount_code',
            points_amount=None, discount_type='percentage',
            discount_value=10, discount_validity_days=30,
        )
        self.qualify(campaign, self.user, code='HOB-TESTCODE')
        rows = self.get().json()['campaigns']
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['discount_code'], 'HOB-TESTCODE')
        self.assertIsNotNone(rows[0]['discount_expires_at'])

    def test_completed_campaign_with_someone_elses_code_hidden(self):
        campaign = self.make_campaign(
            status='completed', action_type='discount_code',
            points_amount=None,
        )
        other = self.make_user('other@example.com', shopify_customer_id='222')
        self.qualify(campaign, other, code='HOB-OTHER')
        self.assertEqual(self.get().json()['campaigns'], [])

    def test_completed_campaign_visible_despite_another_users_empty_code(self):
        """Someone else's failed mint (empty code) must not hide my code."""
        campaign = self.make_campaign(
            status='completed', action_type='discount_code',
            points_amount=None, discount_type='percentage',
            discount_value=10, discount_validity_days=30,
        )
        self.qualify(campaign, self.user, code='HOB-MINE')
        other = self.make_user('failed@example.com', shopify_customer_id='444')
        self.qualify(campaign, other, code='')

        rows = self.get().json()['campaigns']
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['discount_code'], 'HOB-MINE')

    def test_audience_mode_hidden_from_non_members(self):
        self.make_campaign(
            audience_mode='audience',
            manual_user_ids=[999999],
        )
        self.assertEqual(self.get().json()['campaigns'], [])

    def test_audience_mode_visible_once_qualified(self):
        campaign = self.make_campaign(
            audience_mode='audience',
            manual_user_ids=[self.user.id],
        )
        self.qualify(campaign, self.user, points=10)
        rows = self.get().json()['campaigns']
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0]['qualified'])

    def test_orders_mode_audience_gate_hides_teaser_from_outsiders(self):
        other = self.make_user('gated@example.com', shopify_customer_id='333')
        self.make_campaign(manual_user_ids=[other.id])
        self.assertEqual(self.get().json()['campaigns'], [])

    def test_orders_mode_audience_gate_teases_members(self):
        self.make_campaign(manual_user_ids=[self.user.id])
        self.assertEqual(len(self.get().json()['campaigns']), 1)


class QualifyEmailFallbackTest(CampaignTestCase):
    """The qualify notification emails members without push — only when the
    campaign opts in, and never for members who do have push."""

    def qualify_via_order(self, campaign, user):
        with patch(NOTIFY_TARGET) as mock_notify:
            mock_notify.return_value = MagicMock(id=42)
            from loyalty.services.campaigns import apply_order_to_campaigns
            apply_order_to_campaigns(user, order(9001))
        return mock_notify

    def test_fallback_off_keeps_kind_default(self):
        campaign = self.make_campaign(qualify_email_fallback=False)
        user = self.make_user()
        mock_notify = self.qualify_via_order(campaign, user)
        self.assertEqual(mock_notify.call_count, 1)
        self.assertIsNone(mock_notify.call_args.kwargs['email_policy'])

    def test_fallback_on_without_push_emails_always(self):
        campaign = self.make_campaign(qualify_email_fallback=True)
        user = self.make_user()
        mock_notify = self.qualify_via_order(campaign, user)
        self.assertEqual(mock_notify.call_args.kwargs['email_policy'], 'always')

    def test_fallback_on_with_active_push_keeps_kind_default(self):
        from notifications.models import PushSubscription
        campaign = self.make_campaign(qualify_email_fallback=True)
        user = self.make_user()
        PushSubscription.objects.create(
            user=user, endpoint='https://push.example/x', p256dh='k', auth='a',
        )
        mock_notify = self.qualify_via_order(campaign, user)
        self.assertIsNone(mock_notify.call_args.kwargs['email_policy'])

    def test_fallback_on_with_only_inactive_push_emails_always(self):
        from notifications.models import PushSubscription
        campaign = self.make_campaign(qualify_email_fallback=True)
        user = self.make_user()
        PushSubscription.objects.create(
            user=user, endpoint='https://push.example/dead', p256dh='k',
            auth='a', is_active=False,
        )
        mock_notify = self.qualify_via_order(campaign, user)
        self.assertEqual(mock_notify.call_args.kwargs['email_policy'], 'always')


# Plain static storage so the admin-based templates render inside tests
# (the production manifest storage needs collectstatic output).
@override_settings(STORAGES={
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
})
class EndedWindowActivationTest(CampaignTestCase):
    """Activation is blocked once window_end has passed."""

    def setUp(self):
        self.admin = User.objects.create_user(
            username='admin@houseofbeers.nl',
            email='admin@houseofbeers.nl',
            password='SuperSecret123!',
            is_staff=True,
        )
        self.client.force_login(self.admin)

    def make_previewed(self, **kwargs):
        kwargs.setdefault('status', 'previewed')
        campaign = self.make_campaign(**kwargs)
        Campaign.objects.filter(pk=campaign.pk).update(preview_stale=False)
        campaign.refresh_from_db()
        return campaign

    def test_activation_blocked_when_window_ended(self):
        campaign = self.make_previewed(
            window_start=timezone.now() - timedelta(days=30),
            window_end=timezone.now() - timedelta(hours=1),
        )
        response = self.client.post(f'/admin/campaign-studio/{campaign.pk}/activate/')
        self.assertEqual(response.status_code, 302)
        campaign.refresh_from_db()
        self.assertEqual(campaign.status, 'previewed')

    def test_activation_allowed_while_window_open(self):
        campaign = self.make_previewed(
            window_start=timezone.now() - timedelta(days=1),
            window_end=timezone.now() + timedelta(days=7),
        )
        with patch('loyalty.studio_views._dispatch_task', return_value='queued'):
            response = self.client.post(f'/admin/campaign-studio/{campaign.pk}/activate/')
        self.assertEqual(response.status_code, 302)
        campaign.refresh_from_db()
        self.assertEqual(campaign.status, 'active')

    def test_preview_page_lists_ended_window_blocker(self):
        campaign = self.make_previewed(
            window_start=timezone.now() - timedelta(days=30),
            window_end=timezone.now() - timedelta(hours=1),
        )
        response = self.client.get(f'/admin/campaign-studio/{campaign.pk}/')
        self.assertContains(response, 'De actieperiode is al voorbij')
