"""DEV-ONLY: seed a demo livestream with viewers and pending raffles so the
raffle draw (overlay animation + winner notification) can be rehearsed
against a local backend.

    python manage.py seed_demo_livestream --email you@example.com  # live event, viewers, 3 raffles
    python manage.py seed_demo_livestream --email you@example.com  # re-run: re-arms drawn raffles
    python manage.py seed_demo_livestream --clean                  # remove all demo data again

Creates a LIVE event with ~14 named demo viewers (demo-viewer-*@example.com)
whose presence is stamped a few hours into the future — they don't poll, and
real presence would expire 90s after seeding. Your --email account is added
as a viewer too. Re-running resets drawn raffles to pending, deletes their
winners and their outbox notifications (the dedupe key would otherwise
suppress the notification on the next test draw), and refreshes presence.

Draw during the rehearsal exactly as on the night itself: Django admin →
Raffles → "Draw winners", with the PWA open on the livestream screen.

Refuses to run when DEBUG is off: this writes fake users and fake presence.
"""
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from events.models import Event, EventMessage, EventViewer, Raffle

DEMO_EVENT_TITLE = '[DEMO] Livestream proefdraai'
DEMO_YOUTUBE_URL = 'https://www.youtube.com/watch?v=jNQXAC9IVRw'

DEMO_VIEWERS = [
    ('demo-viewer-1@example.com', 'Daan'),
    ('demo-viewer-2@example.com', 'Sanne'),
    ('demo-viewer-3@example.com', 'Bram'),
    ('demo-viewer-4@example.com', 'Lotte'),
    ('demo-viewer-5@example.com', 'Sem'),
    ('demo-viewer-6@example.com', 'Femke'),
    ('demo-viewer-7@example.com', 'Ruben'),
    ('demo-viewer-8@example.com', 'Anouk'),
    ('demo-viewer-9@example.com', 'Thijs'),
    ('demo-viewer-10@example.com', 'Iris'),
    ('demo-viewer-11@example.com', 'Koen'),
    ('demo-viewer-12@example.com', 'Maud'),
    ('demo-viewer-13@example.com', 'Jesse'),
    ('demo-viewer-14@example.com', 'Nina'),
]

DEMO_RAFFLES = [
    ('Bierpakket Hazy IPA', 1),
    ('House of Beers hoodie', 1),
    ('Gratis sixpack', 2),
]

DEMO_CHAT = [
    ('demo-viewer-1@example.com', 'Proost allemaal! 🍻'),
    ('demo-viewer-4@example.com', 'Wanneer is de eerste trekking?'),
    ('demo-viewer-7@example.com', 'Die hazy IPA wil ik winnen'),
]


class Command(BaseCommand):
    help = 'DEV-ONLY: seed (or clean) a demo livestream + raffles for local rehearsal.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--email',
            help='App account to add as an eligible viewer (watch the PWA with this account)',
        )
        parser.add_argument(
            '--clean', action='store_true',
            help='Delete the demo event and demo users instead of creating them',
        )

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError(
                'seed_demo_livestream only runs with DEBUG=True — it creates '
                'fake users and fake presence and must never touch production.'
            )

        User = get_user_model()

        if options['clean']:
            self._clean(User)
            return

        me = None
        if options['email']:
            me = User.objects.filter(email__iexact=options['email']).first()
            if me is None:
                raise CommandError(f'No user with email {options["email"]}')

        now = timezone.now()
        event, _ = Event.objects.get_or_create(
            title=DEMO_EVENT_TITLE,
            defaults={
                'event_type': 'livestream',
                'scheduled_at': now,
                'status': 'live',
                'youtube_url': DEMO_YOUTUBE_URL,
            },
        )
        if event.status != 'live':
            event.status = 'live'
            event.save(update_fields=['status'])

        # Demo viewers don't poll, so real presence would expire after 90s.
        # A future last_seen_at keeps them raffle-eligible for the whole
        # session; the queryset update bypasses auto_now.
        presence = now + timedelta(hours=4)
        viewer_users = []
        for email, first_name in DEMO_VIEWERS:
            user, _ = User.objects.get_or_create(
                email=email,
                defaults={'username': email, 'first_name': first_name},
            )
            viewer_users.append(user)
            EventViewer.objects.get_or_create(event=event, user=user)
        if me is not None:
            EventViewer.objects.get_or_create(event=event, user=me)
            viewer_users.append(me)
        EventViewer.objects.filter(
            event=event, user__in=viewer_users,
        ).update(last_seen_at=presence)

        for email, message in DEMO_CHAT:
            user = User.objects.get(email=email)
            EventMessage.objects.get_or_create(
                event=event, user=user, message=message,
            )

        # (Re)arm the raffles: a drawn demo raffle goes back to pending, its
        # winners AND their outbox notifications are removed — the dedupe key
        # would otherwise silently swallow the notification on the next draw.
        from notifications.models import NotificationDelivery

        raffle_lines = []
        for prize_name, num_winners in DEMO_RAFFLES:
            raffle, _ = Raffle.objects.get_or_create(
                event=event, prize_name=prize_name,
                defaults={'num_winners': num_winners},
            )
            if raffle.status == 'drawn':
                raffle.winners.all().delete()
                raffle.status = 'pending'
                raffle.drawn_at = None
                raffle.save(update_fields=['status', 'drawn_at'])
            NotificationDelivery.objects.filter(
                dedupe_key__startswith=f'event-raffle:{raffle.id}:'
            ).delete()
            raffle_lines.append(f'  #{raffle.id}  {prize_name} ({num_winners} winnaar(s))')

        self.stdout.write(self.style.SUCCESS(
            f'Demo livestream ready: event #{event.id} is LIVE with '
            f'{event.active_viewer_count()} active viewers.'
        ))
        self.stdout.write('Pending raffles:')
        for line in raffle_lines:
            self.stdout.write(line)
        self.stdout.write(
            f'Watch: PWA -> Community -> livestream (eventId={event.id}); '
            'draw via /admin/events/raffle/ -> "Draw winners".'
        )
        self.stdout.write('Clean up with: python manage.py seed_demo_livestream --clean')

    def _clean(self, User):
        from notifications.models import NotificationDelivery

        raffle_ids = list(
            Raffle.objects.filter(event__title=DEMO_EVENT_TITLE)
            .values_list('id', flat=True)
        )
        for raffle_id in raffle_ids:
            NotificationDelivery.objects.filter(
                dedupe_key__startswith=f'event-raffle:{raffle_id}:'
            ).delete()
        deleted, _ = Event.objects.filter(title=DEMO_EVENT_TITLE).delete()
        users_deleted, _ = User.objects.filter(
            email__startswith='demo-viewer-'
        ).delete()
        self.stdout.write(self.style.SUCCESS(
            f'Demo data removed ({deleted} event objects, '
            f'{users_deleted} demo-user objects).'
        ))
