from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Sync loyalty points from Shopify orders (partial, intermediate, or full)'

    def add_arguments(self, parser):
        parser.add_argument(
            '--type',
            type=str,
            default='partial',
            choices=['partial', 'intermediate', 'full'],
            help='Sync type: partial (new orders only), intermediate (all orders, process unprocessed), '
                 'full (check-and-correct all orders)',
        )
        parser.add_argument(
            '--email',
            type=str,
            help='Sync a specific user by email',
        )
        parser.add_argument(
            '--async',
            action='store_true',
            dest='use_async',
            help='Dispatch as Celery tasks instead of running inline',
        )

    def handle(self, *args, **options):
        from users.models import User

        sync_type = options['type']
        use_async = options['use_async']

        if options['email']:
            self._sync_single_user(options['email'], sync_type, use_async)
            return

        # Sync all users with Shopify accounts
        users = User.objects.filter(
            shopify_customer_id__isnull=False
        ).exclude(shopify_customer_id='')

        count = users.count()
        self.stdout.write(f"Starting {sync_type} sync for {count} users...")

        if use_async:
            from loyalty.tasks import (
                partial_sync_user_points, intermediate_sync_user_points, full_sync_user_points
            )
            task_map = {
                'partial': partial_sync_user_points,
                'intermediate': intermediate_sync_user_points,
                'full': full_sync_user_points,
            }
            task = task_map[sync_type]
            for i, user in enumerate(users):
                task.apply_async(args=[user.id], countdown=i * 2)
            self.stdout.write(
                self.style.SUCCESS(f"Dispatched {sync_type} sync tasks for {count} users")
            )
            return

        # Run inline
        from loyalty.services import LoyaltyService
        service = LoyaltyService()
        success_count = 0
        error_count = 0

        sync_method = {
            'partial': service.partial_sync_for_user,
            'intermediate': service.intermediate_sync_for_user,
            'full': service.full_sync_for_user,
        }[sync_type]

        for user in users:
            result = sync_method(user)

            if result.get('success'):
                if sync_type == 'full':
                    self.stdout.write(
                        f"  {user.email}: net {result.get('net_adjustment', 0):+d} points "
                        f"({result.get('corrected_count', 0)} corrected, "
                        f"{result.get('new_count', 0)} new)"
                    )
                else:
                    self.stdout.write(
                        f"  {user.email}: +{result.get('total_awarded', 0)} points "
                        f"({result.get('processed_count', 0)} orders)"
                    )
                success_count += 1
            else:
                self.stdout.write(
                    self.style.WARNING(f"  {user.email}: {result.get('error', 'Unknown error')}")
                )
                error_count += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Sync complete: {success_count} succeeded, {error_count} failed"
            )
        )

    def _sync_single_user(self, email, sync_type, use_async):
        from users.models import User

        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            self.stdout.write(self.style.ERROR(f"User not found: {email}"))
            return

        if not user.shopify_customer_id:
            self.stdout.write(self.style.ERROR(f"User {email} has no Shopify account linked"))
            return

        if use_async:
            from loyalty.tasks import (
                partial_sync_user_points, intermediate_sync_user_points, full_sync_user_points
            )
            task_map = {
                'partial': partial_sync_user_points,
                'intermediate': intermediate_sync_user_points,
                'full': full_sync_user_points,
            }
            task_map[sync_type].delay(user.id)
            self.stdout.write(
                self.style.SUCCESS(f"Dispatched {sync_type} sync task for {email}")
            )
            return

        from loyalty.services import LoyaltyService
        service = LoyaltyService()

        sync_method = {
            'partial': service.partial_sync_for_user,
            'intermediate': service.intermediate_sync_for_user,
            'full': service.full_sync_for_user,
        }[sync_type]

        result = sync_method(user)

        if result.get('success'):
            if sync_type == 'full':
                self.stdout.write(
                    self.style.SUCCESS(
                        f"{sync_type.title()} sync for {email}: "
                        f"net {result.get('net_adjustment', 0):+d} points, "
                        f"{result.get('corrected_count', 0)} corrected, "
                        f"{result.get('new_count', 0)} new, "
                        f"balance: {result.get('new_balance', 0)}"
                    )
                )
            else:
                self.stdout.write(
                    self.style.SUCCESS(
                        f"{sync_type.title()} sync for {email}: "
                        f"+{result.get('total_awarded', 0)} points from "
                        f"{result.get('processed_count', 0)} orders, "
                        f"balance: {result.get('new_balance', 0)}"
                    )
                )
        else:
            self.stdout.write(
                self.style.ERROR(f"Sync failed for {email}: {result.get('error')}")
            )
