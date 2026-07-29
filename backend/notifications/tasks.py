import logging

from celery import shared_task
from django.utils import timezone

logger = logging.getLogger(__name__)


@shared_task
def prune_push_subscriptions():
    """Retire dead push subscriptions and clean up long-retired rows.

    Web push is queued, not delivered, at send time - a 201/202 from the push
    service says nothing about whether a phone showed the message. Without this
    second stage, dead subscriptions accumulate and quietly swallow messages
    while every send still looks successful. Anyone whose subscription dies
    here falls into the email path on the next send, which is the correct
    outcome.
    """
    from .models import FAILURE_THRESHOLD, RETENTION_DAYS, PushSubscription

    now = timezone.now()

    deactivated = PushSubscription.objects.filter(
        is_active=True, failure_count__gte=FAILURE_THRESHOLD,
    ).update(is_active=False, deactivated_at=now)

    cutoff = now - timezone.timedelta(days=RETENTION_DAYS)
    deleted, _ = PushSubscription.objects.filter(
        is_active=False, deactivated_at__lt=cutoff,
    ).delete()

    logger.info(
        f"Push subscription prune: deactivated {deactivated} "
        f"(>= {FAILURE_THRESHOLD} failures), deleted {deleted} "
        f"retired more than {RETENTION_DAYS} days ago"
    )
    return {'deactivated': deactivated, 'deleted': deleted}
