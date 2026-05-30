import logging
from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model

from community.models import CachedBeerCheckin
from recommendations.services import RecommendationService, RecommendationAPIError

User = get_user_model()
logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Sync Untappd check-ins for community members with linked profiles'

    def add_arguments(self, parser):
        parser.add_argument(
            '--user',
            type=str,
            help='Sync only a specific user by email',
        )

    def handle(self, *args, **options):
        queryset = User.objects.filter(
            untappd_profile__isnull=False,
            community_profile__is_visible=True,
        ).select_related('untappd_profile')

        if options['user']:
            queryset = queryset.filter(email=options['user'])

        users = list(queryset)
        self.stdout.write(f"Syncing check-ins for {len(users)} user(s)...")

        service = RecommendationService()
        synced = 0
        errors = 0

        for user in users:
            try:
                result = service.get_recommendations(
                    username=user.untappd_profile.username
                )
                tried_beers = result.get('tried_beers', [])

                for entry in tried_beers:
                    beer = entry.get('beer', entry)
                    if not beer.get('title'):
                        continue

                    CachedBeerCheckin.objects.update_or_create(
                        user=user,
                        beer_title=beer['title'],
                        defaults={
                            'beer_vendor': beer.get('vendor', ''),
                            'beer_style': beer.get('style_category', ''),
                            'beer_abv': beer.get('abv'),
                            'user_rating': beer.get('untappd_rating'),
                        },
                    )

                synced += 1
                self.stdout.write(f"  {user.email}: {len(tried_beers)} beers cached")

            except RecommendationAPIError as e:
                errors += 1
                self.stderr.write(f"  {user.email}: API error - {e}")
            except Exception as e:
                errors += 1
                self.stderr.write(f"  {user.email}: unexpected error - {e}")
                logger.exception(f"Checkin sync failed for {user.email}")

        self.stdout.write(self.style.SUCCESS(
            f"Done. Synced: {synced}, Errors: {errors}"
        ))
