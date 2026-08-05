"""
One-off repair for loyalty history and lifetime counters.

Historical full syncs appended negative "Points correction" transactions and
counted them into lifetime_spent, so users who never redeemed anything saw
large "spent" totals. This command:

1. Folds correction rows (adjusted transactions with a shopify_order_id) into
   the original earned transaction for that order, which is set to the current
   ProcessedOrder.points_awarded, then deletes the correction rows.
2. Recomputes lifetime_spent as the sum of non-cancelled redemptions.
3. Recomputes lifetime_earned from earned transactions plus manual admin
   adjustments (adjusted rows with no order and no reward).
4. Rewrites balance_after chronologically and sets the balance to the final
   running total.
5. Verifies balance == lifetime_earned - lifetime_spent for every user.

Dry-run by default: all changes run inside a transaction that is rolled back
unless --apply is passed, so the printed report always matches what apply
would do.

Usage:
    python manage.py repair_loyalty_history              # dry-run, all users
    python manage.py repair_loyalty_history --apply      # write changes
    python manage.py repair_loyalty_history --email user@example.com
"""
from collections import defaultdict

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction

from loyalty.models import (
    PointsBalance, PointsTransaction, ProcessedOrder, Redemption
)

User = get_user_model()


class Command(BaseCommand):
    help = "Fold correction transactions into earned rows and repair lifetime counters"

    def add_arguments(self, parser):
        parser.add_argument('--email', type=str, help='Repair a single user by email')
        parser.add_argument(
            '--apply', action='store_true',
            help='Write changes (default is dry-run with rollback)'
        )

    def handle(self, *args, **options):
        apply_changes = options['apply']

        if options['email']:
            users = User.objects.filter(email=options['email'])
            if not users.exists():
                self.stderr.write(f"No user found with email {options['email']}")
                return
        else:
            users = User.objects.filter(points_transactions__isnull=False).distinct()

        mode = 'APPLY' if apply_changes else 'DRY-RUN'
        self.stdout.write(f"=== Loyalty history repair ({mode}) — {users.count()} user(s) ===\n")

        mismatches = []
        changed = 0

        for user in users.iterator():
            with transaction.atomic():
                report = self._repair_user(user)
                if not apply_changes:
                    transaction.set_rollback(True)

            if report['folded'] or report['before'] != report['after']:
                changed += 1
                self.stdout.write(
                    f"{user.email}: folded {report['folded']} correction(s), "
                    f"deleted {report['deleted_earned']} empty earned row(s)\n"
                    f"  balance:         {report['before'][0]:>6} -> {report['after'][0]:>6}\n"
                    f"  lifetime_earned: {report['before'][1]:>6} -> {report['after'][1]:>6}\n"
                    f"  lifetime_spent:  {report['before'][2]:>6} -> {report['after'][2]:>6}"
                )
            if not report['invariant_ok']:
                mismatches.append(user.email)
                self.stdout.write(self.style.WARNING(
                    f"  WARNING {user.email}: balance != earned - spent after repair"
                ))

        self.stdout.write(f"\n{changed} user(s) with changes.")
        if mismatches:
            self.stdout.write(self.style.WARNING(
                f"Invariant mismatches for: {', '.join(mismatches)}"
            ))
        else:
            self.stdout.write("Invariant balance == earned - spent holds for all users.")
        if not apply_changes:
            self.stdout.write("Dry-run only — re-run with --apply to write changes.")

    def _repair_user(self, user):
        balance, _ = PointsBalance.objects.get_or_create(user=user)
        before = (balance.balance, balance.lifetime_earned, balance.lifetime_spent)

        # 1. Fold correction rows into the earned row per order
        corrections = PointsTransaction.objects.filter(
            user=user,
            transaction_type='adjusted',
            reward__isnull=True,
        ).exclude(shopify_order_id='')

        by_order = defaultdict(list)
        for txn in corrections:
            by_order[txn.shopify_order_id].append(txn)

        folded = 0
        deleted_earned = 0
        for order_id, txns in by_order.items():
            earned = PointsTransaction.objects.filter(
                user=user, transaction_type='earned', shopify_order_id=order_id
            ).first()
            processed = ProcessedOrder.objects.filter(shopify_order_id=order_id).first()

            if processed:
                target = processed.points_awarded
            else:
                # No ProcessedOrder record — reconstruct from the rows themselves
                target = (earned.points if earned else 0) + sum(t.points for t in txns)

            order_name = (
                processed.shopify_order_name if processed
                else (earned.shopify_order_name if earned else txns[0].shopify_order_name)
            )

            if target <= 0:
                if earned:
                    earned.delete()
                    deleted_earned += 1
            elif earned:
                earned.points = target
                earned.description = f"Points earned from order {order_name}"
                earned.save(update_fields=['points', 'description'])
            else:
                new_txn = PointsTransaction.objects.create(
                    user=user,
                    transaction_type='earned',
                    points=target,
                    balance_after=0,  # rewritten below
                    description=f"Points earned from order {order_name}",
                    shopify_order_id=order_id,
                    shopify_order_name=order_name,
                )
                if processed:
                    PointsTransaction.objects.filter(pk=new_txn.pk).update(
                        created_at=processed.processed_at
                    )

            for txn in txns:
                txn.delete()
                folded += 1

        # 2. Recompute lifetime counters from source data
        lifetime_spent = sum(
            Redemption.objects.filter(user=user)
            .exclude(status='cancelled')
            .values_list('points_spent', flat=True)
        )
        earned_total = sum(
            PointsTransaction.objects.filter(user=user, transaction_type='earned')
            .values_list('points', flat=True)
        )
        manual_adjustments = sum(
            PointsTransaction.objects.filter(
                user=user, transaction_type='adjusted',
                reward__isnull=True, shopify_order_id=''
            ).values_list('points', flat=True)
        )
        lifetime_earned = earned_total + manual_adjustments

        # 3. Rewrite balance_after chronologically; final total is the balance
        running = 0
        for txn in PointsTransaction.objects.filter(user=user).order_by('created_at'):
            running += txn.points
            if txn.balance_after != running:
                txn.balance_after = running
                txn.save(update_fields=['balance_after'])

        balance.balance = running
        balance.lifetime_earned = lifetime_earned
        balance.lifetime_spent = lifetime_spent
        balance.save()

        return {
            'folded': folded,
            'deleted_earned': deleted_earned,
            'before': before,
            'after': (balance.balance, balance.lifetime_earned, balance.lifetime_spent),
            'invariant_ok': running == lifetime_earned - lifetime_spent,
        }
