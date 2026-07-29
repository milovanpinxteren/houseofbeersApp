from django.urls import path

from .views import (
    PreferencesView, SubscribeView, UnsubscribeView, VapidPublicKeyView,
)

urlpatterns = [
    path('subscribe/', SubscribeView.as_view(), name='notifications-subscribe'),
    path('unsubscribe/', UnsubscribeView.as_view(), name='notifications-unsubscribe'),
    path('preferences/', PreferencesView.as_view(), name='notifications-preferences'),
    path('vapid-public-key/', VapidPublicKeyView.as_view(), name='notifications-vapid-public-key'),
]
