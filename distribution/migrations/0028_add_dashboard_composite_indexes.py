from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('distribution', '0027_deliveryexpense_is_voided_and_more'),
    ]

    operations = [
        migrations.AddIndex(
            model_name='sale',
            index=models.Index(fields=['is_voided', 'sale_date'], name='sale_void_date_idx'),
        ),
        migrations.AddIndex(
            model_name='sale',
            index=models.Index(fields=['client', 'is_voided', 'sale_date'], name='sale_client_void_date_idx'),
        ),
        migrations.AddIndex(
            model_name='payment',
            index=models.Index(fields=['is_voided', 'date'], name='payment_void_date_idx'),
        ),
        migrations.AddIndex(
            model_name='payment',
            index=models.Index(fields=['client', 'is_voided', 'date'], name='payment_client_void_date_idx'),
        ),
        migrations.AddIndex(
            model_name='deliveryexpense',
            index=models.Index(fields=['is_voided', 'expense_date'], name='expense_void_date_idx'),
        ),
        migrations.AddIndex(
            model_name='saleitem',
            index=models.Index(fields=['sale', 'cheese_product'], name='saleitem_sale_product_idx'),
        ),
    ]
