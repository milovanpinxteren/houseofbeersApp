"""Campagne Studio tests: access control, builder round-trips, validation,
preview dispatch + stale gating, activation, monitor funnel, winner
fulfilment, draw dispatch and CSV export.

All Shopify calls, Celery dispatches and notification sends are mocked.
Agent B's tasks (draw_campaign_raffle, check_winner_redemptions) are patched
onto loyalty.tasks with create=True so these tests pass before that code
exists.
"""
import json
from datetime import datetime, timezone as dt_timezone
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from loyalty import tasks as loyalty_tasks
from loyalty.models import (
    Campaign, CampaignAward, CampaignPreview, CampaignProgress,
    CampaignRaffle, CampaignRaffleWinner, RaffleEntry,
)

User = get_user_model()

UTC = dt_timezone.utc

WINDOW_START = datetime(2026, 9, 1, 0, 0, tzinfo=UTC)
WINDOW_END = datetime(2026, 9, 30, 20, 0, tzinfo=UTC)

BACKFILL_TARGET = 'loyalty.studio_views.campaign_backfill'
NOTIFY_TARGET = 'notifications.services.send_notification'


# The production manifest storage needs collectstatic output; plain storage
# lets the admin-based templates render inside tests.
@override_settings(STORAGES={
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
})
class StudioTestCase(TestCase):

    def setUp(self):
        self.staff = User.objects.create_user(
            username='admin@houseofbeers.nl',
            email='admin@houseofbeers.nl',
            password='SuperSecret123!',
            is_staff=True,
        )
        self.client.force_login(self.staff)

    def make_user(self, email='drinker@example.com', **kwargs):
        return User.objects.create_user(
            username=email, email=email, password='SuperSecret123!',
            first_name=email.split('@')[0].title(), **kwargs
        )

    def make_campaign(self, **kwargs):
        defaults = {
            'name': 'Septemberactie',
            'status': 'draft',
            'action_type': 'points',
            'points_amount': 100,
            'window_start': WINDOW_START,
            'window_end': WINDOW_END,
        }
        defaults.update(kwargs)
        return Campaign.objects.create(**defaults)

    def make_raffle_campaign(self, **kwargs):
        raffle_kwargs = kwargs.pop('raffle_kwargs', {})
        kwargs.setdefault('action_type', 'raffle')
        kwargs.setdefault('points_amount', None)
        campaign = self.make_campaign(**kwargs)
        raffle_defaults = {'prize_name': 'Magnum fles', 'entry_mode': 'per_item'}
        raffle_defaults.update(raffle_kwargs)
        raffle = CampaignRaffle.objects.create(campaign=campaign, **raffle_defaults)
        return campaign, raffle

    def builder_post_data(self, **overrides):
        data = {
            'name': 'Oktoberfest campagne',
            'description': '',
            'action_type': 'points',
            'window_start': '2026-10-01T00:00',
            'window_end': '2026-10-31T23:59',
            'product_matchers': '[]',
            'min_distinct_products': '1',
            'min_total_quantity': '1',
            'min_order_value': '',
            'min_total_spend': '',
            'min_order_count': '',
            'min_points_balance': '',
            'registered_after': '',
            'points_amount': '100',
            'points_mode': 'fixed',
            'discount_type': '',
            'discount_value': '',
            'discount_product_gid': '',
            'discount_validity_days': '30',
            'notify_on_qualify': 'on',
            'qualify_title': '',
            'qualify_body': '',
            'rule_sentence': '',
        }
        data.update(overrides)
        return data


class StudioAccessTests(StudioTestCase):

    def test_anonymous_is_redirected_to_login(self):
        self.client.logout()
        response = self.client.get(reverse('studio:campaign_list'))
        self.assertEqual(response.status_code, 302)
        self.assertIn('login', response.url)

    def test_non_staff_is_rejected(self):
        user = self.make_user('regular@example.com')
        self.client.force_login(user)
        response = self.client.get(reverse('studio:campaign_list'))
        self.assertEqual(response.status_code, 302)
        self.assertIn('login', response.url)

    def test_non_staff_cannot_post_actions(self):
        campaign = self.make_campaign(status='previewed', preview_stale=False)
        user = self.make_user('regular2@example.com')
        self.client.force_login(user)
        response = self.client.post(reverse('studio:activate', args=[campaign.pk]))
        self.assertEqual(response.status_code, 302)
        self.assertIn('login', response.url)
        campaign.refresh_from_db()
        self.assertEqual(campaign.status, 'previewed')

    def test_staff_sees_list(self):
        self.make_campaign()
        response = self.client.get(reverse('studio:campaign_list'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Septemberactie')
        self.assertContains(response, 'Nieuwe campagne')


class BuilderTests(StudioTestCase):

    def test_create_points_campaign(self):
        matchers = [
            {'type': 'sku', 'value': 'BEER-A'},
            {'type': 'sku', 'value': 'BEER-B', 'label': 'Beer B'},
        ]
        response = self.client.post(
            reverse('studio:campaign_create'),
            self.builder_post_data(
                product_matchers=json.dumps(matchers),
                min_distinct_products='2',
            ),
        )
        self.assertEqual(response.status_code, 302)
        campaign = Campaign.objects.get(name='Oktoberfest campagne')
        self.assertEqual(campaign.status, 'draft')
        self.assertEqual(campaign.action_type, 'points')
        self.assertEqual(campaign.points_amount, 100)
        self.assertEqual(len(campaign.product_matchers), 2)
        self.assertEqual(campaign.product_matchers[0]['value'], 'BEER-A')
        self.assertEqual(campaign.min_distinct_products, 2)
        self.assertTrue(campaign.preview_stale)
        # Sentence auto-generated when left blank
        self.assertIn('Iedereen die', campaign.rule_sentence)

    def test_create_raffle_campaign_creates_raffle_row(self):
        response = self.client.post(
            reverse('studio:campaign_create'),
            self.builder_post_data(
                action_type='raffle',
                points_amount='',
                prize_name='Magnum fles',
                prize_description='Groot bier',
                prize_image_url='',
                num_winners='2',
                draw_at='2026-11-01T20:00',
                entry_mode='per_item',
                fulfillment_type='manual',
                send_reminder='on',
            ),
        )
        self.assertEqual(response.status_code, 302)
        campaign = Campaign.objects.get(name='Oktoberfest campagne')
        raffle = campaign.raffle
        self.assertEqual(raffle.prize_name, 'Magnum fles')
        self.assertEqual(raffle.num_winners, 2)
        self.assertEqual(raffle.entry_mode, 'per_item')
        self.assertTrue(raffle.send_reminder)
        self.assertIsNotNone(raffle.draw_at)

    def test_validation_errors(self):
        response = self.client.post(
            reverse('studio:campaign_create'),
            self.builder_post_data(name='', points_amount=''),
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Geef de campagne een naam.')
        self.assertContains(response, 'Vul het aantal punten in')
        self.assertEqual(Campaign.objects.count(), 0)

    def test_raffle_requires_prize_name(self):
        response = self.client.post(
            reverse('studio:campaign_create'),
            self.builder_post_data(
                action_type='raffle', points_amount='', prize_name='',
                num_winners='1', entry_mode='single', fulfillment_type='manual',
            ),
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Vul een prijsnaam in voor de loting.')

    def test_window_end_must_be_after_start(self):
        response = self.client.post(
            reverse('studio:campaign_create'),
            self.builder_post_data(
                window_start='2026-10-31T00:00', window_end='2026-10-01T00:00',
            ),
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'De einddatum moet na de startdatum liggen.')

    def test_min_distinct_cannot_exceed_matcher_count(self):
        response = self.client.post(
            reverse('studio:campaign_create'),
            self.builder_post_data(
                product_matchers=json.dumps([{'type': 'sku', 'value': 'A'}]),
                min_distinct_products='3',
            ),
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'kan niet groter zijn dan het aantal productregels')

    def test_discount_needs_value(self):
        response = self.client.post(
            reverse('studio:campaign_create'),
            self.builder_post_data(
                action_type='discount_code', points_amount='',
                discount_type='percentage', discount_value='',
            ),
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Vul de waarde van')

    def test_product_id_matcher_normalizes_gid_and_url(self):
        """A pasted GID or product-URL is reduced to the numeric id the
        matching engine compares against order line items."""
        matchers = [
            {'type': 'product_id', 'value': 'gid://shopify/Product/123'},
            {'type': 'product_id', 'value': 'https://admin.shopify.com/store/hob/products/456'},
            {'type': 'product_id', 'value': '789'},
        ]
        response = self.client.post(
            reverse('studio:campaign_create'),
            self.builder_post_data(product_matchers=json.dumps(matchers)),
        )
        self.assertEqual(response.status_code, 302)
        campaign = Campaign.objects.get(name='Oktoberfest campagne')
        self.assertEqual(
            [m['value'] for m in campaign.product_matchers],
            ['123', '456', '789'],
        )

    def test_product_id_matcher_rejects_non_product_value(self):
        matchers = [{'type': 'product_id', 'value': 'not-a-product'}]
        response = self.client.post(
            reverse('studio:campaign_create'),
            self.builder_post_data(product_matchers=json.dumps(matchers)),
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'is geen geldig product-ID')
        self.assertEqual(Campaign.objects.count(), 0)

    def test_free_product_accepts_plain_id(self):
        response = self.client.post(
            reverse('studio:campaign_create'),
            self.builder_post_data(
                action_type='discount_code', points_amount='',
                discount_type='free_product', discount_product_gid='123456789',
            ),
        )
        self.assertEqual(response.status_code, 302)
        campaign = Campaign.objects.get(name='Oktoberfest campagne')
        self.assertEqual(
            campaign.discount_product_gid, 'gid://shopify/Product/123456789'
        )

    def test_free_product_keeps_full_gid(self):
        response = self.client.post(
            reverse('studio:campaign_create'),
            self.builder_post_data(
                action_type='discount_code', points_amount='',
                discount_type='free_product',
                discount_product_gid='gid://shopify/Product/123456789',
            ),
        )
        self.assertEqual(response.status_code, 302)
        campaign = Campaign.objects.get(name='Oktoberfest campagne')
        self.assertEqual(
            campaign.discount_product_gid, 'gid://shopify/Product/123456789'
        )

    def test_free_product_rejects_invalid_reference(self):
        response = self.client.post(
            reverse('studio:campaign_create'),
            self.builder_post_data(
                action_type='discount_code', points_amount='',
                discount_type='free_product', discount_product_gid='nonsense',
            ),
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'is geen geldig product-ID of')
        self.assertEqual(Campaign.objects.count(), 0)

    def test_edit_round_trip_marks_preview_stale(self):
        campaign = self.make_campaign(status='previewed')
        Campaign.objects.filter(pk=campaign.pk).update(preview_stale=False)

        response = self.client.post(
            reverse('studio:campaign_edit', args=[campaign.pk]),
            self.builder_post_data(
                name='Septemberactie',
                product_matchers=json.dumps([{'type': 'tag', 'value': 'ipa'}]),
            ),
        )
        self.assertEqual(response.status_code, 302)
        campaign.refresh_from_db()
        self.assertEqual(campaign.product_matchers, [{'type': 'tag', 'value': 'ipa'}])
        self.assertTrue(campaign.preview_stale)

    def test_edit_form_prefilled(self):
        campaign = self.make_campaign(
            product_matchers=[{'type': 'sku', 'value': 'ABC'}],
        )
        response = self.client.get(reverse('studio:campaign_edit', args=[campaign.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Septemberactie')
        self.assertContains(response, 'ABC')

    def test_edit_blocked_when_completed(self):
        campaign = self.make_campaign(status='completed')
        response = self.client.get(reverse('studio:campaign_edit', args=[campaign.pk]))
        self.assertEqual(response.status_code, 302)
        response = self.client.post(
            reverse('studio:campaign_edit', args=[campaign.pk]),
            self.builder_post_data(name='Gewijzigd'),
        )
        self.assertEqual(response.status_code, 302)
        campaign.refresh_from_db()
        self.assertEqual(campaign.name, 'Septemberactie')

    def test_edit_active_campaign_shows_warning(self):
        campaign = self.make_campaign(status='active')
        response = self.client.get(reverse('studio:campaign_edit', args=[campaign.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'actief')

    def test_action_change_blocked_when_raffle_has_entries(self):
        campaign, raffle = self.make_raffle_campaign()
        RaffleEntry.objects.create(raffle=raffle, user=self.make_user())
        response = self.client.post(
            reverse('studio:campaign_edit', args=[campaign.pk]),
            self.builder_post_data(name='Septemberactie', action_type='points'),
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'er zijn al loten uitgedeeld')
        campaign.refresh_from_db()
        self.assertEqual(campaign.action_type, 'raffle')


class RuleSentenceEndpointTests(StudioTestCase):

    def test_sentence_for_unsaved_form(self):
        response = self.client.post(
            reverse('studio:rule_sentence'),
            self.builder_post_data(),
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn('Iedereen die', payload['sentence'])
        self.assertIn('krijgt 100 punten', payload['sentence'])

    def test_sentence_includes_raffle_prize(self):
        response = self.client.post(
            reverse('studio:rule_sentence'),
            self.builder_post_data(
                action_type='raffle', points_amount='',
                prize_name='Magnum fles', num_winners='1',
                entry_mode='per_item', fulfillment_type='manual',
            ),
        )
        payload = response.json()
        self.assertIn('doet mee in de loting voor Magnum fles', payload['sentence'])

    def test_sentence_needs_window(self):
        response = self.client.post(
            reverse('studio:rule_sentence'),
            self.builder_post_data(window_start='', window_end=''),
        )
        payload = response.json()
        self.assertEqual(payload['sentence'], '')
        self.assertIn('actieperiode', payload['error'])


class ProductSearchTests(StudioTestCase):

    @patch('users.services.shopify.ShopifyService._graphql_request')
    def test_search_returns_products(self, mock_graphql):
        mock_graphql.return_value = {
            'products': {'edges': [{
                'node': {
                    'id': 'gid://shopify/Product/123456',
                    'title': 'Westmalle Tripel',
                    'tags': ['tripel'],
                    'featuredImage': {'url': 'https://cdn/img.jpg'},
                    'variants': {'edges': [{'node': {'sku': 'WM-T', 'price': '4.50'}}]},
                }
            }]}
        }
        response = self.client.get(reverse('studio:product_search'), {'q': 'west'})
        self.assertEqual(response.status_code, 200)
        products = response.json()['products']
        self.assertEqual(len(products), 1)
        self.assertEqual(products[0]['id'], '123456')
        self.assertEqual(products[0]['title'], 'Westmalle Tripel')
        self.assertEqual(products[0]['sku'], 'WM-T')

    @patch('users.services.shopify.ShopifyService._graphql_request')
    def test_short_query_skips_shopify(self, mock_graphql):
        response = self.client.get(reverse('studio:product_search'), {'q': 'w'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['products'], [])
        mock_graphql.assert_not_called()

    @patch('users.services.shopify.ShopifyService._graphql_request')
    def test_shopify_failure_degrades(self, mock_graphql):
        mock_graphql.return_value = None
        response = self.client.get(reverse('studio:product_search'), {'q': 'west'})
        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()['products'], [])

    @patch('users.services.shopify.ShopifyService._graphql_request')
    def test_pasted_ids_resolve_via_id_lookup(self, mock_graphql):
        """A query of only product references (ids/GIDs, comma or space
        separated) is answered with a nodes lookup; unknown ids come back in
        'missing' so the picker can report them."""
        mock_graphql.return_value = {
            'nodes': [
                {
                    'id': 'gid://shopify/Product/111',
                    'title': 'Demo IPA',
                    'tags': [],
                    'featuredImage': None,
                    'variants': {'edges': []},
                },
                None,  # Shopify's shape for an id it doesn't know
            ]
        }
        response = self.client.get(
            reverse('studio:product_search'),
            {'q': '111, gid://shopify/Product/222'},
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['id_lookup'])
        self.assertEqual([p['id'] for p in data['products']], ['111'])
        self.assertEqual(data['products'][0]['title'], 'Demo IPA')
        self.assertEqual(data['missing'], ['222'])
        _query, variables = mock_graphql.call_args.args
        self.assertEqual(
            variables['ids'],
            ['gid://shopify/Product/111', 'gid://shopify/Product/222'],
        )

    @patch('users.services.shopify.ShopifyService._graphql_request')
    def test_mixed_query_stays_a_title_search(self, mock_graphql):
        """Digits mixed with words (e.g. 'tripel 8') is a title search, not
        an id lookup."""
        mock_graphql.return_value = {'products': {'edges': []}}
        response = self.client.get(
            reverse('studio:product_search'), {'q': 'tripel 8'}
        )
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('id_lookup', response.json())
        _query, variables = mock_graphql.call_args.args
        self.assertIn('query', variables)

    @patch('users.services.shopify.ShopifyService._graphql_request')
    def test_id_lookup_failure_degrades(self, mock_graphql):
        mock_graphql.return_value = None
        response = self.client.get(
            reverse('studio:product_search'), {'q': '123456'}
        )
        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()['products'], [])

    @patch('users.services.shopify.ShopifyService._graphql_request')
    def test_search_products_service_sanitizes_and_limits(self, mock_graphql):
        """The promoted ShopifyService.search_products strips quote characters
        (they would break out of the Shopify query string) and passes the
        limit through as the GraphQL page size."""
        from users.services import ShopifyService

        mock_graphql.return_value = {'products': {'edges': []}}
        result = ShopifyService().search_products('west"mal\'le', limit=15)
        self.assertEqual(result, [])

        _query, variables = mock_graphql.call_args.args
        self.assertEqual(variables['first'], 15)
        self.assertIn('westmalle', variables['query'])
        self.assertNotIn('"westmalle"', variables['query'])


class PreviewFlowTests(StudioTestCase):

    def test_run_preview_creates_row_and_dispatches(self):
        campaign = self.make_campaign()
        with patch(BACKFILL_TARGET) as mock_task:
            response = self.client.post(reverse('studio:run_preview', args=[campaign.pk]))
        self.assertEqual(response.status_code, 302)
        preview = campaign.previews.get()
        self.assertEqual(preview.status, 'pending')
        mock_task.delay.assert_called_once_with(campaign.id, preview_id=preview.id)

    def test_run_preview_synchronous_fallback_without_celery(self):
        campaign = self.make_campaign()
        with patch(BACKFILL_TARGET) as mock_task:
            mock_task.delay.side_effect = RuntimeError('broker down')
            response = self.client.post(reverse('studio:run_preview', args=[campaign.pk]))
        self.assertEqual(response.status_code, 302)
        preview = campaign.previews.get()
        mock_task.assert_called_once_with(campaign.id, preview_id=preview.id)

    def test_second_run_blocked_while_running(self):
        campaign = self.make_campaign()
        CampaignPreview.objects.create(campaign=campaign, status='running')
        with patch(BACKFILL_TARGET) as mock_task:
            response = self.client.post(reverse('studio:run_preview', args=[campaign.pk]))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(campaign.previews.count(), 1)
        mock_task.delay.assert_not_called()

    def test_status_endpoint(self):
        campaign = self.make_campaign()
        preview = CampaignPreview.objects.create(
            campaign=campaign, status='done',
            result={'qualified_count': 3, 'users': [], 'near_miss_count': 0,
                    'near_miss_users': [], 'orders_scanned': 12},
            finished_at=timezone.now(),
        )
        response = self.client.get(
            reverse('studio:preview_status', args=[campaign.pk]),
            {'preview_id': preview.id},
        )
        payload = response.json()
        self.assertEqual(payload['status'], 'done')
        self.assertEqual(payload['id'], preview.id)

    def test_preview_page_renders_result(self):
        campaign = self.make_campaign(status='previewed')
        Campaign.objects.filter(pk=campaign.pk).update(preview_stale=False)
        CampaignPreview.objects.create(
            campaign=campaign, status='done',
            result={
                'qualified_count': 1,
                'users': [{'user_id': 1, 'email': 'drinker@example.com',
                           'first_name': 'Drinker', 'tickets': 2,
                           'matched': ['Beer A']}],
                'near_miss_count': 1,
                'near_miss_users': [{'user_id': 2, 'email': 'almost@example.com',
                                     'first_name': 'Almost', 'tickets': 1,
                                     'matched': ['Beer B']}],
                'orders_scanned': 40,
            },
            finished_at=timezone.now(),
        )
        response = self.client.get(reverse('studio:campaign_preview', args=[campaign.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'drinker@example.com')
        self.assertContains(response, 'almost@example.com')
        self.assertContains(response, '40')
        self.assertContains(response, 'Activeer campagne')

    def test_stale_banner_and_activation_blocked_in_page(self):
        campaign = self.make_campaign(status='previewed', preview_stale=True)
        response = self.client.get(reverse('studio:campaign_preview', args=[campaign.pk]))
        self.assertContains(response, 'Preview verouderd')
        self.assertNotContains(response, 'Activeer campagne')


class ActivationTests(StudioTestCase):

    def test_activation_blocked_while_stale(self):
        campaign = self.make_campaign(status='previewed', preview_stale=True)
        with patch(BACKFILL_TARGET) as mock_task:
            response = self.client.post(reverse('studio:activate', args=[campaign.pk]))
        self.assertEqual(response.status_code, 302)
        campaign.refresh_from_db()
        self.assertEqual(campaign.status, 'previewed')
        mock_task.delay.assert_not_called()

    def test_activation_blocked_for_draft(self):
        campaign = self.make_campaign(status='draft')
        with patch(BACKFILL_TARGET) as mock_task:
            self.client.post(reverse('studio:activate', args=[campaign.pk]))
        campaign.refresh_from_db()
        self.assertEqual(campaign.status, 'draft')
        mock_task.delay.assert_not_called()

    def test_activation_flips_status_and_dispatches_live_backfill(self):
        campaign = self.make_campaign(status='previewed')
        Campaign.objects.filter(pk=campaign.pk).update(preview_stale=False)
        with patch(BACKFILL_TARGET) as mock_task:
            response = self.client.post(reverse('studio:activate', args=[campaign.pk]))
        self.assertEqual(response.status_code, 302)
        campaign.refresh_from_db()
        self.assertEqual(campaign.status, 'active')
        mock_task.delay.assert_called_once_with(campaign.id)

    def test_deactivate_completes_campaign(self):
        campaign = self.make_campaign(status='active')
        response = self.client.post(reverse('studio:deactivate', args=[campaign.pk]))
        self.assertEqual(response.status_code, 302)
        campaign.refresh_from_db()
        self.assertEqual(campaign.status, 'completed')

    def test_archive(self):
        campaign = self.make_campaign(status='completed')
        response = self.client.post(reverse('studio:archive', args=[campaign.pk]))
        self.assertEqual(response.status_code, 302)
        campaign.refresh_from_db()
        self.assertEqual(campaign.status, 'archived')


class TestSendTests(StudioTestCase):

    def test_test_send_requires_done_preview(self):
        campaign = self.make_campaign()
        with patch(NOTIFY_TARGET) as mock_notify:
            response = self.client.post(reverse('studio:test_send', args=[campaign.pk]))
        self.assertEqual(response.status_code, 302)
        mock_notify.assert_not_called()

    def test_test_send_goes_to_request_user_only(self):
        campaign, raffle = self.make_raffle_campaign(status='previewed')
        preview = CampaignPreview.objects.create(
            campaign=campaign, status='done', result={'qualified_count': 0},
            finished_at=timezone.now(),
        )
        with patch(NOTIFY_TARGET) as mock_notify:
            mock_notify.return_value = MagicMock(id=99)
            response = self.client.post(reverse('studio:test_send', args=[campaign.pk]))
        self.assertEqual(response.status_code, 302)
        mock_notify.assert_called_once()
        args, kwargs = mock_notify.call_args
        self.assertEqual(args[0], self.staff)
        self.assertEqual(kwargs['kind'], 'raffle')
        self.assertEqual(
            kwargs['dedupe_key'],
            f'campaign:{campaign.id}:test:{self.staff.id}:{preview.id}',
        )
        self.assertEqual(kwargs['data'], {'url': f'/raffle/{raffle.id}'})
        self.assertNotIn('url', kwargs)
        self.assertIn('Magnum fles', kwargs['body'])


class MonitorTests(StudioTestCase):

    def seed_raffle_monitor(self):
        campaign, raffle = self.make_raffle_campaign(status='active')
        alice = self.make_user('alice@example.com')
        bob = self.make_user('bob@example.com')
        carol = self.make_user('carol@example.com')

        RaffleEntry.objects.create(
            raffle=raffle, user=alice, ticket_count=3,
            matched_products=['Beer A', 'Beer B'],
            seen_at=timezone.now(), result_seen_at=timezone.now(),
        )
        RaffleEntry.objects.create(
            raffle=raffle, user=bob, ticket_count=1, seen_at=timezone.now(),
        )
        RaffleEntry.objects.create(raffle=raffle, user=carol, ticket_count=1)

        from notifications.models import NotificationDelivery
        NotificationDelivery.objects.create(
            user=alice, kind='announcement', title='t', body='b',
            dedupe_key=f'campaign:{campaign.id}:{alice.id}:qualified',
            push_status='sent', email_status='skipped',
        )
        NotificationDelivery.objects.create(
            user=bob, kind='announcement', title='t', body='b',
            dedupe_key=f'campaign:{campaign.id}:{bob.id}:qualified',
            push_status='failed', email_status='sent',
        )
        # Test sends never count in the funnel
        NotificationDelivery.objects.create(
            user=self.staff, kind='announcement', title='t', body='b',
            dedupe_key=f'campaign:{campaign.id}:test:{self.staff.id}:1',
            push_status='sent',
        )

        winner = CampaignRaffleWinner.objects.create(
            raffle=raffle, user=alice, fulfillment_status='manual_pending',
        )
        return campaign, raffle, winner

    def test_monitor_funnel_numbers(self):
        campaign, raffle, winner = self.seed_raffle_monitor()
        response = self.client.get(reverse('studio:campaign_monitor', args=[campaign.pk]))
        self.assertEqual(response.status_code, 200)

        funnel = {step['key']: step for step in response.context['funnel']}
        self.assertEqual(funnel['entered']['count'], 3)
        self.assertEqual(funnel['notified']['count'], 2)
        self.assertIn('1 push', funnel['notified']['sub'])
        self.assertIn('1 e-mail', funnel['notified']['sub'])
        self.assertEqual(funnel['opened']['count'], 2)
        self.assertEqual(funnel['watched']['count'], 1)
        self.assertEqual(funnel['redeemed']['count'], 0)

        self.assertContains(response, 'alice@example.com')
        self.assertContains(response, 'carol@example.com')

    def test_monitor_non_raffle_campaign(self):
        campaign = self.make_campaign(status='active')
        user = self.make_user('points@example.com')
        CampaignProgress.objects.create(
            campaign=campaign, user=user, qualified_at=timezone.now(),
            data={'matched_products': ['Beer A']},
        )
        CampaignAward.objects.create(campaign=campaign, user=user, points_awarded=100)
        response = self.client.get(reverse('studio:campaign_monitor', args=[campaign.pk]))
        self.assertEqual(response.status_code, 200)
        funnel = {step['key']: step for step in response.context['funnel']}
        self.assertEqual(funnel['entered']['count'], 1)
        self.assertNotIn('opened', funnel)
        self.assertContains(response, 'points@example.com')
        self.assertContains(response, '100 punten')

    def test_manual_fulfill_toggle(self):
        campaign, raffle, winner = self.seed_raffle_monitor()
        response = self.client.post(
            reverse('studio:toggle_fulfilled', args=[campaign.pk, winner.pk])
        )
        self.assertEqual(response.status_code, 302)
        winner.refresh_from_db()
        self.assertEqual(winner.fulfillment_status, 'fulfilled')
        self.assertIsNotNone(winner.fulfilled_at)

        self.client.post(reverse('studio:toggle_fulfilled', args=[campaign.pk, winner.pk]))
        winner.refresh_from_db()
        self.assertEqual(winner.fulfillment_status, 'manual_pending')
        self.assertIsNone(winner.fulfilled_at)


class DrawAndRedemptionTests(StudioTestCase):

    def test_draw_now_dispatches_agent_b_task(self):
        campaign, raffle = self.make_raffle_campaign(status='active')
        mock_task = MagicMock()
        with patch.object(loyalty_tasks, 'draw_campaign_raffle', mock_task, create=True):
            response = self.client.post(reverse('studio:draw_now', args=[campaign.pk]))
        self.assertEqual(response.status_code, 302)
        mock_task.delay.assert_called_once_with(raffle.id)

    def test_draw_now_sync_fallback(self):
        campaign, raffle = self.make_raffle_campaign(status='active')
        mock_task = MagicMock()
        mock_task.delay.side_effect = RuntimeError('broker down')
        with patch.object(loyalty_tasks, 'draw_campaign_raffle', mock_task, create=True):
            self.client.post(reverse('studio:draw_now', args=[campaign.pk]))
        mock_task.assert_called_once_with(raffle.id)

    def test_draw_now_blocked_when_already_drawn(self):
        campaign, raffle = self.make_raffle_campaign(
            status='active', raffle_kwargs={'status': 'drawn'},
        )
        mock_task = MagicMock()
        with patch.object(loyalty_tasks, 'draw_campaign_raffle', mock_task, create=True):
            self.client.post(reverse('studio:draw_now', args=[campaign.pk]))
        mock_task.delay.assert_not_called()

    def test_draw_now_graceful_when_task_missing(self):
        # Simulate Agent B's task not existing yet (the view getattr-guards).
        campaign, raffle = self.make_raffle_campaign(status='active')
        with patch.object(loyalty_tasks, 'draw_campaign_raffle', None, create=True):
            response = self.client.post(reverse('studio:draw_now', args=[campaign.pk]))
        self.assertEqual(response.status_code, 302)
        raffle.refresh_from_db()
        self.assertEqual(raffle.status, 'open')

    def test_check_redemptions_dispatches(self):
        campaign, _ = self.make_raffle_campaign(status='completed')
        mock_task = MagicMock()
        with patch.object(loyalty_tasks, 'check_winner_redemptions', mock_task, create=True):
            response = self.client.post(
                reverse('studio:check_redemptions', args=[campaign.pk])
            )
        self.assertEqual(response.status_code, 302)
        mock_task.delay.assert_called_once_with()


class CsvExportTests(StudioTestCase):

    def test_raffle_csv(self):
        campaign, raffle = self.make_raffle_campaign(status='active')
        user = self.make_user('csv@example.com')
        RaffleEntry.objects.create(
            raffle=raffle, user=user, ticket_count=4,
            matched_products=['Beer A'], seen_at=timezone.now(),
        )
        CampaignRaffleWinner.objects.create(
            raffle=raffle, user=user, prize_code='WIN-ABC123',
            fulfillment_status='code_issued',
        )
        response = self.client.get(reverse('studio:entrants_csv', args=[campaign.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertIn('text/csv', response['Content-Type'])
        content = response.content.decode('utf-8')
        self.assertIn('csv@example.com', content)
        self.assertIn('4', content)
        self.assertIn('WIN-ABC123', content)
        self.assertIn('loten', content)

    def test_points_csv(self):
        campaign = self.make_campaign(status='active')
        user = self.make_user('csv2@example.com')
        CampaignProgress.objects.create(
            campaign=campaign, user=user, qualified_at=timezone.now(),
            data={'matched_products': ['Beer B']},
        )
        CampaignAward.objects.create(campaign=campaign, user=user, points_awarded=50)
        response = self.client.get(reverse('studio:entrants_csv', args=[campaign.pk]))
        content = response.content.decode('utf-8')
        self.assertIn('csv2@example.com', content)
        self.assertIn('50', content)
        self.assertIn('punten', content)
