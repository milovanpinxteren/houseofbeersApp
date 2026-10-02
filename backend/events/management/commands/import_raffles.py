"""
Bulk-create raffles on an event from a JSON prize list.

Built for giveaway livestreams with dozens of prizes: entering 37 inline
rows in the admin by hand is error-prone minutes before going live. Dry-run
by default; pass --apply to write. Re-running is idempotent: a prize whose
exact name already exists on the event is skipped.

JSON shape (a list, order = draw order shown in the regie page):
    [
      {"prize": "2000 Punten", "points": 2000},
      {"prize": "Goose Island Bourbon County Pet", "winners": 5},
      {"prize": "King Henry II", "policy": "allow"}
    ]
`winners` defaults to 1, `points` to 0, `policy` to "inherit".

Use --json-b64 on Dokku: `dokku run` strips quotes from arguments, so raw
JSON never survives the trip. Locally --json or --file also work.
    python manage.py import_raffles --event 3 --json-b64 <base64> --apply
"""
import base64
import json

from django.core.management.base import BaseCommand, CommandError

from events.models import Event, Raffle

VALID_POLICIES = {value for value, _ in Raffle.WINNER_POLICY_CHOICES}


class Command(BaseCommand):
    help = 'Bulk-create raffles on an event from a JSON prize list (dry-run by default)'

    def add_arguments(self, parser):
        parser.add_argument('--event', type=int, required=True,
                            help='Event id to attach the raffles to')
        source = parser.add_mutually_exclusive_group(required=True)
        source.add_argument('--json', help='Raw JSON list')
        source.add_argument('--json-b64', help='Base64-encoded JSON list')
        source.add_argument('--file', help='Path to a JSON file')
        parser.add_argument('--apply', action='store_true',
                            help='Actually create the raffles (default: dry-run)')

    def handle(self, *args, **options):
        try:
            event = Event.objects.get(pk=options['event'])
        except Event.DoesNotExist:
            raise CommandError(f"Event {options['event']} does not exist")

        if options['json']:
            raw = options['json']
        elif options['json_b64']:
            try:
                raw = base64.b64decode(options['json_b64']).decode('utf-8')
            except Exception as e:
                raise CommandError(f'Invalid base64: {e}')
        else:
            try:
                with open(options['file'], encoding='utf-8') as f:
                    raw = f.read()
            except OSError as e:
                raise CommandError(f'Cannot read file: {e}')

        try:
            items = json.loads(raw)
        except json.JSONDecodeError as e:
            raise CommandError(f'Invalid JSON: {e}')
        if not isinstance(items, list) or not items:
            raise CommandError('JSON must be a non-empty list')

        existing = set(event.raffles.values_list('prize_name', flat=True))
        to_create, skipped = [], []
        for i, item in enumerate(items, start=1):
            if not isinstance(item, dict) or not str(item.get('prize', '')).strip():
                raise CommandError(f'Item {i}: "prize" is required')
            prize = str(item['prize']).strip()[:200]
            winners = item.get('winners', 1)
            points = item.get('points', 0)
            policy = item.get('policy', 'inherit')
            if not isinstance(winners, int) or winners < 1:
                raise CommandError(f'Item {i} ({prize}): winners must be an int >= 1')
            if not isinstance(points, int) or points < 0:
                raise CommandError(f'Item {i} ({prize}): points must be an int >= 0')
            if policy not in VALID_POLICIES:
                raise CommandError(
                    f'Item {i} ({prize}): policy must be one of {sorted(VALID_POLICIES)}')
            if prize in existing:
                skipped.append(prize)
                continue
            existing.add(prize)
            to_create.append(Raffle(
                event=event, prize_name=prize, num_winners=winners,
                points_award=points, winner_policy=policy,
            ))

        mode = 'APPLY' if options['apply'] else 'DRY-RUN'
        self.stdout.write(f"[{mode}] Event: {event.title} (id={event.pk})")
        for raffle in to_create:
            extra = f' | +{raffle.points_award} punten p.p.' if raffle.points_award else ''
            policy = f' | {raffle.winner_policy}' if raffle.winner_policy != 'inherit' else ''
            self.stdout.write(
                f'  + {raffle.prize_name} ({raffle.num_winners}x){extra}{policy}')
        for prize in skipped:
            self.stdout.write(self.style.WARNING(
                f'  = {prize} (bestaat al op dit event, overgeslagen)'))

        if not options['apply']:
            self.stdout.write(self.style.WARNING(
                f'Dry-run: {len(to_create)} raffle(s) NOT created. '
                'Re-run with --apply.'))
            return

        # Sequential creates (not bulk) so ids follow list order — the regie
        # page shows raffles in id order as the planned rundown.
        for raffle in to_create:
            raffle.save()
        self.stdout.write(self.style.SUCCESS(
            f'{len(to_create)} raffle(s) created, {len(skipped)} skipped. '
            f'Totaal prijzen op dit event: '
            f'{sum(event.raffles.values_list("num_winners", flat=True))}'))
