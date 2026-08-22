from rest_framework import serializers

from .models import NotificationDelivery, NotificationPreference, PushSubscription


class PushKeysSerializer(serializers.Serializer):
    """The `keys` object the browser's PushSubscription.toJSON() produces."""
    p256dh = serializers.CharField(max_length=255)
    auth = serializers.CharField(max_length=255)


class SubscribeSerializer(serializers.Serializer):
    endpoint = serializers.CharField(max_length=2000)
    keys = PushKeysSerializer()
    device_label = serializers.CharField(
        max_length=200, required=False, allow_blank=True, default='',
    )


class UnsubscribeSerializer(serializers.Serializer):
    endpoint = serializers.CharField(max_length=2000)


class PushSubscriptionSerializer(serializers.ModelSerializer):
    class Meta:
        model = PushSubscription
        fields = [
            'id', 'endpoint', 'device_label', 'is_active',
            'last_success_at', 'last_seen_at', 'created_at',
        ]
        read_only_fields = fields


class NotificationPreferenceSerializer(serializers.ModelSerializer):
    class Meta:
        model = NotificationPreference
        fields = [
            'push_enabled', 'email_enabled',
            'birthday', 'announcements', 'recommendations', 'raffle',
            'updated_at',
        ]
        read_only_fields = ['updated_at']


class NotificationDeliverySerializer(serializers.ModelSerializer):
    class Meta:
        model = NotificationDelivery
        fields = [
            'id', 'kind', 'title', 'body', 'data', 'dedupe_key',
            'push_status', 'email_status', 'created_at', 'sent_at',
        ]
        read_only_fields = fields
