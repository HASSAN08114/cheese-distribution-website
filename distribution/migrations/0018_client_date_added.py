# Generated migration for adding date_added field to Client model

from django.db import migrations, models
from datetime import datetime
from django.utils import timezone


def populate_date_added(apps, schema_editor):
    """Populate date_added field with January 1st, 2026 for existing clients"""
    Client = apps.get_model('distribution', 'Client')
    default_date = timezone.make_aware(datetime(2026, 1, 1, 0, 0, 0))
    
    for client in Client.objects.filter(date_added__isnull=True):
        client.date_added = default_date
        client.save()


def reverse_populate(apps, schema_editor):
    """Reverse the population (set to NULL)"""
    Client = apps.get_model('distribution', 'Client')
    Client.objects.filter(date_added=timezone.make_aware(datetime(2026, 1, 1, 0, 0, 0))).update(date_added=None)


class Migration(migrations.Migration):

    dependencies = [
        ('distribution', '0017_alter_return_quantity_packets_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='client',
            name='date_added',
            field=models.DateTimeField(auto_now_add=True, null=True),
        ),
        migrations.RunPython(populate_date_added, reverse_populate),
    ]
