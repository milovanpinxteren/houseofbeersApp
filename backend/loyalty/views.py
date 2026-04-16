import logging
from rest_framework import status
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from users.services import ShopifyService
from .models import PointsBalance, Redemption
from .services import LoyaltyService
from .serializers import (
    RewardSerializer, PointsBalanceSerializer, PointsTransactionSerializer,
    RedemptionSerializer, RedeemRewardSerializer, LoyaltySummarySerializer
)

logger = logging.getLogger(__name__)


class LoyaltySummaryView(APIView):
    """Get loyalty summary for current user."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        service = LoyaltyService()
        balance = service.get_or_create_balance(request.user)
        available_rewards = service.get_available_rewards(request.user)
        pending_redemptions = Redemption.objects.filter(
            user=request.user, status='pending'
        ).count()

        data = {
            'balance': balance.balance,
            'lifetime_earned': balance.lifetime_earned,
            'lifetime_spent': balance.lifetime_spent,
            'pending_redemptions': pending_redemptions,
            'available_rewards_count': len(available_rewards),
        }
        serializer = LoyaltySummarySerializer(data)
        return Response(serializer.data)


class PointsBalanceView(APIView):
    """Get detailed points balance for current user."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        service = LoyaltyService()
        balance = service.get_or_create_balance(request.user)
        serializer = PointsBalanceSerializer(balance)
        return Response(serializer.data)


class PointsTransactionsView(APIView):
    """Get points transaction history for current user."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        service = LoyaltyService()
        transactions = service.get_user_transactions(request.user)
        serializer = PointsTransactionSerializer(transactions, many=True)
        return Response({'transactions': serializer.data})


class RewardsListView(APIView):
    """List all available rewards."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        service = LoyaltyService()
        rewards = service.get_all_rewards()
        serializer = RewardSerializer(rewards, many=True, context={'request': request})
        return Response({'rewards': serializer.data})


class RedeemRewardView(APIView):
    """Redeem a reward."""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = RedeemRewardSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        service = LoyaltyService()
        result = service.redeem_reward(
            request.user,
            serializer.validated_data['reward_id']
        )

        if result['success']:
            return Response(result)
        return Response(result, status=status.HTTP_400_BAD_REQUEST)


class RedemptionsListView(APIView):
    """List user's redemptions."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        service = LoyaltyService()
        redemptions = service.get_user_redemptions(request.user)
        serializer = RedemptionSerializer(redemptions, many=True)
        return Response({'redemptions': serializer.data})


class SyncPointsView(APIView):
    """
    Sync points from Shopify orders.
    Recalculates all points from scratch using current rules.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        user = request.user

        if not user.shopify_customer_id:
            return Response(
                {'error': 'No Shopify account linked'},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            # Fetch orders from Shopify
            shopify_service = ShopifyService()
            orders = shopify_service.get_customer_orders(user.shopify_customer_id)

            # Process orders for points
            loyalty_service = LoyaltyService()
            result = loyalty_service.recalculate_all_points(user, orders)

            # Get updated balance
            balance = loyalty_service.get_or_create_balance(user)

            return Response({
                'success': True,
                'points_awarded': result['total_awarded'],
                'orders_processed': result['processed_count'],
                'orders_skipped': result['skipped_count'],
                'new_balance': balance.balance,
            })

        except Exception as e:
            logger.error(f"Failed to sync points for {user.email}: {e}")
            return Response(
                {'error': 'Failed to sync points'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class NotificationsListView(APIView):
    """List active notifications for the current user."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from django.utils import timezone
        from django.db import models
        from .models import Notification
        from .serializers import NotificationSerializer

        now = timezone.now()

        # Get active notifications within their display period
        notifications = Notification.objects.filter(
            is_active=True
        ).filter(
            models.Q(show_from__isnull=True) | models.Q(show_from__lte=now)
        ).filter(
            models.Q(show_until__isnull=True) | models.Q(show_until__gte=now)
        ).order_by('-created_at')

        serializer = NotificationSerializer(
            notifications, many=True, context={'request': request}
        )
        return Response({'notifications': serializer.data})


class NotificationDismissView(APIView):
    """Mark a notification as read/dismissed."""
    permission_classes = [IsAuthenticated]

    def post(self, request, notification_id):
        from .models import Notification, NotificationRead

        try:
            notification = Notification.objects.get(id=notification_id)
        except Notification.DoesNotExist:
            return Response(
                {'error': 'Notification not found'},
                status=status.HTTP_404_NOT_FOUND
            )

        NotificationRead.objects.get_or_create(
            user=request.user,
            notification=notification
        )

        return Response({'success': True})
