import logging
from rest_framework import status
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

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
            from analytics.tracker import track
            track('reward_redeem', user=request.user, reward_id=serializer.validated_data['reward_id'])
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

    User tap triggers an intermediate sync (all orders, process unprocessed) synchronously.
    Full (check-and-correct) sync is admin-only — triggered via Django admin or CLI.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        user = request.user

        if not user.shopify_customer_id:
            return Response(
                {'error': 'No Shopify account linked'},
                status=status.HTTP_400_BAD_REQUEST
            )

        loyalty_service = LoyaltyService()
        try:
            result = loyalty_service.intermediate_sync_for_user(user)

            if not result.get('success'):
                error = result.get('error', 'Sync failed')
                if error == 'Sync already in progress':
                    return Response(
                        {'status': 'in_progress', 'message': error},
                        status=status.HTTP_409_CONFLICT
                    )
                return Response(
                    {'error': error},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR
                )

            from analytics.tracker import track
            track('points_sync', user=user, points_awarded=result.get('total_awarded', 0))

            return Response({
                'success': True,
                'points_awarded': result.get('total_awarded', 0),
                'orders_processed': result.get('processed_count', 0),
                'orders_skipped': result.get('skipped_count', 0),
                'new_balance': result.get('new_balance', 0),
            })

        except Exception as e:
            logger.error(f"Failed to sync points for {user.email}: {e}")
            return Response(
                {'error': 'Failed to sync points'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class SyncStatusView(APIView):
    """Check the status of a user's sync operation."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from loyalty.models import SyncState

        sync_state = SyncState.objects.filter(user=request.user).first()
        if not sync_state:
            return Response({
                'status': 'idle',
                'last_sync': None,
                'last_error': '',
            })

        return Response({
            'status': sync_state.sync_status,
            'last_sync': sync_state.last_successful_sync,
            'last_error': sync_state.last_error,
        })


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

        from analytics.tracker import track
        track('notification_dismiss', user=request.user)

        return Response({'success': True})
