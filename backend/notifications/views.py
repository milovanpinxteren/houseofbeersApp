import logging

from django.conf import settings
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import NotificationPreference, PushSubscription
from .serializers import (
    NotificationPreferenceSerializer, PushSubscriptionSerializer,
    SubscribeSerializer, UnsubscribeSerializer,
)

logger = logging.getLogger(__name__)


class SubscribeView(APIView):
    """Register (or refresh) a browser push subscription.

    The client re-subscribes on every launch, so this upserts by endpoint. A
    subscription can move between users when a device is shared - the endpoint
    is reassigned to whoever is signed in now.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = SubscribeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        validated = serializer.validated_data

        defaults = {
            'user': request.user,
            'p256dh': validated['keys']['p256dh'],
            'auth': validated['keys']['auth'],
            'is_active': True,
            'failure_count': 0,
            'deactivated_at': None,
            'last_seen_at': timezone.now(),
        }
        # Only overwrite the label when the client actually sent one.
        device_label = validated.get('device_label', '')
        if device_label:
            defaults['device_label'] = device_label

        subscription, created = PushSubscription.objects.update_or_create(
            endpoint=validated['endpoint'],
            defaults=defaults,
        )

        return Response(
            PushSubscriptionSerializer(subscription).data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )


class UnsubscribeView(APIView):
    """Deactivate a subscription. Idempotent: 200 even if it is already gone."""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = UnsubscribeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        subscription = PushSubscription.objects.filter(
            endpoint=serializer.validated_data['endpoint'],
            user=request.user,
        ).first()

        if subscription is None:
            return Response({'success': True, 'found': False})

        subscription.deactivate()
        return Response({'success': True, 'found': True})


class PreferencesView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        preference = NotificationPreference.for_user(request.user)
        return Response(NotificationPreferenceSerializer(preference).data)

    def patch(self, request):
        preference = NotificationPreference.for_user(request.user)
        serializer = NotificationPreferenceSerializer(
            preference, data=request.data, partial=True,
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


class VapidPublicKeyView(APIView):
    """The VAPID public key the PWA needs for pushManager.subscribe().

    Public by design - it is also baked into the web build as
    EXPO_PUBLIC_VAPID_PUBLIC_KEY.
    """
    permission_classes = [AllowAny]

    def get(self, request):
        return Response({'public_key': settings.VAPID_PUBLIC_KEY})
