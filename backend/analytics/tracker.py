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

    # Every call to track() means "this user just did something", which makes
    # it the natural place to maintain last_active_at - login included, since
    # the login view already tracks a 'login' event. Kept in its own try so a
    # failure here cannot lose the usage event above, or vice versa.
    if user is not None and getattr(user, 'pk', None):
        try:
            user.touch_last_active()
        except Exception as e:
            logger.warning(f"Failed to update last_active_at for user {user.pk}: {e}")
