# Data migration: raffles that award points ARE the fulfillment — mark the
# pre-existing rows (e.g. the 2026-10-02 giveaway's 2000/1000/500/100 punten
# prizes) so the fulfillment screen never offers a Shopify handover for them.
from django.db import migrations


def set_points_fulfillment(apps, schema_editor):
    Raffle = apps.get_model('events', 'Raffle')
    Raffle.objects.filter(points_award__gt=0).update(fulfillment_type='points')


def unset_points_fulfillment(apps, schema_editor):
    Raffle = apps.get_model('events', 'Raffle')
    Raffle.objects.filter(points_award__gt=0).update(fulfillment_type='manual')


class Migration(migrations.Migration):

    dependencies = [
        ('events', '0006_auctionitem_brewery_auctionitem_description_and_more'),
    ]

    operations = [
        migrations.RunPython(set_points_fulfillment, unset_points_fulfillment),
    ]
