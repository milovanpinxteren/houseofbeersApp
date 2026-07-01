from django.contrib import admin
from django.utils.html import format_html
from .models import (
    CommunityProfile, Post, PostLike, PostComment,
    Conversation, Message, CachedBeerCheckin,
    Group, GroupMembership, GroupMessage,
    Suggestion, SuggestionVote, SuggestionComment,
)


@admin.register(CommunityProfile)
class CommunityProfileAdmin(admin.ModelAdmin):
    list_display = ['user', 'display_name_display', 'is_visible', 'bio_preview', 'created_at']
    list_filter = ['is_visible', 'created_at']
    search_fields = ['user__email', 'user__first_name', 'display_name']
    readonly_fields = ['user', 'created_at', 'updated_at']
    ordering = ['-created_at']

    def display_name_display(self, obj):
        return obj.get_display_name()
    display_name_display.short_description = 'Display Name'

    def bio_preview(self, obj):
        if not obj.bio:
            return '-'
        return obj.bio[:60] + '...' if len(obj.bio) > 60 else obj.bio
    bio_preview.short_description = 'Bio'


@admin.register(Post)
class PostAdmin(admin.ModelAdmin):
    list_display = ['author_display', 'post_type', 'content_preview', 'beer_title',
                    'like_count', 'comment_count', 'created_at']
    list_filter = ['post_type', 'created_at']
    search_fields = ['author__email', 'content', 'beer_title']
    readonly_fields = ['author', 'created_at', 'updated_at']
    ordering = ['-created_at']

    def author_display(self, obj):
        return obj.author.email
    author_display.short_description = 'Author'

    def content_preview(self, obj):
        return obj.content[:80] + '...' if len(obj.content) > 80 else obj.content
    content_preview.short_description = 'Content'

    def like_count(self, obj):
        return obj.likes.count()
    like_count.short_description = 'Likes'

    def comment_count(self, obj):
        return obj.comments.count()
    comment_count.short_description = 'Comments'


@admin.register(PostComment)
class PostCommentAdmin(admin.ModelAdmin):
    list_display = ['author_display', 'post_id', 'is_reply', 'content_preview', 'created_at']
    list_filter = ['created_at']
    search_fields = ['author__email', 'content']
    readonly_fields = ['post', 'author', 'parent', 'created_at']
    ordering = ['-created_at']

    def author_display(self, obj):
        return obj.author.email
    author_display.short_description = 'Author'

    def content_preview(self, obj):
        return obj.content[:80] + '...' if len(obj.content) > 80 else obj.content
    content_preview.short_description = 'Content'

    def is_reply(self, obj):
        return obj.parent is not None
    is_reply.boolean = True
    is_reply.short_description = 'Reply'


@admin.register(Conversation)
class ConversationAdmin(admin.ModelAdmin):
    list_display = ['id', 'participant_1_display', 'participant_2_display',
                    'message_count', 'updated_at']
    search_fields = ['participant_1__email', 'participant_2__email']
    readonly_fields = ['participant_1', 'participant_2', 'created_at', 'updated_at']
    ordering = ['-updated_at']

    def participant_1_display(self, obj):
        return obj.participant_1.email
    participant_1_display.short_description = 'Participant 1'

    def participant_2_display(self, obj):
        return obj.participant_2.email
    participant_2_display.short_description = 'Participant 2'

    def message_count(self, obj):
        return obj.messages.count()
    message_count.short_description = 'Messages'


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ['sender_display', 'conversation_id', 'content_preview',
                    'has_beer', 'is_read', 'created_at']
    list_filter = ['is_read', 'created_at']
    search_fields = ['sender__email', 'content']
    readonly_fields = ['conversation', 'sender', 'created_at']
    ordering = ['-created_at']

    def sender_display(self, obj):
        return obj.sender.email
    sender_display.short_description = 'Sender'

    def content_preview(self, obj):
        return obj.content[:80] + '...' if len(obj.content) > 80 else obj.content
    content_preview.short_description = 'Content'

    def has_beer(self, obj):
        return bool(obj.beer_id)
    has_beer.boolean = True
    has_beer.short_description = 'Beer Shared'


# --- Groups ---

class GroupMembershipInline(admin.TabularInline):
    model = GroupMembership
    extra = 1
    raw_id_fields = ['user']


@admin.register(Group)
class GroupAdmin(admin.ModelAdmin):
    list_display = ['name', 'member_count_display', 'is_active', 'created_at']
    list_filter = ['is_active', 'created_at']
    search_fields = ['name', 'description']
    ordering = ['-created_at']
    inlines = [GroupMembershipInline]

    def member_count_display(self, obj):
        return obj.memberships.count()
    member_count_display.short_description = 'Members'

    def save_model(self, request, obj, form, change):
        if not change:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)


@admin.register(GroupMessage)
class GroupMessageAdmin(admin.ModelAdmin):
    list_display = ['sender_display', 'group', 'content_preview', 'has_beer', 'created_at']
    list_filter = ['group', 'created_at']
    search_fields = ['sender__email', 'content']
    readonly_fields = ['group', 'sender', 'created_at']
    ordering = ['-created_at']

    def sender_display(self, obj):
        return obj.sender.email
    sender_display.short_description = 'Sender'

    def content_preview(self, obj):
        return obj.content[:80] + '...' if len(obj.content) > 80 else obj.content
    content_preview.short_description = 'Content'

    def has_beer(self, obj):
        return bool(obj.beer_id)
    has_beer.boolean = True
    has_beer.short_description = 'Beer'

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


# --- Suggestions (Forum) ---

@admin.register(Suggestion)
class SuggestionAdmin(admin.ModelAdmin):
    list_display = ['title', 'author_display', 'tag', 'status', 'vote_count_display',
                    'comment_count_display', 'created_at']
    list_filter = ['status', 'created_at']
    list_editable = ['status']
    search_fields = ['title', 'content', 'tag', 'author__email']
    readonly_fields = ['author', 'created_at', 'updated_at']
    ordering = ['-created_at']

    def author_display(self, obj):
        return obj.author.email
    author_display.short_description = 'Author'

    def vote_count_display(self, obj):
        return obj.votes.count()
    vote_count_display.short_description = 'Votes'

    def comment_count_display(self, obj):
        return obj.comments.count()
    comment_count_display.short_description = 'Comments'


@admin.register(SuggestionComment)
class SuggestionCommentAdmin(admin.ModelAdmin):
    list_display = ['author_display', 'suggestion_title', 'content_preview', 'created_at']
    search_fields = ['author__email', 'content']
    readonly_fields = ['suggestion', 'author', 'created_at']
    ordering = ['-created_at']

    def author_display(self, obj):
        return obj.author.email
    author_display.short_description = 'Author'

    def suggestion_title(self, obj):
        return obj.suggestion.title[:60]
    suggestion_title.short_description = 'Suggestion'

    def content_preview(self, obj):
        return obj.content[:80] + '...' if len(obj.content) > 80 else obj.content
    content_preview.short_description = 'Content'

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(CachedBeerCheckin)
class CachedBeerCheckinAdmin(admin.ModelAdmin):
    list_display = ['user_display', 'beer_title', 'beer_vendor', 'user_rating', 'checkin_date']
    list_filter = ['checkin_date']
    search_fields = ['user__email', 'beer_title', 'beer_vendor']
    readonly_fields = ['user', 'beer_title', 'beer_vendor', 'beer_style',
                       'beer_abv', 'user_rating', 'checkin_date']
    ordering = ['-checkin_date']

    def user_display(self, obj):
        return obj.user.email
    user_display.short_description = 'User'

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
