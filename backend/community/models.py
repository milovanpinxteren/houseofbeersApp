from django.db import models
from django.conf import settings


class CommunityProfile(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='community_profile',
    )
    is_visible = models.BooleanField(default=True)
    display_name = models.CharField(max_length=100, blank=True)
    bio = models.TextField(max_length=300, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def get_display_name(self):
        return self.display_name or self.user.first_name or self.user.email.split('@')[0]

    def __str__(self):
        return f"{self.get_display_name()} (community profile)"


class Post(models.Model):
    POST_TYPE_CHOICES = [
        ('review', 'Beer Review'),
        ('share', 'Beer Share'),
        ('text', 'Text Post'),
    ]

    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='community_posts',
    )
    post_type = models.CharField(max_length=20, choices=POST_TYPE_CHOICES, default='text')
    content = models.TextField(max_length=1000)

    # Optional beer data (denormalized, same pattern as Favorite model)
    beer_id = models.CharField(max_length=50, blank=True)
    beer_title = models.CharField(max_length=255, blank=True)
    beer_vendor = models.CharField(max_length=255, blank=True)
    beer_image_url = models.URLField(max_length=500, blank=True)
    beer_style = models.CharField(max_length=100, blank=True)
    beer_rating = models.DecimalField(max_digits=3, decimal_places=2, null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.get_post_type_display()} by {self.author.email} at {self.created_at:%Y-%m-%d %H:%M}"


class PostLike(models.Model):
    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name='likes')
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='post_likes',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ['post', 'user']


class PostComment(models.Model):
    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name='comments')
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='post_comments',
    )
    parent = models.ForeignKey(
        'self',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='replies',
    )
    content = models.TextField(max_length=500)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']

    def __str__(self):
        return f"Comment by {self.author.email} on post #{self.post_id}"


class ConversationManager(models.Manager):
    def get_or_create_between(self, user1, user2):
        """Get or create a conversation, enforcing participant_1.id < participant_2.id."""
        p1, p2 = sorted([user1, user2], key=lambda u: u.id)
        return self.get_or_create(participant_1=p1, participant_2=p2)


class Conversation(models.Model):
    participant_1 = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='conversations_as_p1',
    )
    participant_2 = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='conversations_as_p2',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = ConversationManager()

    class Meta:
        unique_together = ['participant_1', 'participant_2']
        ordering = ['-updated_at']

    def get_other_user(self, user):
        return self.participant_2 if self.participant_1 == user else self.participant_1

    def __str__(self):
        return f"Conversation: {self.participant_1.email} <-> {self.participant_2.email}"


class Message(models.Model):
    conversation = models.ForeignKey(
        Conversation, on_delete=models.CASCADE, related_name='messages',
    )
    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='sent_messages',
    )
    content = models.TextField(max_length=1000)

    # Optional beer share
    beer_id = models.CharField(max_length=50, blank=True)
    beer_title = models.CharField(max_length=255, blank=True)
    beer_image_url = models.URLField(max_length=500, blank=True)
    beer_style = models.CharField(max_length=100, blank=True)

    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']

    def __str__(self):
        return f"Message from {self.sender.email} at {self.created_at:%Y-%m-%d %H:%M}"


class Group(models.Model):
    name = models.CharField(max_length=100)
    description = models.TextField(max_length=500, blank=True)
    image_url = models.URLField(max_length=500, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='created_groups',
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at']

    def __str__(self):
        return self.name


class GroupMembership(models.Model):
    ROLE_CHOICES = [
        ('member', 'Member'),
        ('admin', 'Admin'),
    ]

    group = models.ForeignKey(Group, on_delete=models.CASCADE, related_name='memberships')
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='group_memberships',
    )
    role = models.CharField(max_length=10, choices=ROLE_CHOICES, default='member')
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ['group', 'user']
        ordering = ['joined_at']

    def __str__(self):
        return f"{self.user.email} in {self.group.name} ({self.role})"


class GroupMessage(models.Model):
    group = models.ForeignKey(Group, on_delete=models.CASCADE, related_name='messages')
    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='sent_group_messages',
    )
    content = models.TextField(max_length=1000)

    # Optional beer share
    beer_id = models.CharField(max_length=50, blank=True)
    beer_title = models.CharField(max_length=255, blank=True)
    beer_image_url = models.URLField(max_length=500, blank=True)
    beer_style = models.CharField(max_length=100, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']

    def __str__(self):
        return f"GroupMessage from {self.sender.email} in {self.group.name}"


class CachedBeerCheckin(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='cached_checkins',
    )
    beer_title = models.CharField(max_length=255)
    beer_vendor = models.CharField(max_length=255, blank=True)
    beer_style = models.CharField(max_length=100, blank=True)
    beer_abv = models.DecimalField(max_digits=4, decimal_places=1, null=True, blank=True)
    user_rating = models.DecimalField(max_digits=3, decimal_places=2, null=True, blank=True)
    checkin_date = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = ['user', 'beer_title']
        ordering = ['-checkin_date']

    def __str__(self):
        return f"{self.user.email}: {self.beer_title} ({self.user_rating})"


class Suggestion(models.Model):
    STATUS_CHOICES = [
        ('open', 'Open'),
        ('planned', 'Planned'),
        ('done', 'Done'),
        ('declined', 'Declined'),
    ]

    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='suggestions',
    )
    title = models.CharField(max_length=200)
    content = models.TextField(max_length=1000)
    tag = models.CharField(max_length=50, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='open')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.title} by {self.author.email}"


class SuggestionVote(models.Model):
    suggestion = models.ForeignKey(Suggestion, on_delete=models.CASCADE, related_name='votes')
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='suggestion_votes',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ['suggestion', 'user']


class SuggestionComment(models.Model):
    suggestion = models.ForeignKey(Suggestion, on_delete=models.CASCADE, related_name='comments')
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='suggestion_comments',
    )
    content = models.TextField(max_length=500)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']

    def __str__(self):
        return f"Comment by {self.author.email} on '{self.suggestion.title}'"


class SuggestionCommentVote(models.Model):
    comment = models.ForeignKey(SuggestionComment, on_delete=models.CASCADE, related_name='votes')
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='suggestion_comment_votes',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ['comment', 'user']
