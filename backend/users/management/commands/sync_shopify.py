from django.core.management.base import BaseCommand
from users.services import ShopifyService


class Command(BaseCommand):
    help = 'Sync unlinked users with Shopify customers'

    def add_arguments(self, parser):
        parser.add_argument(
            '--all',
            action='store_true',
            help='Resync all users, not just unlinked ones',
        )
        parser.add_argument(
            '--email',
            type=str,
            help='Sync a specific user by email',
        )

    def handle(self, *args, **options):
        from users.models import User

        service = ShopifyService()

        if options['email']:
            # Sync specific user
            try:
                user = User.objects.get(email=options['email'])
                linked = service.resync_user(user)
                if linked:
                    self.stdout.write(
                        self.style.SUCCESS(f"Linked {user.email} to Shopify customer {user.shopify_customer_id}")
                    )
                else:
                    self.stdout.write(
                        self.style.WARNING(f"No Shopify customer found for {user.email}")
                    )
            except User.DoesNotExist:
                self.stdout.write(self.style.ERROR(f"User not found: {options['email']}"))
            return

        if options['all']:
            # Resync all users
            users = User.objects.all()
            self.stdout.write(f"Resyncing all {users.count()} users...")
            for user in users:
                linked = service.resync_user(user)
                status_msg = "linked" if linked else "not found"
                self.stdout.write(f"  {user.email}: {status_msg}")
        else:
            # Sync only unlinked users
            stats = service.sync_all_users()
            self.stdout.write(
                self.style.SUCCESS(
                    f"Sync complete: {stats['processed']} processed, "
                    f"{stats['linked']} linked, {stats['not_found']} not found, "
                    f"{stats['errors']} errors"
                )
            )
