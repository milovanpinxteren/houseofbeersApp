import csv
import logging

from django.contrib import admin, messages
from django.http import HttpResponse

from .models import PickupSchedule, PickupClosure, PickupRSVP, PickupActionLog

logger = logging.getLogger(__name__)


@admin.register(PickupSchedule)
class PickupScheduleAdmin(admin.ModelAdmin):
    list_display = ['weekday', 'open_time', 'close_time', 'active']
    list_filter = ['active']


@admin.register(PickupClosure)
class PickupClosureAdmin(admin.ModelAdmin):
    list_display = ['date', 'reason']
    date_hierarchy = 'date'


@admin.register(PickupRSVP)
class PickupRSVPAdmin(admin.ModelAdmin):
    list_display = ['user', 'date', 'status', 'created_at']
    list_filter = ['status', 'date']
    date_hierarchy = 'date'
    search_fields = ['user__email', 'user__first_name', 'user__last_name']
    actions = ['export_csv']

    @admin.action(description='Exporteer selectie als CSV (afhaallijst)')
    def export_csv(self, request, queryset):
        """The warehouse pickup list. Same CSV idiom as the Studio entrants export."""
        response = HttpResponse(content_type='text/csv; charset=utf-8')
        response['Content-Disposition'] = (
            'attachment; filename="afhaal-aanmeldingen.csv"'
        )
        writer = csv.writer(response)
        writer.writerow([
            'datum', 'email', 'voornaam', 'achternaam', 'status', 'aangemeld_op',
        ])
        for rsvp in queryset.select_related('user').order_by('date', 'user__email'):
            writer.writerow([
                rsvp.date.isoformat(),
                rsvp.user.email,
                rsvp.user.first_name,
                rsvp.user.last_name,
                rsvp.get_status_display(),
                rsvp.created_at.strftime('%Y-%m-%d %H:%M'),
            ])
        return response


@admin.register(PickupActionLog)
class PickupActionLogAdmin(admin.ModelAdmin):
    """Read-only usage log + Shopify-sync health view."""
    list_display = [
        'user', 'action', 'pickup_date', 'sync_status', 'sync_attempts',
        'created_at',
    ]
    list_filter = ['sync_status', 'action']
    date_hierarchy = 'pickup_date'
    search_fields = ['user__email', 'user__first_name', 'user__last_name']
    actions = ['resync_with_shopify']

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    @admin.action(description='Opnieuw synchroniseren met Shopify')
    def resync_with_shopify(self, request, queryset):
        """Re-dispatch the Shopify sync for selected rows (after an outage)."""
        from .tasks import sync_pickup_action

        dispatched = 0
        for log in queryset:
            try:
                sync_pickup_action.delay(log.id)
            except Exception as e:
                logger.warning(
                    f"Celery unavailable ({e}); running pickup resync inline"
                )
                try:
                    sync_pickup_action(log.id)
                except Exception as e2:
                    logger.error(f"Inline pickup resync failed for log {log.id}: {e2}")
                    messages.error(
                        request,
                        f'Synchronisatie van logregel {log.id} mislukt: {e2}',
                    )
                    continue
            dispatched += 1
        if dispatched:
            messages.success(
                request,
                f'{dispatched} logregel(s) opnieuw naar Shopify gestuurd.',
            )
