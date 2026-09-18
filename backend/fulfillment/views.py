import logging
from datetime import date as date_cls, timedelta

from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import PickupClosure, PickupRSVP, PickupSchedule, PickupActionLog

logger = logging.getLogger(__name__)

# How far ahead members can announce a pickup: today + the next 13 days.
DAYS_AHEAD = 14


def _local_now():
    """
    Current local wall-clock time. TIME_ZONE is Europe/Amsterdam (checked),
    so Django's localtime IS store time; if that setting ever changes this
    is the one place to pin the store timezone explicitly.
    """
    return timezone.localtime()


def get_offered_days():
    """
    The pickup days currently on offer: the next DAYS_AHEAD calendar days
    whose weekday has an active PickupSchedule, minus closure dates. Today
    only counts while the store is still open (before close_time, local).
    """
    now = _local_now()
    today = now.date()
    horizon = today + timedelta(days=DAYS_AHEAD)

    schedules = {}
    for schedule in PickupSchedule.objects.filter(active=True):
        schedules.setdefault(schedule.weekday, schedule)
    closures = set(
        PickupClosure.objects.filter(
            date__gte=today, date__lt=horizon
        ).values_list('date', flat=True)
    )

    days = []
    for offset in range(DAYS_AHEAD):
        day = today + timedelta(days=offset)
        schedule = schedules.get(day.weekday())
        if not schedule or day in closures:
            continue
        if offset == 0 and now.time() >= schedule.close_time:
            continue  # store already closed today
        days.append({
            'date': day,
            'open_time': schedule.open_time,
            'close_time': schedule.close_time,
        })
    return days


def _parse_date(value):
    """'YYYY-MM-DD' -> date, or None on any malformed input."""
    if not isinstance(value, str):
        return None
    try:
        return date_cls.fromisoformat(value)
    except ValueError:
        return None


def _dispatch_sync(log):
    """
    Dispatch the hob sync task; fall back to running it inline when the
    broker is unreachable (local dev without Redis) — same idiom as the
    Campagne Studio's _dispatch_task. A sync failure must never fail the
    RSVP request: the log row keeps the failure visible.
    """
    from .tasks import sync_pickup_action
    try:
        sync_pickup_action.delay(log.id)
    except Exception as e:
        logger.warning(f"Celery unavailable ({e}); running pickup sync inline")
        try:
            sync_pickup_action(log.id)
        except Exception as e2:
            logger.error(f"Inline pickup sync failed for log {log.id}: {e2}")


class PickupDaysView(APIView):
    """The pickup days on offer, with the caller's RSVP status per day."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        days = get_offered_days()
        rsvp_dates = set(
            PickupRSVP.objects.filter(
                user=request.user,
                status=PickupRSVP.STATUS_ACTIVE,
                date__in=[d['date'] for d in days],
            ).values_list('date', flat=True)
        )
        return Response({
            'days': [
                {
                    'date': d['date'].isoformat(),
                    'open_time': d['open_time'].strftime('%H:%M'),
                    'close_time': d['close_time'].strftime('%H:%M'),
                    'rsvp': d['date'] in rsvp_dates,
                }
                for d in days
            ]
        })


class PickupRSVPView(APIView):
    """Announce a pickup on an offered day. Idempotent."""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        day = _parse_date(request.data.get('date'))
        if not day:
            return Response(
                {'error': 'A valid date (YYYY-MM-DD) is required.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        offered = {d['date'] for d in get_offered_days()}
        if day not in offered:
            return Response(
                {'error': 'This date is not an available pickup day.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        rsvp, created = PickupRSVP.objects.get_or_create(
            user=request.user, date=day,
        )
        if not created and rsvp.status == PickupRSVP.STATUS_ACTIVE:
            # Already announced: no-op success, no new log row.
            return Response({'date': day.isoformat(), 'rsvp': True})
        if not created:
            # Re-RSVP after cancel reactivates the same row.
            rsvp.status = PickupRSVP.STATUS_ACTIVE
            rsvp.cancelled_at = None
            rsvp.save(update_fields=['status', 'cancelled_at', 'updated_at'])

        log = PickupActionLog.objects.create(
            user=request.user, rsvp=rsvp, action='rsvp', pickup_date=day,
        )
        _dispatch_sync(log)

        from analytics.tracker import track
        track('pickup_rsvp', user=request.user, date=day.isoformat())

        return Response({'date': day.isoformat(), 'rsvp': True})


class PickupRSVPCancelView(APIView):
    """Withdraw an active pickup RSVP."""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        day = _parse_date(request.data.get('date'))
        if not day:
            return Response(
                {'error': 'A valid date (YYYY-MM-DD) is required.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        rsvp = PickupRSVP.objects.filter(
            user=request.user, date=day, status=PickupRSVP.STATUS_ACTIVE,
        ).first()
        if not rsvp:
            return Response(
                {'error': 'No active pickup RSVP for this date.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        rsvp.status = PickupRSVP.STATUS_CANCELLED
        rsvp.cancelled_at = timezone.now()
        rsvp.save(update_fields=['status', 'cancelled_at', 'updated_at'])

        log = PickupActionLog.objects.create(
            user=request.user, rsvp=rsvp, action='cancel', pickup_date=day,
        )
        _dispatch_sync(log)

        from analytics.tracker import track
        track('pickup_rsvp_cancel', user=request.user, date=day.isoformat())

        return Response({'date': day.isoformat(), 'rsvp': False})
