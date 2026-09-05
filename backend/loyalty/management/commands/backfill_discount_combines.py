"""
Make already-minted discount codes combinable.

Until we started sending `combinesWith`, Shopify defaulted every code we
created to "cannot be used together with any other discount" — which is why
members reported not being able to use two of our codes in one order. New
codes are fixed at the source (users.services.shopify.COMBINES_WITH_ALL);
this command repairs the ones already in members' hands.

The flag lives on the Shopify discount, not on our row, so there is nothing
to write locally and nothing to make idempotent: re-running just sets the
same value again.

Only codes that could still be used are touched — expired and already-used
codes are skipped, which keeps this to a couple of Shopify calls per code.

    python manage.py backfill_discount_combines            # dry run
    python manage.py backfill_discount_combines --apply
"""
from django.core.management.base import BaseCommand
from django.db.models import Q
from django.utils import timezone

from loyalty.models import (
    BirthdayReward, CampaignAward, CampaignRaffleWinner, Redemption,
)


class Command(BaseCommand):
    help = "Set combinesWith on discount codes minted before the field was sent"

    def add_arguments(self, parser):
        parser.add_argument(
            '--apply', action='store_true',
            help="Send the updates to Shopify (default is a dry run)",
        )

    def _rows(self):
        """(label, code) for every code a member could still redeem."""
        now = timezone.now()
        unexpired = Q(expires_at__isnull=True) | Q(expires_at__gt=now)

        rows = []

        for r in (Redemption.objects
                  .exclude(discount_code='')
                  .filter(unexpired, discount_code_used=False)):
            rows.append((f"Redemption {r.pk}", r.discount_code))

        for b in (BirthdayReward.objects
                  .exclude(discount_code='')
                  .filter(unexpired)):
            rows.append((f"BirthdayReward {b.pk}", b.discount_code))

        # CampaignAward carries no expiry of its own (the campaign's
        # discount_validity_days sets it Shopify-side), so take them all.
        for a in CampaignAward.objects.exclude(discount_code=''):
            rows.append((f"CampaignAward {a.pk}", a.discount_code))

        for w in (CampaignRaffleWinner.objects
                  .exclude(prize_code='')
                  .filter(redeemed_at__isnull=True)
                  .filter(Q(code_expires_at__isnull=True)
                          | Q(code_expires_at__gt=now))):
            rows.append((f"CampaignRaffleWinner {w.pk}", w.prize_code))

        # Sixpack codes are deliberately absent: they expire within days, so
        # by the time this runs there is nothing live left to repair.
        return rows

    def handle(self, *args, **options):
        apply_changes = options['apply']
        rows = self._rows()

        if not rows:
            self.stdout.write("No live codes to update.")
            return

        if not apply_changes:
            for label, code in rows:
                self.stdout.write(f"  {label}: {code}")
            self.stdout.write(self.style.SUCCESS(
                f"Would update {len(rows)} code(s)."
            ))
            self.stdout.write("Dry run - pass --apply to send to Shopify.")
            return

        from users.services import ShopifyService
        service = ShopifyService()

        counts = {'updated': 0, 'not_found': 0, 'failed': 0}
        for label, code in rows:
            status = service.set_discount_combines_with(code)
            counts[status] = counts.get(status, 0) + 1

            line = f"  {label}: {code} -> {status}"
            if status == 'updated':
                self.stdout.write(line)
            else:
                self.stdout.write(self.style.WARNING(line))

        self.stdout.write(self.style.SUCCESS(
            f"Updated {counts['updated']} of {len(rows)} code(s) "
            f"({counts['not_found']} not in Shopify, {counts['failed']} failed)."
        ))
