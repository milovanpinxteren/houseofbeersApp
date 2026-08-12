from django.urls import path

from .views import ClientEventView

urlpatterns = [
    path('event/', ClientEventView.as_view(), name='analytics_client_event'),
]
