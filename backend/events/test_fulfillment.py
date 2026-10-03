"""
Tests for the prize fulfillment flow (regie "Afhandeling"): UNLISTED
Shopify product per prize, then the prize on each winner's draft order.

Shopify is mocked at the service-layer boundary
(events.services.fulfillment.ShopifyService) — these tests cover the
status bookkeeping, idempotency and the regie views, not the GraphQL
plumbing (that lives in users/test_shopify_fulfillment.py).
"""
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone

from .models import AuctionItem, Event, Raffle, RaffleWinner
from .services import fulfillment

User = get_user_model()

SERVICE = 'events.services.fulfillment.ShopifyService'

PRODUCT_RESULT = {
    'product_gid': 'gid://shopify/Product/111',
    'variant_gid': 'gid://shopify/ProductVariant/222',
    'inventory_item_gid': 'gid://shopify/InventoryItem/333',
    'reused': False,
    'published': True,
}

ATTACH_CREATED = {
    'action': 'draft_created',
    'draft_gid': 'gid://shopify/DraftOrder/901',
    'invoice_url': 'https://shop/invoice/901',
}

ATTACH_UPDATED = {
    'action': 'draft_updated',
    'draft_gid': 'gid://shopify/DraftOrder/902',
    'invoice_url': 'https://shop/invoice/902',
}


def make_user(n, shopify_customer_id=''):
    user = User.objects.create_user(
        username=f'fulfiller{n}',
        email=f'fulfiller{n}@test.com',
        password='testpass123',
    )
    if shopify_customer_id:
        user.shopify_customer_id = shopify_customer_id
        user.save(update_fields=['shopify_customer_id'])
    return user


def make_event(**kwargs):
    defaults = {
        'title': 'Fulfillment Stream',
        'event_type': 'livestream',
        'scheduled_at': timezone.now(),
        # Deliberately ENDED: fulfillment is a post-stream activity and
        # must keep working after the event closes (event 3!).
        'status': 'ended',
    }
    defaults.update(kwargs)
    return Event.objects.create(**defaults)


def make_shopify_raffle(event, winners, price='100.00', **kwargs):
    raffle = Raffle.objects.create(
        event=event,
        prize_name=kwargs.pop('prize_name', 'Goose Island King Henry II'),
        num_winners=len(winners) or 1,
        fulfillment_type='shopify',
        winner_price=Decimal(price) if price is not None else None,
        status='drawn',
        drawn_at=timezone.now(),
        **kwargs,
    )
    rows = [
        RaffleWinner.objects.create(raffle=raffle, user=user)
        for user in winners
    ]
    return raffle, rows


def make_sold_item(event, winner, **kwargs):
    defaults = {
        'title': 'BCBS Vanilla Rye 2014',
        'brewery': 'Goose Island',
        'size': '65cl',
        'starting_price': Decimal('50.00'),
        'final_price': Decimal('210.00'),
        'status': 'sold',
        'winner': winner,
    }
    defaults.update(kwargs)
    return AuctionItem.objects.create(event=event, **defaults)


class EnsurePrizeProductTests(TestCase):
    def setUp(self):
        self.event = make_event()
        self.linked = make_user(1, shopify_customer_id='555001')
        self.raffle, self.winners = make_shopify_raffle(
            self.event, [self.linked, make_user(2)])

    @patch(SERVICE)
    def test_skips_when_gids_already_set(self, mock_service):
        self.raffle.shopify_product_gid = 'gid://shopify/Product/9'
        self.raffle.shopify_variant_gid = 'gid://shopify/ProductVariant/9'
        self.raffle.save()
        result = fulfillment.ensure_prize_product(self.raffle)
        self.assertTrue(result['ok'])
        self.assertTrue(result['skipped'])
        mock_service.assert_not_called()

    @patch(SERVICE)
    def test_creates_and_stores_gids(self, mock_service):
        mock_service.return_value.create_unlisted_product.return_value = (
            PRODUCT_RESULT
        )
        result = fulfillment.ensure_prize_product(self.raffle)
        self.assertTrue(result['ok'])
        mock_service.return_value.create_unlisted_product.assert_called_once_with(
            title='Goose Island King Henry II',
            price=Decimal('100.00'),
            quantity=2,
            description=None,
            image_url=None,
        )
        self.raffle.refresh_from_db()
        self.assertEqual(self.raffle.shopify_product_gid,
                         PRODUCT_RESULT['product_gid'])
        self.assertEqual(self.raffle.shopify_variant_gid,
                         PRODUCT_RESULT['variant_gid'])

    @patch(SERVICE)
    def test_free_prize_creates_zero_price_product(self, mock_service):
        self.raffle.winner_price = None
        self.raffle.save()
        mock_service.return_value.create_unlisted_product.return_value = (
            PRODUCT_RESULT
        )
        fulfillment.ensure_prize_product(self.raffle)
        _, kwargs = mock_service.return_value.create_unlisted_product.call_args
        self.assertEqual(kwargs['price'], 0)

    @patch(SERVICE)
    def test_manual_raffle_rejected(self, mock_service):
        self.raffle.fulfillment_type = 'manual'
        self.raffle.save()
        result = fulfillment.ensure_prize_product(self.raffle)
        self.assertIn('geen Shopify-product nodig', result['error'])
        mock_service.assert_not_called()

    @patch(SERVICE)
    def test_raffle_without_winners_rejected(self, mock_service):
        raffle = Raffle.objects.create(
            event=self.event, prize_name='Niemand won', num_winners=1,
            fulfillment_type='shopify', status='drawn',
            drawn_at=timezone.now(),
        )
        result = fulfillment.ensure_prize_product(raffle)
        self.assertIn('geen winnaars', result['error'])
        mock_service.assert_not_called()

    @patch(SERVICE)
    def test_shopify_failure_keeps_gids_blank(self, mock_service):
        mock_service.return_value.create_unlisted_product.return_value = None
        result = fulfillment.ensure_prize_product(self.raffle)
        self.assertIn('mislukt', result['error'])
        self.raffle.refresh_from_db()
        self.assertEqual(self.raffle.shopify_product_gid, '')

    @patch(SERVICE)
    def test_auction_item_uses_final_price_and_details(self, mock_service):
        item = make_sold_item(self.event, self.linked)
        mock_service.return_value.create_unlisted_product.return_value = (
            PRODUCT_RESULT
        )
        result = fulfillment.ensure_prize_product(item)
        self.assertTrue(result['ok'])
        _, kwargs = mock_service.return_value.create_unlisted_product.call_args
        self.assertEqual(kwargs['price'], Decimal('210.00'))
        self.assertEqual(kwargs['quantity'], 1)
        self.assertIn('Goose Island', kwargs['description'])
        self.assertIn('65cl', kwargs['description'])
        item.refresh_from_db()
        self.assertEqual(item.shopify_variant_gid,
                         PRODUCT_RESULT['variant_gid'])

    @patch(SERVICE)
    def test_unsold_auction_item_rejected(self, mock_service):
        item = make_sold_item(self.event, None, status='pending',
                              final_price=None)
        result = fulfillment.ensure_prize_product(item)
        self.assertIn('nog niet verkocht', result['error'])
        mock_service.assert_not_called()


class AttachToWinnerTests(TestCase):
    def setUp(self):
        self.event = make_event()
        self.linked = make_user(1, shopify_customer_id='555001')
        self.unlinked = make_user(2)
        self.raffle, self.winners = make_shopify_raffle(
            self.event, [self.linked, self.unlinked])
        self.raffle.shopify_product_gid = PRODUCT_RESULT['product_gid']
        self.raffle.shopify_variant_gid = PRODUCT_RESULT['variant_gid']
        self.raffle.save()
        self.winner = self.winners[0]        # linked
        self.unlinked_winner = self.winners[1]

    @patch(SERVICE)
    def test_draft_created_maps_to_status(self, mock_service):
        mock_service.return_value.attach_variant_to_customer.return_value = (
            ATTACH_CREATED
        )
        result = fulfillment.attach_to_winner(self.winner)
        self.assertTrue(result['ok'])
        mock_service.return_value.attach_variant_to_customer.assert_called_once_with(
            '555001', PRODUCT_RESULT['variant_gid'])
        self.winner.refresh_from_db()
        self.assertEqual(self.winner.fulfillment_status, 'draft_created')
        self.assertEqual(self.winner.shopify_order_gid,
                         ATTACH_CREATED['draft_gid'])
        self.assertEqual(self.winner.fulfillment_error, '')

    @patch(SERVICE)
    def test_draft_updated_maps_to_added_to_order(self, mock_service):
        mock_service.return_value.attach_variant_to_customer.return_value = (
            ATTACH_UPDATED
        )
        fulfillment.attach_to_winner(self.winner)
        self.winner.refresh_from_db()
        self.assertEqual(self.winner.fulfillment_status, 'added_to_order')

    @patch(SERVICE)
    def test_unlinked_user_fails_without_shopify_call(self, mock_service):
        result = fulfillment.attach_to_winner(self.unlinked_winner)
        self.assertIn('Shopify-koppeling', result['error'])
        mock_service.assert_not_called()
        self.unlinked_winner.refresh_from_db()
        self.assertEqual(self.unlinked_winner.fulfillment_status, 'failed')
        self.assertIn('Shopify-koppeling',
                      self.unlinked_winner.fulfillment_error)

    @patch(SERVICE)
    def test_failure_then_retry_recovers(self, mock_service):
        attach = mock_service.return_value.attach_variant_to_customer
        attach.return_value = {'error': 'boom'}
        result = fulfillment.attach_to_winner(self.winner)
        self.assertIn('boom', result['error'])
        self.winner.refresh_from_db()
        self.assertEqual(self.winner.fulfillment_status, 'failed')

        attach.return_value = ATTACH_CREATED
        result = fulfillment.attach_to_winner(self.winner)
        self.assertTrue(result['ok'])
        self.winner.refresh_from_db()
        self.assertEqual(self.winner.fulfillment_status, 'draft_created')
        self.assertEqual(self.winner.fulfillment_error, '')

    @patch(SERVICE)
    def test_missing_variant_gid_is_precondition_error(self, mock_service):
        self.raffle.shopify_variant_gid = ''
        self.raffle.save()
        self.winner.raffle.refresh_from_db()
        result = fulfillment.attach_to_winner(
            RaffleWinner.objects.get(pk=self.winner.pk))
        self.assertIn('eerst het Shopify-product', result['error'])
        mock_service.assert_not_called()
        self.winner.refresh_from_db()
        self.assertEqual(self.winner.fulfillment_status, 'pending')

    @patch(SERVICE)
    def test_auction_item_attach(self, mock_service):
        item = make_sold_item(self.event, self.linked)
        item.shopify_variant_gid = PRODUCT_RESULT['variant_gid']
        item.save()
        mock_service.return_value.attach_variant_to_customer.return_value = (
            ATTACH_CREATED
        )
        result = fulfillment.attach_to_winner(item)
        self.assertTrue(result['ok'])
        item.refresh_from_db()
        self.assertEqual(item.fulfillment_status, 'draft_created')


class InvoiceAndToggleTests(TestCase):
    def setUp(self):
        self.event = make_event()
        self.linked = make_user(1, shopify_customer_id='555001')
        self.raffle, self.winners = make_shopify_raffle(
            self.event, [self.linked])
        self.winner = self.winners[0]

    @patch(SERVICE)
    def test_invoice_requires_draft(self, mock_service):
        result = fulfillment.send_invoice(self.winner)
        self.assertIn('nog geen draft order', result['error'])
        mock_service.assert_not_called()

    @patch(SERVICE)
    def test_invoice_success(self, mock_service):
        self.winner.fulfillment_status = 'draft_created'
        self.winner.shopify_order_gid = ATTACH_CREATED['draft_gid']
        self.winner.save()
        mock_service.return_value.send_draft_invoice.return_value = {
            'draft_gid': ATTACH_CREATED['draft_gid'],
            'invoice_url': 'https://shop/invoice/901',
        }
        result = fulfillment.send_invoice(self.winner)
        self.assertTrue(result['ok'])
        self.winner.refresh_from_db()
        self.assertEqual(self.winner.fulfillment_status, 'invoice_sent')

    @patch(SERVICE)
    def test_invoice_failure_keeps_status(self, mock_service):
        self.winner.fulfillment_status = 'draft_created'
        self.winner.shopify_order_gid = ATTACH_CREATED['draft_gid']
        self.winner.save()
        mock_service.return_value.send_draft_invoice.return_value = None
        result = fulfillment.send_invoice(self.winner)
        self.assertIn('mislukt', result['error'])
        self.winner.refresh_from_db()
        # The prize IS on the draft — a failed email must not regress that.
        self.assertEqual(self.winner.fulfillment_status, 'draft_created')
        self.assertIn('mislukt', self.winner.fulfillment_error)

    def test_mark_and_unmark_fulfilled(self):
        fulfillment.mark_fulfilled(self.winner)
        self.winner.refresh_from_db()
        self.assertEqual(self.winner.fulfillment_status, 'fulfilled')
        self.assertIsNotNone(self.winner.fulfilled_at)

        fulfillment.unmark_fulfilled(self.winner)
        self.winner.refresh_from_db()
        self.assertEqual(self.winner.fulfillment_status, 'pending')
        self.assertIsNone(self.winner.fulfilled_at)

    def test_unmark_with_draft_goes_back_to_draft_created(self):
        self.winner.shopify_order_gid = ATTACH_CREATED['draft_gid']
        self.winner.save()
        fulfillment.mark_fulfilled(self.winner)
        fulfillment.unmark_fulfilled(self.winner)
        self.winner.refresh_from_db()
        self.assertEqual(self.winner.fulfillment_status, 'draft_created')


class FulfillmentProgressTests(TestCase):
    def setUp(self):
        self.event = make_event()

    def test_points_auto_count_shopify_and_auction_by_status(self):
        # Points raffle: 2 winners, both processed automatically
        points_raffle = Raffle.objects.create(
            event=self.event, prize_name='500 Punten', num_winners=2,
            fulfillment_type='points', points_award=500,
            status='drawn', drawn_at=timezone.now(),
        )
        for n in (1, 2):
            RaffleWinner.objects.create(
                raffle=points_raffle, user=make_user(n))

        # Shopify raffle: one attached, one pending
        raffle, winners = make_shopify_raffle(
            self.event, [make_user(3), make_user(4)])
        winners[0].fulfillment_status = 'added_to_order'
        winners[0].save()

        # Sold auction item, untouched
        make_sold_item(self.event, make_user(5))

        processed, total = fulfillment.fulfillment_progress(self.event)
        self.assertEqual(total, 5)       # 2 points + 2 raffle + 1 auction
        self.assertEqual(processed, 3)   # 2 points auto + 1 attached


# Plain storage so the admin-based regie template renders in tests
# (same as RegieViewTests in events/tests.py).
@override_settings(STORAGES={
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
})
class RegieFulfillmentViewTests(TestCase):
    """The regie 'Afhandeling' section — explicitly exercised on an ENDED
    event, because that is exactly how event 3 gets processed."""

    def setUp(self):
        self.admin = User.objects.create_superuser(
            username='fadmin', email='fadmin@test.com',
            password='adminpass123',
        )
        self.client.force_login(self.admin)
        self.event = make_event()
        self.linked = make_user(1, shopify_customer_id='555001')
        self.unlinked = make_user(2)
        self.raffle, self.winners = make_shopify_raffle(
            self.event, [self.linked, self.unlinked])
        self.regie_url = f'/admin/events/event/{self.event.pk}/regie/'
        self.base = f'/admin/events/event/{self.event.pk}/regie/fulfill'

    def test_requires_staff(self):
        self.client.force_login(make_user(3))
        response = self.client.post(
            f'{self.base}/product/',
            {'kind': 'raffle', 'obj_id': self.raffle.pk},
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn('/admin/login/', response.url)

    def test_regie_page_shows_fulfillment_section(self):
        response = self.client.get(self.regie_url)
        self.assertContains(response, 'Afhandeling')
        self.assertContains(response, 'Maak Shopify-product')
        self.assertContains(response, 'markeer afgehandeld')

    def test_regie_page_shows_points_as_automatic(self):
        points_raffle = Raffle.objects.create(
            event=self.event, prize_name='2000 Punten', num_winners=1,
            fulfillment_type='points', points_award=2000,
            status='drawn', drawn_at=timezone.now(),
        )
        RaffleWinner.objects.create(raffle=points_raffle, user=make_user(4))
        response = self.client.get(self.regie_url)
        self.assertContains(response, 'automatisch toegekend')

    @patch(SERVICE)
    def test_product_view_on_ended_event(self, mock_service):
        mock_service.return_value.create_unlisted_product.return_value = (
            PRODUCT_RESULT
        )
        response = self.client.post(
            f'{self.base}/product/',
            {'kind': 'raffle', 'obj_id': self.raffle.pk},
        )
        self.assertRedirects(response, self.regie_url)
        self.raffle.refresh_from_db()
        self.assertEqual(self.raffle.shopify_product_gid,
                         PRODUCT_RESULT['product_gid'])

    @patch(SERVICE)
    def test_attach_view(self, mock_service):
        self.raffle.shopify_variant_gid = PRODUCT_RESULT['variant_gid']
        self.raffle.save()
        mock_service.return_value.attach_variant_to_customer.return_value = (
            ATTACH_CREATED
        )
        response = self.client.post(
            f'{self.base}/attach/',
            {'kind': 'winner', 'obj_id': self.winners[0].pk},
        )
        self.assertRedirects(response, self.regie_url)
        self.winners[0].refresh_from_db()
        self.assertEqual(self.winners[0].fulfillment_status, 'draft_created')

    @patch(SERVICE)
    def test_attach_all_mixes_success_and_failure(self, mock_service):
        self.raffle.shopify_variant_gid = PRODUCT_RESULT['variant_gid']
        self.raffle.save()
        mock_service.return_value.attach_variant_to_customer.return_value = (
            ATTACH_CREATED
        )
        response = self.client.post(
            f'{self.base}/attach-all/{self.raffle.pk}/')
        self.assertRedirects(response, self.regie_url)
        linked_winner = RaffleWinner.objects.get(user=self.linked)
        unlinked_winner = RaffleWinner.objects.get(user=self.unlinked)
        self.assertEqual(linked_winner.fulfillment_status, 'draft_created')
        self.assertEqual(unlinked_winner.fulfillment_status, 'failed')
        # Only the linked winner reached Shopify
        mock_service.return_value.attach_variant_to_customer.assert_called_once()

    @patch(SERVICE)
    def test_invoice_view(self, mock_service):
        winner = self.winners[0]
        winner.fulfillment_status = 'draft_created'
        winner.shopify_order_gid = ATTACH_CREATED['draft_gid']
        winner.save()
        mock_service.return_value.send_draft_invoice.return_value = {
            'draft_gid': ATTACH_CREATED['draft_gid'],
            'invoice_url': 'https://shop/invoice/901',
        }
        response = self.client.post(
            f'{self.base}/invoice/',
            {'kind': 'winner', 'obj_id': winner.pk},
        )
        self.assertRedirects(response, self.regie_url)
        winner.refresh_from_db()
        self.assertEqual(winner.fulfillment_status, 'invoice_sent')

    def test_toggle_view_round_trip(self):
        winner = self.winners[0]
        for expected in ('fulfilled', 'pending'):
            response = self.client.post(
                f'{self.base}/toggle/',
                {'kind': 'winner', 'obj_id': winner.pk},
            )
            self.assertRedirects(response, self.regie_url)
            winner.refresh_from_db()
            self.assertEqual(winner.fulfillment_status, expected)

    @patch(SERVICE)
    def test_auction_product_and_attach(self, mock_service):
        item = make_sold_item(self.event, self.linked)
        mock_service.return_value.create_unlisted_product.return_value = (
            PRODUCT_RESULT
        )
        mock_service.return_value.attach_variant_to_customer.return_value = (
            ATTACH_CREATED
        )
        self.client.post(
            f'{self.base}/product/',
            {'kind': 'auction', 'obj_id': item.pk},
        )
        item.refresh_from_db()
        self.assertEqual(item.shopify_variant_gid,
                         PRODUCT_RESULT['variant_gid'])
        self.client.post(
            f'{self.base}/attach/',
            {'kind': 'auction', 'obj_id': item.pk},
        )
        item.refresh_from_db()
        self.assertEqual(item.fulfillment_status, 'draft_created')

    def test_invalid_kind_is_handled(self):
        response = self.client.post(
            f'{self.base}/attach/',
            {'kind': 'bogus', 'obj_id': '12'},
        )
        self.assertRedirects(response, self.regie_url)

    def test_wrong_event_scoping_404s(self):
        other_event = make_event(title='Ander event')
        response = self.client.post(
            f'/admin/events/event/{other_event.pk}/regie/fulfill/attach/',
            {'kind': 'winner', 'obj_id': self.winners[0].pk},
        )
        self.assertEqual(response.status_code, 404)
