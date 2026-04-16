from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from .models import User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = ['email', 'first_name', 'last_name', 'shopify_customer_id', 'is_active']
    search_fields = ['email', 'first_name', 'last_name', 'shopify_customer_id']
    ordering = ['-date_joined']

    fieldsets = BaseUserAdmin.fieldsets + (
        ('Shopify', {'fields': ('shopify_customer_id', 'shopify_linked_at')}),
    )
