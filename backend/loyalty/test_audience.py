"""Audience selection tests: filter queryset, the orders-mode gate, the
audience-mode backfill, raffle visibility and the Studio endpoints."""
from datetime import date, datetime, timedelta, timezone as dt_timezone
from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from loyalty.models import (
    Campaign, CampaignAward, CampaignProgress, CampaignRaffle, ProcessedOrder,
    RaffleEntry,
)
from loyalty.services.audience import (
    audience_user_ids, describe_filters, filter_queryset, has_audience,
    user_in_audience,
)
from loyalty.services.campaigns import (
    apply_order_to_campaigns, build_rule_sentence, run_backfill,
)
from loyalty.tasks import refresh_campaign_snapshots

User = get_user_model()

UTC = dt_timezone.utc
WINDOW_START = datetime(2026, 8, 1, 0, 0, tzinfo=UTC)
WINDOW_END = datetime(2026, 12, 31, 0, 0, tzinfo=UTC)

NOTIFY_TARGET = 'notifications.services.send_notification'


def order(order_id, created_at='2026-08-20T12:00:00+00:00', total='25.00'):
    return {
        'id': order_id,
        'name': f'#{order_id}',
        'created_at': created_at,
        'financial_status': 'paid',
        'total_price': total,
        'line_items': [{'sku': 'A', 'title': 'Beer A', 'quantity': 1,
                        'product_id': 1000}],
    }


class AudienceTestCase(TestCase):

    def make_user(self, email, **kwargs):
        return User.objects.create_user(
            username=email, email=email, password='SuperSecret123!',
            first_name=email.split('@')[0].title(), **kwargs,
        )

    def make_campaign(self, **kwargs):
        defaults = {
            'name': 'Doelgroepactie',
            'status': 'active',
            'action_type': 'points',
            'points_amount': 100,
            'window_start': WINDOW_START,
            'window_end': WINDOW_END,
        }
        defaults.update(kwargs)
        return Campaign.objects.create(**defaults)


class FilterQuerysetTests(AudienceTestCase):

    def test_no_filters_returns_none(self):
        self.assertIsNone(filter_queryset({}))
        self.assertIsNone(filter_queryset(None))
        self.assertIsNone(filter_queryset({'min_age': 0}))

    def test_min_age(self):
        today = timezone.localdate()
        old = self.make_user('old@example.com',
                             birthdate=today.replace(year=today.year - 30))
        young = self.make_user('young@example.com',
                               birthdate=today.replace(year=today.year - 20))
        self.make_user('unknown@example.com')  # no birthdate: never matches

        qs = filter_queryset({'min_age': 25})
        self.assertEqual(set(qs.values_list('email', flat=True)),
                         {'old@example.com'})
        self.assertIn(young, filter_queryset({'min_age': 18}))

    def test_birthday_month(self):
        september = self.make_user('sep@example.com',
                                   birthdate=date(1990, 9, 15))
        self.make_user('may@example.com', birthdate=date(1990, 5, 15))

        qs = filter_queryset({'birthday_month': 9})
        self.assertEqual(list(qs), [september])

    def test_min_app_age_days(self):
        veteran = self.make_user('veteran@example.com')
        User.objects.filter(pk=veteran.pk).update(
            date_joined=timezone.now() - timedelta(days=100)
        )
        self.make_user('fresh@example.com')  # joined just now

        qs = filter_queryset({'min_app_age_days': 30})
        self.assertEqual(set(qs.values_list('email', flat=True)),
                         {'veteran@example.com'})

    def test_min_lifetime_orders(self):
        buyer = self.make_user('buyer@example.com')
        browser = self.make_user('browser@example.com')
        for i in range(3):
            ProcessedOrder.objects.create(
                user=buyer, shopify_order_id=str(9000 + i),
                shopify_order_name=f'#{9000 + i}',
                order_total=Decimal('10.00'), points_awarded=0,
            )

        qs = filter_queryset({'min_lifetime_orders': 2})
        self.assertEqual(list(qs), [buyer])
        self.assertNotIn(browser, qs)

    def test_active_within_days(self):
        recent = self.make_user('recent@example.com',
                                last_active_at=timezone.now() - timedelta(days=5))
        self.make_user('dormant@example.com',
                       last_active_at=timezone.now() - timedelta(days=120))
        self.make_user('never@example.com')  # last_active_at null

        qs = filter_queryset({'active_within_days': 30})
        self.assertEqual(list(qs), [recent])

    def test_filters_combine_with_and(self):
        match = self.make_user('match@example.com', birthdate=date(1990, 9, 1))
        self.make_user('wrongmonth@example.com', birthdate=date(1990, 5, 1))
        qs = filter_queryset({'min_age': 18, 'birthday_month': 9})
        self.assertEqual(list(qs), [match])

    def test_inactive_users_excluded(self):
        user = self.make_user('gone@example.com', birthdate=date(1990, 9, 1))
        user.is_active = False
        user.save(update_fields=['is_active'])
        self.assertEqual(list(filter_queryset({'birthday_month': 9})), [])


class AudienceMembershipTests(AudienceTestCase):

    def test_no_audience_means_everyone(self):
        campaign = self.make_campaign()
        user = self.make_user('anyone@example.com')
        self.assertFalse(has_audience(campaign))
        self.assertIsNone(audience_user_ids(campaign))
        self.assertTrue(user_in_audience(campaign, user))

    def test_manual_union_filters(self):
        by_filter = self.make_user('filter@example.com',
                                   birthdate=date(1990, 9, 1))
        by_hand = self.make_user('hand@example.com')
        outsider = self.make_user('outsider@example.com')
        campaign = self.make_campaign(
            audience_filters={'birthday_month': 9},
            manual_user_ids=[by_hand.id],
        )

        self.assertEqual(audience_user_ids(campaign),
                         {by_filter.id, by_hand.id})
        self.assertTrue(user_in_audience(campaign, by_filter))
        self.assertTrue(user_in_audience(campaign, by_hand))
        self.assertFalse(user_in_audience(campaign, outsider))

    def test_manual_only_audience(self):
        picked = self.make_user('picked@example.com')
        other = self.make_user('other@example.com')
        campaign = self.make_campaign(manual_user_ids=[picked.id])
        self.assertTrue(user_in_audience(campaign, picked))
        self.assertFalse(user_in_audience(campaign, other))


class OrdersModeGateTests(AudienceTestCase):
    """In orders mode a configured audience gates qualification."""

    def test_outside_audience_never_qualifies(self):
        campaign = self.make_campaign(audience_filters={'birthday_month': 9})
        user = self.make_user('wrongmonth@example.com',
                              birthdate=date(1990, 5, 1))

        with patch(NOTIFY_TARGET) as mock_notify:
            mock_notify.return_value = MagicMock(id=1)
            apply_order_to_campaigns(user, order(1))

        progress = CampaignProgress.objects.get(campaign=campaign, user=user)
        self.assertIsNone(progress.qualified_at)
        self.assertFalse(
            CampaignAward.objects.filter(campaign=campaign, user=user).exists()
        )

    def test_inside_audience_qualifies(self):
        campaign = self.make_campaign(audience_filters={'birthday_month': 9})
        user = self.make_user('sep@example.com', birthdate=date(1990, 9, 1))

        with patch(NOTIFY_TARGET) as mock_notify:
            mock_notify.return_value = MagicMock(id=1)
            apply_order_to_campaigns(user, order(2))

        progress = CampaignProgress.objects.get(campaign=campaign, user=user)
        self.assertIsNotNone(progress.qualified_at)
        award = CampaignAward.objects.get(campaign=campaign, user=user)
        self.assertEqual(award.points_awarded, 100)


class AudienceModeBackfillTests(AudienceTestCase):

    def make_audience_campaign(self, **kwargs):
        kwargs.setdefault('audience_mode', 'audience')
        kwargs.setdefault('audience_filters', {'birthday_month': 9})
        return self.make_campaign(**kwargs)

    def test_order_hook_skips_audience_campaigns(self):
        campaign = self.make_audience_campaign()
        user = self.make_user('sep@example.com', birthdate=date(1990, 9, 1))
        with patch(NOTIFY_TARGET):
            apply_order_to_campaigns(user, order(3))
        self.assertFalse(
            CampaignProgress.objects.filter(campaign=campaign, user=user).exists()
        )

    def test_dry_run_lists_audience_without_writes(self):
        campaign = self.make_audience_campaign()
        member = self.make_user('sep@example.com', birthdate=date(1990, 9, 1))
        self.make_user('may@example.com', birthdate=date(1990, 5, 1))

        result = run_backfill(campaign, dry_run=True)

        self.assertEqual(result['qualified_count'], 1)
        self.assertEqual(result['users'][0]['user_id'], member.id)
        self.assertEqual(result['orders_scanned'], 0)
        self.assertEqual(result['near_miss_count'], 0)
        self.assertFalse(CampaignProgress.objects.exists())

    def test_live_run_qualifies_and_is_idempotent(self):
        campaign = self.make_audience_campaign(
            action_type='raffle', points_amount=None,
        )
        raffle = CampaignRaffle.objects.create(
            campaign=campaign, prize_name='Fust bier',
        )
        member = self.make_user('sep@example.com', birthdate=date(1990, 9, 1))
        picked = self.make_user('picked@example.com')
        campaign.manual_user_ids = [picked.id]
        campaign.save()

        with patch(NOTIFY_TARGET) as mock_notify:
            mock_notify.return_value = MagicMock(id=7)
            first = run_backfill(campaign, dry_run=False)
            second = run_backfill(campaign, dry_run=False)

        self.assertEqual(first['qualified_count'], 2)
        self.assertEqual(first['newly_qualified'], 2)
        self.assertEqual(second['newly_qualified'], 0)
        entries = RaffleEntry.objects.filter(raffle=raffle)
        self.assertEqual(entries.count(), 2)
        self.assertEqual({e.ticket_count for e in entries}, {1})
        self.assertEqual({e.user_id for e in entries}, {member.id, picked.id})

    def test_nightly_refresh_adds_new_matches(self):
        campaign = self.make_audience_campaign()
        with patch(NOTIFY_TARGET) as mock_notify:
            mock_notify.return_value = MagicMock(id=7)
            run_backfill(campaign, dry_run=False)
            newcomer = self.make_user('newsep@example.com',
                                      birthdate=date(1995, 9, 3))
            refresh_campaign_snapshots()

        progress = CampaignProgress.objects.get(campaign=campaign, user=newcomer)
        self.assertIsNotNone(progress.qualified_at)


class AudienceRuleSentenceTests(AudienceTestCase):

    def test_filtered_audience_sentence(self):
        campaign = self.make_campaign(
            audience_mode='audience',
            audience_filters={'birthday_month': 9, 'min_age': 21},
        )
        sentence = build_rule_sentence(campaign)
        self.assertIn('Ieder lid dat', sentence)
        self.assertIn('minstens 21 jaar oud is', sentence)
        self.assertIn('in september jarig is', sentence)
        self.assertIn('krijgt 100 punten', sentence)

    def test_manual_only_sentence(self):
        campaign = self.make_campaign(
            audience_mode='audience', manual_user_ids=[1, 2],
        )
        sentence = build_rule_sentence(campaign)
        self.assertIn('geselecteerde groep leden', sentence)

    def test_orders_mode_gate_mentioned(self):
        campaign = self.make_campaign(
            audience_filters={'birthday_month': 9},
        )
        sentence = build_rule_sentence(campaign)
        self.assertIn('Iedereen die', sentence)
        self.assertIn('Alleen voor leden die in september jarig is', sentence)

    def test_describe_filters_all_keys(self):
        campaign = self.make_campaign(audience_filters={
            'min_age': 21, 'birthday_month': 2, 'min_app_age_days': 30,
            'min_lifetime_orders': 3, 'active_within_days': 90,
        })
        parts = describe_filters(campaign)
        self.assertEqual(len(parts), 5)


class AudienceRaffleVisibilityTests(AudienceTestCase):

    def setUp(self):
        self.member = self.make_user('member@example.com')
        self.outsider = self.make_user('outsider@example.com')
        self.campaign = self.make_campaign(
            action_type='raffle', points_amount=None,
            audience_mode='audience',
            manual_user_ids=[self.member.id],
        )
        self.raffle = CampaignRaffle.objects.create(
            campaign=self.campaign, prize_name='Bierpakket',
        )
        RaffleEntry.objects.create(raffle=self.raffle, user=self.member)

    def get_raffles(self, user):
        from rest_framework.test import APIClient
        client = APIClient()
        client.force_authenticate(user=user)
        response = client.get('/api/loyalty/raffles/')
        self.assertEqual(response.status_code, 200)
        return response.json()['raffles']

    def test_entrant_sees_audience_raffle(self):
        raffles = self.get_raffles(self.member)
        self.assertEqual([r['id'] for r in raffles], [self.raffle.id])

    def test_outsider_gets_no_teaser(self):
        self.assertEqual(self.get_raffles(self.outsider), [])

    def test_orders_mode_raffle_still_teases(self):
        self.campaign.audience_mode = 'orders'
        self.campaign.save()
        raffles = self.get_raffles(self.outsider)
        self.assertEqual([r['id'] for r in raffles], [self.raffle.id])
        self.assertFalse(raffles[0]['entered'])


# Plain static storage: the manifest storage needs collectstatic output,
# which tests don't have (same override as test_studio.py).
@override_settings(STORAGES={
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
})
class StudioAudienceTests(AudienceTestCase):

    def setUp(self):
        self.admin = User.objects.create_superuser(
            username='admin@example.com', email='admin@example.com',
            password='AdminSecret123!',
        )
        self.client.force_login(self.admin)

    def test_user_search(self):
        self.make_user('zoekmij@example.com')
        response = self.client.get(
            reverse('studio:user_search'), {'q': 'zoekmij'}
        )
        self.assertEqual(response.status_code, 200)
        users = response.json()['users']
        self.assertEqual(len(users), 1)
        self.assertEqual(users[0]['email'], 'zoekmij@example.com')

    def _builder_post(self, **overrides):
        data = {
            'name': 'Verjaardagsloterij',
            'action_type': 'raffle',
            'window_start': '2026-09-01T00:00',
            'window_end': '2026-09-30T23:59',
            'audience_mode': 'audience',
            'aud_birthday_month': '9',
            'manual_users': '[]',
            'product_matchers': '[]',
            'min_distinct_products': '1',
            'min_total_quantity': '1',
            'prize_name': 'Bierpakket',
            'num_winners': '1',
            'entry_mode': 'per_item',
            'fulfillment_type': 'manual',
            'notify_on_qualify': 'on',
        }
        data.update(overrides)
        return data

    def test_builder_saves_audience_campaign(self):
        response = self.client.post(
            reverse('studio:campaign_create'), self._builder_post()
        )
        self.assertEqual(response.status_code, 302)
        campaign = Campaign.objects.get(name='Verjaardagsloterij')
        self.assertEqual(campaign.audience_mode, 'audience')
        self.assertEqual(campaign.audience_filters, {'birthday_month': 9})
        # Selection-based entry is forced to one ticket each.
        self.assertEqual(campaign.raffle.entry_mode, 'single')
        self.assertIn('jarig', campaign.rule_sentence)

    def test_builder_rejects_empty_audience(self):
        response = self.client.post(
            reverse('studio:campaign_create'),
            self._builder_post(aud_birthday_month='', manual_users='[]'),
        )
        self.assertEqual(response.status_code, 200)  # re-rendered with errors
        self.assertFalse(Campaign.objects.exists())
        self.assertContains(response, 'doelgroepfilter')

    def test_builder_saves_manual_users(self):
        picked = self.make_user('picked@example.com')
        response = self.client.post(
            reverse('studio:campaign_create'),
            self._builder_post(
                aud_birthday_month='',
                manual_users=f'[{{"id": {picked.id}, "label": "picked@example.com"}}]',
            ),
        )
        self.assertEqual(response.status_code, 302)
        campaign = Campaign.objects.get(name='Verjaardagsloterij')
        self.assertEqual(campaign.manual_user_ids, [picked.id])

    def test_audience_count_endpoint(self):
        self.make_user('sep@example.com', birthdate=date(1990, 9, 1))
        self.make_user('may@example.com', birthdate=date(1990, 5, 1))
        response = self.client.post(
            reverse('studio:audience_count'), self._builder_post()
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload['restricted'])
        self.assertEqual(payload['count'], 1)

    def test_audience_count_unrestricted(self):
        response = self.client.post(
            reverse('studio:audience_count'),
            self._builder_post(audience_mode='orders', aud_birthday_month=''),
        )
        payload = response.json()
        self.assertFalse(payload['restricted'])
        self.assertIsNone(payload['count'])
