import csv
from django.contrib import admin
from django.http import HttpResponse
from django.utils import timezone
from .models import Event, EventViewer, EventMessage, Raffle, RaffleWinner, AuctionItem


class AuctionItemInline(admin.TabularInline):
    model = AuctionItem
    extra = 1
    fields = ['title', 'image_url', 'starting_price', 'final_price', 'winner', 'status']
    raw_id_fields = ['winner']


class RaffleInline(admin.TabularInline):
    model = Raffle
    extra = 1
    fields = ['prize_name', 'num_winners', 'status', 'drawn_at']
    readonly_fields = ['status', 'drawn_at']


@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    list_display = ['title', 'event_type', 'status', 'scheduled_at', 'viewer_count_display',
                    'raffle_count_display', 'created_at']
    list_filter = ['status', 'event_type', 'scheduled_at']
    list_editable = ['status']
    search_fields = ['title', 'description']
    readonly_fields = ['created_at', 'updated_at']
    ordering = ['-scheduled_at']
    inlines = [AuctionItemInline, RaffleInline]
    actions = ['set_live', 'set_ended']

    def viewer_count_display(self, obj):
        return obj.viewers.count()
    viewer_count_display.short_description = 'Viewers'

    def raffle_count_display(self, obj):
        return obj.raffles.count()
    raffle_count_display.short_description = 'Raffles'

    @admin.action(description='Set selected events to LIVE')
    def set_live(self, request, queryset):
        queryset.update(status='live')

    @admin.action(description='Set selected events to ENDED')
    def set_ended(self, request, queryset):
        queryset.update(status='ended')


@admin.register(Raffle)
class RaffleAdmin(admin.ModelAdmin):
    list_display = ['event', 'prize_name', 'num_winners', 'status',
                    'winner_list_display', 'drawn_at']
    list_filter = ['status', 'event']
    search_fields = ['prize_name', 'event__title']
    readonly_fields = ['drawn_at']
    ordering = ['-created_at']
    actions = ['draw_winners', 'reset_event_winners']

    def winner_list_display(self, obj):
        winners = obj.winners.select_related('user')
        if not winners.exists():
            return '-'
        return ', '.join(w.user.email for w in winners)
    winner_list_display.short_description = 'Winners'

    @admin.action(description='Draw winners for selected raffles')
    def draw_winners(self, request, queryset):
        for raffle in queryset.filter(status='pending'):
            winners = raffle.draw_winners()
            if winners:
                names = ', '.join(w.user.email for w in winners)
                self.message_user(
                    request,
                    f"Raffle '{raffle.prize_name}': {len(winners)} winner(s) drawn - {names}",
                )
            else:
                self.message_user(
                    request,
                    f"Raffle '{raffle.prize_name}': No eligible viewers to draw from.",
                    level='warning',
                )

    @admin.action(description='Reset ALL winners for selected raffles\' events')
    def reset_event_winners(self, request, queryset):
        event_ids = set(queryset.values_list('event_id', flat=True))
        for event_id in event_ids:
            RaffleWinner.objects.filter(raffle__event_id=event_id).delete()
            Raffle.objects.filter(event_id=event_id).update(
                status='pending', drawn_at=None,
            )
        self.message_user(
            request,
            f"Reset winners for {len(event_ids)} event(s).",
        )


@admin.register(RaffleWinner)
class RaffleWinnerAdmin(admin.ModelAdmin):
    list_display = ['user_email', 'raffle_prize', 'event_title', 'drawn_at']
    list_filter = ['raffle__event']
    search_fields = ['user__email', 'raffle__prize_name']
    readonly_fields = ['raffle', 'user', 'drawn_at']
    ordering = ['-drawn_at']
    actions = ['export_winners_csv']

    def user_email(self, obj):
        return obj.user.email
    user_email.short_description = 'Winner'

    def raffle_prize(self, obj):
        return obj.raffle.prize_name
    raffle_prize.short_description = 'Prize'

    def event_title(self, obj):
        return obj.raffle.event.title
    event_title.short_description = 'Event'

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    @admin.action(description='Export selected winners as CSV')
    def export_winners_csv(self, request, queryset):
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="raffle_winners.csv"'

        writer = csv.writer(response)
        writer.writerow(['Event', 'Prize', 'Winner Email', 'Winner Name', 'Drawn At'])

        for winner in queryset.select_related('raffle__event', 'user'):
            writer.writerow([
                winner.raffle.event.title,
                winner.raffle.prize_name,
                winner.user.email,
                winner.user.first_name or winner.user.email.split('@')[0],
                winner.drawn_at.strftime('%Y-%m-%d %H:%M'),
            ])

        return response


@admin.register(AuctionItem)
class AuctionItemAdmin(admin.ModelAdmin):
    list_display = ['event', 'title', 'starting_price', 'final_price',
                    'winner_display', 'status', 'created_at']
    list_filter = ['status', 'event']
    list_editable = ['status']
    search_fields = ['title', 'event__title']
    raw_id_fields = ['winner']
    ordering = ['-created_at']
    actions = ['set_active', 'export_auction_results_csv']

    def winner_display(self, obj):
        if not obj.winner:
            return '-'
        return obj.winner.email
    winner_display.short_description = 'Winner'

    @admin.action(description='Set selected item as ACTIVE (deactivates others in same event)')
    def set_active(self, request, queryset):
        for item in queryset:
            # Deactivate other active items in the same event
            AuctionItem.objects.filter(
                event=item.event, status='active',
            ).exclude(id=item.id).update(status='pending')
            item.status = 'active'
            item.save()
            self.message_user(request, f"'{item.title}' is now active.")

    @admin.action(description='Export selected items as CSV')
    def export_auction_results_csv(self, request, queryset):
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="auction_results.csv"'

        writer = csv.writer(response)
        writer.writerow(['Event', 'Item', 'Starting Price', 'Final Price', 'Winner Email', 'Winner Name', 'Status'])

        for item in queryset.select_related('event', 'winner'):
            writer.writerow([
                item.event.title,
                item.title,
                item.starting_price,
                item.final_price or '-',
                item.winner.email if item.winner else '-',
                (item.winner.first_name or item.winner.email.split('@')[0]) if item.winner else '-',
                item.get_status_display(),
            ])

        return response


@admin.register(EventViewer)
class EventViewerAdmin(admin.ModelAdmin):
    list_display = ['user_email', 'event_title', 'is_active', 'joined_at', 'last_seen_at']
    list_filter = ['event']
    search_fields = ['user__email']
    readonly_fields = ['event', 'user', 'joined_at', 'last_seen_at']
    ordering = ['-last_seen_at']

    def user_email(self, obj):
        return obj.user.email
    user_email.short_description = 'User'

    def event_title(self, obj):
        return obj.event.title
    event_title.short_description = 'Event'

    def is_active(self, obj):
        cutoff = timezone.now() - timezone.timedelta(seconds=30)
        return obj.last_seen_at >= cutoff
    is_active.boolean = True
    is_active.short_description = 'Active'

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(EventMessage)
class EventMessageAdmin(admin.ModelAdmin):
    list_display = ['user_email', 'event_title', 'message_preview', 'is_system', 'created_at']
    list_filter = ['event', 'is_system']
    search_fields = ['user__email', 'message']
    readonly_fields = ['event', 'user', 'created_at']
    ordering = ['-created_at']

    def user_email(self, obj):
        return obj.user.email
    user_email.short_description = 'User'

    def event_title(self, obj):
        return obj.event.title
    event_title.short_description = 'Event'

    def message_preview(self, obj):
        return obj.message[:80] + '...' if len(obj.message) > 80 else obj.message
    message_preview.short_description = 'Message'

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
