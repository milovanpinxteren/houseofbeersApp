"""DEV-ONLY: seed a demo raffle campaign so the PWA cards/reveal can be
tested against a local backend without Shopify.

    python manage.py seed_demo_raffle --email you@example.com          # open raffle, you're entered
    python manage.py seed_demo_raffle --email you@example.com --drawn  # also drawn (reveal testable)
    python manage.py seed_demo_raffle --clean                          # remove all demo data again

Creates an active campaign + open raffle with a handful of demo entrants
(demo-raffle-*@example.com) and an entry for --email so the app shows the
"Je doet mee" card. With --drawn the raffle is drawn on the spot (manual
fulfillment, so no Shopify calls; a fake WIN- code is stamped on the winner).
Pass --win to force your own account to be the winner.

Refuses to run when DEBUG is off: this writes fake users and fake raffles.
"""
import secrets
import string
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from loyalty.models import Campaign, CampaignRaffle, RaffleEntry
from loyalty.services.raffles import draw_raffle

DEMO_CAMPAIGN_NAME = '[DEMO] Oktoberfest verloting'
DEMO_ENTRANTS = [
    ('demo-raffle-1@example.com', 'Daan'),
    ('demo-raffle-2@example.com', 'Sanne'),
    ('demo-raffle-3@example.com', 'Pieter'),
    ('demo-raffle-4@example.com', 'Lotte'),
]


class Command(BaseCommand):
    help = 'DEV-ONLY: seed (or clean) a demo raffle campaign for local UI testing.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--email',
            help='App account that should have an entry (so the PWA shows "Je doet mee")',
        )
        parser.add_argument(
            '--drawn', action='store_true',
            help='Draw the raffle immediately so the reveal screen is testable',
        )
        parser.add_argument(
            '--win', action='store_true',
            help='With --drawn: make --email the winner instead of a random entrant',
        )
        parser.add_argument(
            '--clean', action='store_true',
            help='Delete the demo campaign and demo users instead of creating them',
        )

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError(
                'seed_demo_raffle only runs with DEBUG=True — it creates fake '
                'users and fake raffles and must never touch production.'
            )

        User = get_user_model()

        if options['clean']:
            deleted, _ = Campaign.objects.filter(name=DEMO_CAMPAIGN_NAME).delete()
            users_deleted, _ = User.objects.filter(
                email__startswith='demo-raffle-'
            ).delete()
            self.stdout.write(self.style.SUCCESS(
                f'Demo data removed ({deleted} campaign objects, '
                f'{users_deleted} demo-user objects).'
            ))
            return

        me = None
        if options['email']:
            me = User.objects.filter(email__iexact=options['email']).first()
            if me is None:
                raise CommandError(f'No user with email {options["email"]}')

        now = timezone.now()
        campaign, created = Campaign.objects.get_or_create(
            name=DEMO_CAMPAIGN_NAME,
            defaults={
                'status': 'active',
                'action_type': 'raffle',
                'window_start': now - timedelta(days=14),
                'window_end': now + timedelta(days=14),
                'product_matchers': [
                    {'type': 'title', 'value': 'IPA'},
                    {'type': 'title', 'value': 'Stout'},
                    {'type': 'title', 'value': 'Tripel'},
                ],
                'min_distinct_products': 2,
                'rule_sentence': (
                    'Iedereen die deze maand minstens 2 van deze 3 bieren '
                    'koopt, doet mee in de loting (1 lot per gekocht item).'
                ),
            },
        )
        raffle, _ = CampaignRaffle.objects.get_or_create(
            campaign=campaign,
            defaults={
                'prize_name': 'Magnum fles Westvleteren',
                'prize_description': 'Een magnum om te delen — of niet.',
                'num_winners': 1,
                'entry_mode': 'per_item',
                'fulfillment_type': 'manual',
                'draw_at': now + timedelta(days=2),
            },
        )
        if not created and raffle.status == 'drawn':
            # Re-seeding after a --drawn run: reset to a fresh open raffle.
            raffle.winners.all().delete()
            raffle.status = 'open'
            raffle.drawn_at = None
            raffle.save(update_fields=['status', 'drawn_at'])
            campaign.status = 'active'
            campaign.save(update_fields=['status', 'updated_at'])

        for email, first_name in DEMO_ENTRANTS:
            user, _ = User.objects.get_or_create(
                email=email,
                defaults={'username': email, 'first_name': first_name},
            )
            RaffleEntry.objects.get_or_create(
                raffle=raffle, user=user,
                defaults={
                    'ticket_count': secrets.randbelow(3) + 1,
                    'matched_products': ['Demo IPA', 'Demo Stout'],
                },
            )

        if me is not None:
            RaffleEntry.objects.get_or_create(
                raffle=raffle, user=me,
                defaults={
                    'ticket_count': 3,
                    'matched_products': ['Demo IPA', 'Demo Stout', 'Demo Tripel'],
                },
            )

        if options['drawn']:
            if options['win']:
                if me is None:
                    raise CommandError('--win needs --email')
                # Give yourself overwhelming odds instead of patching the draw.
                RaffleEntry.objects.filter(raffle=raffle, user=me).update(
                    ticket_count=10_000
                )
            winners = draw_raffle(raffle)
            if winners:
                code = 'WIN-' + ''.join(
                    secrets.choice(string.ascii_uppercase + string.digits)
                    for _ in range(8)
                )
                winner = winners[0]
                winner.prize_code = code
                winner.code_expires_at = now + timedelta(days=30)
                winner.fulfillment_status = 'code_issued'
                winner.save(update_fields=[
                    'prize_code', 'code_expires_at', 'fulfillment_status',
                ])
                self.stdout.write(
                    f'Drawn — winner: {winner.user.email} (code {code})'
                )
            if options['win']:
                RaffleEntry.objects.filter(raffle=raffle, user=me).update(
                    ticket_count=3
                )

        self.stdout.write(self.style.SUCCESS(
            f'Demo raffle ready (campaign #{campaign.id}, raffle #{raffle.id}, '
            f'status {raffle.status}). Open the PWA Home or Loyalty tab'
            + (f' as {me.email}' if me else '') + '.'
        ))
        self.stdout.write('Clean up with: python manage.py seed_demo_raffle --clean')
