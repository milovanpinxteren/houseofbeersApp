from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView

from .views import (
    RegisterView,
    UserMeView,
    UserSyncShopifyView,
    UserOrdersView,
    UserDeleteAccountView,
    EmailTokenObtainPairView,
    PasswordResetRequestView,
    PasswordResetConfirmView,
)

urlpatterns = [
    path('auth/register/', RegisterView.as_view(), name='register'),
    path('auth/login/', EmailTokenObtainPairView.as_view(), name='login'),
    path('auth/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    path('auth/password-reset/', PasswordResetRequestView.as_view(), name='password_reset'),
    path('auth/password-reset/confirm/', PasswordResetConfirmView.as_view(), name='password_reset_confirm'),
    path('users/me/', UserMeView.as_view(), name='user_me'),
    path('users/me/sync-shopify/', UserSyncShopifyView.as_view(), name='user_sync_shopify'),
    path('users/me/orders/', UserOrdersView.as_view(), name='user_orders'),
    path('users/me/delete/', UserDeleteAccountView.as_view(), name='user_delete_account'),
]
