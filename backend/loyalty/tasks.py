import logging
from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def partial_sync_user_points(self, user_id):
    """Incrementally sync new orders since last sync for a single user."""
    from users.models import User
    from loyalty.services import LoyaltyService

    try:
        user = User.objects.get(id=user_id)
    except User.DoesNotExist:
        logger.error(f"User {user_id} not found for partial sync")
        return

    service = LoyaltyService()
    result = service.partial_sync_for_user(user)

    if result.get('success'):
        logger.info(
            f"Partial sync completed for {user.email}: "
            f"+{result.get('total_awarded', 0)} points from "
            f"{result.get('processed_count', 0)} orders"
        )
    else:
        error = result.get('error', 'Unknown error')
        if error == 'Sync already in progress':
            logger.info(f"Skipping {user.email}: sync already in progress")
            return
        logger.error(f"Partial sync failed for {user.email}: {error}")
        raise self.retry(exc=Exception(error))


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def intermediate_sync_user_points(self, user_id):
    """Fetch all orders, process only unprocessed ones."""
    from users.models import User
    from loyalty.services import LoyaltyService

    try:
        user = User.objects.get(id=user_id)
    except User.DoesNotExist:
        logger.error(f"User {user_id} not found for intermediate sync")
        return

    service = LoyaltyService()
    result = service.intermediate_sync_for_user(user)

    if result.get('success'):
        logger.info(
            f"Intermediate sync completed for {user.email}: "
            f"+{result.get('total_awarded', 0)} points from "
            f"{result.get('processed_count', 0)} orders"
        )
    else:
        error = result.get('error', 'Unknown error')
        if error == 'Sync already in progress':
            logger.info(f"Skipping {user.email}: sync already in progress")
            return
        logger.error(f"Intermediate sync failed for {user.email}: {error}")
        raise self.retry(exc=Exception(error))


@shared_task(bind=True, max_retries=2, default_retry_delay=120)
def full_sync_user_points(self, user_id):
    """Check-and-correct: recalculate points per order, adjust differences. Admin only."""
    from users.models import User
    from loyalty.services import LoyaltyService

    try:
        user = User.objects.get(id=user_id)
    except User.DoesNotExist:
        logger.error(f"User {user_id} not found for full sync")
        return

    service = LoyaltyService()
    result = service.full_sync_for_user(user)

    if result.get('success'):
        logger.info(
            f"Full sync completed for {user.email}: "
            f"net adjustment {result.get('net_adjustment', 0):+d}, "
            f"{result.get('corrected_count', 0)} corrected, "
            f"{result.get('new_count', 0)} new"
        )
    else:
        error = result.get('error', 'Unknown error')
        if error == 'Sync already in progress':
            logger.info(f"Skipping {user.email}: sync already in progress")
            return
        logger.error(f"Full sync failed for {user.email}: {error}")
        raise self.retry(exc=Exception(error))


@shared_task
def periodic_partial_sync():
    """Every 3 hours: partial sync (new orders only) for all active users."""
    from users.models import User

    users = User.objects.filter(
        shopify_customer_id__isnull=False
    ).exclude(
        shopify_customer_id=''
    )

    count = 0
    for i, user in enumerate(users):
        partial_sync_user_points.apply_async(
            args=[user.id],
            countdown=i * 2,  # Stagger 2s apart to respect Shopify rate limits
        )
        count += 1

    logger.info(f"Dispatched partial sync for {count} users")


@shared_task
def periodic_intermediate_sync():
    """Nightly: intermediate sync (all orders, process unprocessed) for all active users."""
    from users.models import User

    users = User.objects.filter(
        shopify_customer_id__isnull=False
    ).exclude(
        shopify_customer_id=''
    )

    count = 0
    for i, user in enumerate(users):
        intermediate_sync_user_points.apply_async(
            args=[user.id],
            countdown=i * 2,
        )
        count += 1

    logger.info(f"Dispatched intermediate sync for {count} users")
