from decimal import Decimal
from django.db import models
from django.conf import settings
from django.core.validators import MinValueValidator


class PointsRule(models.Model):
    """
    Rules for earning loyalty points.
    Admin can create rules based on different conditions.
    """
    RULE_TYPE_CHOICES = [
        ('per_euro', 'Points per Euro spent'),
        ('per_order', 'Points per order'),
        ('product_sku', 'Points for specific product (by SKU)'),
        ('product_title', 'Points for product (by title contains)'),
        ('minimum_order', 'Bonus points for minimum order value'),
        ('first_order', 'Bonus points for first order'),
    ]

    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    rule_type = models.CharField(max_length=50, choices=RULE_TYPE_CHOICES)

    # Points to award
    points = models.IntegerField(validators=[MinValueValidator(1)])

    # Conditions (used based on rule_type)
    condition_value = models.CharField(
        max_length=255,
        blank=True,
        help_text="SKU, product title keyword, or minimum order amount"
    )
    multiplier = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=1.0,
        help_text="For per_euro: points per euro (e.g., 10 = 10 points per euro)"
    )

    # Rule status
    is_active = models.BooleanField(default=True)
    priority = models.IntegerField(default=0, help_text="Higher priority rules are evaluated first")

    # Validity period
    valid_from = models.DateTimeField(null=True, blank=True)
    valid_until = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-priority', '-created_at']
        verbose_name = 'Points Rule'
        verbose_name_plural = 'Points Rules'

    def __str__(self):
        return f"{self.name} ({self.get_rule_type_display()})"


class Reward(models.Model):
    """
    Rewards that can be redeemed with loyalty points.
    Can be a fixed discount, percentage discount, or free product.
    """
    REWARD_TYPE_CHOICES = [
        ('fixed_discount', 'Fixed amount discount'),
        ('percentage_discount', 'Percentage discount'),
        ('free_shipping', 'Free shipping'),
        ('free_product', 'Free product'),
    ]

    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    reward_type = models.CharField(max_length=50, choices=REWARD_TYPE_CHOICES)

    # Cost in points
    points_cost = models.IntegerField(validators=[MinValueValidator(1)])

    # Reward value
    discount_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="For fixed_discount: amount in euros"
    )
    discount_percentage = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="For percentage_discount: percentage (e.g., 10 for 10%)"
    )
    shopify_product_id = models.CharField(
        max_length=255,
        blank=True,
        help_text="For free_product: Shopify product GID (e.g., gid://shopify/Product/123456)"
    )

    # Shopify integration
    shopify_discount_code = models.CharField(
        max_length=255,
        blank=True,
        help_text="Pre-created Shopify discount code to use"
    )
    create_shopify_discount = models.BooleanField(
        default=False,
        help_text="Automatically create a unique Shopify discount code when redeemed"
    )

    # Limits
    max_redemptions = models.IntegerField(
        null=True,
        blank=True,
        help_text="Maximum total redemptions (null = unlimited)"
    )
    max_per_customer = models.IntegerField(
        null=True,
        blank=True,
        help_text="Maximum redemptions per customer (null = unlimited)"
    )
    minimum_order_value = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Minimum order value to use this reward"
    )

    # Status
    is_active = models.BooleanField(default=True)
    valid_from = models.DateTimeField(null=True, blank=True)
    valid_until = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['points_cost']
        verbose_name = 'Reward'
        verbose_name_plural = 'Rewards'

    def __str__(self):
        return f"{self.name} ({self.points_cost} points)"

    @property
    def redemption_count(self):
        return self.redemptions.count()


class PointsBalance(models.Model):
    """
    Current points balance for each user.
    """
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='points_balance'
    )
    balance = models.IntegerField(default=0)
    lifetime_earned = models.IntegerField(default=0)
    lifetime_spent = models.IntegerField(default=0)

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Points Balance'
        verbose_name_plural = 'Points Balances'

    def __str__(self):
        return f"{self.user.email}: {self.balance} points"


class PointsTransaction(models.Model):
    """
    Log of all points earned and spent.
    """
    TRANSACTION_TYPE_CHOICES = [
        ('earned', 'Points Earned'),
        ('spent', 'Points Spent'),
        ('adjusted', 'Manual Adjustment'),
        ('expired', 'Points Expired'),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='points_transactions'
    )
    transaction_type = models.CharField(max_length=20, choices=TRANSACTION_TYPE_CHOICES)
    points = models.IntegerField()  # Positive for earned, negative for spent
    balance_after = models.IntegerField()

    # Reference to what caused this transaction
    description = models.CharField(max_length=500)
    rule = models.ForeignKey(
        PointsRule,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='transactions'
    )
    reward = models.ForeignKey(
        Reward,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='transactions'
    )

    # Shopify order reference
    shopify_order_id = models.CharField(max_length=255, blank=True)
    shopify_order_name = models.CharField(max_length=50, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Points Transaction'
        verbose_name_plural = 'Points Transactions'

    def __str__(self):
        return f"{self.user.email}: {self.points:+d} points - {self.description}"


class Redemption(models.Model):
    """
    Record of reward redemptions.
    """
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled'),
        ('expired', 'Expired'),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='redemptions'
    )
    reward = models.ForeignKey(
        Reward,
        on_delete=models.CASCADE,
        related_name='redemptions'
    )
    points_spent = models.IntegerField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')

    # Generated discount code (if applicable)
    discount_code = models.CharField(max_length=255, blank=True)
    discount_code_used = models.BooleanField(default=False)

    # Shopify reference
    shopify_discount_id = models.CharField(max_length=255, blank=True)
    shopify_order_id = models.CharField(max_length=255, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    used_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Redemption'
        verbose_name_plural = 'Redemptions'

    def __str__(self):
        return f"{self.user.email} redeemed {self.reward.name}"


class ProcessedOrder(models.Model):
    """
    Track which Shopify orders have been processed for points.
    Prevents duplicate point awards.
    """
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='processed_orders'
    )
    shopify_order_id = models.CharField(max_length=255, unique=True)
    shopify_order_name = models.CharField(max_length=50)
    order_total = models.DecimalField(max_digits=10, decimal_places=2)
    points_awarded = models.IntegerField()

    processed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Processed Order'
        verbose_name_plural = 'Processed Orders'

    def __str__(self):
        return f"{self.shopify_order_name} - {self.points_awarded} points"


class Notification(models.Model):
    """
    Notifications/announcements for users.
    Created by admin, shown on home screen.
    """
    NOTIFICATION_TYPE_CHOICES = [
        ('announcement', 'Announcement'),
        ('promotion', 'Promotion'),
        ('event', 'Event'),
        ('news', 'News'),
    ]

    title = models.CharField(max_length=200)
    message = models.TextField()
    notification_type = models.CharField(
        max_length=20,
        choices=NOTIFICATION_TYPE_CHOICES,
        default='announcement'
    )

    # Optional link (e.g., to a product or external page)
    link_url = models.URLField(blank=True, help_text="Optional link to open when tapped")
    link_text = models.CharField(max_length=50, blank=True, help_text="Button text (e.g., 'View Products')")

    # Targeting
    is_active = models.BooleanField(default=True)
    show_from = models.DateTimeField(null=True, blank=True, help_text="Leave empty to show immediately")
    show_until = models.DateTimeField(null=True, blank=True, help_text="Leave empty to show indefinitely")

    # Tracking
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Notification'
        verbose_name_plural = 'Notifications'

    def __str__(self):
        return self.title

    @property
    def is_visible(self):
        """Check if notification should be shown based on dates."""
        from django.utils import timezone
        now = timezone.now()

        if not self.is_active:
            return False
        if self.show_from and now < self.show_from:
            return False
        if self.show_until and now > self.show_until:
            return False
        return True


class NotificationRead(models.Model):
    """
    Track which notifications a user has dismissed.
    """
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='read_notifications'
    )
    notification = models.ForeignKey(
        Notification,
        on_delete=models.CASCADE,
        related_name='read_by'
    )
    read_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ['user', 'notification']
        verbose_name = 'Notification Read'
        verbose_name_plural = 'Notifications Read'

    def __str__(self):
        return f"{self.user.email} read {self.notification.title}"
