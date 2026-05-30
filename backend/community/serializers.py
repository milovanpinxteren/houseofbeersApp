from rest_framework import serializers
from .models import (
    CommunityProfile, Post, PostLike, PostComment,
    Conversation, Message, CachedBeerCheckin,
    Group, GroupMembership, GroupMessage,
)


class AuthorSerializer(serializers.Serializer):
    user_id = serializers.IntegerField(source='id')
    display_name = serializers.SerializerMethodField()
    first_name = serializers.CharField()
    has_untappd = serializers.SerializerMethodField()

    def get_display_name(self, obj):
        profile = getattr(obj, 'community_profile', None)
        if profile and profile.display_name:
            return profile.display_name
        return obj.first_name or obj.email.split('@')[0]

    def get_has_untappd(self, obj):
        return hasattr(obj, 'untappd_profile')


class CommunityProfileSerializer(serializers.ModelSerializer):
    user_id = serializers.IntegerField(source='user.id', read_only=True)
    display_name_resolved = serializers.CharField(source='get_display_name', read_only=True)
    first_name = serializers.CharField(source='user.first_name', read_only=True)
    has_untappd = serializers.SerializerMethodField()
    untappd_username = serializers.SerializerMethodField()

    class Meta:
        model = CommunityProfile
        fields = [
            'user_id', 'display_name', 'display_name_resolved', 'bio',
            'is_visible', 'first_name', 'has_untappd', 'untappd_username',
            'created_at',
        ]
        read_only_fields = ['user_id', 'display_name_resolved', 'first_name',
                            'has_untappd', 'untappd_username', 'created_at']

    def get_has_untappd(self, obj):
        return hasattr(obj.user, 'untappd_profile')

    def get_untappd_username(self, obj):
        profile = getattr(obj.user, 'untappd_profile', None)
        return profile.username if profile else None


class MemberDetailSerializer(CommunityProfileSerializer):
    favorite_count = serializers.SerializerMethodField()
    checkin_count = serializers.SerializerMethodField()

    class Meta(CommunityProfileSerializer.Meta):
        fields = CommunityProfileSerializer.Meta.fields + [
            'favorite_count', 'checkin_count',
        ]

    def get_favorite_count(self, obj):
        return obj.user.favorite_beers.count()

    def get_checkin_count(self, obj):
        return obj.user.cached_checkins.count()


class PostSerializer(serializers.ModelSerializer):
    author = AuthorSerializer(read_only=True)
    like_count = serializers.IntegerField(read_only=True)
    comment_count = serializers.IntegerField(read_only=True)
    is_liked = serializers.BooleanField(read_only=True)

    class Meta:
        model = Post
        fields = [
            'id', 'author', 'post_type', 'content',
            'beer_id', 'beer_title', 'beer_vendor', 'beer_image_url',
            'beer_style', 'beer_rating',
            'like_count', 'comment_count', 'is_liked',
            'created_at',
        ]
        read_only_fields = ['id', 'author', 'like_count', 'comment_count',
                            'is_liked', 'created_at']


class CreatePostSerializer(serializers.ModelSerializer):
    class Meta:
        model = Post
        fields = [
            'post_type', 'content',
            'beer_id', 'beer_title', 'beer_vendor', 'beer_image_url',
            'beer_style', 'beer_rating',
        ]


# --- Comments (nested) ---

class CommentReplySerializer(serializers.ModelSerializer):
    """Flat serializer for replies (no further nesting)."""
    author = AuthorSerializer(read_only=True)

    class Meta:
        model = PostComment
        fields = ['id', 'author', 'content', 'parent_id', 'created_at']
        read_only_fields = ['id', 'author', 'created_at']


class CommentSerializer(serializers.ModelSerializer):
    """Top-level comment with nested replies."""
    author = AuthorSerializer(read_only=True)
    replies = CommentReplySerializer(many=True, read_only=True)

    class Meta:
        model = PostComment
        fields = ['id', 'author', 'content', 'parent_id', 'replies', 'created_at']
        read_only_fields = ['id', 'author', 'replies', 'created_at']


# --- Conversations ---

class ConversationSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    other_user = serializers.SerializerMethodField()
    last_message = serializers.SerializerMethodField()
    unread_count = serializers.SerializerMethodField()
    updated_at = serializers.DateTimeField()

    def get_other_user(self, obj):
        request_user = self.context['request'].user
        other = obj.get_other_user(request_user)
        return AuthorSerializer(other).data

    def get_last_message(self, obj):
        last = obj.messages.order_by('-created_at').first()
        if not last:
            return None
        return {
            'content': last.content,
            'sender_id': last.sender_id,
            'created_at': last.created_at,
            'has_beer': bool(last.beer_id),
        }

    def get_unread_count(self, obj):
        request_user = self.context['request'].user
        return obj.messages.filter(is_read=False).exclude(sender=request_user).count()


class MessageSerializer(serializers.ModelSerializer):
    sender_id = serializers.IntegerField(source='sender.id', read_only=True)

    class Meta:
        model = Message
        fields = [
            'id', 'sender_id', 'content',
            'beer_id', 'beer_title', 'beer_image_url', 'beer_style',
            'is_read', 'created_at',
        ]
        read_only_fields = ['id', 'sender_id', 'is_read', 'created_at']


class SendMessageSerializer(serializers.Serializer):
    content = serializers.CharField(max_length=1000)
    beer_id = serializers.CharField(max_length=50, required=False, default='')
    beer_title = serializers.CharField(max_length=255, required=False, default='')
    beer_image_url = serializers.CharField(max_length=500, required=False, default='')
    beer_style = serializers.CharField(max_length=100, required=False, default='')


# --- Groups ---

class GroupMemberSerializer(serializers.ModelSerializer):
    user_id = serializers.IntegerField(source='user.id')
    display_name = serializers.SerializerMethodField()

    class Meta:
        model = GroupMembership
        fields = ['user_id', 'display_name', 'role', 'joined_at']

    def get_display_name(self, obj):
        profile = getattr(obj.user, 'community_profile', None)
        if profile and profile.display_name:
            return profile.display_name
        return obj.user.first_name or obj.user.email.split('@')[0]


class GroupSerializer(serializers.ModelSerializer):
    member_count = serializers.SerializerMethodField()
    is_member = serializers.SerializerMethodField()

    class Meta:
        model = Group
        fields = ['id', 'name', 'description', 'image_url', 'member_count',
                  'is_member', 'created_at']

    def get_member_count(self, obj):
        return obj.memberships.count()

    def get_is_member(self, obj):
        request = self.context.get('request')
        if not request:
            return False
        return obj.memberships.filter(user=request.user).exists()


class GroupDetailSerializer(GroupSerializer):
    members = GroupMemberSerializer(source='memberships', many=True, read_only=True)

    class Meta(GroupSerializer.Meta):
        fields = GroupSerializer.Meta.fields + ['members']


class GroupMessageSerializer(serializers.ModelSerializer):
    sender_id = serializers.IntegerField(source='sender.id', read_only=True)
    sender_name = serializers.SerializerMethodField()

    class Meta:
        model = GroupMessage
        fields = [
            'id', 'sender_id', 'sender_name', 'content',
            'beer_id', 'beer_title', 'beer_image_url', 'beer_style',
            'created_at',
        ]

    def get_sender_name(self, obj):
        profile = getattr(obj.sender, 'community_profile', None)
        if profile and profile.display_name:
            return profile.display_name
        return obj.sender.first_name or obj.sender.email.split('@')[0]


class CachedBeerCheckinSerializer(serializers.ModelSerializer):
    class Meta:
        model = CachedBeerCheckin
        fields = [
            'beer_title', 'beer_vendor', 'beer_style', 'beer_abv',
            'user_rating', 'checkin_date',
        ]
