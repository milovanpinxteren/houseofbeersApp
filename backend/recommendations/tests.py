from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import override_settings
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from users.services.shopify import ShopifyService
from .views import PRODUCT_CACHE_KEY

User = get_user_model()


def _product(**overrides):
    product = {
        'id': 1,
        'title': 'Test IPA',
        'product_type': 'IPA',
        'tags': ['hoppy', 'new'],
        'price': '4.50',
        'image_url': 'https://cdn.shopify.com/ipa.jpg',
        'handle': 'test-ipa',
    }
    product.update(overrides)
    return product


PRODUCTS = [
    _product(id=1, title='Test IPA', product_type='IPA', tags=['hoppy'],
             price='4.50', handle='test-ipa'),
    _product(id=2, title='Dark Stout', product_type='Stout', tags=['dark', 'roasty'],
             price='6.95', handle='dark-stout'),
    _product(id=3, title='Sour Ale', product_type='Sour', tags=['fruity'],
             price='12.00', handle='sour-ale'),
    _product(id=4, title='Mystery Beer', product_type='', tags=['ipa'],
             price=None, handle='mystery-beer'),
]


@override_settings(CACHES={
    'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}
})
class RandomBeerViewTests(APITestCase):
    """GET /api/recommendations/random-beer/ — filtering, empty case, cache."""

    def setUp(self):
        self.url = reverse('random-beer')
        self.user = User.objects.create_user(
            username='beerfan', email='beerfan@example.com', password='SuperSecret123!'
        )
        self.client.force_authenticate(user=self.user)
        cache.delete(PRODUCT_CACHE_KEY)

        patcher = patch('recommendations.views.ShopifyService')
        self.mock_shopify_cls = patcher.start()
        self.addCleanup(patcher.stop)
        self.mock_service = self.mock_shopify_cls.return_value
        self.mock_service.get_active_products.return_value = list(PRODUCTS)

    def test_requires_authentication(self):
        self.client.force_authenticate(user=None)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_returns_random_beer_with_shop_url_and_styles(self):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data['found'])
        beer = response.data['beer']
        self.assertIn(beer['id'], [p['id'] for p in PRODUCTS])
        self.assertEqual(
            beer['shop_url'],
            f"https://houseofbeers.nl/products/{beer['handle']}"
        )
        # Distinct, non-empty product types, sorted (product 4 has none)
        self.assertEqual(response.data['styles'], ['IPA', 'Sour', 'Stout'])

    def test_style_filter_matches_product_type_case_insensitive(self):
        response = self.client.get(self.url, {'style': 'stout'})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data['found'])
        self.assertEqual(response.data['beer']['id'], 2)

    def test_style_filter_matches_tags(self):
        # 'hoppy' is only a tag, never a product_type
        response = self.client.get(self.url, {'style': 'HOPPY'})

        self.assertTrue(response.data['found'])
        self.assertEqual(response.data['beer']['id'], 1)

    def test_style_filter_matches_type_or_tag(self):
        # 'ipa' matches product 1 (type) and product 4 (tag)
        response = self.client.get(self.url, {'style': 'ipa'})

        self.assertTrue(response.data['found'])
        self.assertIn(response.data['beer']['id'], [1, 4])

    def test_max_price_filter(self):
        response = self.client.get(self.url, {'max_price': '5.00'})

        self.assertTrue(response.data['found'])
        # Only product 1 (4.50) is <= 5.00; products without a price are excluded
        self.assertEqual(response.data['beer']['id'], 1)

    def test_combined_filters(self):
        response = self.client.get(self.url, {'style': 'stout', 'max_price': '7.00'})

        self.assertTrue(response.data['found'])
        self.assertEqual(response.data['beer']['id'], 2)

    def test_no_match_returns_found_false_with_styles(self):
        response = self.client.get(self.url, {'style': 'stout', 'max_price': '1.00'})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(response.data['found'])
        self.assertNotIn('beer', response.data)
        # Styles still included so the client can offer looser filters
        self.assertEqual(response.data['styles'], ['IPA', 'Sour', 'Stout'])

    def test_unknown_style_returns_found_false(self):
        response = self.client.get(self.url, {'style': 'Barleywine'})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(response.data['found'])

    def test_empty_product_list_returns_found_false(self):
        self.mock_service.get_active_products.return_value = []

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(response.data['found'])
        self.assertEqual(response.data['styles'], [])

    def test_styles_only_returns_styles_without_a_beer(self):
        response = self.client.get(self.url, {'styles_only': '1'})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, {'styles': ['IPA', 'Sour', 'Stout']})

    def test_invalid_max_price_rejected(self):
        response = self.client.get(self.url, {'max_price': 'abc'})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_product_list_is_cached_between_spins(self):
        self.client.get(self.url)
        self.client.get(self.url)

        self.assertEqual(self.mock_service.get_active_products.call_count, 1)

    def test_empty_product_list_is_not_cached(self):
        """A failed/empty Shopify fetch must not pin an empty list for 15 min."""
        self.mock_service.get_active_products.return_value = []
        self.client.get(self.url)

        self.mock_service.get_active_products.return_value = list(PRODUCTS)
        response = self.client.get(self.url)

        self.assertTrue(response.data['found'])
        self.assertEqual(self.mock_service.get_active_products.call_count, 2)


class GetActiveProductsTests(APITestCase):
    """ShopifyService.get_active_products — parsing and stock filtering."""

    def _raw_product(self, **overrides):
        product = {
            'id': 10,
            'title': 'Raw IPA',
            'product_type': 'IPA',
            'tags': 'hoppy, new ',
            'handle': 'raw-ipa',
            'created_at': '2026-08-01T12:00:00+02:00',
            'image': {'src': 'https://cdn.shopify.com/raw.jpg'},
            'variants': [{
                'id': 501,
                'price': '5.25',
                'inventory_management': 'shopify',
                'inventory_policy': 'deny',
                'inventory_quantity': 3,
            }],
        }
        product.update(overrides)
        return product

    @patch.object(ShopifyService, '_paginated_request')
    def test_parses_product_fields(self, mock_request):
        mock_request.return_value = [self._raw_product()]

        products = ShopifyService().get_active_products()

        mock_request.assert_called_once_with(
            'products.json?limit=250&status=active', data_key='products'
        )
        self.assertEqual(len(products), 1)
        self.assertEqual(products[0], {
            'id': 10,
            'title': 'Raw IPA',
            'product_type': 'IPA',
            'tags': ['hoppy', 'new'],
            'price': '5.25',
            'variant_id': '501',
            'image_url': 'https://cdn.shopify.com/raw.jpg',
            'handle': 'raw-ipa',
            'created_at': '2026-08-01T12:00:00+02:00',
        })

    @patch.object(ShopifyService, '_paginated_request')
    def test_excludes_out_of_stock_products(self, mock_request):
        out_of_stock = self._raw_product(id=11, variants=[{
            'price': '5.25',
            'inventory_management': 'shopify',
            'inventory_policy': 'deny',
            'inventory_quantity': 0,
        }])
        mock_request.return_value = [self._raw_product(), out_of_stock]

        products = ShopifyService().get_active_products()

        self.assertEqual([p['id'] for p in products], [10])

    @patch.object(ShopifyService, '_paginated_request')
    def test_untracked_inventory_counts_as_in_stock(self, mock_request):
        untracked = self._raw_product(id=12, variants=[{
            'price': '3.00',
            'inventory_management': None,
            'inventory_quantity': 0,
        }])
        mock_request.return_value = [untracked]

        products = ShopifyService().get_active_products()

        self.assertEqual([p['id'] for p in products], [12])

    @patch.object(ShopifyService, '_paginated_request')
    def test_continue_policy_counts_as_in_stock(self, mock_request):
        oversellable = self._raw_product(id=13, variants=[{
            'price': '3.00',
            'inventory_management': 'shopify',
            'inventory_policy': 'continue',
            'inventory_quantity': 0,
        }])
        mock_request.return_value = [oversellable]

        products = ShopifyService().get_active_products()

        self.assertEqual([p['id'] for p in products], [13])

    @patch.object(ShopifyService, '_paginated_request')
    def test_product_without_variants_is_excluded(self, mock_request):
        mock_request.return_value = [self._raw_product(id=14, variants=[])]

        products = ShopifyService().get_active_products()

        self.assertEqual(products, [])
