from django.db.models import Count, Exists, OuterRef
from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from .models import Event, EventViewer, EventMessage, RaffleWinner, AuctionItem
from .serializers import (
    EventListSerializer, EventDetailSerializer,
    EventMessageSerializer, RaffleWinnerSerializer,
    AuctionItemSerializer,
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
