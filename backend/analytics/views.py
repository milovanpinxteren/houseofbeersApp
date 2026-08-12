"""
Client-side event ingestion.

The PWA reports events the backend cannot observe itself: screen views
(navigation is entirely client-side) and app-shop checkout taps (the cart
permalink is built on the client). Only whitelisted event types are
accepted; everything else is rejected so the events table stays clean.
"""

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.throttling import UserRateThrottle
from rest_framework import status

from .tracker import track

CLIENT_EVENT_TYPES = {'screen_view', 'app_shop_checkout'}

MAX_METADATA_KEYS = 10
MAX_VALUE_LENGTH = 200


class ClientEventRateThrottle(UserRateThrottle):
    rate = '120/min'


class ClientEventView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_classes = [ClientEventRateThrottle]

    def post(self, request):
        event_type = request.data.get('event_type')
        if event_type not in CLIENT_EVENT_TYPES:
            return Response(
                {'error': 'unknown_event_type'},
                status=status.HTTP_400_BAD_REQUEST
            )

        raw = request.data.get('metadata') or {}
        metadata = {}
        if isinstance(raw, dict):
            for key, value in list(raw.items())[:MAX_METADATA_KEYS]:
                if not isinstance(key, str):
                    continue
                if isinstance(value, (int, float, bool)) or value is None:
                    metadata[key[:50]] = value
                else:
                    metadata[key[:50]] = str(value)[:MAX_VALUE_LENGTH]

        track(event_type, user=request.user, **metadata)
        return Response({'ok': True})
