from django.db import models
from django.conf import settings


class UntappdProfile(models.Model):
    """Stores user's linked Untappd username."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='untappd_profile'
    )
    username = models.CharField(max_length=100)
    linked_at = models.DateTimeField(auto_now_add=True)
    last_synced = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'recommendations_untappd_profile'

    def __str__(self):
        return f"{self.user.email} -> {self.username}"


class Favorite(models.Model):
    """User's saved/wishlisted beers."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='favorite_beers'
    )
    # Beer info from recommendation API
    beer_id = models.CharField(max_length=50)  # ID from recommendation API
    variant_id = models.CharField(max_length=50, blank=True)  # Shopify variant ID for cart
    title = models.CharField(max_length=255)
    vendor = models.CharField(max_length=255, blank=True)
    price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    image_url = models.URLField(max_length=500, blank=True)
    product_url = models.URLField(max_length=500, blank=True)
    untappd_rating = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    abv = models.DecimalField(max_digits=4, decimal_places=1, null=True, blank=True)
    style = models.CharField(max_length=100, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'recommendations_favorite'
        unique_together = ['user', 'beer_id']
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.user.email} - {self.title}"


class SixpackCheckout(models.Model):
    """
    A minted sixpack checkout: the selected beers, the charm price and the
    single-use Shopify discount code. Re-checkouts of the identical pack
    reuse the stored code instead of minting a new one.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='sixpack_checkouts'
    )
    pack_hash = models.CharField(max_length=64, db_index=True)  # sha256 of sorted variant ids
    items = models.JSONField()  # [{shopify_id, variant_id, title, price}]
    pack_value = models.DecimalField(max_digits=10, decimal_places=2)
    charm_price = models.DecimalField(max_digits=10, decimal_places=2)
    discount_amount = models.DecimalField(max_digits=10, decimal_places=2)
    discount_code = models.CharField(max_length=32, blank=True)
    shopify_discount_id = models.CharField(max_length=255, blank=True)
    cart_url = models.TextField()
    expires_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'recommendations_sixpack_checkout'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', 'pack_hash', 'created_at']),
        ]

    def __str__(self):
        return f"{self.user.email} - {self.discount_code or 'no code'} ({self.charm_price})"
