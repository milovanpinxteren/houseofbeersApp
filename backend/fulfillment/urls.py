from django.urls import path

from .views import PickupDaysView, PickupRSVPView, PickupRSVPCancelView

urlpatterns = [
    path('days/', PickupDaysView.as_view(), name='pickup_days'),
    path('rsvp/', PickupRSVPView.as_view(), name='pickup_rsvp'),
    path('rsvp/cancel/', PickupRSVPCancelView.as_view(), name='pickup_rsvp_cancel'),
]
