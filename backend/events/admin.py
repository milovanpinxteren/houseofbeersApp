import csv
from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import path, reverse
from django.utils import timezone
from django.utils.html import format_html
from django.views.decorators.http import require_POST
from .models import Event, EventViewer, EventMessage, Raffle, RaffleWinner, AuctionItem


def _winner_display(user):
    """Same fallback chain as the raffle overlay, plus the email for staff."""
    profile = getattr(user, 'community_profile', None)
    name = (profile.display_name if profile and profile.display_name
            else user.first_name) or 'Member'
    return f'{name} ({user.email})'


def _winners_csv_response(winners):
    """CSV built for prize follow-up: `Email` is the Shopify match key,
    `Shopify customer ID` is pre-filled for accounts the app already linked
    (blank = match on email later). Notification columns show whether the
    winner already got the in-app "je hebt gewonnen" message."""
    from notifications.models import NotificationDelivery

    winners = list(winners.select_related('raffle__event', 'user'))
    dedupe_keys = [
        f'event-raffle:{w.raffle_id}:{w.user_id}:won' for w in winners
    ]
    deliveries = {
        d.dedupe_key: d
        for d in NotificationDelivery.objects.filter(dedupe_key__in=dedupe_keys)
    }

    response = HttpResponse(content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = (
        f'attachment; filename="raffle_winners_{timezone.localdate()}.csv"'
    )
    response.write('﻿')  # BOM: Excel misreads plain UTF-8 CSV names

    writer = csv.writer(response)
    writer.writerow([
        'Event', 'Prize', 'Email', 'First name', 'Last name',
        'Shopify customer ID', 'Drawn at', 'Push status', 'Email status',
    ])
    for winner in winners:
        delivery = deliveries.get(
            f'event-raffle:{winner.raffle_id}:{winner.user_id}:won'
        )
        writer.writerow([
            winner.raffle.event.title,
            winner.raffle.prize_name,
            winner.user.email,
            winner.user.first_name,
            winner.user.last_name,
            winner.user.shopify_customer_id or '',
            timezone.localtime(winner.drawn_at).strftime('%Y-%m-%d %H:%M'),
            delivery.push_status if delivery else '',
            delivery.email_status if delivery else '',
        ])
    return response


class AuctionItemInline(admin.TabularInline):
    model = AuctionItem
    extra = 1
    fields = ['title', 'image_url', 'starting_price', 'final_price', 'winner', 'status']
    raw_id_fields = ['winner']


class RaffleInline(admin.TabularInline):
    model = Raffle
    extra = 1
    fields = ['prize_name', 'num_winners', 'winner_policy', 'points_award',
              'status', 'drawn_at']
    readonly_fields = ['status', 'drawn_at']


@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    list_display = ['title', 'event_type', 'status', 'scheduled_at', 'exclude_past_winners',
                    'viewer_count_display', 'raffle_count_display', 'regie_link',
                    'created_at']
    list_filter = ['status', 'event_type', 'scheduled_at']
    list_editable = ['status', 'exclude_past_winners']
    search_fields = ['title', 'description']
    readonly_fields = ['created_at', 'updated_at']
    ordering = ['-scheduled_at']
    inlines = [AuctionItemInline, RaffleInline]
    actions = ['set_live', 'set_ended', 'export_winners_csv']

    def get_urls(self):
        # Custom URLs must precede the default ones or <pk>/change/ wins.
        custom = [
            path('<int:event_id>/regie/',
                 self.admin_site.admin_view(self.regie_view),
                 name='events_event_regie'),
            path('<int:event_id>/regie/stats/',
                 self.admin_site.admin_view(self.regie_stats_view),
                 name='events_event_regie_stats'),
            path('<int:event_id>/regie/draw/<int:raffle_id>/',
                 self.admin_site.admin_view(require_POST(self.regie_draw_view)),
                 name='events_event_regie_draw'),
            path('<int:event_id>/regie/policy/<int:raffle_id>/',
                 self.admin_site.admin_view(require_POST(self.regie_policy_view)),
                 name='events_event_regie_policy'),
        ]
        return custom + super().get_urls()

    def regie_link(self, obj):
        return format_html(
            '<a class="button" href="{}">Regie</a>',
            reverse('admin:events_event_regie', args=[obj.pk]),
        )
    regie_link.short_description = 'Livestream regie'

    def _regie_context(self, request, event):
        raffles = list(
            event.raffles
            .prefetch_related('winners__user__community_profile')
            .order_by('id')
        )
        for raffle in raffles:
            raffle.winner_names = [
                _winner_display(w.user) for w in raffle.winners.all()
            ]
        drawn = sum(1 for r in raffles if r.status == 'drawn')
        return {
            **self.admin_site.each_context(request),
            'title': f'Livestream regie — {event.title}',
            'event': event,
            'raffles': raffles,
            'drawn_count': drawn,
            'total_count': len(raffles),
            'prize_unit_count': sum(r.num_winners for r in raffles),
            'active_viewer_count': event.active_viewer_count(),
            'policy_choices': Raffle.WINNER_POLICY_CHOICES,
        }

    def regie_view(self, request, event_id):
        event = get_object_or_404(Event, pk=event_id)
        return render(request, 'events/regie.html',
                      self._regie_context(request, event))

    def regie_stats_view(self, request, event_id):
        event = get_object_or_404(Event, pk=event_id)
        return JsonResponse({
            'active_viewer_count': event.active_viewer_count(),
            'status': event.status,
            'winner_count': RaffleWinner.objects.filter(
                raffle__event=event
            ).count(),
        })

    def regie_draw_view(self, request, event_id, raffle_id):
        if not request.user.has_perm('events.change_raffle'):
            raise PermissionDenied
        raffle = get_object_or_404(Raffle, pk=raffle_id, event_id=event_id)
        winners = raffle.draw_winners()
        if winners is None:
            messages.warning(
                request, f"'{raffle.prize_name}' was al getrokken.")
        elif winners:
            names = ', '.join(_winner_display(w.user) for w in winners)
            suffix = (
                f' — {raffle.points_award} punten per winnaar toegevoegd'
                if raffle.points_award else ''
            )
            messages.success(
                request,
                f"'{raffle.prize_name}': {len(winners)} winnaar(s) — "
                f"{names}{suffix}",
            )
        else:
            messages.warning(
                request,
                f"'{raffle.prize_name}': geen kijkers in de afgelopen 90s "
                "om uit te trekken. De loting blijft open.",
            )
        return redirect('admin:events_event_regie', event_id)

    def regie_policy_view(self, request, event_id, raffle_id):
        if not request.user.has_perm('events.change_raffle'):
            raise PermissionDenied
        raffle = get_object_or_404(Raffle, pk=raffle_id, event_id=event_id)
        policy = request.POST.get('winner_policy', '')
        valid = {value for value, _ in Raffle.WINNER_POLICY_CHOICES}
        if raffle.status != 'pending':
            messages.warning(
                request, f"'{raffle.prize_name}' is al getrokken.")
        elif policy not in valid:
            messages.error(request, 'Ongeldig winnaar-beleid.')
        else:
            raffle.winner_policy = policy
            raffle.save(update_fields=['winner_policy'])
            messages.success(
                request,
                f"'{raffle.prize_name}': beleid is nu "
                f"“{raffle.get_winner_policy_display()}”.",
            )
        return redirect('admin:events_event_regie', event_id)

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

    @admin.action(description='Export ALL raffle winners of selected events as CSV')
    def export_winners_csv(self, request, queryset):
        winners = RaffleWinner.objects.filter(
            raffle__event__in=queryset,
        ).order_by('raffle__event_id', 'drawn_at')
        if not winners.exists():
            self.message_user(
                request,
                'No raffle winners yet for the selected event(s).',
                level='warning',
            )
            return None
        return _winners_csv_response(winners)


@admin.register(Raffle)
class RaffleAdmin(admin.ModelAdmin):
    list_display = ['event', 'prize_name', 'num_winners', 'winner_policy',
                    'points_award', 'status', 'winner_list_display', 'drawn_at']
    list_filter = ['status', 'event']
    list_editable = ['winner_policy', 'points_award']
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
            if winners is None:
                # Another request (e.g. a double click) already drew this raffle
                self.message_user(
                    request,
                    f"Raffle '{raffle.prize_name}': already drawn, skipped.",
                    level='warning',
                )
            elif winners:
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
        return _winners_csv_response(queryset.order_by('raffle__event_id', 'drawn_at'))


@admin.register(AuctionItem)
class AuctionItemAdmin(admin.ModelAdmin):
    list_display = ['event', 'title', 'starting_price', 'final_price',
                    'winner_display', 'status', 'created_at']
    list_filter = ['status', 'event']
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
        if queryset.count() != 1:
            self.message_user(
                request,
                'Select exactly one item to set as active.',
                level='error',
            )
            return
        item = queryset.first()
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
