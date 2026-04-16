from django.urls import path
from .views import (
    LoyaltySummaryView,
    PointsBalanceView,
    PointsTransactionsView,
    RewardsListView,
    RedeemRewardView,
    RedemptionsListView,
    SyncPointsView,
    NotificationsListView,
    NotificationDismissView,
)

urlpatterns = [
    path("summary/", LoyaltySummaryView.as_view(), name="loyalty_summary"),
    path("balance/", PointsBalanceView.as_view(), name="points_balance"),
    path("transactions/", PointsTransactionsView.as_view(), name="points_transactions"),
    path("rewards/", RewardsListView.as_view(), name="rewards_list"),
    path("redeem/", RedeemRewardView.as_view(), name="redeem_reward"),
    path("redemptions/", RedemptionsListView.as_view(), name="redemptions_list"),
    path("sync/", SyncPointsView.as_view(), name="sync_points"),
    path("notifications/", NotificationsListView.as_view(), name="notifications_list"),
    path("notifications/<int:notification_id>/dismiss/", NotificationDismissView.as_view(), name="notification_dismiss"),
]
