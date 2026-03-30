# Generated migration to remove invoice-level payment tracking

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('distribution', '0009_siteactivity'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='sale',
            name='payment_status',
        ),
        migrations.RemoveField(
            model_name='sale',
            name='payment_method',
        ),
        migrations.RemoveField(
            model_name='sale',
            name='amount_paid',
        ),
        migrations.RemoveField(
            model_name='sale',
            name='payment_date',
        ),
    ]
