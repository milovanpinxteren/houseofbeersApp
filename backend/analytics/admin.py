from django.contrib import admin
from django.urls import path
from django.template.response import TemplateResponse
from django.utils import timezone
from django.db.models import Count, Q
from django.db.models.functions import TruncDate
from datetime import timedelta

from .models import UsageEvent


@admin.register(UsageEvent)
class UsageEventAdmin(admin.ModelAdmin):
    list_display = ['timestamp', 'event_type', 'user_display', 'metadata_preview']
    list_filter = ['event_type', 'timestamp']
    search_fields = ['user__email', 'user__first_name']
    readonly_fields = ['user', 'event_type', 'timestamp', 'metadata']
    ordering = ['-timestamp']
    date_hierarchy = 'timestamp'

    def user_display(self, obj):
        return obj.user.email if obj.user else '-'
    user_display.short_description = 'User'

    def metadata_preview(self, obj):
        if not obj.metadata:
            return '-'
        preview = str(obj.metadata)
        return preview[:80] + '...' if len(preview) > 80 else preview
    metadata_preview.short_description = 'Details'

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


class AnalyticsDashboardAdmin(admin.ModelAdmin):
    """Proxy admin that provides the dashboard view."""

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path('', self.admin_site.admin_view(self.dashboard_view), name='analytics_dashboard'),
        ]
        return custom_urls + urls

    def dashboard_view(self, request):
        now = timezone.now()
        today = now.date()
        last_7 = now - timedelta(days=7)
        last_30 = now - timedelta(days=30)

        # --- User stats ---
        from django.contrib.auth import get_user_model
        User = get_user_model()
        total_users = User.objects.count()
        users_with_shopify = User.objects.filter(shopify_customer_id__isnull=False).exclude(shopify_customer_id='').count()

        # Active users = distinct users with any event
        active_7d = UsageEvent.objects.filter(
            timestamp__gte=last_7, user__isnull=False
        ).values('user').distinct().count()
        active_30d = UsageEvent.objects.filter(
            timestamp__gte=last_30, user__isnull=False
        ).values('user').distinct().count()
        active_today = UsageEvent.objects.filter(
            timestamp__date=today, user__isnull=False
        ).values('user').distinct().count()

        # --- Event counts ---
        events_7d = UsageEvent.objects.filter(timestamp__gte=last_7)
        events_30d = UsageEvent.objects.filter(timestamp__gte=last_30)
        total_events = UsageEvent.objects.count()

        events_by_type_7d = list(
            events_7d.values('event_type')
            .annotate(count=Count('id'))
            .order_by('-count')
        )
        events_by_type_30d = list(
            events_30d.values('event_type')
            .annotate(count=Count('id'))
            .order_by('-count')
        )

        # Friendly labels
        type_labels = dict(UsageEvent.EVENT_TYPES)
        for item in events_by_type_7d:
            item['label'] = type_labels.get(item['event_type'], item['event_type'])
        for item in events_by_type_30d:
            item['label'] = type_labels.get(item['event_type'], item['event_type'])

        # Max count for bar widths
        max_count_7d = max((e['count'] for e in events_by_type_7d), default=1)
        max_count_30d = max((e['count'] for e in events_by_type_30d), default=1)
        for item in events_by_type_7d:
            item['bar_width'] = int(item['count'] / max_count_7d * 100)
        for item in events_by_type_30d:
            item['bar_width'] = int(item['count'] / max_count_30d * 100)

        # --- Daily active users (last 30 days) ---
        daily_active = list(
            UsageEvent.objects.filter(timestamp__gte=last_30, user__isnull=False)
            .annotate(date=TruncDate('timestamp'))
            .values('date')
            .annotate(users=Count('user', distinct=True))
            .order_by('date')
        )

        # --- Daily events (last 30 days) ---
        daily_events = list(
            UsageEvent.objects.filter(timestamp__gte=last_30)
            .annotate(date=TruncDate('timestamp'))
            .values('date')
            .annotate(count=Count('id'))
            .order_by('date')
        )

        # Fill gaps for charts
        daily_active_map = {d['date']: d['users'] for d in daily_active}
        daily_events_map = {d['date']: d['count'] for d in daily_events}

        chart_days = []
        for i in range(30, -1, -1):
            day = today - timedelta(days=i)
            chart_days.append({
                'date': day,
                'label': day.strftime('%d/%m'),
                'active_users': daily_active_map.get(day, 0),
                'events': daily_events_map.get(day, 0),
            })

        max_daily_users = max((d['active_users'] for d in chart_days), default=1) or 1
        max_daily_events = max((d['events'] for d in chart_days), default=1) or 1
        for d in chart_days:
            d['user_bar_height'] = int(d['active_users'] / max_daily_users * 100)
            d['event_bar_height'] = int(d['events'] / max_daily_events * 100)

        # --- Key feature metrics ---
        from recommendations.models import Favorite, UntappdProfile
        from loyalty.models import Redemption

        total_favorites = Favorite.objects.count()
        total_untappd = UntappdProfile.objects.count()
        total_redemptions = Redemption.objects.filter(status='completed').count()

        # --- Recent events ---
        recent_events = UsageEvent.objects.select_related('user')[:15]

        # --- Top users (last 30 days) ---
        top_users = list(
            events_30d.filter(user__isnull=False)
            .values('user__email')
            .annotate(count=Count('id'))
            .order_by('-count')[:10]
        )

        context = {
            **self.admin_site.each_context(request),
            'title': 'Usage Analytics Dashboard',
            'total_users': total_users,
            'users_with_shopify': users_with_shopify,
            'active_today': active_today,
            'active_7d': active_7d,
            'active_30d': active_30d,
            'total_events': total_events,
            'events_7d_count': events_7d.count(),
            'events_30d_count': events_30d.count(),
            'events_by_type_7d': events_by_type_7d,
            'events_by_type_30d': events_by_type_30d,
            'chart_days': chart_days,
            'max_daily_users': max_daily_users,
            'max_daily_events': max_daily_events,
            'total_favorites': total_favorites,
            'total_untappd': total_untappd,
            'total_redemptions': total_redemptions,
            'recent_events': recent_events,
            'top_users': top_users,
        }

        return TemplateResponse(request, 'admin/analytics/dashboard.html', context)


# Register dashboard as a proxy model so it shows in admin sidebar
class DashboardProxy(UsageEvent):
    class Meta:
        proxy = True
        verbose_name = 'Dashboard'
        verbose_name_plural = 'Dashboard'


class DashboardProxyAdmin(AnalyticsDashboardAdmin):
    model = DashboardProxy

    def has_module_permission(self, request):
        return request.user.is_staff


admin.site.register(DashboardProxy, DashboardProxyAdmin)
