import random
from django.db import models
from django.conf import settings
from django.utils import timezone


class Event(models.Model):
    EVENT_TYPE_CHOICES = [
        ('livestream', 'Livestream'),
        ('auction', 'Auction'),
        ('tasting', 'Tasting'),
        ('release_review', 'Release Review'),
        ('sale', 'Sale'),
    ]

    STATUS_CHOICES = [
        ('scheduled', 'Scheduled'),
        ('live', 'Live'),
        ('ended', 'Ended'),
    ]

    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    event_type = models.CharField(max_length=20, choices=EVENT_TYPE_CHOICES, default='livestream')
    scheduled_at = models.DateTimeField()
    youtube_url = models.URLField(max_length=500, blank=True)
    image_url = models.URLField(max_length=500, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='scheduled')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-scheduled_at']

    def __str__(self):
        return f"{self.title} ({self.get_status_display()}) - {self.scheduled_at:%Y-%m-%d %H:%M}"

    def active_viewer_count(self):
        cutoff = timezone.now() - timezone.timedelta(seconds=30)
        return self.viewers.filter(last_seen_at__gte=cutoff).count()


class EventViewer(models.Model):
    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name='viewers')
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='event_views',
    )
    joined_at = models.DateTimeField(auto_now_add=True)
    last_seen_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ['event', 'user']

    def __str__(self):
        return f"{self.user.email} viewing {self.event.title}"


class EventMessage(models.Model):
    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name='messages')
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='event_messages',
    )
    message = models.TextField(max_length=500)
    is_system = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']

    def __str__(self):
        return f"Message by {self.user.email} in {self.event.title}"


class Raffle(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('drawn', 'Drawn'),
    ]

    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name='raffles')
    prize_name = models.CharField(max_length=200)
    shopify_product_id = models.CharField(max_length=255, blank=True)
    num_winners = models.PositiveIntegerField(default=1)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    drawn_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.prize_name} ({self.get_status_display()}) - {self.event.title}"

    def draw_winners(self):
        """Draw random winners from active viewers, excluding past event winners."""
        cutoff = timezone.now() - timezone.timedelta(minutes=5)
        active_viewer_user_ids = list(
            self.event.viewers
            .filter(last_seen_at__gte=cutoff)
            .values_list('user_id', flat=True)
        )

        # Exclude users who already won in this event
        existing_winner_ids = set(
            RaffleWinner.objects
            .filter(raffle__event=self.event)
            .values_list('user_id', flat=True)
        )

        eligible = [uid for uid in active_viewer_user_ids if uid not in existing_winner_ids]

        num_to_draw = min(self.num_winners, len(eligible))
        if num_to_draw == 0:
            return []

        winner_ids = random.sample(eligible, num_to_draw)
        from django.contrib.auth import get_user_model
        User = get_user_model()
        winners = User.objects.filter(id__in=winner_ids)

        created_winners = []
        for user in winners:
            winner = RaffleWinner.objects.create(raffle=self, user=user)
            created_winners.append(winner)

        self.status = 'drawn'
        self.drawn_at = timezone.now()
        self.save()

        return created_winners


class RaffleWinner(models.Model):
    raffle = models.ForeignKey(Raffle, on_delete=models.CASCADE, related_name='winners')
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='raffle_wins',
    )
    drawn_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ['raffle', 'user']

    def __str__(self):
        return f"{self.user.email} won {self.raffle.prize_name}"
