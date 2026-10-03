import math

from django.db.models import Count, Exists, F, OuterRef
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework import status
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.throttling import UserRateThrottle
from rest_framework.views import APIView

from community.models import ALLOWED_REACTIONS
from community.reactions import reaction_map, toggle_reaction
from .models import (
    Event, EventViewer, EventMessage, RaffleWinner, AuctionItem, Bid,
    PRESENCE_WINDOW_SECONDS,
)
from .serializers import (
    EventListSerializer, EventDetailSerializer,
    EventMessageSerializer, EventViewerNameSerializer,
    RaffleWinnerSerializer, AuctionItemSerializer,
    resolve_public_name,
)


class ChatPostRateThrottle(UserRateThrottle):
    """Per-user rate limit for chat posting. `rate` is set directly so no
    DEFAULT_THROTTLE_RATES settings entry is required."""
    scope = 'event_chat_post'
    rate = '15/min'


class AuctionBidRateThrottle(UserRateThrottle):
    """Per-user rate limit for auction bids (looser than chat: a bidding
    war is short bursts of tiny requests)."""
    scope = 'event_auction_bid'
    rate = '20/min'


class ChatReactionRateThrottle(UserRateThrottle):
    """Per-user rate limit for chat reactions. Every toggle bumps the
    event's reactions_rev, which makes ALL ~200 polling clients download a
    digest on their next poll — so a tap-spammer must not be able to bump
    it 50x/s."""
    scope = 'event_chat_react'
    rate = '60/min'


def _current_auction_item(event):
    """The item the poll should show: the active one, else the most
    recently sold one so clients can detect the active -> sold transition
    and show the sold banner."""
    item = (
        AuctionItem.objects
        .filter(event=event, status='active')
        .select_related('winner', 'winner__community_profile')
        .first()
    )
    if not item:
        item = (
            AuctionItem.objects
            .filter(event=event, status='sold')
            .select_related('winner', 'winner__community_profile')
            .order_by('-updated_at', '-id')
            .first()
        )
    return item


def _annotate_events(queryset, user):
    return queryset.annotate(
        viewer_count=Count('viewers', distinct=True),
        is_joined=Exists(
            EventViewer.objects.filter(event=OuterRef('pk'), user=user)
        ),
    )


def _parse_after_param(request):
    """Parse the `after` query param into an aware datetime, or None if
    missing/malformed (malformed values are ignored, never a 500)."""
    raw = request.query_params.get('after')
    if not raw:
        return None
    parsed = parse_datetime(raw)
    if parsed is None:
        return None
    if timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed)
    return parsed


def _parse_int_param(request, name):
    """Parse an int query param, or None if missing/malformed."""
    raw = request.query_params.get(name)
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


class EventsListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        events = _annotate_events(Event.objects.all(), request.user)

        status_filter = request.query_params.get('status')
        if status_filter:
            events = events.filter(status=status_filter)

        serializer = EventListSerializer(events, many=True)
        return Response({'events': serializer.data})


class EventDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, event_id):
        try:
            event = _annotate_events(
                Event.objects.filter(id=event_id), request.user
            ).get()
        except Event.DoesNotExist:
            return Response({'error': 'Event not found'}, status=status.HTTP_404_NOT_FOUND)

        serializer = EventDetailSerializer(event)
        return Response(serializer.data)


class EventJoinView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, event_id):
        try:
            event = Event.objects.get(id=event_id)
        except Event.DoesNotExist:
            return Response({'error': 'Event not found'}, status=status.HTTP_404_NOT_FOUND)

        # update_or_create (not get_or_create): rejoining after a break must
        # refresh last_seen_at, or the viewer stays raffle-ineligible until
        # their first poll lands.
        EventViewer.objects.update_or_create(
            event=event, user=request.user,
            defaults={'last_seen_at': timezone.now()},
        )

        from analytics.tracker import track
        track('event_join', user=request.user, event_id=event_id)

        return Response({
            'success': True,
            'viewer_count': event.active_viewer_count(),
        })


class EventChatView(APIView):
    permission_classes = [IsAuthenticated]

    def get_throttles(self):
        # Only throttle chat posting, never reads
        if self.request.method == 'POST':
            return [ChatPostRateThrottle()]
        return []

    def get(self, request, event_id):
        try:
            event = Event.objects.get(id=event_id)
        except Event.DoesNotExist:
            return Response({'error': 'Event not found'}, status=status.HTTP_404_NOT_FOUND)

        # Update presence
        EventViewer.objects.update_or_create(
            event=event, user=request.user,
            defaults={'last_seen_at': timezone.now()},
        )

        messages = (
            event.messages
            .select_related('user', 'user__community_profile', 'user__untappd_profile')
            .order_by('created_at')
        )

        after = _parse_after_param(request)
        if after:
            messages = messages.filter(created_at__gt=after)
        else:
            # Limit to last 100 messages if no (valid) after param
            messages = messages.order_by('-created_at')[:100]
            messages = sorted(messages, key=lambda m: m.created_at)

        serializer = EventMessageSerializer(messages, many=True, context={
            'reaction_map': reaction_map(
                'event_message', [m.id for m in messages], request.user,
            ),
        })
        return Response({
            'messages': serializer.data,
            'active_viewer_count': event.active_viewer_count(),
        })

    def post(self, request, event_id):
        try:
            event = Event.objects.get(id=event_id)
        except Event.DoesNotExist:
            return Response({'error': 'Event not found'}, status=status.HTTP_404_NOT_FOUND)

        if event.status != 'live':
            return Response(
                {'error': 'Chat is only available while the event is live'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        message_text = request.data.get('message', '').strip()
        if not message_text:
            return Response(
                {'error': 'Message is required'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Update presence
        EventViewer.objects.update_or_create(
            event=event, user=request.user,
            defaults={'last_seen_at': timezone.now()},
        )

        msg = EventMessage.objects.create(
            event=event,
            user=request.user,
            message=message_text[:500],
        )

        from analytics.tracker import track
        track('event_chat', user=request.user, event_id=event_id)

        serializer = EventMessageSerializer(msg)
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class EventChatReactView(APIView):
    """Toggle an emoji reaction on a livestream chat message.

    Any authenticated member may react (same openness as watching the
    stream); system messages are off-limits. Every change bumps the event's
    reactions_rev so the poll's digest reaches the other viewers.
    """
    permission_classes = [IsAuthenticated]
    throttle_classes = [ChatReactionRateThrottle]

    def post(self, request, event_id, message_id):
        try:
            event = Event.objects.get(id=event_id)
        except Event.DoesNotExist:
            return Response({'error': 'Event not found'}, status=status.HTTP_404_NOT_FOUND)

        try:
            message = EventMessage.objects.get(id=message_id, event=event)
        except EventMessage.DoesNotExist:
            return Response({'error': 'Message not found'}, status=status.HTTP_404_NOT_FOUND)

        if message.is_system:
            return Response({'error': 'Cannot react to system messages'},
                            status=status.HTTP_400_BAD_REQUEST)

        emoji = (request.data.get('emoji') or '').strip()
        if emoji not in ALLOWED_REACTIONS:
            return Response({'error': 'Invalid emoji'}, status=status.HTTP_400_BAD_REQUEST)

        reacted, reactions, mine = toggle_reaction('event_message', message, request.user, emoji)

        # React AND unreact both change what viewers should see, so both
        # bump the rev (atomic — concurrent reactions must not lose bumps).
        Event.objects.filter(pk=event.pk).update(reactions_rev=F('reactions_rev') + 1)

        if reacted:
            from analytics.tracker import track
            track('event_chat_reaction', user=request.user, event_id=event_id, emoji=emoji)

        return Response({'reacted': reacted, 'reactions': reactions, 'mine': mine})


class EventAuctionActiveView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, event_id):
        if not Event.objects.filter(id=event_id).exists():
            return Response({'error': 'Event not found'}, status=status.HTTP_404_NOT_FOUND)

        item = (
            AuctionItem.objects
            .filter(event_id=event_id, status='active')
            .select_related('winner', 'winner__community_profile')
            .first()
        )

        if not item:
            return Response({'item': None})

        serializer = AuctionItemSerializer(item)
        return Response({'item': serializer.data})


class EventAuctionBidView(APIView):
    """Place a bid on the event's active auction item.

    Body: {"amount": <int>} — whole euros only. Errors carry a
    machine-readable code so the app can show a precise message:
    `not_live`, `no_active_item`, `invalid_amount`, `too_low` (with the
    `minimum` the next bid must reach).

    No row lock: two racing bids both get stored and Bid's ordering
    (highest amount, then oldest) decides the leader — same semantics as
    shouting over each other at a real auction.
    """
    permission_classes = [IsAuthenticated]
    throttle_classes = [AuctionBidRateThrottle]

    def post(self, request, event_id):
        try:
            event = Event.objects.get(id=event_id)
        except Event.DoesNotExist:
            return Response({'error': 'Event not found'}, status=status.HTTP_404_NOT_FOUND)

        if event.status != 'live':
            return Response({'error': 'not_live'}, status=status.HTTP_400_BAD_REQUEST)

        item = AuctionItem.objects.filter(event=event, status='active').first()
        if not item:
            return Response({'error': 'no_active_item'}, status=status.HTTP_400_BAD_REQUEST)

        raw = request.data.get('amount')
        try:
            amount = int(str(raw).strip())
        except (TypeError, ValueError):
            return Response({'error': 'invalid_amount'}, status=status.HTTP_400_BAD_REQUEST)
        if amount <= 0:
            return Response({'error': 'invalid_amount'}, status=status.HTTP_400_BAD_REQUEST)

        top = item.bids.first()
        minimum = math.ceil(item.starting_price)
        if top:
            minimum = max(minimum, top.amount + item.min_increment)
        if amount < minimum:
            return Response(
                {'error': 'too_low', 'minimum': minimum},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Bidding proves the member is watching — refresh presence like
        # chat posts do.
        EventViewer.objects.update_or_create(
            event=event, user=request.user,
            defaults={'last_seen_at': timezone.now()},
        )

        Bid.objects.create(item=item, user=request.user, amount=amount)

        from analytics.tracker import track
        track('event_bid', user=request.user, event_id=event_id)

        # Re-read: a racing higher bid may have landed; report the truth.
        leader = (
            item.bids.select_related('user', 'user__community_profile')
            .first()
        )
        return Response({
            'ok': True,
            'current_bid': leader.amount,
            'leader_name': resolve_public_name(leader.user),
        })


class EventAuctionHistoryView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, event_id):
        items = (
            AuctionItem.objects
            .filter(event_id=event_id)
            .select_related('winner', 'winner__community_profile')
            .order_by('-created_at')
        )
        serializer = AuctionItemSerializer(items, many=True)
        return Response({'items': serializer.data})


class EventPollView(APIView):
    """
    Combined poll endpoint for livestream. Returns chat messages, winner count,
    and optionally auction/viewer data. Handles presence heartbeat.

    Query params:
        after       - ISO timestamp for chat messages since
        heartbeat   - "1" to include the viewer count in the response (every ~60s)
        known_winner_count - client's current winner count; full winner data + viewer
                             names returned only when server count differs
        known_reaction_rev - client's reaction revision; a reaction digest is
                             returned only when the server rev differs
        oldest_message_id  - oldest chat message id the client still holds;
                             bounds the reaction digest to that window
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, event_id):
        try:
            event = Event.objects.get(id=event_id)
        except Event.DoesNotExist:
            return Response({'error': 'Event not found'}, status=status.HTTP_404_NOT_FOUND)

        is_heartbeat = request.query_params.get('heartbeat') == '1'

        # Update presence on EVERY poll, not just the ~60s heartbeat: raffle
        # eligibility rides on last_seen_at, and with a 90s window a single
        # missed heartbeat would silently drop an actively-polling viewer
        # out of a draw.
        EventViewer.objects.update_or_create(
            event=event, user=request.user,
            defaults={'last_seen_at': timezone.now()},
        )

        # Chat messages
        messages = (
            event.messages
            .select_related('user', 'user__community_profile', 'user__untappd_profile')
            .order_by('created_at')
        )
        after = _parse_after_param(request)
        if after:
            messages = messages.filter(created_at__gt=after)
        else:
            messages = messages.order_by('-created_at')[:100]
            messages = sorted(messages, key=lambda m: m.created_at)

        # New messages carry their reactions inline (matters for the initial
        # last-100 fetch; after-cursor polls usually return no messages and
        # reaction_map([]) costs zero queries).
        message_serializer = EventMessageSerializer(messages, many=True, context={
            'reaction_map': reaction_map(
                'event_message', [m.id for m in messages], request.user,
            ),
        })

        # Winner count (cheap)
        winner_count = RaffleWinner.objects.filter(raffle__event=event).count()

        response_data = {
            'messages': message_serializer.data,
            'winner_count': winner_count,
            # Rides on the already-fetched event row — zero extra queries in
            # the steady state where nobody is reacting.
            'reaction_rev': event.reactions_rev,
            # Always included: the detail endpoint is only fetched on mount,
            # so a youtube_url corrected mid-stream (or a status flip) must
            # reach viewers who already have the screen open via the poll.
            'event': {
                'status': event.status,
                'youtube_url': event.youtube_url,
            },
        }

        # Reaction digest, only when the client's rev is stale (mirrors
        # known_winner_count). The digest is a full SNAPSHOT of every reacted
        # message inside the covered window — a held message that is absent
        # from the list therefore has zero reactions (this is how un-reacts
        # propagate). Window: messages the client still holds (id >=
        # oldest_message_id), hard-capped at the newest 300 ids to match the
        # client's own message cap.
        known_rev = _parse_int_param(request, 'known_reaction_rev')
        if known_rev is not None and known_rev != event.reactions_rev:
            window = event.messages.order_by('-id')
            oldest_message_id = _parse_int_param(request, 'oldest_message_id')
            if oldest_message_id is not None:
                window = window.filter(id__gte=oldest_message_id)
            window_ids = list(window.values_list('id', flat=True)[:300])
            digest = reaction_map('event_message', window_ids, request.user)
            response_data['reaction_updates'] = [
                {'m': mid, 'r': entry['reactions'], 'mine': entry['mine']}
                for mid, entry in sorted(digest.items())
            ]

        # Include viewer count only on heartbeat
        if is_heartbeat:
            response_data['active_viewer_count'] = event.active_viewer_count()

        # Include full winner data + viewer names when count changed
        known_count = _parse_int_param(request, 'known_winner_count')
        if known_count is not None and known_count != winner_count:
            winners = (
                RaffleWinner.objects
                .filter(raffle__event=event)
                .select_related('raffle', 'user', 'user__community_profile',
                                'user__untappd_profile')
                .order_by('-drawn_at')
            )
            response_data['winners'] = RaffleWinnerSerializer(winners, many=True).data

            # Include viewer names for raffle animation. Blocklisted members
            # (presenting staff) can't win, so they stay off the reel too.
            cutoff = timezone.now() - timezone.timedelta(seconds=PRESENCE_WINDOW_SECONDS)
            viewers = (
                EventViewer.objects
                .filter(event=event, last_seen_at__gte=cutoff)
                .exclude(user__in=event.excluded_users.all())
                .select_related('user', 'user__community_profile')
            )
            response_data['viewer_names'] = EventViewerNameSerializer(
                [v.user for v in viewers], many=True
            ).data

        # Auction item: included for auction-typed events (null when there
        # are no items yet) AND for any event that actually has items —
        # livestreams run raffles and auctions in one event these days.
        item = _current_auction_item(event)
        if item is not None or event.event_type == 'auction':
            response_data['auction_item'] = (
                AuctionItemSerializer(item).data if item else None
            )

        return Response(response_data)


class EventViewersView(APIView):
    """Get display names of active viewers for raffle animation."""
    permission_classes = [IsAuthenticated]

    def get(self, request, event_id):
        cutoff = timezone.now() - timezone.timedelta(seconds=PRESENCE_WINDOW_SECONDS)
        viewers = (
            EventViewer.objects
            .filter(event_id=event_id, last_seen_at__gte=cutoff)
            # Blocklisted members can't win, so keep them off the reel
            # (active_viewer_count stays honest and still includes them).
            .exclude(user__excluded_from_events__id=event_id)
            .select_related('user', 'user__community_profile')
        )
        users = [v.user for v in viewers]
        serializer = EventViewerNameSerializer(users, many=True)
        return Response({'viewers': serializer.data})


class EventRaffleWinnersView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, event_id):
        winners = (
            RaffleWinner.objects
            .filter(raffle__event_id=event_id)
            .select_related('raffle', 'user', 'user__community_profile',
                            'user__untappd_profile')
            .order_by('-drawn_at')
        )
        serializer = RaffleWinnerSerializer(winners, many=True)
        return Response({'winners': serializer.data})
