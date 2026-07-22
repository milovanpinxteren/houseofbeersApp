import logging
import secrets
import string
from decimal import Decimal
from datetime import timedelta
from typing import Optional, List, Dict, Any

from django.db import transaction
from django.utils import timezone

from loyalty.models import (
    PointsRule, Reward, PointsBalance, PointsTransaction,
    Redemption, ProcessedOrder, SyncState
)

logger = logging.getLogger(__name__)


class LoyaltyService:
    """Service for managing loyalty points."""

    def get_or_create_balance(self, user) -> PointsBalance:
        """Get or create a points balance for a user."""
        balance, created = PointsBalance.objects.get_or_create(user=user)
        if created:
            logger.info(f"Created points balance for {user.email}")
        return balance

    def get_active_rules(self) -> List[PointsRule]:
        """Get all currently active point rules."""
        now = timezone.now()
        return PointsRule.objects.filter(
            is_active=True
        ).filter(
            models.Q(valid_from__isnull=True) | models.Q(valid_from__lte=now)
        ).filter(
            models.Q(valid_until__isnull=True) | models.Q(valid_until__gte=now)
        ).order_by('-priority')

    def calculate_order_points(self, user, order: Dict[str, Any]) -> Dict[str, Any]:
        """
        Calculate points to be awarded for an order.
        Returns breakdown of points by rule.

        Rules are matched against the order's creation date, not the current time.
        This ensures that promotional rules apply to orders placed during the promotion,
        even if points are synced/calculated later.
        """
        from django.db import models
        from datetime import datetime

        # Use order creation date for rule validity check
        order_created_at = order.get('created_at')
        if order_created_at:
            if isinstance(order_created_at, str):
                # Parse ISO format datetime from Shopify
                order_date = datetime.fromisoformat(order_created_at.replace('Z', '+00:00'))
            else:
                order_date = order_created_at
        else:
            # Fallback to current time if no order date available
            order_date = timezone.now()

        rules = PointsRule.objects.filter(
            is_active=True
        ).filter(
            models.Q(valid_from__isnull=True) | models.Q(valid_from__lte=order_date)
        ).filter(
            models.Q(valid_until__isnull=True) | models.Q(valid_until__gte=order_date)
        ).order_by('-priority')

        total_points = 0
        breakdown = []
        order_total = Decimal(str(order.get('total_price', 0)))
        line_items = order.get('line_items', [])

        # Check if this is the user's first order
        is_first_order = not ProcessedOrder.objects.filter(user=user).exists()

        for rule in rules:
            # Skip rules that only apply after registration if order predates it
            if rule.only_after_registration and order_date < user.date_joined:
                continue

            points_for_rule = 0

            if rule.rule_type == 'per_euro':
                # Points per euro spent
                points_for_rule = int(order_total * rule.multiplier)

            elif rule.rule_type == 'per_order':
                # Fixed points per order
                points_for_rule = rule.points

            elif rule.rule_type == 'product_sku':
                # Points for specific SKU
                for item in line_items:
                    if item.get('sku') == rule.condition_value:
                        points_for_rule += rule.points * item.get('quantity', 1)

            elif rule.rule_type == 'product_title':
                # Points for product title containing keyword
                keyword = rule.condition_value.lower()
                for item in line_items:
                    if keyword in item.get('title', '').lower():
                        points_for_rule += rule.points * item.get('quantity', 1)

            elif rule.rule_type == 'minimum_order':
                # Bonus points for orders over a minimum value
                min_value = Decimal(rule.condition_value or '0')
                if order_total >= min_value:
                    points_for_rule = rule.points

            elif rule.rule_type == 'first_order':
                # Bonus points for first order
                if is_first_order:
                    points_for_rule = rule.points

            if points_for_rule > 0:
                total_points += points_for_rule
                breakdown.append({
                    'rule_id': rule.id,
                    'rule_name': rule.name,
                    'rule_type': rule.rule_type,
                    'points': points_for_rule,
                })

        return {
            'total_points': total_points,
            'breakdown': breakdown,
            'order_total': str(order_total),
        }

    @transaction.atomic
    def award_points_for_order(self, user, order: Dict[str, Any]) -> Optional[int]:
        """
        Award points for a Shopify order.
        Returns points awarded or None if already processed.
        """
        shopify_order_id = str(order.get('id'))
        shopify_order_name = order.get('name', '')

        # Check if already processed
        if ProcessedOrder.objects.filter(shopify_order_id=shopify_order_id).exists():
            logger.info(f"Order {shopify_order_name} already processed for points")
            return None

        # Calculate points
        calculation = self.calculate_order_points(user, order)
        total_points = calculation['total_points']

        if total_points <= 0:
            logger.info(f"No points to award for order {shopify_order_name}")
            return 0

        # Get or create balance
        balance = self.get_or_create_balance(user)

        # Update balance
        balance.balance += total_points
        balance.lifetime_earned += total_points
        balance.save()

        # Create transaction record
        PointsTransaction.objects.create(
            user=user,
            transaction_type='earned',
            points=total_points,
            balance_after=balance.balance,
            description=f"Points earned from order {shopify_order_name}",
            shopify_order_id=shopify_order_id,
            shopify_order_name=shopify_order_name,
        )

        # Mark order as processed
        ProcessedOrder.objects.create(
            user=user,
            shopify_order_id=shopify_order_id,
            shopify_order_name=shopify_order_name,
            order_total=Decimal(str(order.get('total_price', 0))),
            points_awarded=total_points,
        )

        logger.info(f"Awarded {total_points} points to {user.email} for order {shopify_order_name}")
        return total_points

    def process_all_orders_for_user(self, user, orders: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Process all orders for a user and award points for unprocessed orders.
        """
        total_awarded = 0
        processed_count = 0
        skipped_count = 0

        for order in orders:
            # Only process paid orders
            if order.get('financial_status') != 'paid':
                skipped_count += 1
                continue

            points = self.award_points_for_order(user, order)
            if points is not None and points > 0:
                total_awarded += points
                processed_count += 1
            elif points is None:
                skipped_count += 1

        return {
            'total_awarded': total_awarded,
            'processed_count': processed_count,
            'skipped_count': skipped_count,
        }


    @transaction.atomic
    def check_and_correct_points(self, user, orders: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Check-and-correct sync: recalculates what each order SHOULD award with
        current rules, compares to what WAS awarded, and creates adjustment
        transactions for any differences. Also processes any unprocessed orders.

        Preserves all history — no deletions of transactions, processed orders,
        redemptions, or discount codes.
        """
        net_adjustment = 0
        corrected_count = 0
        new_count = 0
        skipped_count = 0

        for order in orders:
            if order.get('financial_status') != 'paid':
                skipped_count += 1
                continue

            shopify_order_id = str(order.get('id'))
            shopify_order_name = order.get('name', '')

            # Check if already processed
            try:
                processed = ProcessedOrder.objects.get(shopify_order_id=shopify_order_id)
            except ProcessedOrder.DoesNotExist:
                # New unprocessed order — award normally
                points = self.award_points_for_order(user, order)
                if points is not None and points > 0:
                    net_adjustment += points
                    new_count += 1
                continue

            # Already processed — check if points should be different with current rules
            calculation = self.calculate_order_points(user, order)
            should_award = calculation['total_points']
            was_awarded = processed.points_awarded
            diff = should_award - was_awarded

            if diff == 0:
                skipped_count += 1
                continue

            # Points differ — create a correction adjustment
            balance = self.get_or_create_balance(user)
            balance.balance += diff
            if diff > 0:
                balance.lifetime_earned += diff
            else:
                balance.lifetime_spent += abs(diff)
            balance.save()

            PointsTransaction.objects.create(
                user=user,
                transaction_type='adjusted',
                points=diff,
                balance_after=balance.balance,
                description=f"Points correction for order {shopify_order_name} "
                            f"({was_awarded} → {should_award})",
                shopify_order_id=shopify_order_id,
                shopify_order_name=shopify_order_name,
            )

            # Update the processed order record
            processed.points_awarded = should_award
            processed.save(update_fields=['points_awarded'])

            net_adjustment += diff
            corrected_count += 1
            logger.info(
                f"Corrected {user.email} order {shopify_order_name}: "
                f"{was_awarded} → {should_award} (diff: {diff:+d})"
            )

        # Recalculate balance_after on all transactions in chronological order
        running_balance = 0
        all_transactions = PointsTransaction.objects.filter(user=user).order_by('created_at')
        for txn in all_transactions:
            running_balance += txn.points
            if txn.balance_after != running_balance:
                txn.balance_after = running_balance
                txn.save(update_fields=['balance_after'])

        return {
            'net_adjustment': net_adjustment,
            'corrected_count': corrected_count,
            'new_count': new_count,
            'skipped_count': skipped_count,
        }

    def get_available_rewards(self, user) -> List[Reward]:
        """Get rewards available for redemption."""
        from django.db import models

        now = timezone.now()
        balance = self.get_or_create_balance(user)

        rewards = Reward.objects.filter(
            is_active=True,
            points_cost__lte=balance.balance
        ).filter(
            models.Q(valid_from__isnull=True) | models.Q(valid_from__lte=now)
        ).filter(
            models.Q(valid_until__isnull=True) | models.Q(valid_until__gte=now)
        )

        # Filter by max redemptions
        available = []
        for reward in rewards:
            # Check global max
            if reward.max_redemptions:
                if reward.redemption_count >= reward.max_redemptions:
                    continue

            # Check per-customer max
            if reward.max_per_customer:
                user_redemptions = Redemption.objects.filter(
                    user=user,
                    reward=reward,
                    status__in=['pending', 'completed']
                ).count()
                if user_redemptions >= reward.max_per_customer:
                    continue

            available.append(reward)

        return available

    def get_all_rewards(self) -> List[Reward]:
        """Get all active rewards (regardless of points balance)."""
        from django.db import models

        now = timezone.now()
        return list(Reward.objects.filter(
            is_active=True
        ).filter(
            models.Q(valid_from__isnull=True) | models.Q(valid_from__lte=now)
        ).filter(
            models.Q(valid_until__isnull=True) | models.Q(valid_until__gte=now)
        ))

    def _generate_discount_code(self) -> str:
        """Generate a unique discount code."""
        chars = string.ascii_uppercase + string.digits
        code = 'HOB-' + ''.join(secrets.choice(chars) for _ in range(8))
        return code

    def _create_shopify_discount(self, user, reward: Reward, code: str) -> Optional[Dict[str, Any]]:
        """
        Create a Shopify discount code for a reward.
        Supports all reward types: fixed_discount, percentage_discount, free_shipping, free_product.
        """
        from users.services import ShopifyService

        try:
            shopify_service = ShopifyService()
            title = f"Loyalty Reward - {reward.name}"
            result = None

            if reward.reward_type == 'fixed_discount' and reward.discount_amount:
                result = shopify_service.create_basic_discount(
                    code=code,
                    title=title,
                    discount_type='fixed_amount',
                    value=float(reward.discount_amount),
                    usage_limit=1,
                )

            elif reward.reward_type == 'percentage_discount' and reward.discount_percentage:
                result = shopify_service.create_basic_discount(
                    code=code,
                    title=title,
                    discount_type='percentage',
                    value=float(reward.discount_percentage),
                    usage_limit=1,
                )

            elif reward.reward_type == 'free_shipping':
                result = shopify_service.create_free_shipping_discount(
                    code=code,
                    title=title,
                    usage_limit=1,
                )

            elif reward.reward_type == 'free_product' and reward.shopify_product_id:
                result = shopify_service.create_free_product_discount(
                    code=code,
                    title=title,
                    product_id=reward.shopify_product_id,
                    usage_limit=1,
                )

            else:
                logger.warning(f"Cannot create Shopify discount for reward type: {reward.reward_type}")
                return None

            return result
        except Exception as e:
            logger.error(f"Failed to create Shopify discount: {e}")
            return None

    @transaction.atomic
    def redeem_reward(self, user, reward_id: int) -> Dict[str, Any]:
        """
        Redeem a reward for a user.
        Returns redemption details including discount code if applicable.
        """
        try:
            reward = Reward.objects.get(id=reward_id, is_active=True)
        except Reward.DoesNotExist:
            return {'success': False, 'error': 'Reward not found or inactive'}

        balance = self.get_or_create_balance(user)

        # Check if user has enough points
        if balance.balance < reward.points_cost:
            return {
                'success': False,
                'error': f'Not enough points. You have {balance.balance}, need {reward.points_cost}'
            }

        # Check redemption limits
        if reward.max_per_customer:
            user_redemptions = Redemption.objects.filter(
                user=user,
                reward=reward,
                status__in=['pending', 'completed']
            ).count()
            if user_redemptions >= reward.max_per_customer:
                return {'success': False, 'error': 'Maximum redemptions reached for this reward'}

        if reward.max_redemptions:
            if reward.redemption_count >= reward.max_redemptions:
                return {'success': False, 'error': 'This reward is no longer available'}

        # Deduct points
        balance.balance -= reward.points_cost
        balance.lifetime_spent += reward.points_cost
        balance.save()

        # Create transaction
        PointsTransaction.objects.create(
            user=user,
            transaction_type='spent',
            points=-reward.points_cost,
            balance_after=balance.balance,
            description=f"Redeemed: {reward.name}",
            reward=reward,
        )

        # Generate discount code if needed
        discount_code = ''
        shopify_discount_id = ''

        if reward.create_shopify_discount:
            discount_code = self._generate_discount_code()
            # Create discount in Shopify
            shopify_result = self._create_shopify_discount(user, reward, discount_code)
            if shopify_result:
                shopify_discount_id = str(shopify_result.get('price_rule_id', ''))
        elif reward.shopify_discount_code:
            discount_code = reward.shopify_discount_code

        # Create redemption record
        redemption = Redemption.objects.create(
            user=user,
            reward=reward,
            points_spent=reward.points_cost,
            status='pending' if discount_code else 'completed',
            discount_code=discount_code,
            shopify_discount_id=shopify_discount_id,
            expires_at=timezone.now() + timedelta(days=30) if discount_code else None,
        )

        logger.info(f"{user.email} redeemed {reward.name} for {reward.points_cost} points")

        return {
            'success': True,
            'redemption_id': redemption.id,
            'reward_name': reward.name,
            'points_spent': reward.points_cost,
            'new_balance': balance.balance,
            'discount_code': discount_code,
            'expires_at': redemption.expires_at.isoformat() if redemption.expires_at else None,
        }

    @transaction.atomic
    def adjust_points(self, user, points: int, description: str) -> PointsBalance:
        """
        Manually adjust points (admin action).
        Points can be positive or negative.
        """
        balance = self.get_or_create_balance(user)

        balance.balance += points
        if points > 0:
            balance.lifetime_earned += points
        else:
            balance.lifetime_spent += abs(points)
        balance.save()

        PointsTransaction.objects.create(
            user=user,
            transaction_type='adjusted',
            points=points,
            balance_after=balance.balance,
            description=description,
        )

        logger.info(f"Adjusted {user.email} points by {points}: {description}")
        return balance

    def get_user_transactions(self, user, limit: int = 50) -> List[PointsTransaction]:
        """Get recent transactions for a user."""
        return list(PointsTransaction.objects.filter(user=user)[:limit])

    def get_user_redemptions(self, user) -> List[Redemption]:
        """Get redemptions for a user."""
        return list(Redemption.objects.filter(user=user))

    # ============ Sync Orchestration ============

    def _acquire_sync_lock(self, user) -> Optional['SyncState']:
        """
        Acquire a sync lock for the user. Returns SyncState if lock acquired, None if busy.
        Resets stale locks (>10 minutes).
        """
        sync_state, _ = SyncState.objects.get_or_create(user=user)

        if sync_state.sync_status == 'in_progress':
            if not sync_state.is_stale:
                logger.info(f"Sync already in progress for {user.email}")
                return None
            logger.warning(f"Resetting stale sync lock for {user.email}")

        sync_state.sync_status = 'in_progress'
        sync_state.sync_started_at = timezone.now()
        sync_state.last_error = ''
        sync_state.save()
        return sync_state

    def _release_sync_lock(self, sync_state: 'SyncState', success: bool, error: str = ''):
        """Release sync lock and update state."""
        if success:
            sync_state.sync_status = 'idle'
            sync_state.last_successful_sync = timezone.now()
        else:
            sync_state.sync_status = 'failed'
            sync_state.last_error = error
        sync_state.save()

    def partial_sync_for_user(self, user) -> Dict[str, Any]:
        """
        Incremental sync: fetch only new orders since last sync and process them.
        Returns result dict or error.
        """
        from users.services import ShopifyService

        if not user.shopify_customer_id:
            return {'success': False, 'error': 'No Shopify account linked'}

        sync_state = self._acquire_sync_lock(user)
        if sync_state is None:
            return {'success': False, 'error': 'Sync already in progress'}

        try:
            shopify_service = ShopifyService()

            if sync_state.last_successful_sync:
                orders = shopify_service.get_customer_orders_since(
                    user.shopify_customer_id,
                    sync_state.last_successful_sync,
                )
            else:
                # First sync ever — fetch all orders
                orders = shopify_service.get_all_customer_orders(user.shopify_customer_id)

            result = self.process_all_orders_for_user(user, orders)

            # Track highest order ID for reference
            if orders:
                max_order_id = str(max(int(o.get('id', 0)) for o in orders))
                sync_state.last_shopify_order_id = max_order_id

            self._release_sync_lock(sync_state, success=True)

            balance = self.get_or_create_balance(user)
            return {
                'success': True,
                'sync_type': 'partial',
                **result,
                'new_balance': balance.balance,
            }
        except Exception as e:
            logger.error(f"Partial sync failed for {user.email}: {e}")
            self._release_sync_lock(sync_state, success=False, error=str(e))
            return {'success': False, 'error': 'Sync failed'}

    def intermediate_sync_for_user(self, user) -> Dict[str, Any]:
        """
        Intermediate sync: fetch ALL orders (paginated), process only unprocessed ones.
        Catches orders that partial sync may have missed without recalculating anything.
        """
        from users.services import ShopifyService

        if not user.shopify_customer_id:
            return {'success': False, 'error': 'No Shopify account linked'}

        sync_state = self._acquire_sync_lock(user)
        if sync_state is None:
            return {'success': False, 'error': 'Sync already in progress'}

        try:
            shopify_service = ShopifyService()
            orders = shopify_service.get_all_customer_orders(user.shopify_customer_id)

            result = self.process_all_orders_for_user(user, orders)

            if orders:
                max_order_id = str(max(int(o.get('id', 0)) for o in orders))
                sync_state.last_shopify_order_id = max_order_id

            self._release_sync_lock(sync_state, success=True)

            balance = self.get_or_create_balance(user)
            return {
                'success': True,
                'sync_type': 'intermediate',
                **result,
                'new_balance': balance.balance,
            }
        except Exception as e:
            logger.error(f"Intermediate sync failed for {user.email}: {e}")
            self._release_sync_lock(sync_state, success=False, error=str(e))
            return {'success': False, 'error': 'Sync failed'}

    def full_sync_for_user(self, user) -> Dict[str, Any]:
        """
        Full sync (check-and-correct): fetch ALL orders, recalculate what each
        should award with current rules, and create correction adjustments for
        any differences. Also picks up unprocessed orders. No deletions.
        """
        from users.services import ShopifyService

        if not user.shopify_customer_id:
            return {'success': False, 'error': 'No Shopify account linked'}

        sync_state = self._acquire_sync_lock(user)
        if sync_state is None:
            return {'success': False, 'error': 'Sync already in progress'}

        try:
            shopify_service = ShopifyService()
            orders = shopify_service.get_all_customer_orders(user.shopify_customer_id)

            result = self.check_and_correct_points(user, orders)

            if orders:
                max_order_id = str(max(int(o.get('id', 0)) for o in orders))
                sync_state.last_shopify_order_id = max_order_id

            self._release_sync_lock(sync_state, success=True)

            balance = self.get_or_create_balance(user)
            return {
                'success': True,
                'sync_type': 'full',
                **result,
                'new_balance': balance.balance,
            }
        except Exception as e:
            logger.error(f"Full sync failed for {user.email}: {e}")
            self._release_sync_lock(sync_state, success=False, error=str(e))
            return {'success': False, 'error': 'Sync failed'}
