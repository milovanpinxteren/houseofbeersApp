"""
Tests for the one-tap redeem link on discount codes.

A free_product code is 100% off ONE product and prize products are typically
UNLISTED in the webshop, so a bare code is unredeemable by browsing: the fix is
a cart permalink that adds the right variant AND applies the code.
"""
from unittest.mock import MagicMock, patch

from django.utils import timezone
from rest_framework.test import APIClient

from loyalty.models import (
    Campaign, CampaignAward, CampaignProgress, CampaignRaffleWinner,
)
from loyalty.services.discounts import SHOP_BASE_URL, build_cart_url, create_discount_code
from loyalty.test_campaigns import CampaignTestCase
from loyalty.test_raffles import RaffleTestCase

PRODUCT_GID = 'gid://shopify/Product/11068121514322'


def fake_shopify(variant_id='54382170079570'):
    service = MagicMock()
    service.get_product_cart_variant_id.return_value = variant_id
    return service


class BuildCartUrlTest(CampaignTestCase):
    """build_cart_url picks the link shape from the discount type."""

    def config(self, **kwargs):
        defaults = {
            'discount_type': 'free_product',
            'discount_product_gid': PRODUCT_GID,
        }
        defaults.update(kwargs)
        return Campaign(**defaults)

    def test_free_product_gets_cart_permalink_with_code(self):
        service = fake_shopify()
        url = build_cart_url(self.config(), 'HOB-ABC12345', service)
        self.assertEqual(
            url, f'{SHOP_BASE_URL}/cart/54382170079570:1?discount=HOB-ABC12345'
        )
        service.get_product_cart_variant_id.assert_called_once_with(PRODUCT_GID)

    def test_cart_wide_types_get_the_generic_discount_link(self):
        for discount_type in ('percentage', 'fixed_amount', 'free_shipping'):
            with self.subTest(discount_type=discount_type):
                url = build_cart_url(
                    self.config(discount_type=discount_type,
                                discount_product_gid=''),
                    'HOB-ABC12345',
                    fake_shopify(),
                )
                self.assertEqual(url, f'{SHOP_BASE_URL}/discount/HOB-ABC12345')

    def test_falls_back_to_generic_link_when_variant_lookup_fails(self):
        # Shopify silence must not leave the member with no link at all.
        url = build_cart_url(self.config(), 'HOB-ABC12345', fake_shopify(None))
        self.assertEqual(url, f'{SHOP_BASE_URL}/discount/HOB-ABC12345')

    def test_shopify_exception_is_swallowed(self):
        service = MagicMock()
        service.get_product_cart_variant_id.side_effect = RuntimeError('down')
        url = build_cart_url(self.config(), 'HOB-ABC12345', service)
        self.assertEqual(url, f'{SHOP_BASE_URL}/discount/HOB-ABC12345')

    def test_no_code_no_link(self):
        self.assertEqual(build_cart_url(self.config(), '', fake_shopify()), '')

    def test_free_product_without_a_product_gid(self):
        url = build_cart_url(
            self.config(discount_product_gid=''), 'HOB-ABC12345', fake_shopify()
        )
        self.assertEqual(url, f'{SHOP_BASE_URL}/discount/HOB-ABC12345')


class CreateDiscountCodeCartUrlTest(CampaignTestCase):
    """create_discount_code hands the cart link back with the minted code."""

    def test_result_carries_cart_url(self):
        user = self.make_user()
        campaign = self.make_campaign(
            action_type='discount_code',
            discount_type='free_product',
            discount_product_gid=PRODUCT_GID,
        )
        service = fake_shopify()
        service.create_free_product_discount.return_value = {
            'discount_id': 'gid://shopify/DiscountCodeNode/1',
        }
        with patch('users.services.ShopifyService', return_value=service):
            result = create_discount_code(user, campaign, 'HOB-ABC12345')

        self.assertEqual(
            result['cart_url'],
            f'{SHOP_BASE_URL}/cart/54382170079570:1?discount=HOB-ABC12345',
        )


class CampaignApiCartUrlTest(CampaignTestCase):
    """The Acties card gets the link so the member can redeem in one tap."""

    def test_qualified_discount_campaign_serves_cart_url(self):
        user = self.make_user()
        campaign = self.make_campaign(
            action_type='discount_code',
            discount_type='free_product',
            discount_product_gid=PRODUCT_GID,
        )
        CampaignProgress.objects.create(
            campaign=campaign, user=user, qualified_at=timezone.now(),
        )
        CampaignAward.objects.create(
            campaign=campaign, user=user,
            discount_code='HOB-ABC12345',
            cart_url=f'{SHOP_BASE_URL}/cart/54382170079570:1?discount=HOB-ABC12345',
        )

        client = APIClient()
        client.force_authenticate(user=user)
        row = client.get('/api/loyalty/campaigns/').json()['campaigns'][0]
        self.assertEqual(
            row['discount_cart_url'],
            f'{SHOP_BASE_URL}/cart/54382170079570:1?discount=HOB-ABC12345',
        )

    def test_teaser_has_no_cart_url(self):
        user = self.make_user()
        self.make_campaign(action_type='discount_code')
        client = APIClient()
        client.force_authenticate(user=user)
        row = client.get('/api/loyalty/campaigns/').json()['campaigns'][0]
        self.assertIsNone(row['discount_cart_url'])


class RafflePrizeCartUrlTest(RaffleTestCase):
    """Prize codes get the same link, stored at fulfillment and served post-draw."""

    def test_fulfillment_stores_cart_url(self):
        _campaign, raffle = self.make_raffle(
            fulfillment_type='shopify_code',
            discount_type='free_product',
            discount_product_gid=PRODUCT_GID,
        )
        winner_user = self.make_user('winner@example.com')
        self.enter(raffle, winner_user)

        cart_url = f'{SHOP_BASE_URL}/cart/54382170079570:1?discount=WIN-ABC12345'
        with patch('loyalty.services.discounts.create_discount_code', return_value={
            'discount_id': 'gid://shopify/DiscountCodeNode/9',
            'code': 'WIN-ABC12345',
            'expires_at': None,
            'cart_url': cart_url,
        }):
            self.draw(raffle)

        winner = CampaignRaffleWinner.objects.get(raffle=raffle)
        self.assertEqual(winner.cart_url, cart_url)

        client = APIClient()
        client.force_authenticate(user=winner_user)
        row = client.get('/api/loyalty/raffles/').json()['raffles'][0]
        self.assertTrue(row['did_win'])
        self.assertEqual(row['my_code_cart_url'], cart_url)
