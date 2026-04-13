# Generated migration for performance optimization
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('distribution', '0020_alter_client_date_added'),
    ]

    operations = [
        # Sale model indexes
        migrations.AddIndex(
            model_name='sale',
            index=models.Index(fields=['client', 'sale_date'], name='sale_client_date_idx'),
        ),
        migrations.AddIndex(
            model_name='sale',
            index=models.Index(fields=['sale_date'], name='sale_date_idx'),
        ),
        migrations.AddIndex(
            model_name='sale',
            index=models.Index(fields=['client'], name='sale_client_idx'),
        ),
        
        # SaleItem model indexes
        migrations.AddIndex(
            model_name='saleitem',
            index=models.Index(fields=['sale'], name='saleitem_sale_idx'),
        ),
        migrations.AddIndex(
            model_name='saleitem',
            index=models.Index(fields=['cheese_product'], name='saleitem_product_idx'),
        ),
        
        # Payment model indexes
        migrations.AddIndex(
            model_name='payment',
            index=models.Index(fields=['client', 'date'], name='payment_client_date_idx'),
        ),
        migrations.AddIndex(
            model_name='payment',
            index=models.Index(fields=['date'], name='payment_date_idx'),
        ),
        migrations.AddIndex(
            model_name='payment',
            index=models.Index(fields=['client'], name='payment_client_idx'),
        ),
        
        # Client model indexes
        migrations.AddIndex(
            model_name='client',
            index=models.Index(fields=['name'], name='client_name_idx'),
        ),
        
        # CheeseProduct indexes
        migrations.AddIndex(
            model_name='cheeseproduct',
            index=models.Index(fields=['manufacturer'], name='product_manufacturer_idx'),
        ),
    ]
