from django.contrib import admin
from django.urls import path, include
from users.views import password_reset_page

urlpatterns = [
    # Before admin/ so the admin catch-all cannot shadow these staff tools.
    path('admin/campaign-studio/', include('loyalty.studio_urls')),
    path('admin/points-tool/', include('loyalty.points_tool_urls')),
    path('admin/', admin.site.urls),
    path('api/', include('users.urls')),
    path('api/loyalty/', include('loyalty.urls')),
    # Server-to-server surface (HMAC-signed, used by hob) — not for the app.
    path('api/service/loyalty/', include('loyalty.service_urls')),
    path('api/recommendations/', include('recommendations.urls')),
    path('api/community/', include('community.urls')),
    path('api/events/', include('events.urls')),
    path('api/notifications/', include('notifications.urls')),
    path('api/analytics/', include('analytics.urls')),
    path('reset-password/', password_reset_page, name='password_reset_page'),
]
