"""
Fill `cart_url` on campaign awards / raffle winners minted before the field
existed. One Shopify variant lookup per distinct product, so it is cheap even
across every historical code.

    python manage.py backfill_discount_cart_urls            # dry run
    python manage.py backfill_discount_cart_urls --apply
"""
from django.core.management.base import BaseCommand

from loyalty.models import CampaignAward, CampaignRaffleWinner
from loyalty.services.discounts import build_cart_url


class Command(BaseCommand):
    help = "Backfill cart_url on existing campaign discount codes and prize codes"

    def add_arguments(self, parser):
        parser.add_argument(
            '--apply', action='store_true',
            help="Write the URLs (default is a dry run)",
        )

    def handle(self, *args, **options):
        apply_changes = options['apply']
        from users.services import ShopifyService
        service = ShopifyService()

        awards = (
            CampaignAward.objects
            .exclude(discount_code='')
            .filter(cart_url='')
            .select_related('campaign')
        )
        winners = (
            CampaignRaffleWinner.objects
            .exclude(prize_code='')
            .filter(cart_url='')
            .select_related('raffle__campaign')
        )

        rows = (
            [(a, a.campaign, a.discount_code) for a in awards]
            + [(w, w.raffle.campaign, w.prize_code) for w in winners]
        )
        if not rows:
            self.stdout.write("Nothing to backfill.")
            return

        for obj, campaign, code in rows:
            url = build_cart_url(campaign, code, service)
            label = f"{type(obj).__name__} {obj.pk} ({code})"
            if not url:
                self.stdout.write(self.style.WARNING(f"  {label}: no link"))
                continue
            self.stdout.write(f"  {label} -> {url}")
            if apply_changes:
                obj.cart_url = url
                obj.save(update_fields=['cart_url'])

        verb = "Updated" if apply_changes else "Would update"
        self.stdout.write(self.style.SUCCESS(f"{verb} {len(rows)} row(s)."))
        if not apply_changes:
            self.stdout.write("Dry run - pass --apply to write.")
