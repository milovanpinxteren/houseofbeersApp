from django.contrib import admin
from .models import UntappdProfile, Favorite


@admin.register(UntappdProfile)
class UntappdProfileAdmin(admin.ModelAdmin):
    list_display = ['user', 'username', 'linked_at', 'last_synced']
    search_fields = ['user__email', 'username']
    readonly_fields = ['linked_at', 'last_synced']


@admin.register(Favorite)
class FavoriteAdmin(admin.ModelAdmin):
    list_display = ['user', 'title', 'style', 'price', 'created_at']
    list_filter = ['style', 'created_at']
    search_fields = ['user__email', 'title', 'vendor']
    readonly_fields = ['created_at']
