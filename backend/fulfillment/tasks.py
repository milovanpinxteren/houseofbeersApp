import logging
from datetime import timedelta

from celery import shared_task
from django.utils import timezone

logger = logging.getLogger(__name__)

# Local hour (Europe/Amsterdam = store time) from which the day-before
# reminder goes out. The task runs hourly and sends for every run at or
# after this hour, so a beat outage at 18:00 is caught up by the 19:00 run
# (dedupe keys make the repeats no-ops).
REMINDER_HOUR = 18

# Same spelling the campaign rule sentences use (loyalty keeps its own copy;
# the apps stay decoupled).
DUTCH_WEEKDAYS = [
    'maandag', 'dinsdag', 'woensdag', 'donderdag',
    'vrijdag', 'zaterdag', 'zondag',
]
DUTCH_MONTHS = [
    'januari', 'februari', 'maart', 'april', 'mei', 'juni',
    'juli', 'augustus', 'september', 'oktober', 'november', 'december',
]


def _local_now():
    """Current store-local time; separate so tests can freeze it."""
    return timezone.localtime()


def _dutch_date(day):
    """date -> 'vrijdag 2 oktober'."""
    return (
        f"{DUTCH_WEEKDAYS[day.weekday()]} "
        f"{day.day} {DUTCH_MONTHS[day.month - 1]}"
    )


# ignore_result: nobody reads the Celery result (the outcome lives on the
# PickupActionLog row), and WITH a result backend configured but Redis down
# (local dev) .delay() blocks ~2 minutes in the redis result-backend retry
# loop before the inline fallback can run — freezing the RSVP request.
@shared_task(bind=True, max_retries=3, default_retry_delay=60,
             ignore_result=True)
def sync_pickup_action(self, log_id):
    """
    Apply one PickupActionLog row to the customer's Shopify queue/priority
    metafields and record the outcome on the row.

    Retries 3x with 60s delay on failure; after the last attempt the row
    stays 'failed' and shows up in the admin, where the "Opnieuw
    synchroniseren met Shopify" action can re-dispatch it.
    """
    from fulfillment.models import PickupActionLog
    from fulfillment.services import shopify_sync

    try:
        log = PickupActionLog.objects.get(id=log_id)
    except PickupActionLog.DoesNotExist:
        logger.warning(f"Pickup sync: log row {log_id} no longer exists")
        return

    status, response_text = shopify_sync.push_pickup_action(log)

    log.sync_status = status
    log.sync_response = (response_text or '')[:shopify_sync.MAX_RESPONSE_CHARS]
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


@shared_task(ignore_result=True)
def send_pickup_reminders():
    """
    Hourly: from REMINDER_HOUR local onwards, remind everyone with an active
    RSVP for TOMORROW that they announced a pickup. Kind 'transactional'
    (the member asked for this by RSVPing — no marketing opt-out applies);
    one reminder per user per date, guaranteed by the dedupe key.

    The one piece of automation in this app — it only sends a message,
    it never touches the Shopify queue (that stays staff-managed).
    """
    now = _local_now()
    if now.hour < REMINDER_HOUR:
        return {'skipped': 'before send hour'}

    tomorrow = now.date() + timedelta(days=1)

    from fulfillment.models import PickupClosure, PickupRSVP, PickupSchedule

    schedule = PickupSchedule.objects.filter(
        weekday=tomorrow.weekday(), active=True,
    ).first()
    rsvps = (
        PickupRSVP.objects.filter(
            status=PickupRSVP.STATUS_ACTIVE, date=tomorrow,
        ).select_related('user')
    )

    if schedule is None or PickupClosure.objects.filter(date=tomorrow).exists():
        # Closed tomorrow. RSVPs can predate a closure (or a schedule edit);
        # don't invite people to a closed store, but make the conflict loud
        # so staff can reach out to them.
        stranded = rsvps.count()
        if stranded:
            logger.warning(
                f"Pickup reminders: {tomorrow} is closed but {stranded} "
                f"active RSVP(s) exist for it; no reminders sent"
            )
        return {'skipped': 'store closed tomorrow', 'stranded_rsvps': stranded}

    # The later runs of the evening would re-walk every RSVP only for
    # send_notification to dedupe each one; skip the already-delivered keys
    # up front so the log counts stay truthful. (Read-only peek at the
    # outbox — sends still go through send_notification only.)
    from notifications.models import NotificationDelivery

    key_for = {
        rsvp.id: f'pickup:{rsvp.user_id}:{tomorrow.isoformat()}:reminder'
        for rsvp in rsvps
    }
    delivered = set(
        NotificationDelivery.objects.filter(
            dedupe_key__in=key_for.values(), sent_at__isnull=False,
        ).values_list('dedupe_key', flat=True)
    )

    sent = 0
    for rsvp in rsvps:
        if key_for[rsvp.id] in delivered:
            continue
        try:
            from notifications.services import send_notification

            send_notification(
                rsvp.user,
                kind='transactional',
                title='Morgen afhalen bij House of Beers',
                body=(
                    f'Je hebt aangegeven morgen ({_dutch_date(tomorrow)}) je '
                    f'bestelling af te halen. We zijn open van '
                    f'{schedule.open_time:%H:%M} tot {schedule.close_time:%H:%M} '
                    f'uur — Prior van Millstraat 2, Uden. Tot morgen!'
                ),
                data={'url': '/pickup'},
                dedupe_key=key_for[rsvp.id],
            )
            sent += 1
        except Exception:
            # One broken recipient must not stop the rest; the dedupe key
            # lets the next hourly run retry just this one.
            logger.exception(
                f"Pickup reminder failed for user {rsvp.user_id} ({tomorrow})"
            )

    if sent:
        logger.info(f"Pickup reminders: {sent} sent for {tomorrow}")
    return {'date': tomorrow.isoformat(), 'sent': sent}
