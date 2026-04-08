from django.db import migrations, models
import django.utils.timezone


class Migration(migrations.Migration):

    dependencies = [
        ('distribution', '0019_alter_payment_date'),
    ]

    operations = [
        migrations.AlterField(
            model_name='client',
            name='date_added',
            field=models.DateTimeField(default=django.utils.timezone.now, null=True),
        ),
    ]
