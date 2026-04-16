from django.contrib import admin
from django.urls import path, include
from users.views import password_reset_page

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/', include('users.urls')),
    path('api/loyalty/', include('loyalty.urls')),
    path('api/recommendations/', include('recommendations.urls')),
    path('reset-password/', password_reset_page, name='password_reset_page'),
]
