from rest_framework import serializers
from .models import UntappdProfile, Favorite


class UntappdProfileSerializer(serializers.ModelSerializer):
    """Serializer for Untappd profile."""

    class Meta:
        model = UntappdProfile
        fields = ['username', 'linked_at', 'last_synced']
        read_only_fields = ['linked_at', 'last_synced']


class LinkUntappdSerializer(serializers.Serializer):
    """Serializer for linking Untappd account."""
    username = serializers.CharField(max_length=100)


class FavoriteSerializer(serializers.ModelSerializer):
    """Serializer for favorite beers."""

    class Meta:
        model = Favorite
        fields = [
            'id', 'beer_id', 'variant_id', 'title', 'vendor',
            'price', 'image_url', 'product_url', 'untappd_rating',
            'abv', 'style', 'created_at'
        ]
        read_only_fields = ['id', 'created_at']


class AddFavoriteSerializer(serializers.Serializer):
    """Serializer for adding a beer to favorites."""
    beer_id = serializers.CharField(max_length=50)
    variant_id = serializers.CharField(max_length=50, required=False, allow_blank=True)
    title = serializers.CharField(max_length=255)
    vendor = serializers.CharField(max_length=255, required=False, allow_blank=True)
    price = serializers.DecimalField(max_digits=10, decimal_places=2, required=False, allow_null=True)
    image_url = serializers.URLField(max_length=500, required=False, allow_blank=True)
    product_url = serializers.URLField(max_length=500, required=False, allow_blank=True)
    untappd_rating = serializers.DecimalField(max_digits=3, decimal_places=2, required=False, allow_null=True)
    abv = serializers.DecimalField(max_digits=4, decimal_places=1, required=False, allow_null=True)
    style = serializers.CharField(max_length=100, required=False, allow_blank=True)


class RecommendationFilterSerializer(serializers.Serializer):
    """Serializer for recommendation filters."""
    limit = serializers.IntegerField(default=10, min_value=1, max_value=50)
    price_max = serializers.DecimalField(max_digits=10, decimal_places=2, required=False, allow_null=True)
    style_filter = serializers.CharField(max_length=100, required=False, allow_blank=True)
