from django.contrib import admin, messages
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.utils import timezone

from .models import User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = ['email', 'first_name', 'last_name', 'shopify_customer_id',
                    'birthdate', 'last_active_at', 'is_active']
    list_filter = BaseUserAdmin.list_filter + ('last_active_at',)
    search_fields = ['email', 'first_name', 'last_name', 'shopify_customer_id']
    ordering = ['-date_joined']
    readonly_fields = ['birthdate_set_at', 'last_active_at']
    actions = ['send_test_notification', 'issue_birthday_gift_now']

    fieldsets = BaseUserAdmin.fieldsets + (
        ('Shopify', {'fields': ('shopify_customer_id', 'shopify_linked_at')}),
        ('Birthday', {
            'fields': ('birthdate', 'birthdate_set_at'),
            'description': 'Editing the birthdate here bypasses the in-app lock, '
                           'which is the intended way to correct a mistake. '
                           '"Set at" deliberately stays unchanged: a correction '
                           'should not restart the anti-abuse waiting period.'
        }),
        ('Activity', {'fields': ('last_active_at',)}),
    )

    @admin.action(description='Send a test notification')
    def send_test_notification(self, request, queryset):
        """
        Exercise the real delivery pipeline for the selected users.

        Deliberately routed through send_notification rather than pushing
        directly, so this proves what production will actually do: it honours
        the user's preferences, applies the per-kind email policy, and falls
        back to email when no device is reachable. Select yourself to check
        your own setup.

        The dedupe key is timestamped so the action can be repeated.
        """
        from notifications.services import send_notification

        stamp = timezone.now().strftime('%Y%m%d%H%M%S')
        results = []
        for user in queryset:
            delivery = send_notification(
                user,
                kind='transactional',
                title='House of Beers test',
                body='If you can read this, notifications are working.',
                data={'url': '/'},
                dedupe_key=f'admin-test:{user.id}:{stamp}',
                email_subject='House of Beers - test notification',
                email_body=(
                    'This is a test notification sent from the admin panel.\n\n'
                    'If you received it, delivery is working.\n\n'
                    'House of Beers'
                ),
            )
            results.append(
                f"{user.email}: push={delivery.push_status}, "
                f"email={delivery.email_status}"
            )

        # Report per channel rather than a bare "sent": push=skipped is the
        # usual reason for silence, and it means no reachable device.
        self.message_user(request, ' | '.join(results))

    @admin.action(description='Issue birthday gift now (ignores date and send hour)')
    def issue_birthday_gift_now(self, request, queryset):
        """
        Force this year's birthday gift, for testing and for goodwill.

        Skips the send-hour window so the flow can be exercised on any day.
        The one-gift-per-year constraint still applies - this cannot hand
        out a second gift.
        """
        from loyalty.models import BirthdayReward, BirthdayRewardConfig
        from loyalty.tasks import _issue_birthday_gift

        config = BirthdayRewardConfig.load()
        year = timezone.localtime().year

        issued, skipped, failed = 0, [], []
        for user in queryset:
            if not user.birthdate:
                skipped.append(f"{user.email}: no birthdate set")
                continue
            if BirthdayReward.objects.filter(user=user, year=year).exists():
                skipped.append(f"{user.email}: already received one in {year}")
                continue
            try:
                if _issue_birthday_gift(user, year, config):
                    issued += 1
                else:
                    skipped.append(f"{user.email}: not issued")
            except Exception as exc:
                failed.append(f"{user.email}: {exc}")

        if issued:
            self.message_user(request, f"Issued {issued} birthday gift(s).")
        if skipped:
            self.message_user(request, 'Skipped - ' + '; '.join(skipped),
                              level=messages.WARNING)
        if failed:
            self.message_user(request, 'Failed - ' + '; '.join(failed),
                              level=messages.ERROR)
