import logging
from rest_framework import status
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from .models import PointsBalance, Redemption
from .services import LoyaltyService
from .serializers import (
    RewardSerializer, PointsBalanceSerializer, PointsTransactionSerializer,
    RedemptionSerializer, RedeemRewardSerializer, LoyaltySummarySerializer,
    PointsRuleSerializer
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


class PointsRulesView(APIView):
    """List the currently active points rules so the app can explain how points are earned."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        service = LoyaltyService()
        rules = service.get_active_rules()
        serializer = PointsRuleSerializer(rules, many=True)
        return Response({'rules': serializer.data})


class RewardsListView(APIView):
    """List all available rewards, grouped by category."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        service = LoyaltyService()
        grouped = service.get_rewards_grouped()

        categories = []
        for cat_group in grouped['categories']:
            categories.append({
                'id': cat_group['id'],
                'name': cat_group['name'],
                'rewards': RewardSerializer(
                    cat_group['rewards'], many=True, context={'request': request}
                ).data,
            })

        uncategorized = RewardSerializer(
            grouped['uncategorized'], many=True, context={'request': request}
        ).data

        return Response({
            'categories': categories,
            'uncategorized': uncategorized,
        })


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


class RafflesListView(APIView):
    """
    Campaign raffles for the Home/Loyalty cards. FROZEN shape - see
    serialize_raffle. Open raffles of active campaigns are visible to every
    authenticated user (non-entrants get a teaser with entered=false). Drawn
    raffles are the caller's personal archive (the Loyalty codes tab): every
    raffle they entered, newest first, capped so the payload stays bounded
    and a winner's code stays reachable for as long as it is valid.
    """
    permission_classes = [IsAuthenticated]

    DRAWN_HISTORY_LIMIT = 20

    def get(self, request):
        from .models import CampaignRaffle
        from .serializers import serialize_raffle

        open_raffles = list(
            CampaignRaffle.objects.filter(status='open', campaign__status='active')
            .select_related('campaign')
            .prefetch_related('entries__user', 'winners__user')
        )
        # Audience-selected raffles have no "how to enter" — showing a teaser
        # to someone outside the selection would be a promise they can't act
        # on, so only entrants see them.
        open_raffles = [
            r for r in open_raffles
            if r.campaign.audience_mode != 'audience'
            or any(e.user_id == request.user.id for e in r.entries.all())
        ]
        drawn_raffles = list(
            CampaignRaffle.objects.filter(status='drawn', entries__user=request.user)
            .select_related('campaign')
            .prefetch_related('entries__user', 'winners__user')
            .order_by('-drawn_at')[:self.DRAWN_HISTORY_LIMIT]
        )
        raffles = open_raffles + drawn_raffles

        # Open raffles first (soonest draw first, manual-draw ones last),
        # then drawn raffles newest first.
        def sort_key(r):
            if r.status == 'open':
                return (0, r.draw_at.timestamp() if r.draw_at else float('inf'))
            return (1, -(r.drawn_at.timestamp() if r.drawn_at else 0))

        raffles.sort(key=sort_key)

        results = []
        for raffle in raffles:
            entry = next(
                (e for e in raffle.entries.all() if e.user_id == request.user.id),
                None,
            )
            results.append(serialize_raffle(raffle, request.user, entry))
        return Response({'raffles': results})


class RaffleSeenView(APIView):
    """Marks the caller's entry as seen (opened the raffle card).

    Always an empty 204 - the mobile client depends on that - and a no-op
    when the caller has no entry or the timestamp is already set.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, raffle_id):
        from django.utils import timezone
        from .models import RaffleEntry

        entry = RaffleEntry.objects.filter(
            raffle_id=raffle_id, user=request.user,
        ).first()
        if entry and entry.seen_at is None:
            entry.seen_at = timezone.now()
            entry.save(update_fields=['seen_at'])
        return Response(status=status.HTTP_204_NO_CONTENT)


class RaffleResultSeenView(APIView):
    """Marks the caller's entry as having watched the reveal. Empty 204."""
    permission_classes = [IsAuthenticated]

    def post(self, request, raffle_id):
        from django.utils import timezone
        from .models import RaffleEntry

        entry = RaffleEntry.objects.filter(
            raffle_id=raffle_id, user=request.user,
        ).first()
        if entry and entry.result_seen_at is None:
            entry.result_seen_at = timezone.now()
            entry.save(update_fields=['result_seen_at'])
        return Response(status=status.HTTP_204_NO_CONTENT)


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
