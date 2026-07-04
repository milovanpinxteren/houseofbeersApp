from django.urls import path
from .views import (
    EventsListView, EventDetailView, EventJoinView,
    EventChatView, EventRaffleWinnersView,
    EventAuctionActiveView, EventAuctionHistoryView,
)

urlpatterns = [
    path('', EventsListView.as_view(), name='events-list'),
    path('<int:event_id>/', EventDetailView.as_view(), name='event-detail'),
    path('<int:event_id>/join/', EventJoinView.as_view(), name='event-join'),
    path('<int:event_id>/chat/', EventChatView.as_view(), name='event-chat'),
    path('<int:event_id>/raffle/winners/', EventRaffleWinnersView.as_view(), name='event-raffle-winners'),
    path('<int:event_id>/auction/active/', EventAuctionActiveView.as_view(), name='event-auction-active'),
    path('<int:event_id>/auction/history/', EventAuctionHistoryView.as_view(), name='event-auction-history'),
]
