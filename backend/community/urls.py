from django.urls import path
from .views import (
    CommunityProfileView, MembersListView, MemberDetailView,
    FeedView, PostCreateView, PostDeleteView, PostLikeView,
    PostCommentsView, CommentDeleteView,
    ConversationsListView, ConversationCreateView,
    MessagesListView, SendMessageView, MarkReadView, UnreadCountView,
    MemberCheckinsView,
    GroupsListView, AvailableGroupsListView, GroupDetailView,
    GroupJoinView, GroupLeaveView, GroupMessagesListView, GroupSendMessageView,
    UnifiedChatsView,
    SuggestionsListView, SuggestionCreateView, SuggestionDeleteView,
    SuggestionVoteView, SuggestionCommentsView, SuggestionCommentDeleteView,
    SuggestionCommentVoteView,
)

urlpatterns = [
    # Profile
    path('profile/', CommunityProfileView.as_view(), name='community-profile'),

    # Members
    path('members/', MembersListView.as_view(), name='community-members'),
    path('members/<int:user_id>/', MemberDetailView.as_view(), name='community-member-detail'),
    path('members/<int:user_id>/checkins/', MemberCheckinsView.as_view(), name='community-member-checkins'),

    # Feed
    path('feed/', FeedView.as_view(), name='community-feed'),

    # Posts
    path('posts/', PostCreateView.as_view(), name='community-post-create'),
    path('posts/<int:post_id>/', PostDeleteView.as_view(), name='community-post-delete'),
    path('posts/<int:post_id>/like/', PostLikeView.as_view(), name='community-post-like'),
    path('posts/<int:post_id>/comments/', PostCommentsView.as_view(), name='community-post-comments'),

    # Comments
    path('comments/<int:comment_id>/', CommentDeleteView.as_view(), name='community-comment-delete'),

    # Conversations (DMs)
    path('conversations/', ConversationsListView.as_view(), name='community-conversations'),
    path('conversations/create/', ConversationCreateView.as_view(), name='community-conversation-create'),
    path('conversations/<int:conversation_id>/messages/', MessagesListView.as_view(), name='community-messages'),
    path('conversations/<int:conversation_id>/messages/send/', SendMessageView.as_view(), name='community-message-send'),
    path('conversations/<int:conversation_id>/read/', MarkReadView.as_view(), name='community-conversation-read'),

    # Groups
    path('groups/', GroupsListView.as_view(), name='community-groups'),
    path('groups/available/', AvailableGroupsListView.as_view(), name='community-groups-available'),
    path('groups/<int:group_id>/', GroupDetailView.as_view(), name='community-group-detail'),
    path('groups/<int:group_id>/join/', GroupJoinView.as_view(), name='community-group-join'),
    path('groups/<int:group_id>/leave/', GroupLeaveView.as_view(), name='community-group-leave'),
    path('groups/<int:group_id>/messages/', GroupMessagesListView.as_view(), name='community-group-messages'),
    path('groups/<int:group_id>/messages/send/', GroupSendMessageView.as_view(), name='community-group-message-send'),

    # Unified chats
    path('chats/', UnifiedChatsView.as_view(), name='community-chats'),

    # Unread count
    path('unread-count/', UnreadCountView.as_view(), name='community-unread-count'),

    # Suggestions (Forum)
    path('suggestions/', SuggestionsListView.as_view(), name='community-suggestions'),
    path('suggestions/create/', SuggestionCreateView.as_view(), name='community-suggestion-create'),
    path('suggestions/<int:suggestion_id>/', SuggestionDeleteView.as_view(), name='community-suggestion-delete'),
    path('suggestions/<int:suggestion_id>/vote/', SuggestionVoteView.as_view(), name='community-suggestion-vote'),
    path('suggestions/<int:suggestion_id>/comments/', SuggestionCommentsView.as_view(), name='community-suggestion-comments'),
    path('suggestions/comments/<int:comment_id>/', SuggestionCommentDeleteView.as_view(), name='community-suggestion-comment-delete'),
    path('suggestions/comments/<int:comment_id>/vote/', SuggestionCommentVoteView.as_view(), name='community-suggestion-comment-vote'),
]
