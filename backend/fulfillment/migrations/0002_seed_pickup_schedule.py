# Seed the store's pickup days: Prior van Millstraat 2, Uden is open for
# pickups on Friday 10:00-20:00 and Saturday 10:00-17:00 (closed Mon-Thu).
from datetime import time

from django.db import migrations

SEED = [
    (4, time(10, 0), time(20, 0)),  # Friday
    (5, time(10, 0), time(17, 0)),  # Saturday
]


def seed_schedules(apps, schema_editor):
    PickupSchedule = apps.get_model('fulfillment', 'PickupSchedule')
    for weekday, open_time, close_time in SEED:
        PickupSchedule.objects.get_or_create(
            weekday=weekday,
            defaults={'open_time': open_time, 'close_time': close_time, 'active': True},
        )


def unseed_schedules(apps, schema_editor):
    PickupSchedule = apps.get_model('fulfillment', 'PickupSchedule')
    PickupSchedule.objects.filter(weekday__in=[w for w, _, _ in SEED]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('fulfillment', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(seed_schedules, unseed_schedules),
    ]
