from rest_framework import serializers
from community.serializers import AuthorSerializer
from .models import Event, EventMessage, RaffleWinner


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


class EventMessageSerializer(serializers.ModelSerializer):
    user = AuthorSerializer(read_only=True)

    class Meta:
        model = EventMessage
        fields = ['id', 'user', 'message', 'is_system', 'created_at']


class RaffleWinnerSerializer(serializers.ModelSerializer):
    prize_name = serializers.CharField(source='raffle.prize_name', read_only=True)
    user = AuthorSerializer(read_only=True)

    class Meta:
        model = RaffleWinner
        fields = ['id', 'prize_name', 'user', 'drawn_at']
