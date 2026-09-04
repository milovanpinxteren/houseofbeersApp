from django.contrib import admin, messages
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.utils import timezone
from django.utils.html import format_html

from .models import SignupCode, User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = ['email', 'first_name', 'last_name', 'shopify_customer_id',
                    'birthdate', 'signup_code', 'last_active_at', 'is_active']
    list_filter = BaseUserAdmin.list_filter + ('last_active_at', 'signup_code')
    search_fields = ['email', 'first_name', 'last_name', 'shopify_customer_id',
                     'signup_code_raw']
    ordering = ['-date_joined']
    readonly_fields = ['birthdate_set_at', 'last_active_at', 'signup_code_raw',
                       'welcome_bonus_awarded_at']
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
        ('Aanmeldcode', {
            'fields': ('signup_code', 'signup_code_raw', 'welcome_bonus_awarded_at'),
            'description': 'De code waarmee dit lid binnenkwam. '
                           '"Raw" is wat er daadwerkelijk is ingevuld — ook '
                           'als die code niet (meer) geldig was. De '
                           'welkomstbonus wordt per lid één keer uitgekeerd; '
                           'de datum hieronder is de garantie daarvoor.'
        }),
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


@admin.register(SignupCode)
class SignupCodeAdmin(admin.ModelAdmin):
    list_display = ['code', 'label', 'points', 'aantal_aanmeldingen',
                    'max_uses', 'is_active', 'valid_until']
    list_filter = ['is_active']
    search_fields = ['code', 'label', 'notes']
    ordering = ['-created_at']
    readonly_fields = ['qr_link', 'aantal_aanmeldingen', 'created_at', 'updated_at']

    fieldsets = (
        (None, {
            'fields': ('code', 'label', 'points'),
            'description': 'De code wordt automatisch in HOOFDLETTERS opgeslagen: '
                           'een QR met "FLYER-UTRECHT" en iemand die '
                           '"flyer-utrecht" intikt zijn dezelfde code.'
        }),
        ('Voor de drukker', {
            'fields': ('qr_link',),
            'description': 'Zet deze URL in de QR-code. Druk de code er in '
                           'gewone letters naast: wie de PWA op iOS aan het '
                           'beginscherm toevoegt, verliest de opgeslagen code '
                           'en moet hem kunnen overtypen.'
        }),
        ('Geldigheid', {
            'fields': ('is_active', 'valid_from', 'valid_until', 'max_uses',
                       'aantal_aanmeldingen')
        }),
        ('Overig', {'fields': ('notes', 'created_at', 'updated_at')}),
    )

    @admin.display(description='Aantal aanmeldingen')
    def aantal_aanmeldingen(self, obj):
        """Members who actually received this code's bonus."""
        if not obj.pk:
            return 0
        return obj.signup_count

    @admin.display(description='QR-URL')
    def qr_link(self, obj):
        """
        The deliverable the printer needs. Rendered in a wide read-only input
        so it can be selected and copied in one go — a plain <p> in the admin
        is fiddly to select without picking up the surrounding label.
        """
        if not obj.pk:
            return '(eerst opslaan)'
        url = obj.qr_url
        return format_html(
            '<input type="text" readonly value="{}" '
            'style="width:32em;font-family:monospace" '
            'onclick="this.select()"> <a href="{}" target="_blank">openen</a>',
            url, url,
        )
