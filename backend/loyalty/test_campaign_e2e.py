"""End-to-end campaign & raffle test (Agent E, per CAMPAIGN_CONTRACT.md).

One story, front to back: a staff member builds a 2-of-3 raffle campaign in
the Studio, previews it against mocked shop orders, activates it (live
backfill through the synchronous Celery fallback), a later order arrives via
the points-sync path and qualifies the near-miss user, the raffle is drawn
via the task, and both winner and loser see the frozen API payloads. Seen
endpoints, Studio funnel numbers and the CSV export close the loop.

No network: Shopify order scans and discount creation are mocked; the
notifications outbox runs for real (push skips - no VAPID keys in tests -
and email lands in Django's locmem outbox), so delivery rows and funnel
numbers are the production code path.
"""
from datetime import timedelta
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from loyalty.models import (
    Campaign, CampaignAward, CampaignPreview, CampaignProgress,
    CampaignRaffle, CampaignRaffleWinner, PointsBalance, PointsRule,
    RaffleEntry,
)
from loyalty.services import LoyaltyService
from loyalty.tasks import campaign_backfill, draw_campaign_raffle
from notifications.models import NotificationDelivery

User = get_user_model()

SHOP_ORDERS_TARGET = 'users.services.shopify.ShopifyService.get_shop_orders_in_window'
DISCOUNT_TARGET = 'loyalty.services.discounts.create_discount_code'
STUDIO_BACKFILL_TARGET = 'loyalty.studio_views.campaign_backfill'

NOW = timezone.now()
WINDOW_START = NOW - timedelta(days=10)
WINDOW_END = NOW + timedelta(days=10)


def shop_order(order_id, customer_id, skus, days_ago=5, total='25.00',
               financial_status='paid'):
    """A Shopify order dict as the REST API returns it (newest-first lists)."""
    return {
        'id': order_id,
        'name': f'#{order_id}',
        'created_at': (NOW - timedelta(days=days_ago)).isoformat(),
        'financial_status': financial_status,
        'total_price': total,
        'customer': {'id': customer_id},
        'line_items': [
            {'sku': sku, 'title': f'Beer {sku}', 'quantity': 1, 'product_id': 1000}
            for sku in skus
        ],
    }


def sync_studio_dispatch(real_task):
    """
    A stand-in for a Studio-dispatched Celery task whose broker is down:
    .delay() raises, so _dispatch_task falls back to running the real task
    synchronously — the exact local-dev path.
    """
    mock_task = MagicMock()
    mock_task.delay.side_effect = RuntimeError('broker unreachable')
    mock_task.side_effect = lambda *args, **kwargs: real_task(*args, **kwargs)
    return mock_task


# Studio pages render admin templates; plain static storage avoids needing
# collectstatic output (same override as test_studio.py).
@override_settings(STORAGES={
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
})
class CampaignRaffleE2ETest(TestCase):
    """The full journey in one narrative test, plus focused error-path tests."""

    def setUp(self):
        self.staff = User.objects.create_user(
            username='admin@houseofbeers.nl', email='admin@houseofbeers.nl',
            password='SuperSecret123!', is_staff=True,
        )
        self.alice = self._member('alice@example.com', '111')     # qualifies 2-of-3
        self.bob = self._member('bob@example.com', '222')         # near-miss 1-of-3
        self.charlie = self._member('charlie@example.com', '333') # no match

        self.campaign = Campaign.objects.create(
            name='Oktoberfest 2-van-3',
            status='draft',
            action_type='raffle',
            window_start=WINDOW_START,
            window_end=WINDOW_END,
            product_matchers=[
                {'type': 'sku', 'value': 'A'},
                {'type': 'sku', 'value': 'B'},
                {'type': 'sku', 'value': 'C'},
            ],
            min_distinct_products=2,
            rule_sentence='Koop 2 van deze 3 bieren en loot mee.',
            discount_type='percentage',
            discount_value=100,
        )
        self.raffle = CampaignRaffle.objects.create(
            campaign=self.campaign,
            prize_name='Magnum fles',
            prize_description='Een magnum om te delen',
            num_winners=1,
            entry_mode='per_item',
            fulfillment_type='shopify_code',
            draw_at=None,  # manual draw — the API must serve draw_at: null
        )

        # Backfill scan: alice bought A and B (2 orders), bob bought A,
        # charlie bought only an unrelated beer, and one order belongs to a
        # Shopify customer without an app account. Newest-first, as Shopify
        # returns them.
        self.backfill_orders = [
            shop_order(4, 111, ['B'], days_ago=2),
            shop_order(3, 222, ['A'], days_ago=3),
            shop_order(2, 333, ['Z'], days_ago=4),
            shop_order(1, 111, ['A'], days_ago=5),
            shop_order(0, 999, ['A', 'B'], days_ago=5),  # not an app user
        ]

    def _member(self, email, customer_id):
        user = User.objects.create_user(
            username=email, email=email, password='SuperSecret123!',
            first_name=email.split('@')[0].title(),
            shopify_customer_id=customer_id,
        )
        # Email is opt-in (NotificationPreference.email_enabled defaults to
        # False); opt these members in so the fallback/always policies have an
        # open email channel and delivery rows read 'sent'.
        from notifications.models import NotificationPreference
        NotificationPreference.objects.create(user=user, email_enabled=True)
        return user

    def _api(self, user=None):
        client = APIClient()
        if user is not None:
            client.force_authenticate(user=user)
        return client

    def _campaign_deliveries(self):
        return NotificationDelivery.objects.filter(
            dedupe_key__startswith=f'campaign:{self.campaign.id}:'
        )

    # ---- The story ----

    def test_full_campaign_raffle_journey(self):
        self.client.force_login(self.staff)

        # 1. Preview (dry run) via the Studio, broker down -> sync fallback.
        with patch(SHOP_ORDERS_TARGET, return_value=self.backfill_orders), \
                patch(STUDIO_BACKFILL_TARGET, sync_studio_dispatch(campaign_backfill)):
            response = self.client.post(
                reverse('studio:run_preview', kwargs={'pk': self.campaign.pk})
            )
        self.assertEqual(response.status_code, 302)

        preview = self.campaign.previews.get()
        self.assertEqual(preview.status, 'done')
        result = preview.result
        self.assertEqual(result['orders_scanned'], 5)
        self.assertEqual(result['qualified_count'], 1)
        self.assertEqual(result['near_miss_count'], 1)
        [qualified] = result['users']
        self.assertEqual(qualified['email'], 'alice@example.com')
        self.assertEqual(qualified['tickets'], 2)  # per_item: A + B
        self.assertEqual(sorted(qualified['matched']), ['Beer A', 'Beer B'])
        [near_miss] = result['near_miss_users']
        self.assertEqual(near_miss['email'], 'bob@example.com')
        # Charlie matched nothing: neither qualified nor a near miss.
        self.assertNotIn('charlie@example.com',
                         [u['email'] for u in result['users'] + result['near_miss_users']])

        # Dry run wrote nothing.
        self.assertFalse(CampaignProgress.objects.exists())
        self.assertFalse(RaffleEntry.objects.exists())
        self.campaign.refresh_from_db()
        self.assertEqual(self.campaign.status, 'previewed')
        self.assertFalse(self.campaign.preview_stale)

        # 2. Activate -> live backfill (same sync fallback), real outbox.
        with patch(SHOP_ORDERS_TARGET, return_value=self.backfill_orders), \
                patch(STUDIO_BACKFILL_TARGET, sync_studio_dispatch(campaign_backfill)):
            response = self.client.post(
                reverse('studio:activate', kwargs={'pk': self.campaign.pk})
            )
        self.assertEqual(response.status_code, 302)
        self.campaign.refresh_from_db()
        self.assertEqual(self.campaign.status, 'active')

        entry = RaffleEntry.objects.get(raffle=self.raffle, user=self.alice)
        self.assertEqual(entry.ticket_count, 2)
        self.assertIsNone(
            CampaignProgress.objects.get(campaign=self.campaign, user=self.bob).qualified_at
        )
        self.assertFalse(RaffleEntry.objects.filter(user=self.bob).exists())

        # Alice got the qualify notification: push skipped (no VAPID keys),
        # so the raffle kind's fallback policy emailed her.
        qualify = NotificationDelivery.objects.get(
            dedupe_key=f'campaign:{self.campaign.id}:{self.alice.id}:qualified'
        )
        self.assertEqual(qualify.kind, 'raffle')
        self.assertEqual(qualify.email_status, 'sent')
        self.assertEqual(qualify.data['url'], f'/raffle/{self.raffle.id}')
        award = CampaignAward.objects.get(campaign=self.campaign, user=self.alice)
        self.assertEqual(award.notified_delivery_id, qualify.id)

        # 3. A NEW order arrives through the points-sync path and turns the
        # near-miss into a qualifier — while a PointsRule keeps working
        # alongside untouched.
        PointsRule.objects.create(name='Order bonus', rule_type='per_order', points=10)
        new_order = shop_order(5, 222, ['B'], days_ago=0)
        sync_result = LoyaltyService().process_all_orders_for_user(self.bob, [new_order])

        self.assertEqual(sync_result['total_awarded'], 10)
        self.assertEqual(PointsBalance.objects.get(user=self.bob).balance, 10)
        bob_entry = RaffleEntry.objects.get(raffle=self.raffle, user=self.bob)
        self.assertEqual(bob_entry.ticket_count, 2)  # per_item: A + B
        self.assertTrue(NotificationDelivery.objects.filter(
            dedupe_key=f'campaign:{self.campaign.id}:{self.bob.id}:qualified'
        ).exists())

        # Pre-draw API: bob sees his entry, draw_at is null (manual draw).
        payload = self._api(self.bob).get('/api/loyalty/raffles/').json()
        [raffle_json] = payload['raffles']
        self.assertEqual(raffle_json['status'], 'open')
        self.assertTrue(raffle_json['entered'])
        self.assertEqual(raffle_json['ticket_count'], 2)
        self.assertIsNone(raffle_json['draw_at'])
        self.assertEqual(raffle_json['entrant_count'], 2)
        self.assertIsNone(raffle_json['did_win'])
        self.assertIsNone(raffle_json['entrant_first_names'])

        # Opening the card pre-draw marks it seen — literal empty 204.
        response = self._api(self.bob).post(
            f'/api/loyalty/raffles/{self.raffle.id}/seen/'
        )
        self.assertEqual(response.status_code, 204)
        self.assertEqual(response.content, b'')
        bob_entry.refresh_from_db()
        self.assertIsNotNone(bob_entry.seen_at)

        # 4. Draw via the task. Discount creation is mocked to mint a WIN-
        # code; random.choices is pinned so the first entry (alice) wins.
        mail.outbox = []
        expires = NOW + timedelta(days=30)
        with patch(DISCOUNT_TARGET, return_value={
            'discount_id': 'gid://shopify/DiscountCodeNode/9',
            'code': 'WIN-E2ETEST1',
            'expires_at': expires,
        }) as mock_discount, patch(
            'loyalty.services.raffles.random.choices',
            side_effect=lambda pool, weights, k: [pool[0]],
        ):
            draw_result = draw_campaign_raffle(self.raffle.id)

        self.assertEqual(draw_result, {'winners': 1})
        self.raffle.refresh_from_db()
        self.campaign.refresh_from_db()
        self.assertEqual(self.raffle.status, 'drawn')
        self.assertEqual(self.campaign.status, 'completed')

        winner = CampaignRaffleWinner.objects.get(raffle=self.raffle)
        self.assertEqual(winner.user, self.alice)
        self.assertEqual(winner.prize_code, 'WIN-E2ETEST1')
        self.assertEqual(winner.fulfillment_status, 'code_issued')
        self.assertEqual(winner.code_expires_at, expires)
        # The minted code was created against the campaign's discount config.
        self.assertEqual(mock_discount.call_args.args[1], self.campaign)

        # Winner notification: email_policy 'always' (the code must land in
        # an inbox) and the code is in the mail. Loser gets the softer body.
        win_delivery = NotificationDelivery.objects.get(
            dedupe_key=f'campaign:{self.campaign.id}:{self.alice.id}:result'
        )
        self.assertEqual(win_delivery.email_policy, 'always')
        self.assertEqual(win_delivery.email_status, 'sent')
        self.assertEqual(winner.result_delivery_id, win_delivery.id)
        winner_mails = [m for m in mail.outbox if m.to == ['alice@example.com']]
        self.assertTrue(any('WIN-E2ETEST1' in m.body for m in winner_mails))

        lose_delivery = NotificationDelivery.objects.get(
            dedupe_key=f'campaign:{self.campaign.id}:{self.bob.id}:result'
        )
        self.assertEqual(lose_delivery.kind, 'raffle')
        self.assertNotIn('WIN-E2ETEST1', lose_delivery.body)

        # 5. Dedupe: drawing again is a no-op — no new winners, no re-sends.
        delivery_count = self._campaign_deliveries().count()
        with patch(DISCOUNT_TARGET) as mock_discount_again:
            self.assertEqual(draw_campaign_raffle(self.raffle.id), {'already_drawn': True})
        mock_discount_again.assert_not_called()
        self.assertEqual(CampaignRaffleWinner.objects.count(), 1)
        self.assertEqual(self._campaign_deliveries().count(), delivery_count)

        # 6. Post-draw API for winner and loser (frozen shape fields).
        winner_json = self._api(self.alice).get('/api/loyalty/raffles/').json()['raffles'][0]
        self.assertEqual(winner_json['status'], 'drawn')
        self.assertTrue(winner_json['did_win'])
        self.assertEqual(winner_json['my_code'], 'WIN-E2ETEST1')
        self.assertIsNotNone(winner_json['my_code_expires_at'])
        self.assertEqual(winner_json['public_winner_names'], ['Alice'])
        self.assertEqual(winner_json['winner_first_names'], ['Alice'])
        self.assertEqual(sorted(winner_json['entrant_first_names']), ['Alice', 'Bob'])

        loser_json = self._api(self.bob).get('/api/loyalty/raffles/').json()['raffles'][0]
        self.assertFalse(loser_json['did_win'])
        self.assertIsNone(loser_json['my_code'])
        self.assertEqual(loser_json['public_winner_names'], ['Alice'])
        self.assertTrue(loser_json['seen'])
        self.assertFalse(loser_json['result_seen'])

        # 7. Both watch the reveal.
        for user in (self.alice, self.bob):
            response = self._api(user).post(
                f'/api/loyalty/raffles/{self.raffle.id}/result-seen/'
            )
            self.assertEqual(response.status_code, 204)
            self.assertEqual(response.content, b'')
        self.assertEqual(
            RaffleEntry.objects.filter(
                raffle=self.raffle, result_seen_at__isnull=False
            ).count(),
            2,
        )

        # 8. Studio monitor funnel reflects all of it.
        response = self.client.get(
            reverse('studio:campaign_monitor', kwargs={'pk': self.campaign.pk})
        )
        self.assertEqual(response.status_code, 200)
        funnel = {stage['key']: stage['count'] for stage in response.context['funnel']}
        self.assertEqual(funnel['entered'], 2)
        self.assertEqual(funnel['notified'], 2)   # both got sent emails
        self.assertEqual(funnel['opened'], 1)     # only bob hit /seen/ pre-draw
        self.assertEqual(funnel['watched'], 2)
        self.assertEqual(funnel['redeemed'], 0)

        # 9. CSV export smoke.
        response = self.client.get(
            reverse('studio:entrants_csv', kwargs={'pk': self.campaign.pk})
        )
        self.assertEqual(response.status_code, 200)
        content = response.content.decode('utf-8')
        self.assertIn('alice@example.com', content)
        self.assertIn('WIN-E2ETEST1', content)
        self.assertIn('bob@example.com', content)

    # ---- Focused error paths ----

    def test_raffles_list_requires_auth(self):
        response = APIClient().get('/api/loyalty/raffles/')
        self.assertIn(response.status_code, (401, 403))

    def test_seen_endpoints_never_500(self):
        """Nonexistent numeric id: contract-conform empty-204 no-op (there is
        no entry to stamp). Malformed id: 404 from the int URL converter."""
        api = self._api(self.alice)
        for endpoint in ('seen', 'result-seen'):
            response = api.post(f'/api/loyalty/raffles/999999/{endpoint}/')
            self.assertEqual(response.status_code, 204)
            self.assertEqual(response.content, b'')

            response = api.post(f'/api/loyalty/raffles/not-a-number/{endpoint}/')
            self.assertEqual(response.status_code, 404)

    def test_qualification_discount_failure_still_qualifies(self):
        """Shopify refusing the code must not cost the user their
        qualification: award recorded with a blank code, notification sent."""
        campaign = Campaign.objects.create(
            name='Kortingsactie', status='active', action_type='discount_code',
            window_start=WINDOW_START, window_end=WINDOW_END,
            discount_type='percentage', discount_value=10,
        )
        with patch(DISCOUNT_TARGET, return_value=None):
            from loyalty.services.campaigns import apply_order_to_campaigns
            apply_order_to_campaigns(self.alice, shop_order(50, 111, ['A']))

        progress = CampaignProgress.objects.get(campaign=campaign, user=self.alice)
        self.assertIsNotNone(progress.qualified_at)
        award = CampaignAward.objects.get(campaign=campaign, user=self.alice)
        self.assertEqual(award.discount_code, '')
        self.assertTrue(NotificationDelivery.objects.filter(
            dedupe_key=f'campaign:{campaign.id}:{self.alice.id}:qualified'
        ).exists())

    def test_seed_demo_raffle_command(self):
        """The dev-only seeder builds a demo raffle, draws it on demand and
        cleans up after itself; without DEBUG it refuses to run."""
        from io import StringIO
        from django.core.management import call_command
        from django.core.management.base import CommandError

        with self.assertRaises(CommandError):  # DEBUG=False in tests
            call_command('seed_demo_raffle', stdout=StringIO())

        with override_settings(DEBUG=True):
            call_command(
                'seed_demo_raffle', '--email', 'alice@example.com',
                '--drawn', '--win', stdout=StringIO(),
            )
            raffle = CampaignRaffle.objects.get(
                campaign__name='[DEMO] Oktoberfest verloting'
            )
            self.assertEqual(raffle.status, 'drawn')
            winner = raffle.winners.get()
            self.assertEqual(winner.user, self.alice)
            self.assertTrue(winner.prize_code.startswith('WIN-'))
            # --win must not leave the inflated ticket count behind.
            self.assertEqual(
                RaffleEntry.objects.get(raffle=raffle, user=self.alice).ticket_count, 3
            )

            call_command('seed_demo_raffle', '--clean', stdout=StringIO())
            self.assertFalse(
                Campaign.objects.filter(name='[DEMO] Oktoberfest verloting').exists()
            )
            self.assertFalse(
                User.objects.filter(email__startswith='demo-raffle-').exists()
            )

    def test_preview_failure_when_shopify_down(self):
        """The order scan raising marks the preview failed with the error and
        leaves the campaign untouched."""
        self.client.force_login(self.staff)
        with patch(SHOP_ORDERS_TARGET, side_effect=RuntimeError('shopify down')), \
                patch(STUDIO_BACKFILL_TARGET, sync_studio_dispatch(campaign_backfill)):
            response = self.client.post(
                reverse('studio:run_preview', kwargs={'pk': self.campaign.pk})
            )
        self.assertEqual(response.status_code, 302)

        preview = self.campaign.previews.get()
        self.assertEqual(preview.status, 'failed')
        self.assertIn('shopify down', preview.error)
        self.campaign.refresh_from_db()
        self.assertEqual(self.campaign.status, 'draft')
        self.assertTrue(self.campaign.preview_stale)
        self.assertFalse(CampaignProgress.objects.exists())
