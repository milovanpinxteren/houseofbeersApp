import logging

from celery import shared_task
from django.core.cache import cache
from django.utils import timezone

logger = logging.getLogger(__name__)

# Ready reports live a day (the dashboard shows built-at + a refresh button);
# the 'running' marker is short so a dead worker can't lock a range forever.
REVENUE_READY_TTL = 24 * 3600
REVENUE_RUNNING_TTL = 10 * 60


def revenue_cache_key(start_date, end_date) -> str:
    """Cache key for the Shopify revenue report of an inclusive date range."""
    return f'analytics:revenue:v4:{start_date}:{end_date}'


@shared_task
def build_revenue_report(start_date: str, end_date: str):
    """
    Build the Shopify revenue report for [start_date, end_date] (ISO dates)
    in the worker, so the dashboard never blocks on Shopify round-trips.
    """
    from users.services.shopify import ShopifyService

    key = revenue_cache_key(start_date, end_date)
    try:
        report = ShopifyService().get_app_sales_report(start_date, end_date)
    except Exception:
        logger.exception(f"Revenue report build failed for {start_date}..{end_date}")
        report = None

    if report is None:
        cache.set(
            key,
            {'status': 'failed', 'built_at': timezone.now().isoformat()},
            REVENUE_RUNNING_TTL,
        )
        return 'failed'

    cache.set(
        key,
        {'status': 'ready', 'built_at': timezone.now().isoformat(), 'data': report},
        REVENUE_READY_TTL,
    )
    return 'ready'
