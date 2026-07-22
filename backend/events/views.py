from django.db.models import Count, Exists, OuterRef
from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from .models import Event, EventViewer, EventMessage, RaffleWinner, AuctionItem
from .serializers import (
    EventListSerializer, EventDetailSerializer,
    EventMessageSerializer, EventViewerNameSerializer,
    RaffleWinnerSerializer, AuctionItemSerializer,
)


def _annotate_events(queryset, user):
    return queryset.annotate(
        viewer_count=Count('viewers', distinct=True),
        is_joined=Exists(
            EventViewer.objects.filter(event=OuterRef('pk'), user=user)
        ),
    )


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

        EventViewer.objects.get_or_create(event=event, user=request.user)

        from analytics.tracker import track
        track('event_join', user=request.user, event_id=event_id)

        return Response({
            'success': True,
            'viewer_count': event.viewers.count(),
        })


class EventChatView(APIView):
    permission_classes = [IsAuthenticated]

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
            .select_related('user', 'user__community_profile')
            .order_by('created_at')
        )

        after = request.query_params.get('after')
        if after:
            messages = messages.filter(created_at__gt=after)

        # Limit to last 100 messages if no after param
        if not after:
            messages = messages.order_by('-created_at')[:100]
            messages = sorted(messages, key=lambda m: m.created_at)

        serializer = EventMessageSerializer(messages, many=True)
        return Response({
            'messages': serializer.data,
            'active_viewer_count': event.active_viewer_count(),
        })

    def post(self, request, event_id):
        try:
            event = Event.objects.get(id=event_id)
        except Event.DoesNotExist:
            return Response({'error': 'Event not found'}, status=status.HTTP_404_NOT_FOUND)

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


class EventAuctionActiveView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, event_id):
        try:
            item = (
                AuctionItem.objects
                .filter(event_id=event_id, status='active')
                .select_related('winner', 'winner__community_profile')
                .first()
            )
        except Event.DoesNotExist:
            return Response({'error': 'Event not found'}, status=status.HTTP_404_NOT_FOUND)

        if not item:
            return Response({'item': None})

        serializer = AuctionItemSerializer(item)
        return Response({'item': serializer.data})


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
        heartbeat   - "1" to update presence and get viewer count (every ~60s)
        known_winner_count - client's current winner count; full winner data + viewer
                             names returned only when server count differs
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, event_id):
        try:
            event = Event.objects.get(id=event_id)
        except Event.DoesNotExist:
            return Response({'error': 'Event not found'}, status=status.HTTP_404_NOT_FOUND)

        is_heartbeat = request.query_params.get('heartbeat') == '1'

        # Update presence only on heartbeat (every ~60s from client)
        if is_heartbeat:
            EventViewer.objects.update_or_create(
                event=event, user=request.user,
                defaults={'last_seen_at': timezone.now()},
            )

        # Chat messages
        messages = (
            event.messages
            .select_related('user', 'user__community_profile')
            .order_by('created_at')
        )
        after = request.query_params.get('after')
        if after:
            messages = messages.filter(created_at__gt=after)
        else:
            messages = messages.order_by('-created_at')[:100]
            messages = sorted(messages, key=lambda m: m.created_at)

        message_serializer = EventMessageSerializer(messages, many=True)

        # Winner count (cheap)
        winner_count = RaffleWinner.objects.filter(raffle__event=event).count()

        response_data = {
            'messages': message_serializer.data,
            'winner_count': winner_count,
        }

        # Include viewer count only on heartbeat
        if is_heartbeat:
            response_data['active_viewer_count'] = event.active_viewer_count()

        # Include full winner data + viewer names when count changed
        known_count = request.query_params.get('known_winner_count')
        if known_count is not None and int(known_count) != winner_count:
            winners = (
                RaffleWinner.objects
                .filter(raffle__event=event)
                .select_related('raffle', 'user', 'user__community_profile')
                .order_by('-drawn_at')
            )
            response_data['winners'] = RaffleWinnerSerializer(winners, many=True).data

            # Include viewer names for raffle animation
            cutoff = timezone.now() - timezone.timedelta(minutes=5)
            viewers = (
                EventViewer.objects
                .filter(event=event, last_seen_at__gte=cutoff)
                .select_related('user', 'user__community_profile')
            )
            response_data['viewer_names'] = EventViewerNameSerializer(
                [v.user for v in viewers], many=True
            ).data

        # Auction item (only for auction events)
        if event.event_type == 'auction':
            item = (
                AuctionItem.objects
                .filter(event=event, status='active')
                .select_related('winner', 'winner__community_profile')
                .first()
            )
            response_data['auction_item'] = (
                AuctionItemSerializer(item).data if item else None
            )

        return Response(response_data)


class EventViewersView(APIView):
    """Get display names of active viewers for raffle animation."""
    permission_classes = [IsAuthenticated]

    def get(self, request, event_id):
        cutoff = timezone.now() - timezone.timedelta(minutes=5)
        viewers = (
            EventViewer.objects
            .filter(event_id=event_id, last_seen_at__gte=cutoff)
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
            .select_related('raffle', 'user', 'user__community_profile')
            .order_by('-drawn_at')
        )
        serializer = RaffleWinnerSerializer(winners, many=True)
        return Response({'winners': serializer.data})
