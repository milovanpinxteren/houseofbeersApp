from django.db import models
from django.conf import settings


class UsageEvent(models.Model):
    EVENT_TYPES = [
        ('login', 'Login'),
        ('register', 'Registration'),
        ('recommendations', 'View Recommendations'),
        ('taste_profile', 'View Taste Profile'),
        ('favorite_add', 'Add Favorite'),
        ('favorite_remove', 'Remove Favorite'),
        ('reward_redeem', 'Redeem Reward'),
        ('points_sync', 'Sync Points'),
        ('orders_view', 'View Orders'),
        ('untappd_link', 'Link Untappd'),
        ('untappd_unlink', 'Unlink Untappd'),
        ('cart_link', 'Generate Cart Link'),
        ('notification_dismiss', 'Dismiss Notification'),
        ('community_post', 'Create Post'),
        ('community_like', 'Like Post'),
        ('community_comment', 'Comment on Post'),
        ('community_message', 'Send Message'),
        ('community_profile_view', 'View Member Profile'),
        ('community_visibility_toggle', 'Toggle Community Visibility'),
        ('community_group_join', 'Join Group'),
        ('community_group_leave', 'Leave Group'),
        ('community_group_message', 'Group Message'),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='usage_events',
    )
    event_type = models.CharField(max_length=30, choices=EVENT_TYPES, db_index=True)
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['event_type', 'timestamp']),
            models.Index(fields=['user', 'timestamp']),
        ]

    def __str__(self):
        user_str = self.user.email if self.user else 'anonymous'
        return f"{self.get_event_type_display()} by {user_str} at {self.timestamp:%Y-%m-%d %H:%M}"
