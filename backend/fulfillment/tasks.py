import logging

from celery import shared_task

logger = logging.getLogger(__name__)


# ignore_result: nobody reads the Celery result (the outcome lives on the
# PickupActionLog row), and WITH a result backend configured but Redis down
# (local dev) .delay() blocks ~2 minutes in the redis result-backend retry
# loop before the inline fallback can run — freezing the RSVP request.
@shared_task(bind=True, max_retries=3, default_retry_delay=60,
             ignore_result=True)
def sync_pickup_action(self, log_id):
    """
    Push one PickupActionLog row to hob and record the outcome on the row.

    Retries 3x with 60s delay on failure; after the last attempt the row
    stays 'failed' and shows up in the admin, where the "Opnieuw
    synchroniseren met hob" action can re-dispatch it.
    """
    from fulfillment.models import PickupActionLog
    from fulfillment.services import hob_sync

    try:
        log = PickupActionLog.objects.get(id=log_id)
    except PickupActionLog.DoesNotExist:
        logger.warning(f"Pickup sync: log row {log_id} no longer exists")
        return

    status, response_text = hob_sync.push_pickup_action(log)

    log.sync_status = status
    log.sync_response = (response_text or '')[:hob_sync.MAX_RESPONSE_CHARS]
    if status != 'skipped':
        log.sync_attempts += 1
    log.save(update_fields=[
        'sync_status', 'sync_response', 'sync_attempts', 'updated_at',
    ])

    if status == 'failed':
        logger.error(
            f"Pickup sync failed for log {log_id} "
            f"(attempt {log.sync_attempts}): {response_text[:200]}"
        )
        raise self.retry(exc=Exception(response_text[:200]))

    logger.info(f"Pickup sync {status} for log {log_id}")
    return {'log_id': log_id, 'status': status}
