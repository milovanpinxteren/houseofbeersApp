"""
Tests for sixpack charm pricing and the checkout endpoint.
"""

from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from recommendations.models import SixpackCheckout
from recommendations.pricing import charm_price

User = get_user_model()


class CharmPriceTests(TestCase):

    def test_typical_pack_lands_on_charm_price(self):
        result = charm_price(Decimal('54.30'))
        self.assertTrue(result['charm'])
        cents = result['price'] % 1
        self.assertIn(cents, (Decimal('0.49'), Decimal('0.99')))
        pct = result['discount'] / result['value']
        self.assertGreaterEqual(pct, Decimal('0.03'))
        self.assertLessEqual(pct, Decimal('0.08'))

    def test_examples(self):
        self.assertEqual(charm_price(Decimal('52.40'))['price'], Decimal('49.99'))
        self.assertEqual(charm_price(Decimal('31.20'))['price'], Decimal('29.49'))
        self.assertEqual(charm_price(Decimal('68.10'))['price'], Decimal('64.49'))
        self.assertEqual(charm_price(Decimal('12.40'))['price'], Decimal('11.99'))

    def test_small_value_fallback(self):
        # Below ~€10 the 3-8% clamp window is narrower than the €0.50 charm
        # steps, so no charm candidate fits and a plain 5% applies.
        result = charm_price(Decimal('6.00'))
        self.assertFalse(result['charm'])
        self.assertEqual(result['discount'], Decimal('0.30'))
        self.assertEqual(result['price'], Decimal('5.70'))

    def test_zero_and_invalid_guard(self):
        for bad in (0, Decimal('0'), None, 'abc', -5):
            result = charm_price(bad)
            self.assertEqual(result['discount'], Decimal('0.00'))
            self.assertFalse(result['charm'])

    def test_clamp_property_over_range(self):
        value = Decimal('20.00')
        while value <= Decimal('150.00'):
            result = charm_price(value)
            self.assertGreater(result['discount'], 0)
            self.assertLess(result['price'], value)
            pct = result['discount'] / value
            if result['charm']:
                self.assertGreaterEqual(pct, Decimal('0.03'))
                self.assertLessEqual(pct, Decimal('0.08'))
            self.assertEqual(result['price'] + result['discount'], result['value'])
            value += Decimal('0.73')


FAKE_PRODUCTS = [
    {'id': 100 + i, 'title': f'Beer {i}', 'product_type': 'Beer',
     'tags': [], 'price': '9.50', 'image_url': '', 'handle': f'beer-{i}'}
    for i in range(6)
]


def _items():
    return [
        {'shopify_id': str(100 + i), 'variant_id': str(900 + i)}
        for i in range(6)
    ]


@patch('recommendations.views._get_shop_products', return_value=FAKE_PRODUCTS)
class SixpackCheckoutViewTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user(
            email='tester@example.com', password='secret123',
            username='tester@example.com',
        )
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.url = '/api/recommendations/sixpack/checkout/'

    def _post(self, items=None):
        return self.client.post(
            self.url, {'items': items or _items()}, format='json'
        )

    @patch('recommendations.views.ShopifyService')
    def test_happy_path_mints_code(self, shopify_cls, _products):
        shopify_cls.return_value.create_basic_discount.return_value = {
            'discount_id': 'gid://shopify/Discount/1', 'code': 'SIX-TEST1234',
        }
        response = self._post()
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['value'], '57.00')
        self.assertIn('discount=', data['cart_url'])
        self.assertTrue(data['code'].startswith('SIX-'))
        self.assertEqual(SixpackCheckout.objects.count(), 1)

        kwargs = shopify_cls.return_value.create_basic_discount.call_args.kwargs
        self.assertEqual(kwargs['discount_type'], 'fixed_amount')
        self.assertEqual(kwargs['usage_limit'], 1)
        self.assertAlmostEqual(kwargs['minimum_subtotal'], 55.86, places=2)
        # The pack code stacks with the member's other codes: no override, so
        # create_basic_discount applies the combines-with-everything default.
        self.assertNotIn('combines_with', kwargs)

    @patch('recommendations.views.ShopifyService')
    def test_identical_pack_reuses_code(self, shopify_cls, _products):
        shopify_cls.return_value.create_basic_discount.return_value = {
            'discount_id': 'gid://shopify/Discount/1', 'code': 'X',
        }
        first = self._post().json()
        second = self._post().json()
        self.assertEqual(first['code'], second['code'])
        self.assertEqual(SixpackCheckout.objects.count(), 1)
        self.assertEqual(
            shopify_cls.return_value.create_basic_discount.call_count, 1
        )

    def test_unavailable_product_returns_409(self, _products):
        items = _items()
        items[0]['shopify_id'] = '999999'
        response = self._post(items)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()['unavailable'], ['999999'])

    @patch('recommendations.views.ShopifyService')
    def test_shopify_failure_returns_502_without_row(self, shopify_cls, _products):
        shopify_cls.return_value.create_basic_discount.return_value = None
        response = self._post()
        self.assertEqual(response.status_code, 502)
        self.assertEqual(SixpackCheckout.objects.count(), 0)

    def test_rejects_wrong_item_count(self, _products):
        response = self._post(_items()[:5])
        self.assertEqual(response.status_code, 400)

    def test_rejects_duplicate_items(self, _products):
        items = _items()
        items[1] = dict(items[0])
        response = self._post(items)
        self.assertEqual(response.status_code, 400)
