"""External service grants.

Points awarded by trusted external systems (the houseofbeers_whatsapp Django
app, "hob") over the HMAC-signed service API. One row per grant request —
audit trail + idempotency guard (`dedupe_key` is unique) + the pending store
for people who are not app members yet: a pending grant is claimed
automatically when a matching user registers or links Shopify.

Imported at the end of models.py so `from loyalty.models import ServiceGrant`
works.
"""
from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models

__all__ = ['ServiceGrant']


class ServiceGrant(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending (no matching member yet)'),
        ('granted', 'Granted'),
        ('revoked', 'Revoked'),
    ]

    # Idempotency: callers construct a stable key (e.g. from the WhatsApp
    # message timestamp + phone) so retries and pipeline re-runs are no-ops.
    dedupe_key = models.CharField(max_length=255, unique=True)
    source = models.CharField(
        max_length=50,
        default='hob',
        help_text="Which external system sent this grant"
    )

    points = models.IntegerField(validators=[MinValueValidator(1)])
    reason = models.CharField(
        max_length=255,
        help_text="Customer-facing NL text; rendered verbatim in the app's "
                  "transaction history"
    )
    context = models.JSONField(
        null=True,
        blank=True,
        help_text="Caller-supplied context (sale id, chat message, ...) — "
                  "audit only, never shown to the customer"
    )

    # Identity as supplied by the caller. Matching order: shopify_customer_id,
    # then email (case-insensitive). Phone is stored for audit/debugging only —
    # User has no phone field, so it can never match by itself.
    shopify_customer_id = models.CharField(max_length=255, blank=True, default='')
    email = models.CharField(max_length=255, blank=True, default='')
    phone = models.CharField(max_length=50, blank=True, default='')

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    notify = models.BooleanField(
        default=True,
        help_text="Send an in-app notification when the grant is fulfilled "
                  "(also on a later claim)"
    )

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='service_grants',
    )
    transaction = models.ForeignKey(
        'loyalty.PointsTransaction',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='service_grants',
    )
    # Plain int, not a FK — loyalty and notifications stay decoupled (same
    # convention as CampaignAward.notified_delivery_id / BirthdayReward).
    notified_delivery_id = models.IntegerField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    granted_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Service Grant'
        verbose_name_plural = 'Service Grants'
        indexes = [
            models.Index(fields=['status', 'shopify_customer_id']),
            models.Index(fields=['status', 'email']),
        ]

    def __str__(self):
        who = self.user.email if self.user else (
            self.email or self.phone or self.shopify_customer_id or '?'
        )
        return f"{self.source}: {self.points} points to {who} ({self.status})"
