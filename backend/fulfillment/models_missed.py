"""Missed items pushed by hob.

Per-(sale, customer) snapshots of beers someone ordered in a WhatsApp sale
but did not (fully) receive because they were too late — hob pushes them
over the HMAC-signed service API so the app's orders screen can show "these
you missed". One row per dedupe_key; a re-push REPLACES the lines and the
draft/order ids (hob re-pushes after refulfilments), and an empty `lines`
list clears the record (the customer no longer misses anything) while the
row itself stays as the idempotency guard.

Same pending/claim shape as loyalty's ServiceGrant: a snapshot whose
identity matches no member is stored `pending` and attached automatically
by `claim_pending_missed(user)`, hooked into registration and Shopify
linking.

Imported at the end of models.py so `from fulfillment.models import
MissedItemsRecord` works.
"""
from django.conf import settings
from django.db import models

__all__ = ['MissedItemsRecord']


class MissedItemsRecord(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending (no matching member yet)'),
        ('attached', 'Attached to a member'),
        ('cleared', 'Cleared (nothing missed anymore)'),
    ]

    # Idempotency: hob constructs a stable key per (sale, customer) —
    # "hob:missed:<sale_id>:<shopify_customer_id>" — so retries and
    # refulfilment re-pushes update the same row instead of stacking up.
    dedupe_key = models.CharField(max_length=120, unique=True)
    source = models.CharField(
        max_length=50,
        default='hob',
        help_text="Which external system sent this snapshot"
    )

    # Identity as supplied by the caller. Matching order:
    # shopify_customer_id, then email (case-insensitive). Phone is stored
    # for audit/debugging only — User has no phone field, so it can never
    # match by itself. Same convention as ServiceGrant.
    shopify_customer_id = models.CharField(max_length=255, blank=True, null=True)
    email = models.CharField(max_length=255, blank=True, default='')
    phone = models.CharField(max_length=50, blank=True, default='')

    sale_id = models.IntegerField()
    sale_name = models.CharField(max_length=100, blank=True, default='')
    sale_date = models.DateField(db_index=True)

    # Where this customer's sale lines live on the Shopify side: the draft
    # order hob sent, and the real order once that draft was paid. Numeric
    # id strings (not gids); blank when hob does not know (yet).
    draft_order_id = models.CharField(max_length=64, blank=True, default='')
    draft_order_name = models.CharField(max_length=64, blank=True, default='')
    shopify_order_id = models.CharField(max_length=64, blank=True, default='')

    # [{'product_id', 'title', 'requested', 'received', 'reason'}, ...] —
    # stored verbatim; the orders API serves it back to the mobile app.
    lines = models.JSONField(default=list)

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='missed_items',
    )

    # When hob generated the snapshot (its clock, not ours).
    pushed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-sale_date', '-created_at']
        verbose_name = 'Missed Items Record'
        verbose_name_plural = 'Missed Items Records'
        indexes = [
            models.Index(fields=['status', 'shopify_customer_id']),
            models.Index(fields=['status', 'email']),
            # The orders API reads "this user's recent missed sales".
            models.Index(fields=['user', 'sale_date']),
        ]

    def __str__(self):
        who = self.user.email if self.user else (
            self.email or self.phone or self.shopify_customer_id or '?'
        )
        return (
            f"{self.source}: sale {self.sale_name or self.sale_id} — "
            f"{len(self.lines)} missed line(s) for {who} ({self.status})"
        )
