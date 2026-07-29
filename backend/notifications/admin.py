from django.conf import settings
from django.contrib import admin, messages
from django.db import models
from django.utils import timezone

from .models import (Broadcast, NotificationDelivery, NotificationKindSetting,
                     NotificationPreference, PushSubscription)


@admin.register(NotificationKindSetting)
class NotificationKindSettingAdmin(admin.ModelAdmin):
    """How each type of notification is delivered. The email tickbox here is
    what stops every push also generating an email."""

    list_display = ['get_kind_display', 'send_push', 'send_email',
                    'email_only_if_push_failed', 'summary', 'updated_at']
    list_editable = ['send_push', 'send_email', 'email_only_if_push_failed']
    readonly_fields = ['updated_at']

    def summary(self, obj):
        return obj.email_policy_label
    summary.short_description = 'Result'

    def has_add_permission(self, request):
        # One row per known kind, created by migration. Adding a kind the code
        # does not send would be misleading.
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        self._flush()

    def save_related(self, request, form, formsets, change):
        super().save_related(request, form, formsets, change)
        self._flush()

    def _flush(self):
        # Settings are cached for a minute; drop it so an edit applies at once.
        from .services import invalidate_kind_settings_cache
        invalidate_kind_settings_cache()


@admin.register(PushSubscription)
class PushSubscriptionAdmin(admin.ModelAdmin):
    list_display = ['user_email', 'device_label', 'endpoint_preview', 'is_active',
                    'failure_count', 'last_success_at', 'last_seen_at', 'created_at']
    list_filter = ['is_active', 'created_at']
    search_fields = ['user__email', 'device_label', 'endpoint']
    readonly_fields = ['user', 'endpoint', 'p256dh', 'auth', 'failure_count',
                       'last_success_at', 'last_seen_at', 'deactivated_at', 'created_at']
    ordering = ['-created_at']
    actions = ['send_test_push', 'deactivate_subscriptions']

    def user_email(self, obj):
        return obj.user.email
    user_email.short_description = 'User'

    def endpoint_preview(self, obj):
        return obj.endpoint[:60] + '...' if len(obj.endpoint) > 60 else obj.endpoint
    endpoint_preview.short_description = 'Endpoint'

    @admin.action(description='Send a test push to selected devices')
    def send_test_push(self, request, queryset):
        """
        Push straight to one device, bypassing preferences and the outbox.

        This answers "is this specific device reachable?" — useful when a
        subscription looks alive but nothing arrives. To test the whole
        pipeline (preferences, policy, email fallback) instead, use the
        "Send a test notification" action on Users.
        """
        import json

        from .services import _push_to_subscription

        if not settings.VAPID_PRIVATE_KEY:
            self.message_user(
                request,
                'VAPID keys are not configured, so no push can be sent. '
                'Generate a pair with `vapid --gen` and set VAPID_PRIVATE_KEY '
                'and VAPID_PUBLIC_KEY.',
                level=messages.ERROR,
            )
            return

        payload = json.dumps({
            'title': 'House of Beers test',
            'body': 'If you can read this, push notifications are working.',
            'url': '/',
        })

        delivered, failed = 0, []
        for subscription in queryset:
            error = _push_to_subscription(subscription, payload)
            if error is None:
                delivered += 1
            else:
                failed.append(f"{subscription.device_label or subscription.id}: {error}")

        if delivered:
            self.message_user(request, f"Test push delivered to {delivered} device(s).")
        if failed:
            self.message_user(
                request,
                'Failed: ' + '; '.join(failed),
                level=messages.WARNING,
            )

    def has_add_permission(self, request):
        # Subscriptions only ever come from the browser's subscribe flow.
        return False

    @admin.action(description='Deactivate selected subscriptions')
    def deactivate_subscriptions(self, request, queryset):
        updated = queryset.filter(is_active=True).update(
            is_active=False, deactivated_at=timezone.now(),
        )
        self.message_user(request, f"Deactivated {updated} subscription(s).")


@admin.register(NotificationPreference)
class NotificationPreferenceAdmin(admin.ModelAdmin):
    list_display = ['user_email', 'push_enabled', 'email_enabled',
                    'birthday', 'announcements', 'recommendations', 'updated_at']
    list_filter = ['push_enabled', 'email_enabled', 'birthday',
                   'announcements', 'recommendations']
    search_fields = ['user__email']
    readonly_fields = ['user', 'created_at', 'updated_at']
    ordering = ['-updated_at']

    def user_email(self, obj):
        return obj.user.email
    user_email.short_description = 'User'

    def has_add_permission(self, request):
        # Created on demand by NotificationPreference.for_user().
        return False


@admin.register(NotificationDelivery)
class NotificationDeliveryAdmin(admin.ModelAdmin):
    """Read-only: the delivery table is an audit trail, not an editing surface."""

    list_display = ['user_email', 'kind', 'title', 'push_status', 'email_status',
                    'email_policy_display', 'created_at', 'sent_at']
    list_filter = ['kind', 'push_status', 'email_status', 'email_policy', 'created_at']
    search_fields = ['user__email', 'title', 'dedupe_key']
    readonly_fields = ['user', 'kind', 'title', 'body', 'data', 'dedupe_key',
                       'email_policy', 'push_status', 'push_error',
                       'email_status', 'email_error', 'created_at', 'sent_at']
    ordering = ['-created_at']
    actions = ['retry_failed']

    @admin.action(description='Retry sending (only rows where a channel failed)')
    def retry_failed(self, request, queryset):
        """
        Re-run delivery for rows where a channel failed.

        `send_notification` short-circuits on `sent_at`, so a message that
        failed both channels — an SMTP outage, say — would otherwise be dead
        forever. Clearing `sent_at` lets the same dedupe_key run again;
        anything that already succeeded is left alone so a retry cannot
        double-send to a channel that worked.
        """
        from .services import send_notification

        candidates = queryset.filter(
            models.Q(push_status='failed') | models.Q(email_status='failed')
        )
        skipped = queryset.count() - candidates.count()

        retried, still_failing = 0, 0
        for delivery in candidates:
            delivery.sent_at = None
            delivery.save(update_fields=['sent_at'])
            result = send_notification(
                delivery.user,
                kind=delivery.kind,
                title=delivery.title,
                body=delivery.body,
                data=delivery.data,
                dedupe_key=delivery.dedupe_key,
                email_policy=delivery.email_policy or None,
            )
            retried += 1
            if 'failed' in (result.push_status, result.email_status):
                still_failing += 1

        if retried:
            self.message_user(
                request,
                f"Retried {retried} delivery(ies); {still_failing} still failing.",
                level=messages.WARNING if still_failing else messages.INFO,
            )
        if skipped:
            self.message_user(
                request,
                f"Skipped {skipped} row(s) with nothing in a failed state.",
            )

    def user_email(self, obj):
        return obj.user.email
    user_email.short_description = 'User'

    def email_policy_display(self, obj):
        """Show which policy actually applied, not just the override."""
        if obj.email_policy:
            return f"{obj.get_email_policy_display()} (override)"
        from .services import DEFAULT_KIND_POLICY, KIND_POLICY
        return f"{KIND_POLICY.get(obj.kind, DEFAULT_KIND_POLICY)} (kind default)"
    email_policy_display.short_description = 'Email policy'

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(Broadcast)
class BroadcastAdmin(admin.ModelAdmin):
    """
    Write a message, choose who gets it, send now or schedule it.

    Sending is queued to a background worker rather than done in this request:
    a few hundred pushes and emails would take far longer than a web request
    is allowed to run.
    """

    list_display = ['title', 'kind', 'audience', 'status', 'scheduled_for',
                    'delivery_summary', 'created_at']
    list_filter = ['status', 'kind', 'audience', 'created_at']
    search_fields = ['title', 'body']
    filter_horizontal = ['recipients']
    date_hierarchy = 'created_at'
    actions = ['queue_selected', 'send_test_to_myself']

    fieldsets = (
        ('Message', {
            'fields': ('title', 'body', 'url', 'kind'),
        }),
        ('Who gets it', {
            'fields': ('audience', 'recipients'),
            'description': 'Recipients are worked out when the message is '
                           'actually sent, so a scheduled message reaches '
                           'whoever qualifies at that moment.'
        }),
        ('When', {
            'fields': ('scheduled_for', 'send_now'),
            'description': 'To send straight away: leave the time empty and '
                           'tick "Send now". To schedule: set a time and tick '
                           '"Send now" - it will go out then.'
        }),
        ('Result', {
            'fields': ('status', 'recipient_count', 'push_sent_count',
                       'email_sent_count', 'sent_at', 'error', 'created_by'),
            'classes': ('collapse',),
        }),
    )

    def get_readonly_fields(self, request, obj=None):
        base = ['status', 'recipient_count', 'push_sent_count',
                'email_sent_count', 'sent_at', 'error', 'created_by']
        if obj and not obj.is_editable:
            # Editing an already-sent message would misrepresent what went out.
            return base + ['title', 'body', 'url', 'kind', 'audience',
                           'recipients', 'scheduled_for', 'send_now']
        return base

    def delivery_summary(self, obj):
        if obj.status != Broadcast.STATUS_SENT:
            return '-'
        return (f"{obj.recipient_count} recipients / "
                f"{obj.push_sent_count} push / {obj.email_sent_count} email")
    delivery_summary.short_description = 'Delivered'

    def save_model(self, request, obj, form, change):
        if not obj.created_by_id:
            obj.created_by = request.user

        queue_it = obj.send_now and obj.is_editable
        if queue_it:
            obj.status = (Broadcast.STATUS_SCHEDULED if obj.scheduled_for
                          else Broadcast.STATUS_DRAFT)
        super().save_model(request, obj, form, change)

        if not queue_it:
            return

        if obj.scheduled_for:
            self.message_user(
                request,
                f'"{obj.title}" is scheduled for '
                f'{timezone.localtime(obj.scheduled_for):%d %b %Y %H:%M}. '
                f'It will be sent automatically.',
            )
        else:
            # M2M recipients are not saved yet at this point, so the actual
            # dispatch happens in save_related below.
            self._queue_after_save = obj.pk

    def save_related(self, request, form, formsets, change):
        super().save_related(request, form, formsets, change)
        pk = getattr(self, '_queue_after_save', None)
        if pk is None:
            return
        self._queue_after_save = None

        from .tasks import send_broadcast
        obj = Broadcast.objects.get(pk=pk)
        count = obj.resolve_recipients().count()
        send_broadcast.delay(pk)
        self.message_user(
            request,
            f'"{obj.title}" queued for {count} recipient(s). '
            f'Refresh in a moment to see the result.',
        )

    @admin.action(description='Send selected messages now')
    def queue_selected(self, request, queryset):
        from .tasks import send_broadcast

        queued, skipped = 0, 0
        for broadcast in queryset:
            if not broadcast.is_editable:
                skipped += 1
                continue
            send_broadcast.delay(broadcast.pk)
            queued += 1

        if queued:
            self.message_user(request, f"Queued {queued} message(s) for sending.")
        if skipped:
            self.message_user(
                request,
                f"Skipped {skipped} already sent or in progress.",
                level=messages.WARNING,
            )

    @admin.action(description='Send a preview to myself only')
    def send_test_to_myself(self, request, queryset):
        """
        Check wording and the deep link before it reaches customers.

        Bypasses the audience entirely and delivers only to the admin running
        it, with its own dedupe key so the real send is unaffected.
        """
        from .services import send_notification

        stamp = timezone.now().strftime('%Y%m%d%H%M%S')
        for broadcast in queryset:
            delivery = send_notification(
                request.user,
                kind=broadcast.kind,
                title=broadcast.title,
                body=broadcast.body,
                data={'url': broadcast.url or '/'},
                dedupe_key=f'broadcast-preview:{broadcast.pk}:{request.user.pk}:{stamp}',
            )
            self.message_user(
                request,
                f'Preview of "{broadcast.title}" to {request.user.email}: '
                f'push={delivery.push_status}, email={delivery.email_status}',
            )
