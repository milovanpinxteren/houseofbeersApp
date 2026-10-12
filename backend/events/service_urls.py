from django.urls import path

from . import service_api

urlpatterns = [
    path('upcoming-events/', service_api.upcoming_events_view,
         name='service_upcoming_events'),
    path('auction-items/upsert/', service_api.auction_item_upsert_view,
         name='service_auction_item_upsert'),
]
