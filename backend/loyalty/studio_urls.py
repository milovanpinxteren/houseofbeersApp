"""URL map of the Campagne Studio, mounted at /admin/campaign-studio/."""
from django.urls import path

from . import studio_views

app_name = 'studio'

urlpatterns = [
    path('', studio_views.campaign_list, name='campaign_list'),
    path('new/', studio_views.campaign_builder, name='campaign_create'),
    path('sentence/', studio_views.rule_sentence_preview, name='rule_sentence'),
    path('product-search/', studio_views.product_search, name='product_search'),

    path('<int:pk>/edit/', studio_views.campaign_builder, name='campaign_edit'),
    path('<int:pk>/', studio_views.campaign_preview_page, name='campaign_preview'),
    path('<int:pk>/preview/run/', studio_views.run_preview, name='run_preview'),
    path('<int:pk>/preview/status/', studio_views.preview_status, name='preview_status'),
    path('<int:pk>/test-send/', studio_views.send_test_notification, name='test_send'),
    path('<int:pk>/activate/', studio_views.activate_campaign, name='activate'),
    path('<int:pk>/deactivate/', studio_views.deactivate_campaign, name='deactivate'),
    path('<int:pk>/archive/', studio_views.archive_campaign, name='archive'),

    path('<int:pk>/monitor/', studio_views.campaign_monitor, name='campaign_monitor'),
    path('<int:pk>/draw/', studio_views.draw_now, name='draw_now'),
    path('<int:pk>/check-redemptions/', studio_views.check_redemptions, name='check_redemptions'),
    path(
        '<int:pk>/winners/<int:winner_id>/fulfill/',
        studio_views.toggle_winner_fulfilled,
        name='toggle_fulfilled',
    ),
    path('<int:pk>/entrants.csv', studio_views.export_entrants_csv, name='entrants_csv'),
]
