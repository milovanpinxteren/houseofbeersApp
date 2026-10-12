"""
Tests for prize/auction draft-order payment tracking
(events/services/payments.py + the regie "Check betalingen" button).

Shopify is mocked at the service boundary
(events.services.payments.ShopifyService); the GraphQL plumbing of
get_draft_order_payment_state lives in users/test_shopify_fulfillment.py.
"""
from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .models import AuctionItem, Event, Raffle, RaffleWinner
from .services import payments

User = get_user_model()

SERVICE = 'events.services.payments.ShopifyService'

STATE_PAID = {
    'found': True,
    'status': 'COMPLETED',
    'order': {
        'order_gid': 'gid://shopify/Order/777',
        'name': '#1234',
        'financial_status': 'PAID',
        'created_at': '2026-10-05T12:00:00Z',
    },
}
STATE_ORDER_UNPAID = {
    'found': True,
    'status': 'COMPLETED',
    'order': {
        'order_gid': 'gid://shopify/Order/778',
        'name': '#1235',
        'financial_status': 'PENDING',
        'created_at': '2026-10-05T12:00:00Z',
    },
}
STATE_INVOICE_SENT = {'found': True, 'status': 'INVOICE_SENT', 'order': None}
STATE_OPEN = {'found': True, 'status': 'OPEN', 'order': None}
STATE_GONE = {'found': False}


def make_user(n, **extra):
    return User.objects.create_user(
        username=f'payer{n}', email=f'payer{n}@test.com',
        password='testpass123', **extra,
    )


def make_event(**kwargs):
    defaults = {
        'title': 'Payment Stream',
        'event_type': 'livestream',
        'scheduled_at': timezone.now(),
        'status': 'ended',
    }
    defaults.update(kwargs)
    return Event.objects.create(**defaults)


def make_winner(event, user, price='100.00', fulfillment_type='shopify',
                draft_gid='gid://shopify/DraftOrder/901', **winner_kwargs):
    raffle = Raffle.objects.create(
        event=event, prize_name='Prize', num_winners=1,
        fulfillment_type=fulfillment_type,
        winner_price=Decimal(price) if price is not None else None,
        status='drawn', drawn_at=timezone.now(),
    )
    return RaffleWinner.objects.create(
        raffle=raffle, user=user, shopify_order_gid=draft_gid,
        **winner_kwargs,
    )


def make_item(event, winner, price='210.00',
              draft_gid='gid://shopify/DraftOrder/902', **kwargs):
    defaults = {
        'title': 'Auction beer',
        'starting_price': Decimal('50.00'),
        'final_price': Decimal(price) if price is not None else None,
        'status': 'sold',
        'winner': winner,
        'shopify_order_gid': draft_gid,
    }
    defaults.update(kwargs)
    return AuctionItem.objects.create(event=event, **defaults)


class PaymentTargetsTests(TestCase):
    def setUp(self):
        self.event = make_event()
        self.user = make_user(1)

    def test_selects_priced_draft_rows_only(self):
        tracked_winner = make_winner(self.event, self.user)
        tracked_item = make_item(self.event, make_user(2))
        # None of these may be selected:
        make_winner(self.event, make_user(3), price='0')          # free prize
        make_winner(self.event, make_user(4), price=None)         # free prize
        make_winner(self.event, make_user(5), fulfillment_type='manual')
        make_winner(self.event, make_user(6), draft_gid='')       # no draft
        make_winner(self.event, make_user(7), payment_status='paid')
        make_winner(self.event, make_user(8), payment_status='cancelled')
        make_item(self.event, make_user(9), price='0')
        make_item(self.event, None, price=None, draft_gid='',
                  status='active')

        targets = payments.payment_targets()
        self.assertCountEqual(targets, [tracked_winner, tracked_item])

    def test_event_filter(self):
        other_event = make_event(title='Other')
        mine = make_winner(self.event, self.user)
        make_winner(other_event, make_user(2))
        self.assertEqual(payments.payment_targets(self.event), [mine])


class CheckPaymentTests(TestCase):
    def setUp(self):
        self.event = make_event()
        self.winner = make_winner(self.event, make_user(1))

    def _check(self, state):
        service = MagicMock()
        service.get_draft_order_payment_state.return_value = state
        result = payments.check_payment(self.winner, service=service)
        self.winner.refresh_from_db()
        return result

    def test_transport_failure_writes_nothing(self):
        result = self._check(None)
        self.assertIn('error', result)
        self.assertEqual(self.winner.payment_status, 'pending')
        self.assertIsNone(self.winner.payment_checked_at)

    def test_paid_order(self):
        result = self._check(STATE_PAID)
        self.assertEqual(result, {'ok': True, 'status': 'paid',
                                  'changed': True})
        self.assertEqual(self.winner.payment_status, 'paid')
        self.assertEqual(self.winner.paid_at.year, 2026)
        self.assertEqual(self.winner.shopify_final_order_gid,
                         'gid://shopify/Order/777')
        self.assertEqual(self.winner.shopify_final_order_name, '#1234')
        self.assertIsNotNone(self.winner.payment_checked_at)

    def test_refunded_still_counts_as_paid(self):
        state = {**STATE_PAID, 'order': {**STATE_PAID['order'],
                                         'financial_status': 'REFUNDED'}}
        self._check(state)
        self.assertEqual(self.winner.payment_status, 'paid')

    def test_order_pending_means_invoiced(self):
        self._check(STATE_ORDER_UNPAID)
        self.assertEqual(self.winner.payment_status, 'invoiced')
        self.assertIsNone(self.winner.paid_at)
        self.assertEqual(self.winner.shopify_final_order_name, '#1235')

    def test_voided_order_means_cancelled(self):
        state = {**STATE_PAID, 'order': {**STATE_PAID['order'],
                                         'financial_status': 'VOIDED'}}
        self._check(state)
        self.assertEqual(self.winner.payment_status, 'cancelled')

    def test_invoice_sent_draft(self):
        self._check(STATE_INVOICE_SENT)
        self.assertEqual(self.winner.payment_status, 'invoiced')

    def test_completed_draft_without_order_is_paid(self):
        self._check({'found': True, 'status': 'COMPLETED', 'order': None})
        self.assertEqual(self.winner.payment_status, 'paid')
        self.assertIsNotNone(self.winner.paid_at)

    def test_open_draft_stays_pending(self):
        result = self._check(STATE_OPEN)
        self.assertEqual(self.winner.payment_status, 'pending')
        self.assertFalse(result['changed'])
        self.assertIsNotNone(self.winner.payment_checked_at)

    def test_deleted_draft_means_cancelled(self):
        self._check(STATE_GONE)
        self.assertEqual(self.winner.payment_status, 'cancelled')


class SweepTests(TestCase):
    def setUp(self):
        self.event = make_event()

    @patch(SERVICE)
    def test_sweep_summary(self, mock_service):
        make_winner(self.event, make_user(1))
        make_item(self.event, make_user(2))
        mock_service.return_value.get_draft_order_payment_state.side_effect = [
            STATE_PAID, None,
        ]
        summary = payments.sweep_payments(self.event)
        self.assertEqual(summary, {'checked': 1, 'paid': 1, 'changed': 1,
                                   'failed': 1})

    @patch(SERVICE)
    def test_crash_on_one_row_does_not_kill_sweep(self, mock_service):
        make_winner(self.event, make_user(1))
        winner2 = make_winner(self.event, make_user(2))
        mock_service.return_value.get_draft_order_payment_state.side_effect = [
            RuntimeError('boom'), STATE_PAID,
        ]
        summary = payments.sweep_payments(self.event)
        self.assertEqual(summary['failed'], 1)
        self.assertEqual(summary['paid'], 1)
        winner2.refresh_from_db()
        self.assertEqual(winner2.payment_status, 'paid')

    @patch(SERVICE)
    def test_no_targets_makes_no_service(self, mock_service):
        summary = payments.sweep_payments()
        self.assertEqual(summary['checked'], 0)
        mock_service.assert_not_called()


# Plain storage so the admin-based regie template renders in tests
# (same as RegieViewTests in events/tests.py).
@override_settings(STORAGES={
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
})
class RegiePaymentsViewTests(TestCase):
    def setUp(self):
        self.event = make_event()
        self.staff = User.objects.create_superuser(
            username='admin', email='admin@test.com', password='adminpass',
        )
        self.client.force_login(self.staff)
        self.url = reverse('admin:events_event_regie_fulfill_payments',
                           args=[self.event.pk])

    @patch(SERVICE)
    def test_button_sweeps_event(self, mock_service):
        winner = make_winner(self.event, make_user(1))
        mock_service.return_value.get_draft_order_payment_state.return_value = (
            STATE_PAID
        )
        response = self.client.post(self.url)
        self.assertRedirects(
            response,
            reverse('admin:events_event_regie', args=[self.event.pk]),
        )
        winner.refresh_from_db()
        self.assertEqual(winner.payment_status, 'paid')

    def test_requires_post(self):
        self.assertEqual(self.client.get(self.url).status_code, 405)
