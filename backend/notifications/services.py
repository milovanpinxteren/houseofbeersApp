"""Notification delivery: push first, email per the per-kind policy.

The single public entry point is `send_notification`. Other apps should never
touch PushSubscription or the mail backend directly - route everything through
here so the dedupe key, the preference checks and the outbox row all apply.
"""
import json
import logging

from django.conf import settings
from django.core.cache import cache
from django.core.mail import send_mail
from django.db.utils import OperationalError, ProgrammingError
from django.utils import timezone

from .models import (NotificationDelivery, NotificationKindSetting,
                     NotificationPreference, PushSubscription)

logger = logging.getLogger(__name__)

try:  # pragma: no cover - exercised only when the dependency is missing
    from pywebpush import WebPushException, webpush
except ImportError:  # pragma: no cover
    webpush = None

    class WebPushException(Exception):
        response = None


# Email policy per kind. Fallback should not mean "email everything" - that is
# how people learn to ignore you.
#   'always'   - send email regardless of whether push worked
#   'fallback' - email only when push did not succeed
#   'never'    - push only
EMAIL_ALWAYS = 'always'
EMAIL_FALLBACK = 'fallback'
EMAIL_NEVER = 'never'

KIND_POLICY = {
    # A discount code belongs in an inbox where it can be found later.
    'birthday_gift': EMAIL_ALWAYS,
    'announcement': EMAIL_FALLBACK,
    'recommendations': EMAIL_NEVER,
    'transactional': EMAIL_ALWAYS,
}

# Unknown kinds behave like an announcement: push, email only if push failed.
DEFAULT_KIND_POLICY = EMAIL_FALLBACK

# Valid values for the per-message `email_policy` override.
EMAIL_POLICIES = (EMAIL_ALWAYS, EMAIL_FALLBACK, EMAIL_NEVER)

# Which NotificationPreference category gates each kind. `None` means the kind
# has no per-category opt-out (transactional mail is not marketing).
KIND_CATEGORY = {
    'birthday_gift': 'birthday',
    'announcement': 'announcements',
    'recommendations': 'recommendations',
    'transactional': None,
}

DEFAULT_KIND_CATEGORY = 'announcements'

# Statuses that count as "the push service took the message".
PUSH_GONE_STATUS_CODES = (404, 410)

# Admin-editable per-kind settings are cached briefly: a fan-out to many users
# would otherwise repeat the same lookup once per recipient. Short enough that
# a change in the admin takes effect within a minute.
KIND_SETTING_CACHE_KEY = 'notifications:kind_settings'
KIND_SETTING_CACHE_SECONDS = 60


def _kind_settings():
    """{kind: {'send_push': bool, 'email_policy': str}} from the admin table."""
    cached = cache.get(KIND_SETTING_CACHE_KEY)
    if cached is not None:
        return cached

    try:
        settings_map = {
            row.kind: {'send_push': row.send_push, 'email_policy': row.email_policy}
            for row in NotificationKindSetting.objects.all()
        }
    except (OperationalError, ProgrammingError):
        # The table may not exist yet during an initial migrate; the hardcoded
        # defaults below keep delivery working rather than erroring.
        return {}

    cache.set(KIND_SETTING_CACHE_KEY, settings_map, KIND_SETTING_CACHE_SECONDS)
    return settings_map


def invalidate_kind_settings_cache():
    """Called from the admin so an edit takes effect immediately."""
    cache.delete(KIND_SETTING_CACHE_KEY)


def resolve_email_policy(kind, override=None):
    """Explicit override wins, then the admin setting, then the code default."""
    if override:
        return override
    setting = _kind_settings().get(kind)
    if setting:
        return setting['email_policy']
    return KIND_POLICY.get(kind, DEFAULT_KIND_POLICY)


def push_enabled_for_kind(kind):
    setting = _kind_settings().get(kind)
    return setting['send_push'] if setting else True


def send_notification(user, *, kind, title, body, data=None, dedupe_key,
                      email_subject=None, email_body=None, email_policy=None):
    """Deliver one message to one user, idempotently on `dedupe_key`.

    Returns the NotificationDelivery row. Calling twice with the same
    dedupe_key returns the first row untouched - no second push, no second
    email. Never raises for a delivery failure; failures are recorded on the
    row so a later run can inspect them.

    `email_policy` overrides the per-kind default for this one message:
    'always', 'fallback' or 'never'. None keeps the kind's own policy, so
    every existing caller is unaffected. The chosen policy is stored on the
    delivery row, so "why did this not get emailed?" is answerable later.
    """
    data = data or {}

    if email_policy is not None and email_policy not in EMAIL_POLICIES:
        raise ValueError(
            f"Unknown email_policy {email_policy!r}; expected one of {EMAIL_POLICIES}"
        )

    delivery, created = NotificationDelivery.objects.get_or_create(
        dedupe_key=dedupe_key,
        defaults={
            'user': user,
            'kind': kind,
            'title': title,
            'body': body,
            'data': data,
            'email_policy': email_policy or '',
        },
    )

    if not created and delivery.is_processed:
        logger.info(f"Notification {dedupe_key} already delivered, skipping")
        return delivery

    # An unprocessed existing row means a previous attempt died before it
    # finished, so falling through and retrying is deliberate.
    #
    # Known narrow race: two callers hitting the same dedupe_key *simultaneously*
    # would both see an unprocessed row and both send. It is not guarded here
    # because holding a row lock across the push/SMTP round-trips is worse than
    # the failure it prevents, and callers already serialise upstream —
    # birthday_scan is gated by a unique (user, year) constraint, and beat
    # dispatches each task once. If a future fan-out sends the same key from
    # several workers at once, add a claimed_at column and claim it under
    # select_for_update before sending.

    preference = NotificationPreference.for_user(user)

    push_status, push_error = _deliver_push(
        user, kind, title, body, data, preference,
    )
    # An explicit argument wins, so an operator retrying a stuck row can
    # override it; otherwise the policy recorded on the row is authoritative.
    effective_policy = email_policy or delivery.email_policy or None

    email_status, email_error = _deliver_email(
        user, kind, title, body, preference, push_status,
        email_subject=email_subject, email_body=email_body,
        email_policy=effective_policy,
    )

    delivery.push_status = push_status
    delivery.push_error = push_error
    delivery.email_status = email_status
    delivery.email_error = email_error
    delivery.email_policy = effective_policy or ''
    delivery.sent_at = timezone.now()
    delivery.save(update_fields=[
        'push_status', 'push_error', 'email_status', 'email_error',
        'email_policy', 'sent_at',
    ])

    logger.info(
        f"Notification {dedupe_key} ({kind}) for {user.email}: "
        f"push={push_status} email={email_status}"
    )
    return delivery


# --- Channel: push ---

def _deliver_push(user, kind, title, body, data, preference):
    """Push to every active subscription. Returns (status, error)."""
    if not push_enabled_for_kind(kind):
        return 'skipped', 'Push is switched off for this kind in the admin'

    if not _channel_allowed(preference, kind, 'push'):
        return 'skipped', 'User opted out of push for this kind'

    if not settings.VAPID_PRIVATE_KEY or not settings.VAPID_PUBLIC_KEY:
        logger.warning(
            'VAPID keys are not configured; skipping push delivery. '
            'Generate a keypair with `vapid --gen` and set VAPID_PRIVATE_KEY.'
        )
        return 'skipped', 'VAPID keys not configured'

    if webpush is None:  # pragma: no cover
        logger.warning('pywebpush is not installed; skipping push delivery')
        return 'skipped', 'pywebpush not installed'

    subscriptions = list(
        PushSubscription.objects.filter(user=user, is_active=True)
    )
    if not subscriptions:
        return 'skipped', 'No active push subscriptions'

    # These three keys are exactly what mobile/public/service-worker.js reads
    # in its `push` handler. Do not add or rename without changing it too.
    payload = json.dumps({
        'title': title,
        'body': body,
        'url': data.get('url') or '/',
    })

    accepted = 0
    errors = []
    for subscription in subscriptions:
        error = _push_to_subscription(subscription, payload)
        if error is None:
            accepted += 1
        else:
            errors.append(error)

    if accepted:
        return 'sent', '; '.join(errors)
    return 'failed', '; '.join(errors) or 'Push failed'


def _push_to_subscription(subscription, payload):
    """Send to one subscription. Returns None on success, an error string otherwise."""
    try:
        webpush(
            subscription_info={
                'endpoint': subscription.endpoint,
                'keys': {
                    'p256dh': subscription.p256dh,
                    'auth': subscription.auth,
                },
            },
            data=payload,
            vapid_private_key=settings.VAPID_PRIVATE_KEY,
            # pywebpush mutates the claims dict (it fills in aud/exp), so build
            # a fresh one per call rather than sharing a module-level dict.
            vapid_claims={'sub': settings.VAPID_SUBJECT},
        )
    except WebPushException as exc:
        status_code = getattr(getattr(exc, 'response', None), 'status_code', None)
        if status_code in PUSH_GONE_STATUS_CODES:
            # Gone for good: PWA deleted or permission revoked.
            subscription.deactivate()
            logger.info(
                f"Deactivated push subscription {subscription.id} "
                f"({status_code} from push service)"
            )
            return f"{status_code} gone"
        _record_failure(subscription)
        logger.warning(f"Push failed for subscription {subscription.id}: {exc}")
        return f"{status_code or 'error'}: {exc}"
    except Exception as exc:  # network blip, DNS, malformed key...
        _record_failure(subscription)
        logger.warning(f"Push errored for subscription {subscription.id}: {exc}")
        return str(exc)

    subscription.failure_count = 0
    subscription.last_success_at = timezone.now()
    subscription.save(update_fields=['failure_count', 'last_success_at'])
    return None


def _record_failure(subscription):
    subscription.failure_count = (subscription.failure_count or 0) + 1
    subscription.save(update_fields=['failure_count'])


# --- Channel: email ---

def _deliver_email(user, kind, title, body, preference, push_status,
                   email_subject=None, email_body=None, email_policy=None):
    """Apply the email policy for this message. Returns (status, error).

    Precedence: an explicit per-message `email_policy`, then the admin's
    per-kind setting, then the hardcoded default.
    """
    policy = resolve_email_policy(kind, override=email_policy)

    if policy == EMAIL_NEVER:
        return 'skipped', 'Email is disabled for this notification'

    if not _channel_allowed(preference, kind, 'email'):
        return 'skipped', 'User opted out of email for this kind'

    if policy == EMAIL_FALLBACK and push_status == 'sent':
        return 'skipped', 'Push succeeded; no email fallback needed'

    if not user.email:
        return 'skipped', 'User has no email address'

    try:
        send_mail(
            subject=email_subject or title,
            message=email_body or body,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user.email],
            fail_silently=False,
        )
    except Exception as exc:
        # An SMTP outage must never bubble out of send_notification - the push
        # may well have landed, and the caller has nothing useful to do here.
        logger.error(f"Email delivery failed for {user.email}: {exc}")
        return 'failed', str(exc)

    return 'sent', ''


# --- Preferences ---

def _channel_allowed(preference, kind, channel):
    """False when the user has opted out of this channel or this category."""
    if channel == 'push' and not preference.push_enabled:
        return False
    if channel == 'email' and not preference.email_enabled:
        return False

    category = KIND_CATEGORY.get(kind, DEFAULT_KIND_CATEGORY)
    if category and not getattr(preference, category, True):
        return False
    return True
