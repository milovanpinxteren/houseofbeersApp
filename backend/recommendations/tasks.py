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
    the multi-second paginated Shopify fetch. Runs every 10 minutes via
    beat (cache TTL is 15 minutes, so the cache never goes cold between
    refreshes as long as the worker is up).
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
