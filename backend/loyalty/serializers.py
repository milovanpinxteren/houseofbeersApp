from rest_framework import serializers
from .models import PointsRule, Reward, PointsBalance, PointsTransaction, Redemption, Notification


class PointsRuleSerializer(serializers.ModelSerializer):
    rule_type_display = serializers.CharField(source='get_rule_type_display', read_only=True)

    class Meta:
        model = PointsRule
        fields = ['id', 'name', 'description', 'rule_type', 'rule_type_display',
                  'points', 'condition_value', 'multiplier', 'is_active']


class RewardSerializer(serializers.ModelSerializer):
    reward_type_display = serializers.CharField(source='get_reward_type_display', read_only=True)
    can_redeem = serializers.SerializerMethodField()

    class Meta:
        model = Reward
        fields = ['id', 'name', 'description', 'reward_type', 'reward_type_display',
                  'points_cost', 'discount_amount', 'discount_percentage',
                  'minimum_order_value', 'is_active', 'can_redeem']

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

    class Meta:
        model = PointsTransaction
        fields = ['id', 'transaction_type', 'transaction_type_display', 'points',
                  'balance_after', 'description', 'shopify_order_name', 'created_at']


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
