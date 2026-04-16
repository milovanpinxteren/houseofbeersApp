from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """Custom user model with Shopify integration."""

    email = models.EmailField(unique=True)
    shopify_customer_id = models.CharField(max_length=255, blank=True, null=True)
    shopify_linked_at = models.DateTimeField(blank=True, null=True)

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['username']

    class Meta:
        db_table = 'users'

    def __str__(self):
        return self.email
