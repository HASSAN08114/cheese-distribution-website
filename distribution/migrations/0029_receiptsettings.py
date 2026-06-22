from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('distribution', '0028_add_dashboard_composite_indexes'),
    ]

    operations = [
        migrations.CreateModel(
            name='ReceiptSettings',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('company_name', models.CharField(default='Zain Traders', max_length=200)),
                ('phone_number', models.CharField(default='03134628929', max_length=30)),
                ('address', models.TextField(default='')),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'verbose_name': 'Receipt Settings',
                'verbose_name_plural': 'Receipt Settings',
            },
        ),
    ]
