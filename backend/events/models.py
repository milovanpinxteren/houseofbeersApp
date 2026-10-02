import logging
import random
from django.db import models, transaction
from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)

# Single presence window used for both the active viewer count and raffle
# eligibility. Matches the client heartbeat (~60s) with margin.
PRESENCE_WINDOW_SECONDS = 90


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
    exclude_past_winners = models.BooleanField(
        default=True,
        help_text="If checked, users who already won a raffle in this event cannot win again"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-scheduled_at']

    def __str__(self):
        return f"{self.title} ({self.get_status_display()}) - {self.scheduled_at:%Y-%m-%d %H:%M}"

    def active_viewer_count(self):
        cutoff = timezone.now() - timezone.timedelta(seconds=PRESENCE_WINDOW_SECONDS)
        return self.viewers.filter(last_seen_at__gte=cutoff).count()


class EventViewer(models.Model):
    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name='viewers')
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='event_views',
    )
    joined_at = models.DateTimeField(auto_now_add=True)
    last_seen_at = models.DateTimeField(auto_now=True, db_index=True)

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
        indexes = [
            models.Index(fields=['event', 'created_at']),
        ]

    def __str__(self):
        return f"Message by {self.user.email} in {self.event.title}"


class Raffle(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('drawn', 'Drawn'),
    ]

    WINNER_POLICY_CHOICES = [
        ('inherit', 'Event default'),
        ('exclude', 'Exclude past winners'),
        ('allow', 'Everyone can win'),
    ]

    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name='raffles')
    prize_name = models.CharField(max_length=200)
    shopify_product_id = models.CharField(max_length=255, blank=True)
    num_winners = models.PositiveIntegerField(default=1)
    winner_policy = models.CharField(
        max_length=10, choices=WINNER_POLICY_CHOICES, default='inherit',
        help_text=(
            "Per-raffle override of the event's exclude_past_winners flag "
            "(can still be changed while the raffle is pending)"
        ),
    )
    points_award = models.PositiveIntegerField(
        default=0,
        help_text=(
            "Loyalty points credited to EACH winner automatically on draw "
            "(0 = physical prize, manual fulfillment)"
        ),
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    drawn_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.prize_name} ({self.get_status_display()}) - {self.event.title}"

    def excludes_past_winners(self):
        """Effective winner policy: per-raffle override, else the event flag."""
        if self.winner_policy == 'exclude':
            return True
        if self.winner_policy == 'allow':
            return False
        return self.event.exclude_past_winners

    def draw_winners(self):
        """Draw random winners from active viewers.

        Atomic: locks the raffle row and re-checks status so a concurrent
        (double-clicked) draw can't run twice. Returns None if the raffle
        was already drawn, a (possibly empty) list of RaffleWinner otherwise.

        Winner notifications go out after the transaction commits: they do
        network I/O and their failure must never undo the draw.
        """
        with transaction.atomic():
            raffle = Raffle.objects.select_for_update().get(pk=self.pk)
            if raffle.status != 'pending':
                return None

            cutoff = timezone.now() - timezone.timedelta(seconds=PRESENCE_WINDOW_SECONDS)
            eligible = list(
                raffle.event.viewers
                .filter(last_seen_at__gte=cutoff)
                .values_list('user_id', flat=True)
            )

            # Optionally exclude users who already won in this event
            if raffle.excludes_past_winners():
                existing_winner_ids = set(
                    RaffleWinner.objects
                    .filter(raffle__event=raffle.event)
                    .values_list('user_id', flat=True)
                )
                eligible = [uid for uid in eligible if uid not in existing_winner_ids]

            num_to_draw = min(raffle.num_winners, len(eligible))
            if num_to_draw == 0:
                return []

            winner_ids = random.sample(eligible, num_to_draw)
            from django.contrib.auth import get_user_model
            User = get_user_model()
            winners = User.objects.filter(id__in=winner_ids)

            created_winners = RaffleWinner.objects.bulk_create(
                [RaffleWinner(raffle=raffle, user=user) for user in winners]
            )

            # Points prizes are credited INSIDE the draw transaction: a draw
            # whose points can't land must roll back whole, never produce
            # winners without their prize. DB-only, so safe in the lock.
            raffle._award_points_locked(created_winners)

            raffle.status = 'drawn'
            raffle.drawn_at = timezone.now()
            raffle.save(update_fields=['status', 'drawn_at'])

            # Keep the in-memory instance consistent with the DB
            self.status = raffle.status
            self.drawn_at = raffle.drawn_at

        self._notify_winners(created_winners)
        return created_winners

    def _award_points_locked(self, winners):
        """Credit `points_award` to each winner's balance. Caller must hold
        the draw transaction. Same transaction shape as service grants
        (`earned`, rule=None, no shopify_order_id): the app renders the
        description verbatim and every sync tier leaves it alone."""
        if not self.points_award or not winners:
            return
        from loyalty.models import PointsBalance, PointsTransaction

        description = f'Livestream prijs: {self.prize_name}'
        for winner in winners:
            balance, _ = (
                PointsBalance.objects.select_for_update()
                .get_or_create(user=winner.user)
            )
            balance.balance += self.points_award
            # lifetime_spent only tracks reward redemptions; prizes land in
            # lifetime_earned, keeping balance == earned - spent intact.
            balance.lifetime_earned += self.points_award
            balance.save()
            PointsTransaction.objects.create(
                user=winner.user,
                transaction_type='earned',
                points=self.points_award,
                balance_after=balance.balance,
                description=description,
                breakdown=[{
                    'event_raffle_id': self.pk,
                    'source': 'livestream_raffle',
                    'rule_name': description,
                    'points': self.points_award,
                }],
            )
            logger.info(
                f"Raffle {self.pk} ({self.prize_name}): {self.points_award} "
                f"points credited to {winner.user.email}"
            )

    def _notify_winners(self, winners):
        """One "je hebt gewonnen" per winner via the notifications outbox.

        The in-stream overlay is ephemeral (5s, and a locked phone stops
        polling entirely), so a winner needs a durable record that they won
        and that staff will contact them about the prize. Failures are
        logged per user and never abort the rest of the fan-out.
        """
        if self.points_award:
            follow_up = (
                f'De {self.points_award} punten zijn direct toegevoegd '
                'aan je saldo.'
            )
        else:
            follow_up = 'We nemen contact met je op over je prijs.'
        for winner in winners:
            try:
                from notifications.services import send_notification

                send_notification(
                    winner.user,
                    kind='raffle',
                    title='Je hebt gewonnen!',
                    body=(
                        f'Gefeliciteerd! Je hebt gewonnen: {self.prize_name}. '
                        f'{follow_up}'
                    ),
                    data={'url': f'/livestream?eventId={self.event_id}'},
                    dedupe_key=f'event-raffle:{self.pk}:{winner.user_id}:won',
                )
            except Exception as e:
                logger.error(
                    f"Winner notification failed for raffle {self.pk}, "
                    f"user {winner.user.email}: {e}",
                    exc_info=True,
                )


class AuctionItem(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('active', 'Active'),
        ('sold', 'Sold'),
    ]

    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name='auction_items')
    title = models.CharField(max_length=200)
    image_url = models.URLField(max_length=500, blank=True)
    starting_price = models.DecimalField(max_digits=10, decimal_places=2)
    final_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    winner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='auction_wins',
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['created_at']

    def __str__(self):
        return f"{self.title} ({self.get_status_display()}) - {self.event.title}"


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
