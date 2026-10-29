from django.urls import path

from . import service_api

urlpatterns = [
    path('missed/', service_api.missed_upsert_view, name='service_missed_upsert'),
]
