"""Campaign & raffle models.

Campaigns sit ALONGSIDE the PointsRule engine: structured purchase/customer
conditions -> action (points, discount code, raffle entry) -> notifications.
Imported at the end of models.py so `from loyalty.models import Campaign` works.
"""
from django.conf import settings
from django.db import models

__all__ = [
    'Campaign', 'CampaignProgress', 'CampaignAward', 'CampaignRaffle',
    'RaffleEntry', 'CampaignRaffleWinner', 'CampaignPreview',
]


class Campaign(models.Model):
    """
    Admin-defined campaign: conditions evaluated cumulatively across a user's
    paid orders inside the window; the action fires once at qualification.
    """
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('previewed', 'Previewed'),
        ('active', 'Active'),
        ('completed', 'Completed'),
        ('archived', 'Archived'),
    ]
    ACTION_TYPE_CHOICES = [
        ('points', 'Points'),
        ('discount_code', 'Discount code'),
        ('raffle', 'Raffle entry'),
    ]
    POINTS_MODE_CHOICES = [
        ('fixed', 'Fixed (once, on qualification)'),
        ('per_item', 'Per matched item'),
    ]
    DISCOUNT_TYPE_CHOICES = [
        ('fixed_amount', 'Fixed amount discount'),
        ('percentage', 'Percentage discount'),
        ('free_shipping', 'Free shipping'),
        ('free_product', 'Free product'),
    ]
    AUDIENCE_MODE_CHOICES = [
        ('orders', 'Purchase conditions'),
        ('audience', 'Selected audience (no purchase needed)'),
    ]

    # Fields whose change invalidates an existing preview (see save()).
    CONDITION_FIELDS = [
        'window_start', 'window_end', 'product_matchers',
        'min_distinct_products', 'min_total_quantity', 'min_order_value',
        'min_total_spend', 'min_order_count', 'first_order_only',
        'only_after_registration', 'requires_untappd', 'min_points_balance',
        'registered_after', 'action_type', 'points_amount', 'points_mode',
        'discount_type', 'discount_value', 'discount_product_gid',
        'discount_validity_days', 'audience_mode', 'audience_filters',
        'manual_user_ids',
    ]

    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    action_type = models.CharField(max_length=20, choices=ACTION_TYPE_CHOICES)

    # Orders with created_at inside [window_start, window_end] count.
    # Retroactive = window_start before activation; backfill covers it.
    window_start = models.DateTimeField()
    window_end = models.DateTimeField()

    # Conditions — ALL configured conditions must be satisfied;
    # blank/null = condition not used.
    product_matchers = models.JSONField(
        default=list, blank=True,
        help_text='[{"type": "sku"|"product_id"|"title"|"tag"|"collection", "value": "..."}]. '
                  'Empty list = any product/order counts.'
    )
    min_distinct_products = models.PositiveIntegerField(
        default=1,
        help_text="Distinct matchers satisfied (the k-of-n case)"
    )
    min_total_quantity = models.PositiveIntegerField(
        default=1,
        help_text="Total matched item quantity across the window"
    )
    min_order_value = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True,
        help_text="At least one qualifying order with total >= this"
    )
    min_total_spend = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True,
        help_text="Cumulative paid-order spend inside the window >= this (all orders)"
    )
    min_order_count = models.PositiveIntegerField(
        null=True, blank=True,
        help_text="Number of paid orders inside the window >= this"
    )
    first_order_only = models.BooleanField(
        default=False,
        help_text="User's first-ever order must fall inside the window"
    )
    only_after_registration = models.BooleanField(
        default=False,
        help_text="Only count orders placed after the user registered in the app"
    )
    requires_untappd = models.BooleanField(
        default=False,
        help_text="User has a linked Untappd profile"
    )
    min_points_balance = models.IntegerField(
        null=True, blank=True,
        help_text="Current points balance >= this at evaluation time"
    )
    registered_after = models.DateTimeField(null=True, blank=True)

    # Audience selection. In 'orders' mode a configured audience acts as an
    # extra gate on top of the purchase conditions; in 'audience' mode the
    # audience itself qualifies (no purchase needed) — members are qualified
    # on activation and new filter matches are added nightly.
    audience_mode = models.CharField(
        max_length=10, choices=AUDIENCE_MODE_CHOICES, default='orders'
    )
    audience_filters = models.JSONField(
        default=dict, blank=True,
        help_text='{"min_age": 21, "birthday_month": 9, "min_app_age_days": 30, '
                  '"min_lifetime_orders": 3, "active_within_days": 90} — '
                  'all configured filters must match (AND). See services/audience.py.'
    )
    manual_user_ids = models.JSONField(
        default=list, blank=True,
        help_text="Hand-picked user ids, added to the filter matches (OR)."
    )

    # Snapshot of tag/collection matcher resolution:
    # {matcher_index: [product_id, ...]}
    resolved_product_ids = models.JSONField(default=dict, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    rule_sentence = models.TextField(
        blank=True,
        help_text="Plain-language NL summary shown to customers; auto-generated, editable"
    )

    # Action config: points
    points_amount = models.IntegerField(null=True, blank=True)
    points_mode = models.CharField(
        max_length=10, choices=POINTS_MODE_CHOICES, default='fixed'
    )

    # Action config: discount_code (also used as the raffle prize code config)
    discount_type = models.CharField(
        max_length=20, choices=DISCOUNT_TYPE_CHOICES, blank=True
    )
    discount_value = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True
    )
    discount_product_gid = models.CharField(
        max_length=255, blank=True,
        help_text="For free_product: Shopify product GID"
    )
    discount_validity_days = models.PositiveIntegerField(default=30)

    # Notification config
    notify_on_qualify = models.BooleanField(default=True)
    qualify_title = models.CharField(max_length=200, blank=True)
    qualify_body = models.TextField(
        blank=True,
        help_text="Blank = sensible NL default built from rule_sentence/prize"
    )
    qualify_email_fallback = models.BooleanField(
        default=False,
        help_text="Email the qualify notification to members without an "
                  "active push subscription (push-skip normally sends "
                  "nothing at all). Off by default — be careful with email."
    )

    preview_stale = models.BooleanField(
        default=True,
        help_text="Set on every condition-affecting save in draft/previewed; "
                  "Studio requires a fresh preview to activate"
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Campaign'
        verbose_name_plural = 'Campaigns'

    def __str__(self):
        return f"{self.name} ({self.get_action_type_display()}, {self.status})"

    def save(self, *args, **kwargs):
        # A condition edit while draft/previewed invalidates the last preview.
        # Queryset .update() bypasses this on purpose (the preview task uses it
        # to clear the flag without re-tripping it).
        if self.pk and self.status in ('draft', 'previewed'):
            old = Campaign.objects.filter(pk=self.pk).first()
            if old and any(
                getattr(old, field) != getattr(self, field)
                for field in self.CONDITION_FIELDS
            ):
                self.preview_stale = True
        super().save(*args, **kwargs)


class CampaignProgress(models.Model):
    """
    Cumulative per-user campaign state, so k-of-n works ACROSS orders.

    `data` shape: {"spend": "123.45", "order_count": 3,
    "matcher_qty": {"0": 2}, "matched_order_ids": [...],
    "processed_order_ids": [...]} — processed_order_ids is the idempotency
    guard: an order id already present is skipped entirely.
    """
    campaign = models.ForeignKey(
        Campaign, on_delete=models.CASCADE, related_name='progress_entries'
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name='campaign_progress'
    )
    data = models.JSONField(default=dict, blank=True)
    qualified_at = models.DateTimeField(
        null=True, blank=True,
        help_text="Set once when thresholds are first met"
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ['campaign', 'user']
        verbose_name = 'Campaign Progress'
        verbose_name_plural = 'Campaign Progress'

    def __str__(self):
        state = 'qualified' if self.qualified_at else 'in progress'
        return f"{self.user.email} @ {self.campaign.name}: {state}"


class CampaignAward(models.Model):
    """Audit + idempotency of the fired campaign action."""
    campaign = models.ForeignKey(
        Campaign, on_delete=models.CASCADE, related_name='awards'
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name='campaign_awards'
    )
    points_awarded = models.IntegerField(
        default=0, help_text="Cumulative for per_item mode"
    )
    points_transaction = models.ForeignKey(
        'PointsTransaction', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='campaign_awards'
    )
    discount_code = models.CharField(max_length=255, blank=True)
    shopify_discount_id = models.CharField(max_length=255, blank=True)
    cart_url = models.TextField(
        blank=True,
        help_text="Storefront link that applies the code (and adds the free "
                  "product to the cart); resolved once when the code is minted"
    )
    notified_delivery_id = models.IntegerField(
        null=True, blank=True,
        help_text="notifications.NotificationDelivery id (not a FK, apps stay decoupled)"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ['campaign', 'user']
        verbose_name = 'Campaign Award'
        verbose_name_plural = 'Campaign Awards'

    def __str__(self):
        return f"{self.user.email} @ {self.campaign.name}"


class CampaignRaffle(models.Model):
    """Raffle config + state for a campaign with action_type='raffle'."""
    ENTRY_MODE_CHOICES = [
        ('single', '1 ticket'),
        ('per_order', '1 ticket per qualifying order'),
        ('per_item', '1 ticket per matched item'),
    ]
    FULFILLMENT_TYPE_CHOICES = [
        ('shopify_code', 'Shopify discount code'),
        ('manual', 'Manual'),
    ]
    STATUS_CHOICES = [
        ('open', 'Open'),
        ('drawn', 'Drawn'),
    ]

    campaign = models.OneToOneField(
        Campaign, on_delete=models.CASCADE, related_name='raffle'
    )
    prize_name = models.CharField(max_length=200)
    prize_description = models.TextField(blank=True)
    prize_image_url = models.URLField(blank=True)
    num_winners = models.PositiveIntegerField(default=1)
    draw_at = models.DateTimeField(
        null=True, blank=True, help_text="Null = manual draw only"
    )
    entry_mode = models.CharField(
        max_length=10, choices=ENTRY_MODE_CHOICES, default='single'
    )
    fulfillment_type = models.CharField(
        max_length=20, choices=FULFILLMENT_TYPE_CHOICES, default='manual',
        help_text="shopify_code uses the campaign discount_* fields for the prize code"
    )
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='open')
    drawn_at = models.DateTimeField(null=True, blank=True)
    send_reminder = models.BooleanField(
        default=True, help_text="Reminder notification ~3h before draw_at"
    )
    reminder_sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = 'Campaign Raffle'
        verbose_name_plural = 'Campaign Raffles'

    def __str__(self):
        return f"Raffle: {self.prize_name} ({self.status})"


class RaffleEntry(models.Model):
    raffle = models.ForeignKey(
        CampaignRaffle, on_delete=models.CASCADE, related_name='entries'
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name='raffle_entries'
    )
    ticket_count = models.PositiveIntegerField(default=1)
    matched_products = models.JSONField(
        default=list, blank=True,
        help_text="Display strings of what qualified them"
    )
    seen_at = models.DateTimeField(
        null=True, blank=True, help_text="Opened the raffle card"
    )
    result_seen_at = models.DateTimeField(
        null=True, blank=True, help_text="Watched the reveal"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ['raffle', 'user']
        verbose_name = 'Raffle Entry'
        verbose_name_plural = 'Raffle Entries'

    def __str__(self):
        return f"{self.user.email}: {self.ticket_count} tickets in {self.raffle.prize_name}"


class CampaignRaffleWinner(models.Model):
    FULFILLMENT_STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('code_issued', 'Code issued'),
        ('manual_pending', 'Manual fulfillment pending'),
        ('fulfilled', 'Fulfilled'),
    ]

    raffle = models.ForeignKey(
        CampaignRaffle, on_delete=models.CASCADE, related_name='winners'
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        # events.RaffleWinner (livestream) already owns User.raffle_wins
        related_name='campaign_raffle_wins'
    )
    prize_code = models.CharField(max_length=255, blank=True)
    shopify_discount_id = models.CharField(max_length=255, blank=True)
    cart_url = models.TextField(
        blank=True,
        help_text="Storefront link that applies the prize code (and adds the "
                  "prize product to the cart); resolved once at fulfillment"
    )
    code_expires_at = models.DateTimeField(null=True, blank=True)
    fulfillment_status = models.CharField(
        max_length=20, choices=FULFILLMENT_STATUS_CHOICES, default='pending'
    )
    fulfilled_at = models.DateTimeField(null=True, blank=True)
    redeemed_at = models.DateTimeField(null=True, blank=True)
    redeemed_order_name = models.CharField(max_length=50, blank=True)
    result_delivery_id = models.IntegerField(
        null=True, blank=True,
        help_text="notifications.NotificationDelivery id (not a FK, apps stay decoupled)"
    )
    drawn_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ['raffle', 'user']
        verbose_name = 'Campaign Raffle Winner'
        verbose_name_plural = 'Campaign Raffle Winners'

    def __str__(self):
        return f"{self.user.email} won {self.raffle.prize_name}"


class CampaignPreview(models.Model):
    """Async dry-run results for the Campagne Studio."""
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('running', 'Running'),
        ('done', 'Done'),
        ('failed', 'Failed'),
    ]

    campaign = models.ForeignKey(
        Campaign, on_delete=models.CASCADE, related_name='previews'
    )
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='pending')
    error = models.TextField(blank=True)
    result = models.JSONField(
        null=True, blank=True,
        help_text='{"qualified_count", "users", "near_miss_count", '
                  '"near_miss_users", "orders_scanned"}'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Campaign Preview'
        verbose_name_plural = 'Campaign Previews'

    def __str__(self):
        return f"Preview of {self.campaign.name} ({self.status})"
