"""
Celery tasks for the recommendations app.
"""
import logging

from celery import shared_task
from django.core.cache import cache

logger = logging.getLogger(__name__)


@shared_task
def refresh_random_beer_products():
    """
    Keep the random-beer product cache warm so no user request ever pays
    the multi-second paginated Shopify fetch. Runs hourly via beat (cache
    TTL is 2 hours, so the cache never goes cold between refreshes as long
    as the worker is up, even if a single run fails).
    """
    from users.services.shopify import ShopifyService
    from recommendations.views import PRODUCT_CACHE_KEY, PRODUCT_CACHE_TTL

    products = ShopifyService().get_active_products()
    if products:
        cache.set(PRODUCT_CACHE_KEY, products, PRODUCT_CACHE_TTL)
        logger.info(f"Refreshed random-beer product cache: {len(products)} products")
    else:
        # Keep whatever is cached; an empty list usually means the fetch failed
        logger.warning("Random-beer product refresh returned no products; cache left as-is")
    return {'products': len(products)}


@shared_task
def refresh_app_only_products():
    """
    Keep the app-shop cache warm. Leftover-sale products tagged `app-only`
    change after each sale and as items sell out; every 30 minutes matches
    the cache TTL. An empty list is a normal state here (no leftovers) and
    is cached too.
    """
    from users.services.shopify import ShopifyService
    from recommendations.views import APP_SHOP_CACHE_KEY, APP_SHOP_CACHE_TTL

    products = ShopifyService().get_app_only_products()
    cache.set(APP_SHOP_CACHE_KEY, products, APP_SHOP_CACHE_TTL if products else 300)
    logger.info(f"Refreshed app-shop cache: {len(products)} products")
    return {'products': len(products)}
