import logging
from django.db.models import Count, Exists, OuterRef, Prefetch, Q
from rest_framework import status
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView
from rest_framework.pagination import CursorPagination, PageNumberPagination

from .models import (
    CommunityProfile, Post, PostLike, PostComment,
    Conversation, Message, CachedBeerCheckin,
    Group, GroupMembership, GroupMessage,
    Suggestion, SuggestionVote, SuggestionComment, SuggestionCommentVote,
)
from .serializers import (
    CommunityProfileSerializer, MemberDetailSerializer,
    PostSerializer, CreatePostSerializer, CommentSerializer, CommentReplySerializer,
    ConversationSerializer, MessageSerializer, SendMessageSerializer,
    CachedBeerCheckinSerializer,
    GroupSerializer, GroupDetailSerializer, GroupMessageSerializer,
    SuggestionSerializer, CreateSuggestionSerializer, SuggestionCommentSerializer,
)

logger = logging.getLogger(__name__)


class FeedCursorPagination(CursorPagination):
    page_size = 20
    ordering = '-created_at'
    cursor_query_param = 'cursor'


class MessagePagination(PageNumberPagination):
    page_size = 30


class MemberPagination(PageNumberPagination):
    page_size = 20


# --- Community Profile ---

class CommunityProfileView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        profile, _ = CommunityProfile.objects.get_or_create(user=request.user)
        serializer = CommunityProfileSerializer(profile)
        return Response(serializer.data)

    def patch(self, request):
        profile, _ = CommunityProfile.objects.get_or_create(user=request.user)
        serializer = CommunityProfileSerializer(profile, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()

        if 'is_visible' in request.data:
            from analytics.tracker import track
            track('community_visibility_toggle', user=request.user,
                  visible=serializer.validated_data.get('is_visible'))

        return Response(serializer.data)


# --- Members ---

class MembersListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        profiles = (
            CommunityProfile.objects
            .filter(is_visible=True)
            .select_related('user')
            .order_by('-created_at')
        )

        search = request.query_params.get('search', '').strip()
        if search:
            profiles = profiles.filter(
                Q(display_name__icontains=search) |
                Q(user__first_name__icontains=search) |
                Q(user__last_name__icontains=search) |
                Q(user__email__icontains=search)
            )

        paginator = MemberPagination()
        page = paginator.paginate_queryset(profiles, request)
        serializer = MemberDetailSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)


class MemberDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, user_id):
        try:
            profile = (
                CommunityProfile.objects
                .select_related('user')
                .get(user_id=user_id, is_visible=True)
            )
        except CommunityProfile.DoesNotExist:
            return Response({'error': 'Member not found'}, status=status.HTTP_404_NOT_FOUND)

        profile_data = MemberDetailSerializer(profile).data

        posts = _annotate_posts(Post.objects.filter(author_id=user_id), request.user)[:10]
        posts_data = PostSerializer(posts, many=True).data

        checkins = CachedBeerCheckin.objects.filter(user_id=user_id)[:20]
        checkins_data = CachedBeerCheckinSerializer(checkins, many=True).data

        from recommendations.models import Favorite
        from recommendations.serializers import FavoriteSerializer
        favorites = Favorite.objects.filter(user_id=user_id)
        favorites_data = FavoriteSerializer(favorites, many=True).data

        from analytics.tracker import track
        track('community_profile_view', user=request.user, viewed_user_id=user_id)

        return Response({
            'profile': profile_data,
            'posts': posts_data,
            'checkins': checkins_data,
            'favorites': favorites_data,
        })


# --- Feed ---

class FeedView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        visible_users = CommunityProfile.objects.filter(
            is_visible=True
        ).values_list('user_id', flat=True)

        posts = _annotate_posts(
            Post.objects.filter(
                Q(author_id__in=visible_users) | Q(author=request.user)
            ),
            request.user,
        )

        paginator = FeedCursorPagination()
        page = paginator.paginate_queryset(posts, request)
        serializer = PostSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)


class PostCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = CreatePostSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        post = serializer.save(author=request.user)

        from analytics.tracker import track
        track('community_post', user=request.user, post_type=post.post_type)

        annotated = _annotate_posts(Post.objects.filter(id=post.id), request.user).first()
        return Response(PostSerializer(annotated).data, status=status.HTTP_201_CREATED)


class PostDeleteView(APIView):
    permission_classes = [IsAuthenticated]

    def delete(self, request, post_id):
        try:
            post = Post.objects.get(id=post_id, author=request.user)
        except Post.DoesNotExist:
            return Response({'error': 'Post not found'}, status=status.HTTP_404_NOT_FOUND)
        post.delete()
        return Response({'success': True})


class PostLikeView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, post_id):
        try:
            post = Post.objects.get(id=post_id)
        except Post.DoesNotExist:
            return Response({'error': 'Post not found'}, status=status.HTTP_404_NOT_FOUND)

        like, created = PostLike.objects.get_or_create(post=post, user=request.user)
        if not created:
            like.delete()
            liked = False
        else:
            liked = True
            from analytics.tracker import track
            track('community_like', user=request.user, post_id=post_id)

        return Response({'liked': liked, 'like_count': post.likes.count()})


# --- Comments (nested) ---

class PostCommentsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, post_id):
        comments = (
            PostComment.objects
            .filter(post_id=post_id, parent__isnull=True)
            .select_related('author')
            .prefetch_related(
                Prefetch(
                    'replies',
                    queryset=PostComment.objects.select_related('author').order_by('created_at'),
                )
            )
        )
        serializer = CommentSerializer(comments, many=True)
        return Response({'comments': serializer.data})

    def post(self, request, post_id):
        try:
            post = Post.objects.get(id=post_id)
        except Post.DoesNotExist:
            return Response({'error': 'Post not found'}, status=status.HTTP_404_NOT_FOUND)

        content = request.data.get('content', '').strip()
        if not content:
            return Response({'error': 'Content is required'}, status=status.HTTP_400_BAD_REQUEST)

        parent = None
        parent_id = request.data.get('parent_id')
        if parent_id:
            try:
                parent = PostComment.objects.get(id=parent_id, post_id=post_id, parent__isnull=True)
            except PostComment.DoesNotExist:
                return Response({'error': 'Invalid parent comment'}, status=status.HTTP_400_BAD_REQUEST)

        comment = PostComment.objects.create(
            post=post, author=request.user, content=content[:500], parent=parent,
        )

        from analytics.tracker import track
        track('community_comment', user=request.user, post_id=post_id)

        serializer = CommentReplySerializer(comment) if parent else CommentSerializer(comment)
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class CommentDeleteView(APIView):
    permission_classes = [IsAuthenticated]

    def delete(self, request, comment_id):
        try:
            comment = PostComment.objects.get(id=comment_id, author=request.user)
        except PostComment.DoesNotExist:
            return Response({'error': 'Comment not found'}, status=status.HTTP_404_NOT_FOUND)
        comment.delete()
        return Response({'success': True})


# --- Messaging ---

class ConversationsListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        conversations = (
            Conversation.objects
            .filter(Q(participant_1=request.user) | Q(participant_2=request.user))
            .select_related('participant_1', 'participant_2')
            .order_by('-updated_at')
        )
        serializer = ConversationSerializer(
            conversations, many=True, context={'request': request}
        )
        return Response({'conversations': serializer.data})


class ConversationCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        user_id = request.data.get('user_id')
        if not user_id:
            return Response({'error': 'user_id is required'}, status=status.HTTP_400_BAD_REQUEST)

        if int(user_id) == request.user.id:
            return Response({'error': 'Cannot message yourself'}, status=status.HTTP_400_BAD_REQUEST)

        from django.contrib.auth import get_user_model
        User = get_user_model()
        try:
            other_user = User.objects.get(id=user_id)
        except User.DoesNotExist:
            return Response({'error': 'User not found'}, status=status.HTTP_404_NOT_FOUND)

        conversation, created = Conversation.objects.get_or_create_between(request.user, other_user)
        serializer = ConversationSerializer(conversation, context={'request': request})
        return Response(serializer.data, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)


class MessagesListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, conversation_id):
        try:
            conversation = Conversation.objects.get(
                Q(participant_1=request.user) | Q(participant_2=request.user),
                id=conversation_id,
            )
        except Conversation.DoesNotExist:
            return Response({'error': 'Conversation not found'}, status=status.HTTP_404_NOT_FOUND)

        messages = conversation.messages.select_related('sender')
        paginator = MessagePagination()
        page = paginator.paginate_queryset(messages, request)
        serializer = MessageSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)


class SendMessageView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, conversation_id):
        try:
            conversation = Conversation.objects.get(
                Q(participant_1=request.user) | Q(participant_2=request.user),
                id=conversation_id,
            )
        except Conversation.DoesNotExist:
            return Response({'error': 'Conversation not found'}, status=status.HTTP_404_NOT_FOUND)

        serializer = SendMessageSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        message = Message.objects.create(
            conversation=conversation, sender=request.user, **serializer.validated_data,
        )
        conversation.save()

        from analytics.tracker import track
        track('community_message', user=request.user, conversation_id=conversation_id)

        return Response(MessageSerializer(message).data, status=status.HTTP_201_CREATED)


class MarkReadView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, conversation_id):
        try:
            conversation = Conversation.objects.get(
                Q(participant_1=request.user) | Q(participant_2=request.user),
                id=conversation_id,
            )
        except Conversation.DoesNotExist:
            return Response({'error': 'Conversation not found'}, status=status.HTTP_404_NOT_FOUND)

        conversation.messages.filter(is_read=False).exclude(sender=request.user).update(is_read=True)
        return Response({'success': True})


class UnreadCountView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        count = Message.objects.filter(
            Q(conversation__participant_1=request.user) |
            Q(conversation__participant_2=request.user),
            is_read=False,
        ).exclude(sender=request.user).count()
        return Response({'unread_count': count})


# --- Groups ---

class GroupsListView(APIView):
    """List groups the user is a member of."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        groups = Group.objects.filter(
            is_active=True, memberships__user=request.user,
        ).distinct()
        serializer = GroupSerializer(groups, many=True, context={'request': request})
        return Response({'groups': serializer.data})


class AvailableGroupsListView(APIView):
    """List all active groups for browsing/joining."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        groups = Group.objects.filter(is_active=True)
        serializer = GroupSerializer(groups, many=True, context={'request': request})
        return Response({'groups': serializer.data})


class GroupDetailView(APIView):
    """Group detail with member list."""
    permission_classes = [IsAuthenticated]

    def get(self, request, group_id):
        try:
            group = Group.objects.prefetch_related(
                Prefetch('memberships', queryset=GroupMembership.objects.select_related('user'))
            ).get(id=group_id, is_active=True)
        except Group.DoesNotExist:
            return Response({'error': 'Group not found'}, status=status.HTTP_404_NOT_FOUND)

        serializer = GroupDetailSerializer(group, context={'request': request})
        return Response(serializer.data)


class GroupJoinView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, group_id):
        try:
            group = Group.objects.get(id=group_id, is_active=True)
        except Group.DoesNotExist:
            return Response({'error': 'Group not found'}, status=status.HTTP_404_NOT_FOUND)

        _, created = GroupMembership.objects.get_or_create(group=group, user=request.user)
        if not created:
            return Response({'error': 'Already a member'}, status=status.HTTP_400_BAD_REQUEST)

        from analytics.tracker import track
        track('community_group_join', user=request.user, group_id=group_id)

        return Response({'success': True}, status=status.HTTP_201_CREATED)


class GroupLeaveView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, group_id):
        try:
            membership = GroupMembership.objects.get(group_id=group_id, user=request.user)
        except GroupMembership.DoesNotExist:
            return Response({'error': 'Not a member'}, status=status.HTTP_400_BAD_REQUEST)

        membership.delete()

        from analytics.tracker import track
        track('community_group_leave', user=request.user, group_id=group_id)

        return Response({'success': True})


class GroupMessagesListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, group_id):
        if not GroupMembership.objects.filter(group_id=group_id, user=request.user).exists():
            return Response({'error': 'Not a member'}, status=status.HTTP_403_FORBIDDEN)

        messages = GroupMessage.objects.filter(group_id=group_id).select_related('sender')
        paginator = MessagePagination()
        page = paginator.paginate_queryset(messages, request)
        serializer = GroupMessageSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)


class GroupSendMessageView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, group_id):
        if not GroupMembership.objects.filter(group_id=group_id, user=request.user).exists():
            return Response({'error': 'Not a member'}, status=status.HTTP_403_FORBIDDEN)

        serializer = SendMessageSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            group = Group.objects.get(id=group_id, is_active=True)
        except Group.DoesNotExist:
            return Response({'error': 'Group not found'}, status=status.HTTP_404_NOT_FOUND)

        message = GroupMessage.objects.create(
            group=group, sender=request.user, **serializer.validated_data,
        )
        group.save()  # update updated_at

        from analytics.tracker import track
        track('community_group_message', user=request.user, group_id=group_id)

        return Response(GroupMessageSerializer(message).data, status=status.HTTP_201_CREATED)


# --- Unified Chats ---

class UnifiedChatsView(APIView):
    """Combined list of DM conversations + group chats, sorted by last activity."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        items = []

        # DM conversations — prefetch last message and profiles to avoid N+1
        conversations = (
            Conversation.objects
            .filter(Q(participant_1=user) | Q(participant_2=user))
            .select_related(
                'participant_1', 'participant_1__community_profile',
                'participant_2', 'participant_2__community_profile',
            )
            .prefetch_related(
                Prefetch(
                    'messages',
                    queryset=Message.objects.order_by('-created_at'),
                    to_attr='prefetched_messages',
                ),
            )
        )
        for conv in conversations:
            last_msg = conv.prefetched_messages[0] if conv.prefetched_messages else None
            other = conv.get_other_user(user)
            profile = getattr(other, 'community_profile', None)
            display_name = (
                profile.get_display_name() if profile
                else other.first_name or other.email.split('@')[0]
            )
            unread = sum(
                1 for m in conv.prefetched_messages
                if not m.is_read and m.sender_id != user.id
            )
            items.append({
                'type': 'dm',
                'id': conv.id,
                'name': display_name,
                'image_url': None,
                'last_message': {
                    'content': last_msg.content,
                    'sender_id': last_msg.sender_id,
                    'created_at': last_msg.created_at,
                    'has_beer': bool(last_msg.beer_id),
                } if last_msg else None,
                'unread_count': unread,
                'updated_at': conv.updated_at,
                'other_user_id': other.id,
                'member_count': None,
            })

        # Group chats — prefetch last message and annotate member count
        memberships = (
            GroupMembership.objects
            .filter(user=user, group__is_active=True)
            .select_related('group')
            .prefetch_related(
                Prefetch(
                    'group__messages',
                    queryset=GroupMessage.objects.order_by('-created_at')[:1],
                    to_attr='prefetched_messages',
                ),
            )
            .annotate(group_member_count=Count('group__memberships'))
        )
        for membership in memberships:
            group = membership.group
            last_msg = group.prefetched_messages[0] if group.prefetched_messages else None
            items.append({
                'type': 'group',
                'id': group.id,
                'name': group.name,
                'image_url': group.image_url or None,
                'last_message': {
                    'content': last_msg.content,
                    'sender_id': last_msg.sender_id,
                    'created_at': last_msg.created_at,
                    'has_beer': bool(last_msg.beer_id),
                } if last_msg else None,
                'unread_count': 0,
                'updated_at': group.updated_at,
                'other_user_id': None,
                'member_count': membership.group_member_count,
            })

        items.sort(key=lambda x: x['updated_at'], reverse=True)
        return Response({'chats': items})


# --- Checkins ---

class MemberCheckinsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, user_id):
        checkins = CachedBeerCheckin.objects.filter(user_id=user_id)[:30]
        serializer = CachedBeerCheckinSerializer(checkins, many=True)
        return Response({'checkins': serializer.data})


# --- Helpers ---

# --- Suggestions (Forum) ---

class SuggestionPagination(PageNumberPagination):
    page_size = 20


class SuggestionsListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        sort = request.query_params.get('sort', 'top')
        suggestions = _annotate_suggestions(
            Suggestion.objects.all(), request.user,
        )
        if sort == 'new':
            suggestions = suggestions.order_by('-created_at')
        else:
            suggestions = suggestions.order_by('-vote_count', '-created_at')

        paginator = SuggestionPagination()
        page = paginator.paginate_queryset(suggestions, request)
        serializer = SuggestionSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)


class SuggestionCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = CreateSuggestionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        suggestion = serializer.save(author=request.user)

        from analytics.tracker import track
        track('community_suggestion', user=request.user, suggestion_id=suggestion.id)

        annotated = _annotate_suggestions(
            Suggestion.objects.filter(id=suggestion.id), request.user,
        ).first()
        return Response(SuggestionSerializer(annotated).data, status=status.HTTP_201_CREATED)


class SuggestionDeleteView(APIView):
    permission_classes = [IsAuthenticated]

    def delete(self, request, suggestion_id):
        try:
            suggestion = Suggestion.objects.get(id=suggestion_id, author=request.user)
        except Suggestion.DoesNotExist:
            return Response({'error': 'Suggestion not found'}, status=status.HTTP_404_NOT_FOUND)
        suggestion.delete()
        return Response({'success': True})


class SuggestionVoteView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, suggestion_id):
        try:
            suggestion = Suggestion.objects.get(id=suggestion_id)
        except Suggestion.DoesNotExist:
            return Response({'error': 'Suggestion not found'}, status=status.HTTP_404_NOT_FOUND)

        vote, created = SuggestionVote.objects.get_or_create(
            suggestion=suggestion, user=request.user,
        )
        if not created:
            vote.delete()
            voted = False
        else:
            voted = True
            from analytics.tracker import track
            track('community_suggestion_vote', user=request.user, suggestion_id=suggestion_id)

        return Response({'voted': voted, 'vote_count': suggestion.votes.count()})


class SuggestionCommentsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, suggestion_id):
        comments = _annotate_suggestion_comments(
            SuggestionComment.objects.filter(suggestion_id=suggestion_id),
            request.user,
        )
        serializer = SuggestionCommentSerializer(comments, many=True)
        return Response({'comments': serializer.data})

    def post(self, request, suggestion_id):
        try:
            suggestion = Suggestion.objects.get(id=suggestion_id)
        except Suggestion.DoesNotExist:
            return Response({'error': 'Suggestion not found'}, status=status.HTTP_404_NOT_FOUND)

        content = request.data.get('content', '').strip()
        if not content:
            return Response({'error': 'Content is required'}, status=status.HTTP_400_BAD_REQUEST)

        comment = SuggestionComment.objects.create(
            suggestion=suggestion, author=request.user, content=content[:500],
        )

        from analytics.tracker import track
        track('community_suggestion_comment', user=request.user, suggestion_id=suggestion_id)

        annotated = _annotate_suggestion_comments(
            SuggestionComment.objects.filter(id=comment.id), request.user,
        ).first()
        serializer = SuggestionCommentSerializer(annotated)
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class SuggestionCommentVoteView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, comment_id):
        try:
            comment = SuggestionComment.objects.get(id=comment_id)
        except SuggestionComment.DoesNotExist:
            return Response({'error': 'Comment not found'}, status=status.HTTP_404_NOT_FOUND)

        vote, created = SuggestionCommentVote.objects.get_or_create(
            comment=comment, user=request.user,
        )
        if not created:
            vote.delete()
            voted = False
        else:
            voted = True

        return Response({'voted': voted, 'vote_count': comment.votes.count()})


class SuggestionCommentDeleteView(APIView):
    permission_classes = [IsAuthenticated]

    def delete(self, request, comment_id):
        try:
            comment = SuggestionComment.objects.get(id=comment_id, author=request.user)
        except SuggestionComment.DoesNotExist:
            return Response({'error': 'Comment not found'}, status=status.HTTP_404_NOT_FOUND)
        comment.delete()
        return Response({'success': True})


# --- Helpers ---

def _annotate_suggestion_comments(queryset, request_user):
    return queryset.select_related('author', 'author__community_profile').annotate(
        vote_count=Count('votes', distinct=True),
        is_voted=Exists(
            SuggestionCommentVote.objects.filter(comment=OuterRef('pk'), user=request_user)
        ),
    )


def _annotate_suggestions(queryset, request_user):
    return queryset.select_related('author', 'author__community_profile').annotate(
        vote_count=Count('votes', distinct=True),
        comment_count=Count('comments', distinct=True),
        is_voted=Exists(
            SuggestionVote.objects.filter(suggestion=OuterRef('pk'), user=request_user)
        ),
    )


def _annotate_posts(queryset, request_user):
    return queryset.select_related('author', 'author__community_profile').annotate(
        like_count=Count('likes', distinct=True),
        comment_count=Count('comments', distinct=True),
        is_liked=Exists(
            PostLike.objects.filter(post=OuterRef('pk'), user=request_user)
        ),
    )
