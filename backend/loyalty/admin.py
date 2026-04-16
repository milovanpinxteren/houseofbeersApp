from django.contrib import admin
from django.utils.html import format_html
from django.utils.safestring import mark_safe
from .models import PointsRule, Reward, PointsBalance, PointsTransaction, Redemption, ProcessedOrder, Notification, NotificationRead


@admin.register(PointsRule)
class PointsRuleAdmin(admin.ModelAdmin):
    list_display = ['name', 'rule_type', 'rule_summary', 'is_active', 'priority', 'valid_from', 'valid_until']
    list_filter = ['rule_type', 'is_active']
    search_fields = ['name', 'description']
    ordering = ['-priority', '-created_at']
    readonly_fields = ['rule_preview']

    fieldsets = (
        (None, {
            'fields': ('name', 'description', 'rule_type'),
            'description': 'Choose a rule type to see which fields to fill in below.'
        }),
        ('Points Configuration', {
            'fields': ('points', 'multiplier', 'condition_value'),
            'description': '''
                <div style="background: #f8f9fa; padding: 15px; border-radius: 8px; margin-bottom: 15px; border-left: 4px solid #17a2b8;">
                    <strong style="color: #17a2b8;">📋 How to configure each rule type:</strong>
                    <table style="margin-top: 10px; width: 100%; border-collapse: collapse; font-size: 13px;">
                        <tr style="background: #e9ecef;">
                            <th style="padding: 8px; text-align: left; border: 1px solid #dee2e6;">Rule Type</th>
                            <th style="padding: 8px; text-align: left; border: 1px solid #dee2e6;">Points</th>
                            <th style="padding: 8px; text-align: left; border: 1px solid #dee2e6;">Multiplier</th>
                            <th style="padding: 8px; text-align: left; border: 1px solid #dee2e6;">Condition Value</th>
                            <th style="padding: 8px; text-align: left; border: 1px solid #dee2e6;">Example</th>
                        </tr>
                        <tr>
                            <td style="padding: 8px; border: 1px solid #dee2e6;"><strong>Points per Euro</strong></td>
                            <td style="padding: 8px; border: 1px solid #dee2e6; color: #6c757d;">Not used</td>
                            <td style="padding: 8px; border: 1px solid #dee2e6;">Order total × multiplier = points<br><small style="color:#666;">e.g., 0.1 = 1pt/€10, 1 = 1pt/€1</small></td>
                            <td style="padding: 8px; border: 1px solid #dee2e6; color: #6c757d;">Not used</td>
                            <td style="padding: 8px; border: 1px solid #dee2e6; color: #28a745;">Multiplier=0.1 → €100 order = 10 points<br>Multiplier=1 → €100 order = 100 points</td>
                        </tr>
                        <tr style="background: #f8f9fa;">
                            <td style="padding: 8px; border: 1px solid #dee2e6;"><strong>Points per Order</strong></td>
                            <td style="padding: 8px; border: 1px solid #dee2e6;">Fixed points to award</td>
                            <td style="padding: 8px; border: 1px solid #dee2e6; color: #6c757d;">Not used</td>
                            <td style="padding: 8px; border: 1px solid #dee2e6; color: #6c757d;">Not used</td>
                            <td style="padding: 8px; border: 1px solid #dee2e6; color: #28a745;">Points=50 → Every order gets 50 points</td>
                        </tr>
                        <tr>
                            <td style="padding: 8px; border: 1px solid #dee2e6;"><strong>Product by SKU</strong></td>
                            <td style="padding: 8px; border: 1px solid #dee2e6;">Points per item</td>
                            <td style="padding: 8px; border: 1px solid #dee2e6; color: #6c757d;">Not used</td>
                            <td style="padding: 8px; border: 1px solid #dee2e6;">Product SKU</td>
                            <td style="padding: 8px; border: 1px solid #dee2e6; color: #28a745;">Points=100, SKU="SPECIAL-BEER" → 100 pts per item</td>
                        </tr>
                        <tr style="background: #f8f9fa;">
                            <td style="padding: 8px; border: 1px solid #dee2e6;"><strong>Product by Title</strong></td>
                            <td style="padding: 8px; border: 1px solid #dee2e6;">Points per item</td>
                            <td style="padding: 8px; border: 1px solid #dee2e6; color: #6c757d;">Not used</td>
                            <td style="padding: 8px; border: 1px solid #dee2e6;">Keyword in title</td>
                            <td style="padding: 8px; border: 1px solid #dee2e6; color: #28a745;">Points=25, Keyword="IPA" → 25 pts for any IPA</td>
                        </tr>
                        <tr>
                            <td style="padding: 8px; border: 1px solid #dee2e6;"><strong>Minimum Order</strong></td>
                            <td style="padding: 8px; border: 1px solid #dee2e6;">Bonus points</td>
                            <td style="padding: 8px; border: 1px solid #dee2e6; color: #6c757d;">Not used</td>
                            <td style="padding: 8px; border: 1px solid #dee2e6;">Min. order €</td>
                            <td style="padding: 8px; border: 1px solid #dee2e6; color: #28a745;">Points=200, Min=100 → 200 bonus if order ≥ €100</td>
                        </tr>
                        <tr style="background: #f8f9fa;">
                            <td style="padding: 8px; border: 1px solid #dee2e6;"><strong>First Order</strong></td>
                            <td style="padding: 8px; border: 1px solid #dee2e6;">Welcome bonus</td>
                            <td style="padding: 8px; border: 1px solid #dee2e6; color: #6c757d;">Not used</td>
                            <td style="padding: 8px; border: 1px solid #dee2e6; color: #6c757d;">Not used</td>
                            <td style="padding: 8px; border: 1px solid #dee2e6; color: #28a745;">Points=500 → New customers get 500 points</td>
                        </tr>
                    </table>
                </div>
            '''
        }),
        ('Rule Preview', {
            'fields': ('rule_preview',),
            'description': 'This shows what the rule will do based on your configuration.'
        }),
        ('Status & Priority', {
            'fields': ('is_active', 'priority'),
            'description': 'Higher priority rules are evaluated first. Use this to ensure important rules apply before general ones.'
        }),
        ('Validity Period', {
            'fields': ('valid_from', 'valid_until'),
            'classes': ('collapse',),
            'description': 'Optional: Set a time period when this rule is active. Leave empty for always active.'
        }),
    )

    def rule_summary(self, obj):
        """Display a human-readable summary of the rule in the list view."""
        if obj.rule_type == 'per_euro':
            multiplier = float(obj.multiplier) if obj.multiplier else 0
            # Show as "1 point per €X" for clarity
            if multiplier > 0:
                euros_per_point = 1 / multiplier
                if euros_per_point == int(euros_per_point):
                    return format_html('<span style="color: #28a745;">1 point per €{} spent</span>', int(euros_per_point))
                else:
                    return format_html('<span style="color: #28a745;">{} points per €1 spent</span>', multiplier)
            return format_html('<span style="color: #dc3545;">Not configured</span>')
        elif obj.rule_type == 'per_order':
            return format_html('<span style="color: #28a745;">{} points per order</span>', obj.points)
        elif obj.rule_type == 'product_sku':
            return format_html('<span style="color: #17a2b8;">{} points for SKU "{}"</span>', obj.points, obj.condition_value or '?')
        elif obj.rule_type == 'product_title':
            return format_html('<span style="color: #17a2b8;">{} points for "{}" products</span>', obj.points, obj.condition_value or '?')
        elif obj.rule_type == 'minimum_order':
            return format_html('<span style="color: #ffc107;">{} bonus points on €{}+ orders</span>', obj.points, obj.condition_value or '?')
        elif obj.rule_type == 'first_order':
            return format_html('<span style="color: #6f42c1;">{} welcome bonus points</span>', obj.points)
        return '-'
    rule_summary.short_description = 'Rule Effect'

    def rule_preview(self, obj):
        """Display a detailed preview of what the rule does."""
        if not obj.pk:
            return mark_safe('''
                <div style="background: #fff3cd; padding: 15px; border-radius: 8px; border-left: 4px solid #ffc107;">
                    <strong>👆 Fill in the fields above to see a preview of your rule.</strong><br>
                    <span style="color: #856404;">Select a rule type and configure the points to see how it will work.</span>
                </div>
            ''')

        preview_html = '<div style="background: #d4edda; padding: 15px; border-radius: 8px; border-left: 4px solid #28a745;">'
        preview_html += '<strong style="color: #155724;">✅ Rule Summary:</strong><br><br>'

        if obj.rule_type == 'per_euro':
            multiplier = float(obj.multiplier) if obj.multiplier else 0
            # Calculate example points using actual formula: order_total * multiplier
            pts_25 = int(25 * multiplier)
            pts_50 = int(50 * multiplier)
            pts_100 = int(100 * multiplier)

            if multiplier > 0:
                euros_per_point = 1 / multiplier
                if euros_per_point == int(euros_per_point):
                    explanation = f'<strong>1 point for every €{int(euros_per_point)} spent</strong>'
                else:
                    explanation = f'<strong>{multiplier} points for every €1 spent</strong>'
            else:
                explanation = '<strong style="color: #dc3545;">Multiplier not set!</strong>'

            preview_html += f'''
                <strong>"{obj.name}"</strong> awards {explanation}.<br><br>
                <em>Formula: order total × {multiplier} = points</em><br><br>
                <em>Examples:</em><br>
                • €25 order → €25 × {multiplier} = <strong>{pts_25} points</strong><br>
                • €50 order → €50 × {multiplier} = <strong>{pts_50} points</strong><br>
                • €100 order → €100 × {multiplier} = <strong>{pts_100} points</strong>
            '''
        elif obj.rule_type == 'per_order':
            preview_html += f'''
                <strong>"{obj.name}"</strong> awards <strong>{obj.points} points for every order</strong>.<br><br>
                <em>This is a flat bonus regardless of order value.</em>
            '''
        elif obj.rule_type == 'product_sku':
            preview_html += f'''
                <strong>"{obj.name}"</strong> awards <strong>{obj.points} points</strong> for each product with SKU <strong>"{obj.condition_value}"</strong>.<br><br>
                <em>If a customer orders 3 of this product, they get {obj.points * 3} points.</em>
            '''
        elif obj.rule_type == 'product_title':
            preview_html += f'''
                <strong>"{obj.name}"</strong> awards <strong>{obj.points} points</strong> for each product containing <strong>"{obj.condition_value}"</strong> in the title.<br><br>
                <em>Example: If "{obj.condition_value}" matches "Premium {obj.condition_value} Beer", points are awarded.</em>
            '''
        elif obj.rule_type == 'minimum_order':
            min_val = obj.condition_value or '0'
            preview_html += f'''
                <strong>"{obj.name}"</strong> awards a <strong>{obj.points} point bonus</strong> when order total is <strong>€{min_val} or more</strong>.<br><br>
                <em>This is a one-time bonus per order, not multiplied.</em>
            '''
        elif obj.rule_type == 'first_order':
            preview_html += f'''
                <strong>"{obj.name}"</strong> awards <strong>{obj.points} welcome points</strong> on a customer's <strong>first order ever</strong>.<br><br>
                <em>Only applies once per customer, for their very first purchase.</em>
            '''

        preview_html += '</div>'
        return mark_safe(preview_html)
    rule_preview.short_description = 'What this rule does'

    class Media:
        js = ('loyalty/js/pointsrule_admin.js',)


@admin.register(Reward)
class RewardAdmin(admin.ModelAdmin):
    list_display = ['name', 'reward_type', 'points_cost', 'is_active', 'redemption_count_display']
    list_filter = ['reward_type', 'is_active']
    search_fields = ['name', 'description']
    ordering = ['points_cost']

    fieldsets = (
        (None, {
            'fields': ('name', 'description', 'reward_type', 'points_cost')
        }),
        ('Reward Value', {
            'fields': ('discount_amount', 'discount_percentage', 'shopify_product_id')
        }),
        ('Shopify Integration', {
            'fields': ('shopify_discount_code', 'create_shopify_discount')
        }),
        ('Limits', {
            'fields': ('max_redemptions', 'max_per_customer', 'minimum_order_value'),
            'classes': ('collapse',)
        }),
        ('Status & Validity', {
            'fields': ('is_active', 'valid_from', 'valid_until')
        }),
    )

    def redemption_count_display(self, obj):
        return obj.redemption_count
    redemption_count_display.short_description = 'Redemptions'


@admin.register(PointsBalance)
class PointsBalanceAdmin(admin.ModelAdmin):
    list_display = ['user', 'balance', 'lifetime_earned', 'lifetime_spent', 'updated_at']
    search_fields = ['user__email', 'user__first_name', 'user__last_name']
    readonly_fields = ['user', 'lifetime_earned', 'lifetime_spent', 'updated_at']
    ordering = ['-balance']

    fieldsets = (
        (None, {
            'fields': ('user', 'balance'),
            'description': 'You can manually adjust the balance here. A transaction record will be created automatically.'
        }),
        ('Lifetime Statistics', {
            'fields': ('lifetime_earned', 'lifetime_spent', 'updated_at'),
        }),
    )

    def has_add_permission(self, request):
        return False  # Balances are created automatically

    def save_model(self, request, obj, form, change):
        """Create a transaction record when balance is manually adjusted."""
        if change and 'balance' in form.changed_data:
            from .models import PointsTransaction
            old_balance = PointsBalance.objects.get(pk=obj.pk).balance
            points_diff = obj.balance - old_balance

            if points_diff != 0:
                # Update lifetime stats
                if points_diff > 0:
                    obj.lifetime_earned += points_diff
                else:
                    obj.lifetime_spent += abs(points_diff)

                # Save the balance first
                super().save_model(request, obj, form, change)

                # Create transaction record
                PointsTransaction.objects.create(
                    user=obj.user,
                    transaction_type='adjusted',
                    points=points_diff,
                    balance_after=obj.balance,
                    description=f"Manual adjustment by admin ({request.user.email})"
                )
                return

        super().save_model(request, obj, form, change)


@admin.register(PointsTransaction)
class PointsTransactionAdmin(admin.ModelAdmin):
    list_display = ['user', 'transaction_type', 'points_display', 'balance_after', 'description', 'created_at']
    list_filter = ['transaction_type', 'created_at']
    search_fields = ['user__email', 'description', 'shopify_order_name']
    readonly_fields = ['user', 'transaction_type', 'points', 'balance_after', 'description',
                       'rule', 'reward', 'shopify_order_id', 'shopify_order_name', 'created_at']
    ordering = ['-created_at']

    def points_display(self, obj):
        if obj.points >= 0:
            return format_html('<span style="color: green;">+{}</span>', obj.points)
        return format_html('<span style="color: red;">{}</span>', obj.points)
    points_display.short_description = 'Points'

    def has_add_permission(self, request):
        return False  # Transactions are created by the system

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(Redemption)
class RedemptionAdmin(admin.ModelAdmin):
    list_display = ['user', 'reward', 'points_spent', 'status', 'discount_code', 'created_at']
    list_filter = ['status', 'created_at']
    search_fields = ['user__email', 'reward__name', 'discount_code']
    readonly_fields = ['user', 'reward', 'points_spent', 'discount_code',
                       'shopify_discount_id', 'shopify_order_id', 'created_at', 'used_at']
    ordering = ['-created_at']
    actions = ['cancel_and_refund']

    fieldsets = (
        (None, {
            'fields': ('user', 'reward', 'points_spent', 'status')
        }),
        ('Discount Code', {
            'fields': ('discount_code', 'discount_code_used', 'expires_at')
        }),
        ('Shopify', {
            'fields': ('shopify_discount_id', 'shopify_order_id'),
            'classes': ('collapse',)
        }),
        ('Timestamps', {
            'fields': ('created_at', 'used_at'),
            'classes': ('collapse',)
        }),
    )

    @admin.action(description='Cancel and refund points')
    def cancel_and_refund(self, request, queryset):
        """Cancel selected redemptions and refund points to users."""
        from django.db import transaction
        from .models import PointsBalance, PointsTransaction

        refunded_count = 0
        skipped_count = 0

        for redemption in queryset:
            if redemption.status == 'cancelled':
                skipped_count += 1
                continue

            if redemption.discount_code_used:
                self.message_user(
                    request,
                    f"Skipped {redemption}: discount code was already used.",
                    level='warning'
                )
                skipped_count += 1
                continue

            with transaction.atomic():
                # Get or create balance
                balance, _ = PointsBalance.objects.get_or_create(user=redemption.user)

                # Refund points
                balance.balance += redemption.points_spent
                balance.lifetime_spent -= redemption.points_spent
                balance.save()

                # Create refund transaction
                PointsTransaction.objects.create(
                    user=redemption.user,
                    transaction_type='adjusted',
                    points=redemption.points_spent,
                    balance_after=balance.balance,
                    description=f"Refund for cancelled redemption: {redemption.reward.name} (by {request.user.email})",
                    reward=redemption.reward
                )

                # Mark redemption as cancelled
                redemption.status = 'cancelled'
                redemption.save()

                refunded_count += 1

        if refunded_count:
            self.message_user(request, f"Successfully cancelled and refunded {refunded_count} redemption(s).")
        if skipped_count:
            self.message_user(request, f"Skipped {skipped_count} redemption(s) (already cancelled or code used).", level='warning')


@admin.register(ProcessedOrder)
class ProcessedOrderAdmin(admin.ModelAdmin):
    list_display = ['shopify_order_name', 'user', 'order_total', 'points_awarded', 'processed_at']
    search_fields = ['shopify_order_name', 'shopify_order_id', 'user__email']
    readonly_fields = ['user', 'shopify_order_id', 'shopify_order_name',
                       'order_total', 'points_awarded', 'processed_at']
    ordering = ['-processed_at']

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ['title', 'notification_type', 'is_active', 'is_visible_display', 'show_from', 'show_until', 'created_at']
    list_filter = ['notification_type', 'is_active', 'created_at']
    search_fields = ['title', 'message']
    ordering = ['-created_at']

    fieldsets = (
        (None, {
            'fields': ('title', 'message', 'notification_type')
        }),
        ('Link (optional)', {
            'fields': ('link_url', 'link_text'),
            'classes': ('collapse',)
        }),
        ('Display Settings', {
            'fields': ('is_active', 'show_from', 'show_until')
        }),
    )

    def is_visible_display(self, obj):
        if obj.is_visible:
            return format_html('<span style="color: green;">Visible</span>')
        return format_html('<span style="color: gray;">Hidden</span>')
    is_visible_display.short_description = 'Status'


@admin.register(NotificationRead)
class NotificationReadAdmin(admin.ModelAdmin):
    list_display = ['user', 'notification', 'read_at']
    list_filter = ['read_at']
    search_fields = ['user__email', 'notification__title']
    readonly_fields = ['user', 'notification', 'read_at']

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
