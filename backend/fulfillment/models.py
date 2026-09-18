"""
Fulfillment: user-facing fulfillment requests around Shopify orders.

Today this is only the pickup RSVP feature (members tell us on which
store-open day they will collect their order, replacing a WhatsApp poll).
The app is deliberately named broadly — future requests like "ship my
orders" / "check my orders" belong here too — but nothing beyond pickup
is built yet.
"""
from django.conf import settings
from django.db import models


class PickupSchedule(models.Model):
    """A weekday the store is open for pickups (Prior van Millstraat 2, Uden)."""

    WEEKDAY_CHOICES = [
        (0, 'Maandag'),
        (1, 'Dinsdag'),
        (2, 'Woensdag'),
        (3, 'Donderdag'),
        (4, 'Vrijdag'),
        (5, 'Zaterdag'),
        (6, 'Zondag'),
    ]

    weekday = models.IntegerField(choices=WEEKDAY_CHOICES)
    open_time = models.TimeField()
    close_time = models.TimeField()
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ['weekday']
        verbose_name = 'Afhaaldag'
        verbose_name_plural = 'Afhaaldagen'

    def __str__(self):
        return (
            f"{self.get_weekday_display()} "
            f"{self.open_time:%H:%M}-{self.close_time:%H:%M}"
        )


class PickupClosure(models.Model):
    """An exception date (holiday etc.) on which pickup is NOT possible."""

    date = models.DateField(unique=True)
    reason = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ['date']
        verbose_name = 'Sluitingsdag'
        verbose_name_plural = 'Sluitingsdagen'

    def __str__(self):
        return f"{self.date} ({self.reason})" if self.reason else str(self.date)


class PickupRSVP(models.Model):
    """A member's announcement that they will pick up on a given date.

    One row per (user, date), ever: cancelling flips status, re-RSVPing
    after a cancel reactivates the same row.
    """

    STATUS_ACTIVE = 'active'
    STATUS_CANCELLED = 'cancelled'
    STATUS_CHOICES = [
        (STATUS_ACTIVE, 'Aangemeld'),
        (STATUS_CANCELLED, 'Geannuleerd'),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='pickup_rsvps',
    )
    date = models.DateField()
    status = models.CharField(
        max_length=10, choices=STATUS_CHOICES, default=STATUS_ACTIVE
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = [('user', 'date')]
        ordering = ['-date']
        verbose_name = 'Afhaal-aanmelding'
        verbose_name_plural = 'Afhaal-aanmeldingen'

    def __str__(self):
        return f"{self.user.email} — {self.date} ({self.status})"


class PickupActionLog(models.Model):
    """One row per user action (rsvp/cancel).

    Doubles as the usage log AND the Shopify-sync health view: every action
    must reach Shopify (the customer's warehouse queue/priority metafields,
    which hob reads), and this row records whether that write succeeded.
    """

    ACTION_CHOICES = [
        ('rsvp', 'Aangemeld'),
        ('cancel', 'Geannuleerd'),
    ]
    SYNC_STATUS_CHOICES = [
        ('pending', 'In afwachting'),
        ('success', 'Gelukt'),
        ('failed', 'Mislukt'),
        ('skipped', 'Overgeslagen'),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='pickup_action_logs',
    )
    rsvp = models.ForeignKey(
        PickupRSVP,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='action_logs',
    )
    action = models.CharField(max_length=10, choices=ACTION_CHOICES)
    pickup_date = models.DateField()
    sync_status = models.CharField(
        max_length=10, choices=SYNC_STATUS_CHOICES, default='pending'
    )
    sync_attempts = models.IntegerField(default=0)
    sync_response = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Afhaal-actielog'
        verbose_name_plural = 'Afhaal-actielogs'

    def __str__(self):
        return f"{self.user.email} {self.action} {self.pickup_date} [{self.sync_status}]"
