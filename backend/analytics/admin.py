from django.contrib import admin
from django.core.cache import cache
from django.http import HttpResponseRedirect
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.utils import timezone
from django.db.models import Count
from django.db.models.functions import TruncDate
from datetime import date, datetime, time, timedelta

from .models import UsageEvent
from .tasks import build_revenue_report, revenue_cache_key, REVENUE_RUNNING_TTL


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

    MAX_RANGE_DAYS = 365

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                'refresh-revenue/',
                self.admin_site.admin_view(self.refresh_revenue_view),
                name='analytics_refresh_revenue',
            ),
            path('', self.admin_site.admin_view(self.dashboard_view), name='analytics_dashboard'),
        ]
        return custom_urls + urls

    def _parse_range(self, request):
        """Selected [start, end] dates (inclusive); defaults to the last 30 days."""
        params = request.POST if request.method == 'POST' else request.GET
        today = timezone.localdate()

        def _parse(name, fallback):
            try:
                return date.fromisoformat(params.get(name) or '')
            except ValueError:
                return fallback

        end = min(_parse('end', today), today)
        start = _parse('start', end - timedelta(days=29))
        if start > end:
            start = end
        if (end - start).days >= self.MAX_RANGE_DAYS:
            start = end - timedelta(days=self.MAX_RANGE_DAYS - 1)
        return start, end

    def _enqueue_build(self, key, start, end) -> str:
        """Mark the range as building and dispatch the Celery task."""
        cache.set(
            key,
            {'status': 'running', 'built_at': timezone.now().isoformat()},
            REVENUE_RUNNING_TTL,
        )
        try:
            build_revenue_report.delay(start.isoformat(), end.isoformat())
        except Exception:
            # Broker unreachable — degrade to a visible failed state instead
            # of breaking the dashboard.
            cache.set(
                key,
                {'status': 'failed', 'built_at': timezone.now().isoformat()},
                REVENUE_RUNNING_TTL,
            )
            return 'failed'
        return 'running'

    def _ensure_revenue_report(self, start, end):
        """
        Cached Shopify revenue report for the range. Enqueues a Celery build
        when none exists yet — the dashboard itself never calls Shopify.
        Returns (status, data, built_at datetime).
        """
        key = revenue_cache_key(start, end)
        cached = cache.get(key)
        if cached is None:
            status = self._enqueue_build(key, start, end)
            return status, None, None
        built_at = cached.get('built_at')
        if built_at:
            try:
                built_at = datetime.fromisoformat(built_at)
            except ValueError:
                built_at = None
        return cached.get('status'), cached.get('data'), built_at

    def refresh_revenue_view(self, request):
        """Force a rebuild of the revenue report for the selected range."""
        start, end = self._parse_range(request)
        key = revenue_cache_key(start, end)
        existing = cache.get(key)
        already_running = existing and existing.get('status') == 'running'
        if request.method == 'POST' and not already_running:
            self._enqueue_build(key, start, end)
        dashboard_url = reverse('admin:analytics_dashboard')
        return HttpResponseRedirect(
            f"{dashboard_url}?start={start.isoformat()}&end={end.isoformat()}"
        )

    def dashboard_view(self, request):
        now = timezone.now()
        today = timezone.localdate()
        last_7 = now - timedelta(days=7)
        last_30 = now - timedelta(days=30)

        # --- Selected window ---
        start_date, end_date = self._parse_range(request)
        tz = timezone.get_current_timezone()
        window_start = timezone.make_aware(datetime.combine(start_date, time.min), tz)
        window_end = timezone.make_aware(
            datetime.combine(end_date + timedelta(days=1), time.min), tz
        )
        window_days = (end_date - start_date).days + 1

        presets = [
            {'label': 'Last 7 days', 'start': today - timedelta(days=6)},
            {'label': 'Last 30 days', 'start': today - timedelta(days=29)},
            {'label': 'Last 90 days', 'start': today - timedelta(days=89)},
        ]

        # --- User stats (fixed windows, cheap) ---
        from django.contrib.auth import get_user_model
        User = get_user_model()
        total_users = User.objects.count()
        users_with_shopify = User.objects.filter(
            shopify_customer_id__isnull=False
        ).exclude(shopify_customer_id='').count()

        active_7d = UsageEvent.objects.filter(
            timestamp__gte=last_7, user__isnull=False
        ).values('user').distinct().count()
        active_30d = UsageEvent.objects.filter(
            timestamp__gte=last_30, user__isnull=False
        ).values('user').distinct().count()
        active_today = UsageEvent.objects.filter(
            timestamp__date=today, user__isnull=False
        ).values('user').distinct().count()

        # Stickiness: what share of the monthly actives came back today
        stickiness = round(active_today / active_30d * 100) if active_30d else 0

        # --- Window-driven stats ---
        events_window = UsageEvent.objects.filter(
            timestamp__gte=window_start, timestamp__lt=window_end
        )
        events_window_count = events_window.count()
        active_window = events_window.filter(
            user__isnull=False
        ).values('user').distinct().count()
        new_users_window = User.objects.filter(
            date_joined__gte=window_start, date_joined__lt=window_end
        ).count()

        events_by_type = list(
            events_window.values('event_type')
            .annotate(count=Count('id'), users=Count('user', distinct=True))
            .order_by('-count')
        )
        type_labels = dict(UsageEvent.EVENT_TYPES)
        max_count = max((e['count'] for e in events_by_type), default=1)
        for item in events_by_type:
            item['label'] = type_labels.get(item['event_type'], item['event_type'])
            item['bar_width'] = int(item['count'] / max_count * 100)

        # --- Daily charts over the window ---
        daily_active = list(
            events_window.filter(user__isnull=False)
            .annotate(date=TruncDate('timestamp'))
            .values('date')
            .annotate(users=Count('user', distinct=True))
            .order_by('date')
        )
        daily_events = list(
            events_window
            .annotate(date=TruncDate('timestamp'))
            .values('date')
            .annotate(count=Count('id'))
            .order_by('date')
        )
        daily_active_map = {d['date']: d['users'] for d in daily_active}
        daily_events_map = {d['date']: d['count'] for d in daily_events}

        label_step = max(1, window_days // 7)
        chart_days = []
        for i in range(window_days):
            day = start_date + timedelta(days=i)
            chart_days.append({
                'date': day,
                'label': day.strftime('%d/%m'),
                'show_label': i % label_step == 0,
                'active_users': daily_active_map.get(day, 0),
                'events': daily_events_map.get(day, 0),
            })
        max_daily_users = max((d['active_users'] for d in chart_days), default=1) or 1
        max_daily_events = max((d['events'] for d in chart_days), default=1) or 1
        for d in chart_days:
            d['user_bar_height'] = int(d['active_users'] / max_daily_users * 100)
            d['event_bar_height'] = int(d['events'] / max_daily_events * 100)

        # --- Key feature metrics (all time) ---
        from recommendations.models import Favorite, SixpackCheckout, UntappdProfile
        from loyalty.models import Redemption

        total_favorites = Favorite.objects.count()
        total_untappd = UntappdProfile.objects.count()
        total_redemptions = Redemption.objects.filter(status='completed').count()

        # --- Revenue (built by Celery, cached per range) ---
        revenue_status, revenue, revenue_built_at = self._ensure_revenue_report(
            start_date, end_date
        )
        sixpack_minted = SixpackCheckout.objects.filter(
            created_at__gte=window_start, created_at__lt=window_end
        ).count()

        # --- Conversion funnels (window): usage events → mints → paid orders ---
        def _users_and_count(event_type):
            agg = events_window.filter(event_type=event_type).aggregate(
                count=Count('id'), users=Count('user', distinct=True)
            )
            return {'count': agg['count'] or 0, 'users': agg['users'] or 0}

        funnels = [
            {
                'name': 'App Shop',
                'steps': [
                    {'label': 'Views', **_users_and_count('app_shop_view')},
                    {'label': 'Checkouts', **_users_and_count('app_shop_checkout')},
                    {
                        'label': 'Paid orders',
                        'count': revenue['app_shop']['orders'] if revenue else None,
                        'users': None,
                    },
                ],
            },
            {
                'name': 'Sixpack',
                'steps': [
                    {'label': 'Spins', **_users_and_count('sixpack_generate')},
                    {'label': 'Packs minted', **_users_and_count('sixpack_checkout')},
                    {
                        'label': 'Bought',
                        'count': revenue['sixpack']['orders'] if revenue else None,
                        'users': None,
                    },
                ],
            },
            {
                'name': 'Random Beer',
                'steps': [
                    {'label': 'Spins', **_users_and_count('random_beer')},
                    {'label': 'Bought', 'count': None, 'users': None,
                     'note': 'not measurable — flow opens an untagged product page'},
                ],
            },
        ]

        # --- Top screens (window, from screen_view metadata) ---
        from django.db.models.fields.json import KeyTextTransform

        top_screens = list(
            events_window.filter(event_type='screen_view')
            .annotate(screen=KeyTextTransform('screen', 'metadata'))
            .exclude(screen__isnull=True)
            .values('screen')
            .annotate(count=Count('id'), users=Count('user', distinct=True))
            .order_by('-count')[:12]
        )
        max_screen_count = max((s['count'] for s in top_screens), default=1)
        for s in top_screens:
            s['bar_width'] = int(s['count'] / max_screen_count * 100)

        # --- Sync health / errors ---
        from loyalty.models import SyncState

        failed_syncs = SyncState.objects.filter(sync_status='failed')
        stuck_syncs = SyncState.objects.filter(
            sync_status='in_progress',
            sync_started_at__lt=now - timedelta(minutes=10),
        ).count()
        # Partial sync runs every 3h; a linked user not synced for >24h is broken
        stale_syncs = SyncState.objects.filter(
            user__shopify_customer_id__isnull=False,
            last_successful_sync__lt=now - timedelta(hours=24),
        ).exclude(user__shopify_customer_id='').count()
        recent_sync_errors = list(
            failed_syncs.exclude(last_error='')
            .select_related('user')
            .order_by('-updated_at')[:5]
        )

        # --- Recent events ---
        recent_events = UsageEvent.objects.select_related('user')[:15]

        # --- Top users (window) ---
        top_users = list(
            events_window.filter(user__isnull=False)
            .values('user__email')
            .annotate(count=Count('id'))
            .order_by('-count')[:10]
        )

        context = {
            **self.admin_site.each_context(request),
            'title': 'Usage Analytics Dashboard',
            'start_date': start_date,
            'end_date': end_date,
            'today': today,
            'window_days': window_days,
            'presets': presets,
            'total_users': total_users,
            'users_with_shopify': users_with_shopify,
            'new_users_window': new_users_window,
            'stickiness': stickiness,
            'active_today': active_today,
            'active_7d': active_7d,
            'active_30d': active_30d,
            'active_window': active_window,
            'events_window_count': events_window_count,
            'events_by_type': events_by_type,
            'chart_days': chart_days,
            'total_favorites': total_favorites,
            'total_untappd': total_untappd,
            'total_redemptions': total_redemptions,
            'revenue_status': revenue_status,
            'revenue': revenue,
            'revenue_built_at': revenue_built_at,
            'sixpack_minted': sixpack_minted,
            'funnels': funnels,
            'top_screens': top_screens,
            'failed_sync_count': failed_syncs.count(),
            'stuck_sync_count': stuck_syncs,
            'stale_sync_count': stale_syncs,
            'recent_sync_errors': recent_sync_errors,
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
