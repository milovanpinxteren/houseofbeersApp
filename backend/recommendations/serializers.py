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
    username = serializers.RegexField(
        r'^[A-Za-z0-9_.-]+$',
        max_length=100,
        error_messages={
            'invalid': 'Username may only contain letters, numbers, dots, dashes and underscores.'
        }
    )


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
    variant_id = serializers.RegexField(
        r'^\d*$',
        max_length=50,
        required=False,
        allow_blank=True,
        error_messages={'invalid': 'Variant ID must be numeric.'}
    )
    title = serializers.CharField(max_length=255)
    vendor = serializers.CharField(max_length=255, required=False, allow_blank=True)
    price = serializers.DecimalField(max_digits=10, decimal_places=2, required=False, allow_null=True)
    image_url = serializers.CharField(max_length=500, required=False, allow_blank=True)
    product_url = serializers.CharField(max_length=500, required=False, allow_blank=True)
    untappd_rating = serializers.FloatField(required=False, allow_null=True)
    abv = serializers.DecimalField(max_digits=4, decimal_places=1, required=False, allow_null=True)
    style = serializers.CharField(max_length=100, required=False, allow_blank=True)


class RecommendationFilterSerializer(serializers.Serializer):
    """Serializer for recommendation filters."""
    limit = serializers.IntegerField(default=10, min_value=1, max_value=50)
    price_max = serializers.DecimalField(max_digits=10, decimal_places=2, required=False, allow_null=True)
    style_filter = serializers.CharField(max_length=100, required=False, allow_blank=True)


class RandomBeerFilterSerializer(serializers.Serializer):
    """Optional filters for the random beer picker."""
    style = serializers.CharField(max_length=100, required=False, allow_blank=True)
    max_price = serializers.DecimalField(
        max_digits=10, decimal_places=2, required=False, allow_null=True, min_value=0
    )


class SixpackLockedSlotSerializer(serializers.Serializer):
    """A locked reel the client wants to keep during a re-spin."""
    shopify_id = serializers.CharField(max_length=50)
    role = serializers.ChoiceField(choices=['safe', 'adjacent', 'wildcard'])


class SixpackGenerateSerializer(serializers.Serializer):
    """Wizard parameters for generating a sixpack."""
    budget = serializers.DecimalField(
        max_digits=10, decimal_places=2, min_value=20, max_value=250
    )
    exclude_style_categories = serializers.ListField(
        child=serializers.CharField(max_length=50),
        required=False, default=list, max_length=20,
    )
    include_alcohol_free = serializers.BooleanField(required=False, default=False)
    adventurousness = serializers.ChoiceField(
        choices=['safe', 'balanced', 'adventurous'],
        required=False, default='balanced',
    )
    max_abv = serializers.FloatField(
        required=False, allow_null=True, min_value=0, max_value=60
    )
    locked = SixpackLockedSlotSerializer(many=True, required=False, default=list)
    exclude = serializers.ListField(
        child=serializers.CharField(max_length=50),
        required=False, default=list, max_length=120,
    )

    def validate_locked(self, value):
        if len(value) > 5:
            raise serializers.ValidationError('At most 5 slots can be locked.')
        return value


class SixpackCheckoutItemSerializer(serializers.Serializer):
    shopify_id = serializers.CharField(max_length=50)
    variant_id = serializers.RegexField(
        r'^\d+$',
        max_length=50,
        error_messages={'invalid': 'Variant ID must be numeric.'}
    )


class SixpackCheckoutSerializer(serializers.Serializer):
    """The six selected beers for checkout."""
    items = SixpackCheckoutItemSerializer(many=True, min_length=6, max_length=6)

    def validate_items(self, value):
        shopify_ids = {item['shopify_id'] for item in value}
        variant_ids = {item['variant_id'] for item in value}
        if len(shopify_ids) != 6 or len(variant_ids) != 6:
            raise serializers.ValidationError('Items must be 6 unique beers.')
        return value


class SelectedFavoritesSerializer(serializers.Serializer):
    """Serializer for generating a cart link from selected favorites."""
    favorite_ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1),
        allow_empty=False,
        max_length=200,
    )
