import logging

logger = logging.getLogger(__name__)


def track(event_type, user=None, **metadata):
    """Log a usage event. Fails silently to never break the main request."""
    try:
        from .models import UsageEvent
        UsageEvent.objects.create(
            user=user,
            event_type=event_type,
            metadata=metadata or {},
        )
    except Exception as e:
        logger.warning(f"Failed to track event {event_type}: {e}")
