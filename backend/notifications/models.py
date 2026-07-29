from django.conf import settings
from django.db import models
from django.utils import timezone

# A subscription is retired once the push service has failed this many times
# without ever succeeding again. See notifications.tasks.prune_push_subscriptions.
FAILURE_THRESHOLD = 5

# Retired subscriptions are kept this long before the row is deleted, so an
# operator can still see why a user stopped receiving push.
RETENTION_DAYS = 30


class PushSubscription(models.Model):
    """One browser+device install that has granted push permission.

    `endpoint` is the identity: the same browser re-subscribing must update the
    existing row rather than create a duplicate, and a subscription can move
    between users when a device is shared.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='push_subscriptions',
    )
    endpoint = models.TextField(unique=True)
    p256dh = models.CharField(max_length=255)
    auth = models.CharField(max_length=255)
    device_label = models.CharField(max_length=200, blank=True)
    is_active = models.BooleanField(default=True)
    failure_count = models.PositiveIntegerField(default=0)
    last_success_at = models.DateTimeField(null=True, blank=True)
    last_seen_at = models.DateTimeField(default=timezone.now)
    deactivated_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', 'is_active']),
        ]

    def __str__(self):
        label = self.device_label or self.endpoint[:40]
        return f"{self.user.email} - {label}"

    def deactivate(self, save=True):
        """Retire this subscription; the push service says it is gone."""
        self.is_active = False
        if self.deactivated_at is None:
            self.deactivated_at = timezone.now()
        if save:
            self.save(update_fields=['is_active', 'deactivated_at'])


class NotificationPreference(models.Model):
    """Per-user channel and category opt-outs. One row per user."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='notification_preference',
    )
    push_enabled = models.BooleanField(default=True)
    email_enabled = models.BooleanField(default=True)

    # Per-category opt-outs
    birthday = models.BooleanField(default=True)
    announcements = models.BooleanField(default=True)
    recommendations = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Preferences for {self.user.email}"

    @classmethod
    def for_user(cls, user):
        """Return the user's preferences, creating defaults on first access."""
        preference, _ = cls.objects.get_or_create(user=user)
        return preference


class NotificationDelivery(models.Model):
    """The outbox: one row per message per user.

    `dedupe_key` is the reliability primitive - every send is idempotent on it,
    so a retried task, an overlapping beat run or a worker restart mid-send
    cannot produce a duplicate message.
    """

    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('sent', 'Sent'),
        ('failed', 'Failed'),
        ('skipped', 'Skipped'),
    ]

    KIND_CHOICES = [
        ('birthday_gift', 'Birthday Gift'),
        ('announcement', 'Announcement'),
        ('recommendations', 'Recommendations'),
        ('transactional', 'Transactional'),
    ]

    # Per-message override of the per-kind email policy. Blank means "use the
    # default for this kind" (notifications.services.KIND_POLICY), which is
    # what every existing caller gets.
    EMAIL_POLICY_CHOICES = [
        ('always', 'Always email'),
        ('fallback', 'Email only if push failed'),
        ('never', 'Never email'),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='notification_deliveries',
    )
    kind = models.CharField(max_length=50, choices=KIND_CHOICES)
    title = models.CharField(max_length=200)
    body = models.TextField()
    data = models.JSONField(default=dict, blank=True)
    dedupe_key = models.CharField(max_length=255, unique=True)

    email_policy = models.CharField(
        max_length=20,
        choices=EMAIL_POLICY_CHOICES,
        blank=True,
        help_text="Overrides the default email policy for this kind. Blank = use the kind default.",
    )

    push_status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    email_status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    push_error = models.TextField(blank=True)
    email_error = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', 'kind']),
        ]

    def __str__(self):
        return f"{self.kind} to {self.user.email} ({self.dedupe_key})"

    @property
    def is_processed(self):
        """True once send_notification has run to completion for this row."""
        return self.sent_at is not None


class NotificationKindSetting(models.Model):
    """
    Per-kind delivery settings, editable in the admin.

    The point of this table is control over the email fallback. Emailing on
    every push is how people learn to ignore you (and how a shared SMTP
    reputation gets burned), so each kind can be tuned without a deploy.

    Rows are seeded with the same defaults the code used before; a missing row
    falls back to those defaults, so deleting one is never fatal.
    """

    KIND_CHOICES = [
        ('birthday_gift', 'Birthday gift'),
        ('announcement', 'Announcement'),
        ('recommendations', 'Beer recommendations'),
        ('transactional', 'Transactional (orders, rewards)'),
    ]

    kind = models.CharField(max_length=50, unique=True, choices=KIND_CHOICES)

    send_push = models.BooleanField(
        default=True,
        help_text='Send a push notification for this kind.',
    )
    send_email = models.BooleanField(
        default=True,
        help_text='Send an email for this kind. Untick to never email - '
                  'push only.',
    )
    email_only_if_push_failed = models.BooleanField(
        default=True,
        verbose_name='Only email when push did not get through',
        help_text='Ticked: email is a fallback, sent only when the push could '
                  'not be delivered (nobody gets both). Unticked: the email is '
                  'always sent alongside the push - right for things worth '
                  'keeping, like a discount code. Ignored when "Send email" is off.',
    )

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['kind']
        verbose_name = 'Notification delivery setting'
        verbose_name_plural = 'Notification delivery settings'

    def __str__(self):
        return f"{self.get_kind_display()} ({self.email_policy_label})"

    @property
    def email_policy(self):
        """Collapse the checkboxes to the policy value services.py works in."""
        if not self.send_email:
            return 'never'
        return 'fallback' if self.email_only_if_push_failed else 'always'

    @property
    def email_policy_label(self):
        return {
            'never': 'push only, never email',
            'fallback': 'email only if push fails',
            'always': 'push and email',
        }[self.email_policy]
