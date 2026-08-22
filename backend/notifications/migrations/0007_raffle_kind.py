# Adds the 'raffle' notification kind (campaign draw results, reminders) and
# the matching per-user category opt-out. The seeded kind setting mirrors
# KIND_POLICY: push yes, email only as fallback (a winner's prize code is
# forced to email per-message via email_policy='always').
from django.db import migrations, models


def seed_raffle_kind(apps, schema_editor):
    NotificationKindSetting = apps.get_model('notifications', 'NotificationKindSetting')
    NotificationKindSetting.objects.update_or_create(
        kind='raffle',
        defaults={
            'send_push': True,
            'send_email': True,
            'email_only_if_push_failed': True,
        },
    )


def unseed_raffle_kind(apps, schema_editor):
    NotificationKindSetting = apps.get_model('notifications', 'NotificationKindSetting')
    NotificationKindSetting.objects.filter(kind='raffle').delete()


class Migration(migrations.Migration):

    dependencies = [
        ('notifications', '0006_alter_notificationpreference_email_enabled'),
    ]

    operations = [
        migrations.AddField(
            model_name='notificationpreference',
            name='raffle',
            field=models.BooleanField(default=True),
        ),
        migrations.AlterField(
            model_name='notificationdelivery',
            name='kind',
            field=models.CharField(choices=[('birthday_gift', 'Birthday Gift'), ('announcement', 'Announcement'), ('recommendations', 'Recommendations'), ('transactional', 'Transactional'), ('raffle', 'Raffle')], max_length=50),
        ),
        migrations.AlterField(
            model_name='notificationkindsetting',
            name='kind',
            field=models.CharField(choices=[('birthday_gift', 'Birthday gift'), ('announcement', 'Announcement'), ('recommendations', 'Beer recommendations'), ('transactional', 'Transactional (orders, rewards)'), ('raffle', 'Raffle (campaigns & draws)')], max_length=50, unique=True),
        ),
        migrations.AlterField(
            model_name='broadcast',
            name='kind',
            field=models.CharField(choices=[('birthday_gift', 'Birthday gift'), ('announcement', 'Announcement'), ('recommendations', 'Beer recommendations'), ('transactional', 'Transactional (orders, rewards)'), ('raffle', 'Raffle (campaigns & draws)')], default='announcement', help_text='Decides whether an email follows the push - see Notification delivery settings.', max_length=50),
        ),
        migrations.RunPython(seed_raffle_kind, unseed_raffle_kind),
    ]
