from django.db import migrations
from django.db.models import Count
from django.db.models.functions import Lower


def lowercase_emails(apps, schema_editor):
    """
    Lowercase email + username for existing users, skipping accounts whose
    lowercased email would collide with another account (legacy case-duplicate
    pairs like Foo@x.com / foo@x.com — those are left for a manual merge).
    """
    User = apps.get_model('users', 'User')

    duplicate_keys = set(
        User.objects.annotate(lower_email=Lower('email'))
        .values('lower_email')
        .annotate(n=Count('id'))
        .filter(n__gt=1)
        .values_list('lower_email', flat=True)
    )

    for user in User.objects.all().iterator():
        new_email = user.email.lower()
        new_username = user.username.lower()
        if new_email == user.email and new_username == user.username:
            continue
        if new_email in duplicate_keys:
            continue
        if User.objects.exclude(pk=user.pk).filter(username=new_username).exists():
            continue
        User.objects.filter(pk=user.pk).update(
            email=new_email, username=new_username
        )


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0003_user_last_active_at'),
    ]

    operations = [
        migrations.RunPython(lowercase_emails, migrations.RunPython.noop),
    ]
