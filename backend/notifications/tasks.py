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


# Recipients are handed to send_notification in batches with a short gap
# between them. Blasting a few hundred emails at a shared SMTP host in one
# burst is the fastest way to hurt deliverability for every other message the
# shop sends, including password resets.
BROADCAST_BATCH_SIZE = 25
BROADCAST_BATCH_PAUSE_SECONDS = 2


@shared_task
def send_broadcast(broadcast_id):
    """
    Fan one Broadcast out to its audience, one delivery row per recipient.

    Claims the row before doing any work, so two overlapping runs (a retry, or
    the scheduler firing while a manual send is already going) cannot both
    send it. Per-recipient dedupe keys mean a re-run after a crash resumes
    rather than duplicating.
    """
    import time

    from django.db import transaction

    from .models import Broadcast
    from .services import send_notification

    # Claim: only one worker can move it out of a queued state.
    with transaction.atomic():
        claimed = (
            Broadcast.objects
            .select_for_update()
            .filter(
                pk=broadcast_id,
                status__in=[Broadcast.STATUS_SCHEDULED, Broadcast.STATUS_DRAFT],
            )
            .update(status=Broadcast.STATUS_SENDING)
        )
    if not claimed:
        logger.info(
            f"Broadcast {broadcast_id} was not in a sendable state "
            f"(already sending or sent); skipping"
        )
        return {'skipped': 'not claimable'}

    broadcast = Broadcast.objects.get(pk=broadcast_id)

    push_sent = 0
    email_sent = 0
    total = 0

    try:
        recipients = list(broadcast.resolve_recipients())
        total = len(recipients)
        logger.info(f"Broadcast {broadcast_id} fanning out to {total} recipient(s)")

        for index, user in enumerate(recipients):
            try:
                delivery = send_notification(
                    user,
                    kind=broadcast.kind,
                    title=broadcast.title,
                    body=broadcast.body,
                    data={'url': broadcast.url or '/'},
                    dedupe_key=f'broadcast:{broadcast.pk}:{user.pk}',
                    # A push-only audience must never generate email, whatever
                    # the kind's usual policy says.
                    email_policy=(
                        'never'
                        if broadcast.audience == Broadcast.AUDIENCE_PUSH_ONLY
                        else None
                    ),
                )
                if delivery.push_status == 'sent':
                    push_sent += 1
                if delivery.email_status == 'sent':
                    email_sent += 1
            except Exception as exc:
                # One bad recipient must not abandon the rest of the audience.
                logger.error(
                    f"Broadcast {broadcast_id} failed for user {user.pk}: {exc}",
                    exc_info=True,
                )

            if (index + 1) % BROADCAST_BATCH_SIZE == 0 and index + 1 < total:
                time.sleep(BROADCAST_BATCH_PAUSE_SECONDS)

        Broadcast.objects.filter(pk=broadcast_id).update(
            status=Broadcast.STATUS_SENT,
            sent_at=timezone.now(),
            recipient_count=total,
            push_sent_count=push_sent,
            email_sent_count=email_sent,
            error='',
        )
        logger.info(
            f"Broadcast {broadcast_id} complete: {total} recipients, "
            f"{push_sent} push, {email_sent} email"
        )
    except Exception as exc:
        logger.error(f"Broadcast {broadcast_id} failed: {exc}", exc_info=True)
        Broadcast.objects.filter(pk=broadcast_id).update(
            status=Broadcast.STATUS_FAILED,
            recipient_count=total,
            push_sent_count=push_sent,
            email_sent_count=email_sent,
            error=str(exc)[:1000],
        )
        raise

    return {'recipients': total, 'push': push_sent, 'email': email_sent}


@shared_task
def process_scheduled_broadcasts():
    """Queue any scheduled message whose time has come."""
    from .models import Broadcast

    due = Broadcast.objects.filter(
        status=Broadcast.STATUS_SCHEDULED,
        scheduled_for__lte=timezone.now(),
    ).values_list('pk', flat=True)

    for pk in due:
        send_broadcast.delay(pk)

    if due:
        logger.info(f"Queued {len(due)} scheduled broadcast(s)")
    return {'queued': len(due)}
