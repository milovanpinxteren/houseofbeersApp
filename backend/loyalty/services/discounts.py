"""Shared Shopify discount-code creation.

Extracted from LoyaltyService._create_shopify_discount so campaigns and
raffles mint codes through the same machinery as reward redemptions.
"""
import logging
from datetime import timedelta
from typing import Any, Dict, Optional

from django.utils import timezone

logger = logging.getLogger(__name__)

# Same storefront the recommendations cart permalinks target.
SHOP_BASE_URL = 'https://houseofbeers.nl'


class DiscountConfig:
    """
    Plain config for create_discount_code. Any object with the same attribute
    names works too (a Campaign instance passes directly).
    """

    def __init__(self, discount_type, discount_value=None, discount_product_gid='',
                 discount_validity_days=None, discount_title=''):
        self.discount_type = discount_type
        self.discount_value = discount_value
        self.discount_product_gid = discount_product_gid
        self.discount_validity_days = discount_validity_days
        self.discount_title = discount_title


def reward_discount_config(reward) -> Optional[DiscountConfig]:
    """
    Map a Reward to a DiscountConfig, or None when the reward type/value
    combination can't produce a Shopify discount. validity_days stays None:
    reward codes never carried a Shopify-side expiry.
    """
    title = f"Loyalty Reward - {reward.name}"

    if reward.reward_type == 'fixed_discount' and reward.discount_amount:
        return DiscountConfig('fixed_amount', reward.discount_amount, discount_title=title)
    if reward.reward_type == 'percentage_discount' and reward.discount_percentage:
        return DiscountConfig('percentage', reward.discount_percentage, discount_title=title)
    if reward.reward_type == 'free_shipping':
        return DiscountConfig('free_shipping', discount_title=title)
    if reward.reward_type == 'free_product' and reward.shopify_product_id:
        return DiscountConfig(
            'free_product',
            discount_product_gid=reward.shopify_product_id,
            discount_title=title,
        )
    return None


def build_cart_url(config, code: str, shopify_service=None) -> str:
    """
    A one-tap "redeem this code" storefront link.

    free_product codes are 100% off ONE specific product, so handing the user a
    bare code is a trap: the discount only applies once that exact product sits
    in the cart, and prize products are typically UNLISTED (not reachable by
    browsing the shop at all). For those we return a cart permalink that both
    puts the right variant in the cart AND applies the code — the same
    /cart/<variant>:1?discount=<code> shape the sixpack checkout uses.

    Every other discount type applies cart-wide, so /discount/<code> is enough:
    Shopify stores the code on the session and drops the user in the shop.

    Returns '' when no useful link can be built (never raises).
    """
    if not code:
        return ''

    discount_type = getattr(config, 'discount_type', '')
    product_gid = getattr(config, 'discount_product_gid', '') or ''

    if discount_type == 'free_product' and product_gid:
        try:
            if shopify_service is None:
                from users.services import ShopifyService
                shopify_service = ShopifyService()
            variant_id = shopify_service.get_product_cart_variant_id(product_gid)
        except Exception as e:
            logger.error(f"Cart variant lookup failed for {product_gid}: {e}")
            variant_id = None

        if variant_id:
            return f"{SHOP_BASE_URL}/cart/{variant_id}:1?discount={code}"
        # Shopify did not answer: fall through to the generic link rather than
        # leaving the user with no link at all.
        logger.warning(
            f"No cart variant for {product_gid}; falling back to /discount link"
        )

    return f"{SHOP_BASE_URL}/discount/{code}"


def create_discount_code(user, config, code: str) -> Optional[Dict[str, Any]]:
    """
    Create a single-use Shopify discount code.

    `config` needs: discount_type ('fixed_amount' | 'percentage' |
    'free_shipping' | 'free_product'), discount_value, discount_product_gid,
    discount_validity_days (None/0 = the code never expires) and optionally
    discount_title. A Campaign instance qualifies as-is.

    Returns the ShopifyService result dict (with 'code', 'cart_url' and, when
    the config sets validity, 'expires_at' added) or None on any failure —
    never raises.
    """
    from users.services import ShopifyService

    try:
        shopify_service = ShopifyService()
        title = (
            getattr(config, 'discount_title', '')
            or f"Campaign - {getattr(config, 'name', code)}"
        )
        validity_days = getattr(config, 'discount_validity_days', None)
        ends_at = timezone.now() + timedelta(days=validity_days) if validity_days else None
        discount_type = config.discount_type
        result = None

        if discount_type in ('fixed_amount', 'percentage') and config.discount_value:
            result = shopify_service.create_basic_discount(
                code=code,
                title=title,
                discount_type=discount_type,
                value=float(config.discount_value),
                usage_limit=1,
                ends_at=ends_at,
            )

        elif discount_type == 'free_shipping':
            result = shopify_service.create_free_shipping_discount(
                code=code,
                title=title,
                usage_limit=1,
            )

        elif discount_type == 'free_product' and getattr(config, 'discount_product_gid', ''):
            result = shopify_service.create_free_product_discount(
                code=code,
                title=title,
                product_id=config.discount_product_gid,
                usage_limit=1,
            )

        else:
            logger.warning(f"Cannot create Shopify discount for type: {discount_type}")
            return None

        if result is None:
            return None

        result = dict(result)
        result.setdefault('code', code)
        result['expires_at'] = ends_at
        result['cart_url'] = build_cart_url(config, code, shopify_service)
        return result
    except Exception as e:
        logger.error(f"Failed to create Shopify discount: {e}")
        return None
