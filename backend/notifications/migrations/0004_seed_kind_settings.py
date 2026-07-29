from django.db import migrations


# Mirrors KIND_POLICY in notifications/services.py, expressed as the two
# checkboxes the admin shows. Seeding these means the admin page is populated
# on first load rather than empty, and behaviour is unchanged until an
# operator edits something.
DEFAULTS = [
    # kind,              send_push, send_email, email_only_if_push_failed
    ('birthday_gift',    True,      True,       False),  # always email: the code matters
    ('announcement',     True,      True,       True),   # email only if push missed
    ('recommendations',  True,      False,      True),   # push only, never email
    ('transactional',    True,      True,       False),  # always email
]


def seed(apps, schema_editor):
    NotificationKindSetting = apps.get_model('notifications', 'NotificationKindSetting')
    for kind, send_push, send_email, only_if_failed in DEFAULTS:
        NotificationKindSetting.objects.update_or_create(
            kind=kind,
            defaults={
                'send_push': send_push,
                'send_email': send_email,
                'email_only_if_push_failed': only_if_failed,
            },
        )


def unseed(apps, schema_editor):
    NotificationKindSetting = apps.get_model('notifications', 'NotificationKindSetting')
    NotificationKindSetting.objects.filter(
        kind__in=[k for k, *_ in DEFAULTS]
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('notifications', '0003_notificationkindsetting'),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]
