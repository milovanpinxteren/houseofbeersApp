from rest_framework import serializers
from community.serializers import AuthorSerializer, ReactionFieldsMixin
from .models import Event, EventMessage, RaffleWinner, AuctionItem


def resolve_public_name(user):
    """Public name on raffle/auction surfaces: community display name if the
    member set one, else first name + last-name initial ("Ivo B.") so
    namesakes can tell who actually won. Never the email prefix."""
    profile = getattr(user, 'community_profile', None)
    if profile and profile.display_name:
        return profile.display_name
    if user.first_name:
        if user.last_name:
            return f'{user.first_name} {user.last_name[0].upper()}.'
        return user.first_name
    return 'Member'


class EventAuthorSerializer(AuthorSerializer):
    """Community AuthorSerializer with the events-scoped last-initial
    fallback (community surfaces keep plain first names)."""

    def get_display_name(self, obj):
        return resolve_public_name(obj)


class EventListSerializer(serializers.ModelSerializer):
    viewer_count = serializers.IntegerField(read_only=True, default=0)
    is_joined = serializers.BooleanField(read_only=True, default=False)

    class Meta:
        model = Event
        fields = [
            'id', 'title', 'description', 'event_type', 'scheduled_at',
            'youtube_url', 'image_url', 'status',
            'viewer_count', 'is_joined',
            'created_at',
        ]


class EventDetailSerializer(EventListSerializer):
    active_viewer_count = serializers.SerializerMethodField()

    class Meta(EventListSerializer.Meta):
        fields = EventListSerializer.Meta.fields + ['active_viewer_count']

    def get_active_viewer_count(self, obj):
        return obj.active_viewer_count()


class EventMessageSerializer(ReactionFieldsMixin, serializers.ModelSerializer):
    user = AuthorSerializer(read_only=True)

    class Meta:
        model = EventMessage
        fields = ['id', 'user', 'message', 'is_system', 'created_at']


class AuctionItemSerializer(serializers.ModelSerializer):
    winner_name = serializers.SerializerMethodField()
    current_bid = serializers.SerializerMethodField()
    bid_count = serializers.SerializerMethodField()
    leader_name = serializers.SerializerMethodField()

    class Meta:
        model = AuctionItem
        fields = [
            'id', 'title', 'description', 'brewery', 'size',
            'untappd_rating', 'image_url', 'starting_price', 'min_increment',
            'current_bid', 'bid_count', 'leader_name',
            'final_price', 'winner_name', 'status', 'created_at',
        ]

    def _top_bid(self, obj):
        # One query, cached on the instance: current_bid + leader_name both
        # need the highest bid (Bid.Meta orders highest-first, ties oldest).
        if not hasattr(obj, '_top_bid_cache'):
            obj._top_bid_cache = (
                obj.bids.select_related('user', 'user__community_profile')
                .first()
            )
        return obj._top_bid_cache

    def get_current_bid(self, obj):
        top = self._top_bid(obj)
        return top.amount if top else None

    def get_bid_count(self, obj):
        return obj.bids.count()

    def get_leader_name(self, obj):
        top = self._top_bid(obj)
        return resolve_public_name(top.user) if top else None

    def get_winner_name(self, obj):
        if not obj.winner:
            return None
        return resolve_public_name(obj.winner)


class EventViewerNameSerializer(serializers.Serializer):
    """Lightweight serializer for viewer display names only (privacy-safe)."""
    display_name = serializers.SerializerMethodField()

    def get_display_name(self, obj):
        # obj is a User instance (from EventViewer.user); email prefixes
        # must never appear on the raffle overlay.
        return resolve_public_name(obj)


class RaffleWinnerSerializer(serializers.ModelSerializer):
    prize_name = serializers.CharField(source='raffle.prize_name', read_only=True)
    raffle_id = serializers.IntegerField(read_only=True)
    user = EventAuthorSerializer(read_only=True)

    class Meta:
        model = RaffleWinner
        fields = ['id', 'raffle_id', 'prize_name', 'user', 'drawn_at']
