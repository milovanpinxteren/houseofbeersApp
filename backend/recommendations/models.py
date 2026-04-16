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
    untappd_rating = models.DecimalField(max_digits=3, decimal_places=2, null=True, blank=True)
    abv = models.DecimalField(max_digits=4, decimal_places=1, null=True, blank=True)
    style = models.CharField(max_length=100, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'recommendations_favorite'
        unique_together = ['user', 'beer_id']
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.user.email} - {self.title}"
