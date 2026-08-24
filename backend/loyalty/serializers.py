import random

from rest_framework import serializers
from .models import PointsRule, RewardCategory, Reward, PointsBalance, PointsTransaction, Redemption, Notification


class PointsRuleSerializer(serializers.ModelSerializer):
    rule_type_display = serializers.CharField(source='get_rule_type_display', read_only=True)

    class Meta:
        model = PointsRule
        fields = ['id', 'name', 'description', 'rule_type', 'rule_type_display',
                  'points', 'condition_value', 'multiplier', 'only_after_registration',
                  'is_active']


class RewardCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = RewardCategory
        fields = ['id', 'name']


class RewardSerializer(serializers.ModelSerializer):
    reward_type_display = serializers.CharField(source='get_reward_type_display', read_only=True)
    can_redeem = serializers.SerializerMethodField()

    class Meta:
        model = Reward
        fields = ['id', 'name', 'description', 'reward_type', 'reward_type_display',
                  'points_cost', 'discount_amount', 'discount_percentage',
                  'minimum_order_value', 'is_active', 'can_redeem', 'image_url']

    def get_can_redeem(self, obj):
        request = self.context.get('request')
        if not request or not request.user.is_authenticated:
            return False
        try:
            balance = request.user.points_balance
            return balance.balance >= obj.points_cost
        except PointsBalance.DoesNotExist:
            return False


class PointsBalanceSerializer(serializers.ModelSerializer):
    class Meta:
        model = PointsBalance
        fields = ['balance', 'lifetime_earned', 'lifetime_spent', 'updated_at']


class PointsTransactionSerializer(serializers.ModelSerializer):
    transaction_type_display = serializers.CharField(source='get_transaction_type_display', read_only=True)
    reward_name = serializers.CharField(source='reward.name', read_only=True, default=None)

    class Meta:
        model = PointsTransaction
        fields = ['id', 'transaction_type', 'transaction_type_display', 'points',
                  'balance_after', 'description', 'breakdown', 'reward_name',
                  'shopify_order_name', 'created_at']


class RedemptionSerializer(serializers.ModelSerializer):
    reward_name = serializers.CharField(source='reward.name', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = Redemption
        fields = ['id', 'reward', 'reward_name', 'points_spent', 'status', 'status_display',
                  'discount_code', 'discount_code_used', 'created_at', 'expires_at']


class RedeemRewardSerializer(serializers.Serializer):
    reward_id = serializers.IntegerField()


class LoyaltySummarySerializer(serializers.Serializer):
    """Summary of user's loyalty status."""
    balance = serializers.IntegerField()
    lifetime_earned = serializers.IntegerField()
    lifetime_spent = serializers.IntegerField()
    pending_redemptions = serializers.IntegerField()
    available_rewards_count = serializers.IntegerField()

class NotificationSerializer(serializers.ModelSerializer):
    notification_type_display = serializers.CharField(source='get_notification_type_display', read_only=True)
    is_read = serializers.SerializerMethodField()

    class Meta:
        model = Notification
        fields = ['id', 'title', 'message', 'notification_type', 'notification_type_display',
                  'link_url', 'link_text', 'created_at', 'is_read']

    def get_is_read(self, obj):
        request = self.context.get('request')
        if not request or not request.user.is_authenticated:
            return False
        return obj.read_by.filter(user=request.user).exists()


def serialize_campaign(campaign, progress, award):
    """
    One non-raffle campaign for /api/loyalty/campaigns/ — the in-app "Acties"
    cards. `progress` and `award` are the caller's rows (or None): a card is
    either a teaser (how to earn) or the qualified state (what you got).
    """
    qualified = bool(progress and progress.qualified_at)
    discount_expires_at = None
    if award and award.discount_code and campaign.discount_validity_days:
        from datetime import timedelta
        discount_expires_at = award.created_at + timedelta(
            days=campaign.discount_validity_days
        )
    return {
        'id': campaign.id,
        'name': campaign.name,
        'rule_sentence': campaign.rule_sentence,
        'action_type': campaign.action_type,
        'status': campaign.status,
        'window_start': campaign.window_start,
        'window_end': campaign.window_end,
        'qualified': qualified,
        'qualified_at': progress.qualified_at if qualified else None,
        'points_awarded': award.points_awarded if award else 0,
        'discount_code': (award.discount_code or None) if award else None,
        'discount_expires_at': discount_expires_at,
    }


def _raffle_first_name(user):
    return user.first_name or user.email.split('@')[0]


def serialize_raffle(raffle, user, entry):
    """
    One raffle as the FROZEN /api/loyalty/raffles/ shape (see
    CAMPAIGN_CONTRACT.md - the mobile app depends on it field-for-field).
    Expects `entries__user` and `winners__user` to be prefetched; `entry` is
    the caller's RaffleEntry or None (teaser card for non-entrants).
    """
    campaign = raffle.campaign
    data = {
        'id': raffle.id,
        'campaign_id': campaign.id,
        'title': campaign.name,
        'rule_sentence': campaign.rule_sentence,
        'prize_name': raffle.prize_name,
        'prize_description': raffle.prize_description,
        'prize_image_url': raffle.prize_image_url,
        'draw_at': raffle.draw_at,
        'status': raffle.status,
        'entered': entry is not None,
        'ticket_count': entry.ticket_count if entry else 0,
        'matched_products': entry.matched_products if entry else [],
        'seen': bool(entry and entry.seen_at),
        'result_seen': bool(entry and entry.result_seen_at),
        'entrant_count': len(raffle.entries.all()),
        'entrant_first_names': None,
        'winner_first_names': None,
        'did_win': None,
        'my_code': None,
        'my_code_expires_at': None,
        'public_winner_names': None,
    }

    if raffle.status == 'drawn':
        # Shuffled so the reveal animation can cycle names without leaking
        # entry order; winners stay in draw order (creation pk order).
        entrant_names = [_raffle_first_name(e.user) for e in raffle.entries.all()]
        random.shuffle(entrant_names)
        winners = sorted(raffle.winners.all(), key=lambda w: w.pk)
        winner_names = [_raffle_first_name(w.user) for w in winners]
        my_win = next((w for w in winners if w.user_id == user.id), None)

        data['entrant_first_names'] = entrant_names
        data['winner_first_names'] = winner_names
        data['public_winner_names'] = winner_names
        data['did_win'] = my_win is not None
        if my_win:
            data['my_code'] = my_win.prize_code or None
            data['my_code_expires_at'] = my_win.code_expires_at

    return data
