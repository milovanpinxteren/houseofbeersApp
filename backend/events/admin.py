import csv
from decimal import Decimal, InvalidOperation

from django.contrib import admin, messages
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Q
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import path, reverse
from django.utils import timezone
from django.utils.html import format_html
from django.views.decorators.http import require_POST
from .models import (
    Event, EventViewer, EventMessage, Raffle, RaffleWinner, AuctionItem, Bid,
)
from .services import fulfillment as fulfillment_service


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
    fields = ['title', 'brewery', 'size', 'image_url', 'starting_price',
              'min_increment', 'final_price', 'winner', 'status']
    raw_id_fields = ['winner']


class RaffleInline(admin.TabularInline):
    model = Raffle
    extra = 1
    fields = ['prize_name', 'num_winners', 'winner_policy', 'points_award',
              'fulfillment_type', 'winner_price', 'status', 'drawn_at']
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
    filter_horizontal = ['excluded_users']
    inlines = [AuctionItemInline, RaffleInline]
    actions = ['set_live', 'set_ended', 'export_winners_csv', 'export_chat_csv']

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
            path('<int:event_id>/regie/exclude/add/',
                 self.admin_site.admin_view(require_POST(self.regie_exclude_add_view)),
                 name='events_event_regie_exclude_add'),
            path('<int:event_id>/regie/exclude/remove/',
                 self.admin_site.admin_view(require_POST(self.regie_exclude_remove_view)),
                 name='events_event_regie_exclude_remove'),
            path('<int:event_id>/regie/auction/save/',
                 self.admin_site.admin_view(require_POST(self.regie_auction_save_view)),
                 name='events_event_regie_auction_save'),
            path('<int:event_id>/regie/auction/<int:item_id>/activate/',
                 self.admin_site.admin_view(require_POST(self.regie_auction_activate_view)),
                 name='events_event_regie_auction_activate'),
            path('<int:event_id>/regie/auction/<int:item_id>/close/',
                 self.admin_site.admin_view(require_POST(self.regie_auction_close_view)),
                 name='events_event_regie_auction_close'),
            path('<int:event_id>/regie/fulfill/product/',
                 self.admin_site.admin_view(require_POST(self.regie_fulfill_product_view)),
                 name='events_event_regie_fulfill_product'),
            path('<int:event_id>/regie/fulfill/attach/',
                 self.admin_site.admin_view(require_POST(self.regie_fulfill_attach_view)),
                 name='events_event_regie_fulfill_attach'),
            path('<int:event_id>/regie/fulfill/attach-all/<int:raffle_id>/',
                 self.admin_site.admin_view(require_POST(self.regie_fulfill_attach_all_view)),
                 name='events_event_regie_fulfill_attach_all'),
            path('<int:event_id>/regie/fulfill/invoice/',
                 self.admin_site.admin_view(require_POST(self.regie_fulfill_invoice_view)),
                 name='events_event_regie_fulfill_invoice'),
            path('<int:event_id>/regie/fulfill/toggle/',
                 self.admin_site.admin_view(require_POST(self.regie_fulfill_toggle_view)),
                 name='events_event_regie_fulfill_toggle'),
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
            raffle.drawn_so_far = len(raffle.winner_names)
            raffle.slots_left = raffle.num_winners - raffle.drawn_so_far
        drawn = sum(1 for r in raffles if r.status == 'drawn')

        auction_items = list(
            event.auction_items.select_related('winner').order_by('created_at')
        )
        for item in auction_items:
            item.top_bid = (
                item.bids.select_related('user', 'user__community_profile')
                .first()
            )
            item.total_bid_count = item.bids.count()
            if item.top_bid:
                item.leader_display = _winner_display(item.top_bid.user)

        # Afhandeling: everything with a winner to hand a prize to
        fulfillment_raffles = [r for r in raffles if r.status == 'drawn']
        for raffle in fulfillment_raffles:
            raffle.effective_price = raffle.winner_price or 0
        sold_auction_items = [i for i in auction_items if i.status == 'sold']
        processed, total = fulfillment_service.fulfillment_progress(event)

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
            'auction_items': auction_items,
            'excluded_users': list(
                event.excluded_users.order_by('first_name', 'email')
            ),
            'fulfillment_raffles': fulfillment_raffles,
            'sold_auction_items': sold_auction_items,
            'fulfillment_processed': processed,
            'fulfillment_total': total,
        }

    def regie_view(self, request, event_id):
        event = get_object_or_404(Event, pk=event_id)
        return render(request, 'events/regie.html',
                      self._regie_context(request, event))

    def regie_stats_view(self, request, event_id):
        event = get_object_or_404(Event, pk=event_id)
        active_item = (
            AuctionItem.objects.filter(event=event, status='active').first()
        )
        auction = None
        if active_item:
            top = (
                active_item.bids
                .select_related('user', 'user__community_profile')
                .first()
            )
            auction = {
                'item_id': active_item.pk,
                'current_bid': top.amount if top else None,
                'bid_count': active_item.bids.count(),
                'leader': _winner_display(top.user) if top else None,
            }
        return JsonResponse({
            'active_viewer_count': event.active_viewer_count(),
            'status': event.status,
            'winner_count': RaffleWinner.objects.filter(
                raffle__event=event
            ).count(),
            'auction': auction,
        })

    def regie_draw_view(self, request, event_id, raffle_id):
        if not request.user.has_perm('events.change_raffle'):
            raise PermissionDenied
        raffle = get_object_or_404(Raffle, pk=raffle_id, event_id=event_id)
        count_param = request.POST.get('draw_count', '')
        count = int(count_param) if count_param.isdigit() else None
        winners = raffle.draw_winners(count=count)
        if winners is None:
            messages.warning(
                request, f"'{raffle.prize_name}' was al getrokken.")
        elif winners:
            names = ', '.join(_winner_display(w.user) for w in winners)
            suffix = (
                f' — {raffle.points_award} punten per winnaar toegevoegd'
                if raffle.points_award else ''
            )
            if raffle.status == 'pending':
                slots_left = raffle.num_winners - raffle.winners.count()
                suffix += f' — nog {slots_left} plek(ken) open'
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

    def regie_exclude_add_view(self, request, event_id):
        if not request.user.has_perm('events.change_event'):
            raise PermissionDenied
        event = get_object_or_404(Event, pk=event_id)
        query = request.POST.get('q', '').strip()
        if not query:
            messages.error(request, 'Geen zoekterm opgegeven.')
            return redirect('admin:events_event_regie', event_id)

        User = get_user_model()
        # Exact email first (there are unmerged case-duplicate accounts),
        # then a broad name/email search.
        matches = list(User.objects.filter(email__iexact=query)[:6])
        if not matches:
            matches = list(
                User.objects.filter(
                    Q(email__icontains=query)
                    | Q(first_name__icontains=query)
                    | Q(last_name__icontains=query)
                )[:6]
            )
        if len(matches) == 1:
            event.excluded_users.add(matches[0])
            messages.success(
                request,
                f'{_winner_display(matches[0])} is uitgesloten van winnen '
                'in dit event.',
            )
        elif not matches:
            messages.warning(request, f"Geen lid gevonden voor '{query}'.")
        else:
            options = '; '.join(_winner_display(u) for u in matches)
            messages.warning(
                request,
                f'Meerdere leden gevonden — gebruik het e-mailadres: {options}',
            )
        return redirect('admin:events_event_regie', event_id)

    def regie_exclude_remove_view(self, request, event_id):
        if not request.user.has_perm('events.change_event'):
            raise PermissionDenied
        event = get_object_or_404(Event, pk=event_id)
        User = get_user_model()
        user = get_object_or_404(User, pk=request.POST.get('user_id'))
        event.excluded_users.remove(user)
        messages.success(
            request, f'{_winner_display(user)} doet weer mee met lotingen.')
        return redirect('admin:events_event_regie', event_id)

    def regie_auction_save_view(self, request, event_id):
        if not request.user.has_perm('events.change_auctionitem'):
            raise PermissionDenied
        event = get_object_or_404(Event, pk=event_id)

        title = request.POST.get('title', '').strip()
        if not title:
            messages.error(request, 'Titel is verplicht.')
            return redirect('admin:events_event_regie', event_id)
        try:
            starting_price = Decimal(request.POST.get('starting_price', '').strip() or '0')
        except InvalidOperation:
            messages.error(request, 'Ongeldige startprijs.')
            return redirect('admin:events_event_regie', event_id)
        rating_raw = request.POST.get('untappd_rating', '').strip().replace(',', '.')
        try:
            untappd_rating = Decimal(rating_raw) if rating_raw else None
        except InvalidOperation:
            messages.error(request, 'Ongeldige Untappd-score.')
            return redirect('admin:events_event_regie', event_id)
        increment_raw = request.POST.get('min_increment', '').strip()
        min_increment = int(increment_raw) if increment_raw.isdigit() else 5

        fields = {
            'title': title,
            'description': request.POST.get('description', '').strip(),
            'brewery': request.POST.get('brewery', '').strip(),
            'size': request.POST.get('size', '').strip(),
            'untappd_rating': untappd_rating,
            'image_url': request.POST.get('image_url', '').strip(),
            'starting_price': starting_price,
            'min_increment': min_increment,
        }
        item_id = request.POST.get('item_id', '')
        if item_id:
            item = get_object_or_404(AuctionItem, pk=item_id, event=event)
            if item.status != 'pending':
                messages.warning(
                    request,
                    f"'{item.title}' is al {item.get_status_display().lower()} "
                    'en kan niet meer bewerkt worden.',
                )
                return redirect('admin:events_event_regie', event_id)
            for name, value in fields.items():
                setattr(item, name, value)
            item.save()
            messages.success(request, f"'{item.title}' bijgewerkt.")
        else:
            item = AuctionItem.objects.create(event=event, **fields)
            messages.success(request, f"Veilingitem '{item.title}' toegevoegd.")
        return redirect('admin:events_event_regie', event_id)

    def regie_auction_activate_view(self, request, event_id, item_id):
        if not request.user.has_perm('events.change_auctionitem'):
            raise PermissionDenied
        item = get_object_or_404(AuctionItem, pk=item_id, event_id=event_id)
        if item.status != 'pending':
            messages.warning(
                request,
                f"'{item.title}' is al {item.get_status_display().lower()}.",
            )
            return redirect('admin:events_event_regie', event_id)
        # Only one item may be live at a time
        AuctionItem.objects.filter(
            event_id=event_id, status='active',
        ).exclude(pk=item.pk).update(status='pending')
        item.status = 'active'
        item.save(update_fields=['status', 'updated_at'])
        messages.success(
            request,
            f"Veiling gestart: '{item.title}' (startbod €{item.starting_price}).",
        )
        return redirect('admin:events_event_regie', event_id)

    def regie_auction_close_view(self, request, event_id, item_id):
        if not request.user.has_perm('events.change_auctionitem'):
            raise PermissionDenied
        # Lock the row: a double-clicked "Sluit veiling" must not re-close
        # (the second request sees status != 'active' and backs off).
        with transaction.atomic():
            item = get_object_or_404(
                AuctionItem.objects.select_for_update(),
                pk=item_id, event_id=event_id,
            )
            if item.status != 'active':
                messages.warning(
                    request,
                    f"'{item.title}' is niet actief "
                    f'(status: {item.get_status_display().lower()}).',
                )
                return redirect('admin:events_event_regie', event_id)
            top = item.bids.select_related('user').first()
            if not top:
                item.status = 'pending'
                item.save(update_fields=['status', 'updated_at'])
                messages.warning(
                    request,
                    f"'{item.title}': geen biedingen — terug in de wachtrij.",
                )
                return redirect('admin:events_event_regie', event_id)
            item.winner = top.user
            item.final_price = Decimal(top.amount)
            item.status = 'sold'
            item.save(update_fields=[
                'winner', 'final_price', 'status', 'updated_at',
            ])
        messages.success(
            request,
            f"'{item.title}' verkocht aan {_winner_display(top.user)} "
            f'voor €{top.amount}.',
        )
        return redirect('admin:events_event_regie', event_id)

    # --- Afhandeling (prize fulfillment) -------------------------------
    # Thin wrappers around events.services.fulfillment; every outcome is a
    # Django message and the service never raises for Shopify failures.

    def _fulfillment_target(self, request, event_id):
        """Resolve POSTed kind/obj_id into a RaffleWinner ('winner') or
        AuctionItem ('auction') of this event, enforcing the matching model
        permission. Returns (target, label) or raises 404/PermissionDenied;
        returns (None, None) on malformed input."""
        kind = request.POST.get('kind', '')
        obj_id = request.POST.get('obj_id', '')
        if not obj_id.isdigit():
            return None, None
        if kind == 'winner':
            if not request.user.has_perm('events.change_raffle'):
                raise PermissionDenied
            winner = get_object_or_404(
                RaffleWinner.objects.select_related('raffle', 'user'),
                pk=obj_id, raffle__event_id=event_id,
            )
            return winner, f'{winner.raffle.prize_name} — {winner.user.email}'
        if kind == 'auction':
            if not request.user.has_perm('events.change_auctionitem'):
                raise PermissionDenied
            item = get_object_or_404(
                AuctionItem.objects.select_related('winner'),
                pk=obj_id, event_id=event_id,
            )
            return item, item.title
        return None, None

    def regie_fulfill_product_view(self, request, event_id):
        kind = request.POST.get('kind', '')
        obj_id = request.POST.get('obj_id', '')
        if not obj_id.isdigit() or kind not in ('raffle', 'auction'):
            messages.error(request, 'Ongeldig afhandel-doel.')
            return redirect('admin:events_event_regie', event_id)
        if kind == 'raffle':
            if not request.user.has_perm('events.change_raffle'):
                raise PermissionDenied
            obj = get_object_or_404(Raffle, pk=obj_id, event_id=event_id)
            label = obj.prize_name
        else:
            if not request.user.has_perm('events.change_auctionitem'):
                raise PermissionDenied
            obj = get_object_or_404(AuctionItem, pk=obj_id, event_id=event_id)
            label = obj.title

        result = fulfillment_service.ensure_prize_product(obj)
        if result.get('error'):
            messages.error(request, result['error'])
        elif result.get('skipped'):
            messages.info(request, f"'{label}': Shopify-product bestond al.")
        else:
            how = 'hergebruikt' if result.get('reused') else 'aangemaakt'
            messages.success(
                request, f"'{label}': Shopify-product {how} (unlisted).")
        return redirect('admin:events_event_regie', event_id)

    def regie_fulfill_attach_view(self, request, event_id):
        target, label = self._fulfillment_target(request, event_id)
        if target is None:
            messages.error(request, 'Ongeldig afhandel-doel.')
            return redirect('admin:events_event_regie', event_id)
        result = fulfillment_service.attach_to_winner(target)
        if result.get('error'):
            messages.error(request, result['error'])
        else:
            what = ('nieuwe draft order'
                    if result['status'] == 'draft_created'
                    else 'bestaande draft order')
            messages.success(
                request, f'{label}: prijs op {what} gezet.')
        return redirect('admin:events_event_regie', event_id)

    def regie_fulfill_attach_all_view(self, request, event_id, raffle_id):
        if not request.user.has_perm('events.change_raffle'):
            raise PermissionDenied
        raffle = get_object_or_404(Raffle, pk=raffle_id, event_id=event_id)
        pending = raffle.winners.select_related('user').exclude(
            fulfillment_status__in=sorted(
                fulfillment_service.PROCESSED_STATUSES),
        )
        ok, failed = 0, []
        for winner in pending:
            result = fulfillment_service.attach_to_winner(winner)
            if result.get('error'):
                failed.append(f'{winner.user.email}: {result["error"]}')
            else:
                ok += 1
        if ok:
            messages.success(
                request,
                f"'{raffle.prize_name}': prijs bij {ok} winnaar(s) op een "
                'draft order gezet.',
            )
        if failed:
            messages.error(
                request,
                f"'{raffle.prize_name}': {len(failed)} mislukt — "
                + '; '.join(failed),
            )
        if not ok and not failed:
            messages.info(
                request, f"'{raffle.prize_name}': niets meer te verwerken.")
        return redirect('admin:events_event_regie', event_id)

    def regie_fulfill_invoice_view(self, request, event_id):
        target, label = self._fulfillment_target(request, event_id)
        if target is None:
            messages.error(request, 'Ongeldig afhandel-doel.')
            return redirect('admin:events_event_regie', event_id)
        result = fulfillment_service.send_invoice(target)
        if result.get('error'):
            messages.error(request, result['error'])
        else:
            messages.success(request, f'{label}: factuur verstuurd.')
        return redirect('admin:events_event_regie', event_id)

    def regie_fulfill_toggle_view(self, request, event_id):
        target, label = self._fulfillment_target(request, event_id)
        if target is None:
            messages.error(request, 'Ongeldig afhandel-doel.')
            return redirect('admin:events_event_regie', event_id)
        if target.fulfillment_status == 'fulfilled':
            fulfillment_service.unmark_fulfilled(target)
            messages.success(
                request, f'{label}: niet meer afgehandeld.')
        else:
            fulfillment_service.mark_fulfilled(target)
            messages.success(request, f'{label}: afgehandeld.')
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

    @admin.action(description='Export chat CSV')
    def export_chat_csv(self, request, queryset):
        if queryset.count() != 1:
            self.message_user(
                request,
                'Selecteer precies één event voor de chat-export.',
                level='error',
            )
            return None
        event = queryset.first()
        chat = event.messages.select_related('user').order_by('created_at')

        response = HttpResponse(content_type='text/csv; charset=utf-8')
        response['Content-Disposition'] = (
            f'attachment; filename="chat-{event.pk}-{timezone.localdate()}.csv"'
        )
        response.write('﻿')  # BOM: Excel misreads plain UTF-8 CSV
        # Semicolon-delimited: NL-locale Excel splits on ; by default
        writer = csv.writer(response, delimiter=';')
        writer.writerow(['tijd', 'naam', 'email', 'bericht'])
        for message in chat.iterator():
            writer.writerow([
                timezone.localtime(message.created_at).strftime('%Y-%m-%d %H:%M:%S'),
                message.user.first_name or message.user.email.split('@')[0],
                message.user.email,
                message.message,
            ])
        return response


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


@admin.register(Bid)
class BidAdmin(admin.ModelAdmin):
    list_display = ['item', 'amount', 'user_email', 'created_at']
    list_filter = ['item__event']
    search_fields = ['user__email', 'item__title']
    readonly_fields = ['item', 'user', 'amount', 'created_at']
    ordering = ['-created_at']

    def user_email(self, obj):
        return obj.user.email
    user_email.short_description = 'Bidder'

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


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
