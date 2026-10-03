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
    excluded_users = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        blank=True,
        related_name='excluded_from_events',
        help_text=(
            "Members who can never win in this event (e.g. the staff "
            "presenting the stream). They still count as viewers."
        ),
    )
    # Bumped (F() + 1) on every chat reaction change. The poll compares it to
    # the client's known_reaction_rev and ships a reaction digest only when
    # they differ — same idiom as known_winner_count, so ~200 viewers polling
    # every 3s cost nothing while nobody is reacting.
    reactions_rev = models.PositiveIntegerField(default=0)
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


# Fulfillment pipeline shared by raffle prizes and auction wins: how the
# winner receives their prize, and how far the (future) Shopify handover got.
FULFILLMENT_TYPE_CHOICES = [
    ('manual', 'Manual (WhatsApp/pickup)'),
    ('shopify', 'Shopify product on order'),
    ('points', 'Loyalty points'),
]

FULFILLMENT_STATUS_CHOICES = [
    ('pending', 'Pending'),
    ('draft_created', 'Draft order created'),
    ('added_to_order', 'Added to order'),
    ('invoice_sent', 'Invoice sent'),
    ('fulfilled', 'Fulfilled'),
    ('failed', 'Failed'),
]


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
    fulfillment_type = models.CharField(
        max_length=10, choices=FULFILLMENT_TYPE_CHOICES, default='manual',
        help_text="How winners receive this prize",
    )
    winner_price = models.DecimalField(
        max_digits=8, decimal_places=2, null=True, blank=True,
        help_text=(
            "What the winner pays for the prize (empty/0 = free). Only "
            "meaningful for Shopify fulfillment, e.g. 'won for €100, "
            "normally €200'."
        ),
    )
    # Set once the prize product exists on Shopify (UNLISTED), so every
    # winner handover reuses the same product/variant.
    shopify_product_gid = models.CharField(max_length=255, blank=True)
    shopify_variant_gid = models.CharField(max_length=255, blank=True)
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

    def draw_winners(self, count=None):
        """Draw random winners from active viewers.

        `count` limits this batch ("Trek 1" on the regie page); None fills
        every remaining slot. The raffle only flips to 'drawn' once all
        num_winners slots are filled, so a multi-prize raffle can be
        revealed one winner at a time, and a draw that found fewer eligible
        viewers than slots stays open for a later retry.

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

            already_won = set(
                RaffleWinner.objects
                .filter(raffle=raffle)
                .values_list('user_id', flat=True)
            )
            remaining = raffle.num_winners - len(already_won)
            if remaining <= 0:
                # Slots were filled out-of-band (e.g. num_winners lowered
                # after a partial draw): just close the raffle.
                raffle.status = 'drawn'
                raffle.drawn_at = timezone.now()
                raffle.save(update_fields=['status', 'drawn_at'])
                self.status = raffle.status
                self.drawn_at = raffle.drawn_at
                return []

            cutoff = timezone.now() - timezone.timedelta(seconds=PRESENCE_WINDOW_SECONDS)
            eligible = list(
                raffle.event.viewers
                .filter(last_seen_at__gte=cutoff)
                .values_list('user_id', flat=True)
            )

            # Optionally exclude users who already won in this event; a
            # winner of an earlier batch of THIS raffle is never redrawn
            # regardless of policy (the unique constraint would trip).
            if raffle.excludes_past_winners():
                ineligible = set(
                    RaffleWinner.objects
                    .filter(raffle__event=raffle.event)
                    .values_list('user_id', flat=True)
                )
            else:
                ineligible = set(already_won)
            # Members on the event blocklist (presenting staff) never win.
            ineligible |= set(
                raffle.event.excluded_users.values_list('id', flat=True)
            )
            eligible = [uid for uid in eligible if uid not in ineligible]

            num_to_draw = min(count or remaining, remaining, len(eligible))
            if num_to_draw <= 0:
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

            if len(already_won) + num_to_draw >= raffle.num_winners:
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
    # Beer details shown in the app while the item is up for auction, so
    # late joiners also know what is being auctioned.
    description = models.TextField(blank=True)
    brewery = models.CharField(max_length=200, blank=True)
    size = models.CharField(max_length=50, blank=True, help_text="e.g. 75cl")
    untappd_rating = models.DecimalField(
        max_digits=3, decimal_places=2, null=True, blank=True,
    )
    image_url = models.URLField(max_length=500, blank=True)
    starting_price = models.DecimalField(max_digits=10, decimal_places=2)
    min_increment = models.PositiveIntegerField(
        default=5, help_text="Minimum euros above the current bid",
    )
    final_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    winner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='auction_wins',
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    # Shopify handover state for the winner (same pipeline as raffle prizes)
    shopify_product_gid = models.CharField(max_length=255, blank=True)
    shopify_variant_gid = models.CharField(max_length=255, blank=True)
    fulfillment_status = models.CharField(
        max_length=20, choices=FULFILLMENT_STATUS_CHOICES, default='pending',
    )
    fulfillment_error = models.TextField(blank=True)
    shopify_order_gid = models.CharField(max_length=255, blank=True)
    fulfilled_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['created_at']

    def __str__(self):
        return f"{self.title} ({self.get_status_display()}) - {self.event.title}"

    def current_bid(self):
        """Highest bid amount, or None before the first bid."""
        top = self.bids.first()  # Bid.Meta orders highest-first
        return top.amount if top else None


class Bid(models.Model):
    """One bid on an auction item. Whole euros only — the app enforces an
    integer-only input so the chat stays free of number spam. Ties go to
    the earliest bid (ordering below)."""
    item = models.ForeignKey(AuctionItem, on_delete=models.CASCADE, related_name='bids')
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='auction_bids',
    )
    amount = models.PositiveIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        # id as final tie-breaker: created_at resolution can collide on
        # same-moment bids and the earlier INSERT must stay the leader
        ordering = ['-amount', 'created_at', 'id']
        indexes = [
            models.Index(fields=['item', 'amount']),
        ]

    def __str__(self):
        return f"€{self.amount} by {self.user.email} on {self.item.title}"


class RaffleWinner(models.Model):
    raffle = models.ForeignKey(Raffle, on_delete=models.CASCADE, related_name='winners')
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='raffle_wins',
    )
    drawn_at = models.DateTimeField(auto_now_add=True)
    # Shopify handover state (per winner — each gets the prize product on
    # their own order/draft order)
    fulfillment_status = models.CharField(
        max_length=20, choices=FULFILLMENT_STATUS_CHOICES, default='pending',
    )
    fulfillment_error = models.TextField(blank=True)
    shopify_order_gid = models.CharField(max_length=255, blank=True)
    fulfilled_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = ['raffle', 'user']

    def __str__(self):
        return f"{self.user.email} won {self.raffle.prize_name}"
