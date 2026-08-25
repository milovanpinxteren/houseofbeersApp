from django.urls import path

from . import service_api

urlpatterns = [
    path('grant/', service_api.grant_view, name='service_grant'),
    path('lookup/', service_api.lookup_view, name='service_lookup'),
    path('status/', service_api.status_view, name='service_grant_status'),
    path('revoke/', service_api.revoke_view, name='service_grant_revoke'),
]
