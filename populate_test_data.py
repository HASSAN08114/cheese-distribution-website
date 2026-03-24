import os
import django
from datetime import datetime, timedelta

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'cheese_distribution.settings')
django.setup()

from distribution.models import (
    Manufacturer, CheeseType, CheeseProduct, Client, Sale, SaleItem, 
    StockAdditionHistory, UserProfile
)
from django.contrib.auth.models import User
from decimal import Decimal
from django.utils import timezone

def populate_data():
    print("Creating test data...")
    
    # Get or create admin user
    admin_user = User.objects.filter(username='admin').first()
    if admin_user:
        admin_profile = UserProfile.objects.filter(user=admin_user).first()
    else:
        admin_user = User.objects.create_user(username='admin', email='admin@test.com', password='admin123')
        admin_profile = UserProfile.objects.create(user=admin_user, role='owner')
    
    # Create Cheese Types
    print("\nCreating cheese types...")
    cheddar = CheeseType.objects.create(name="Cheddar") if not CheeseType.objects.filter(name="Cheddar").exists() else CheeseType.objects.get(name="Cheddar")
    mozzarella = CheeseType.objects.create(name="Mozzarella") if not CheeseType.objects.filter(name="Mozzarella").exists() else CheeseType.objects.get(name="Mozzarella")
    swiss = CheeseType.objects.create(name="Swiss") if not CheeseType.objects.filter(name="Swiss").exists() else CheeseType.objects.get(name="Swiss")
    feta = CheeseType.objects.create(name="Feta") if not CheeseType.objects.filter(name="Feta").exists() else CheeseType.objects.get(name="Feta")
    gouda = CheeseType.objects.create(name="Gouda") if not CheeseType.objects.filter(name="Gouda").exists() else CheeseType.objects.get(name="Gouda")
    print(f"Cheese types: {CheeseType.objects.count()}")
    
    # Create Manufacturers
    print("Creating manufacturers...")
    manufacturer1, _ = Manufacturer.objects.get_or_create(
        name="Alpine Dairy Co.",
        defaults={
            'contact_info': "+92-300-1234567",
            'address': "123 Dairy Street, Lahore, Pakistan"
        }
    )
    
    manufacturer2, _ = Manufacturer.objects.get_or_create(
        name="Swiss Cheese Masters",
        defaults={
            'contact_info': "+92-300-2345678",
            'address': "456 Cheese Avenue, Karachi, Pakistan"
        }
    )
    
    manufacturer3, _ = Manufacturer.objects.get_or_create(
        name="Premium Cheese Factory",
        defaults={
            'contact_info': "+92-300-3456789",
            'address': "789 Factory Road, Islamabad, Pakistan"
        }
    )
    
    print(f"Manufacturers: {Manufacturer.objects.count()}")
    
    # Create Cheese Products with correct fields
    print("Creating cheese products...")
    products = []
    
    product1, _ = CheeseProduct.objects.get_or_create(
        manufacturer=manufacturer1,
        type=cheddar,
        packet_size=Decimal('1.00'),
        defaults={
            'purchase_price_per_packet': Decimal('1200.00'),
            'available_quantity_packets': Decimal('100.00')
        }
    )
    products.append(product1)
    
    product2, _ = CheeseProduct.objects.get_or_create(
        manufacturer=manufacturer1,
        type=mozzarella,
        packet_size=Decimal('1.00'),
        defaults={
            'purchase_price_per_packet': Decimal('1100.00'),
            'available_quantity_packets': Decimal('80.00')
        }
    )
    products.append(product2)
    
    product3, _ = CheeseProduct.objects.get_or_create(
        manufacturer=manufacturer2,
        type=swiss,
        packet_size=Decimal('1.00'),
        defaults={
            'purchase_price_per_packet': Decimal('1500.00'),
            'available_quantity_packets': Decimal('60.00')
        }
    )
    products.append(product3)
    
    product4, _ = CheeseProduct.objects.get_or_create(
        manufacturer=manufacturer2,
        type=gouda,
        packet_size=Decimal('1.00'),
        defaults={
            'purchase_price_per_packet': Decimal('1300.00'),
            'available_quantity_packets': Decimal('70.00')
        }
    )
    products.append(product4)
    
    product5, _ = CheeseProduct.objects.get_or_create(
        manufacturer=manufacturer3,
        type=feta,
        packet_size=Decimal('0.50'),
        defaults={
            'purchase_price_per_packet': Decimal('600.00'),
            'available_quantity_packets': Decimal('120.00')
        }
    )
    products.append(product5)
    
    print(f"Cheese Products: {CheeseProduct.objects.count()}")
    
    # Create Clients
    print("Creating clients...")
    client1, _ = Client.objects.get_or_create(
        name="City Supermarket",
        defaults={
            'phone': "+92-300-1111111",
            'address': "Main Market, Lahore"
        }
    )
    
    client2, _ = Client.objects.get_or_create(
        name="Gourmet Restaurant",
        defaults={
            'phone': "+92-300-2222222",
            'address': "Food Street, Karachi"
        }
    )
    
    client3, _ = Client.objects.get_or_create(
        name="Wholesale Distributors",
        defaults={
            'phone': "+92-300-3333333",
            'address': "Industrial Area, Islamabad"
        }
    )
    
    client4, _ = Client.objects.get_or_create(
        name="Delicious Bakery",
        defaults={
            'phone': "+92-300-4444444",
            'address': "Bakery Lane, Rawalpindi"
        }
    )
    
    client5, _ = Client.objects.get_or_create(
        name="Fast Food Chain",
        defaults={
            'phone': "+92-300-5555555",
            'address': "Commercial Plaza, Faisalabad"
        }
    )
    
    print(f"Clients: {Client.objects.count()}")
    
    # Create Stock Addition History (5-6 entries)
    print("Creating stock addition history...")
    now = timezone.now()
    
    stock_entries = [
        (product1, Decimal('50.00'), now - timedelta(days=5)),
        (product2, Decimal('40.00'), now - timedelta(days=4)),
        (product3, Decimal('30.00'), now - timedelta(days=3)),
        (product4, Decimal('35.00'), now - timedelta(days=2)),
        (product5, Decimal('60.00'), now - timedelta(days=1)),
        (product1, Decimal('45.00'), now),
    ]
    
    for product, quantity, date_added in stock_entries:
        # Create with correct date
        stock = StockAdditionHistory.objects.create(
            cheese_product=product,
            added_by=admin_profile,
            quantity_packets=quantity,
            modified=False
        )
        # Update the date_added after creation
        StockAdditionHistory.objects.filter(pk=stock.pk).update(date_added=date_added)
    
    print(f"Stock Addition Entries: {StockAdditionHistory.objects.count()}")
    
    # Create Sales (for Sales History page)
    print("Creating sales records...")
    sale_dates = [
        now - timedelta(days=6),
        now - timedelta(days=4),
        now - timedelta(days=2),
        now - timedelta(days=1),
        now,
    ]
    
    clients = [client1, client2, client3, client4, client5]
    
    for idx, sale_date in enumerate(sale_dates):
        client = clients[idx]
        sale = Sale.objects.create(
            client=client,
            total_amount=Decimal('5000.00'),
            payment_status='partial' if idx % 2 == 0 else 'unpaid',
            amount_paid=Decimal('2500.00') if idx % 2 == 0 else Decimal('0.00'),
        )
        # Update the sale_date
        Sale.objects.filter(pk=sale.pk).update(sale_date=sale_date)
        
        # Add sale items
        SaleItem.objects.create(
            sale=sale,
            cheese_product=products[idx % len(products)],
            quantity_packets=Decimal('10.00'),
            selling_price_per_packet=products[idx % len(products)].purchase_price_per_packet * Decimal('1.5'),
        )
    
    print(f"Sales: {Sale.objects.count()}")
    print(f"Sale Items: {SaleItem.objects.count()}")
    
    print("\n✓ Test data populated successfully!")
    print("\n=== SUMMARY ===")
    print(f"Cheese Types: {CheeseType.objects.count()}")
    print(f"Manufacturers: {Manufacturer.objects.count()}")
    print(f"Cheese Products: {CheeseProduct.objects.count()}")
    print(f"Clients: {Client.objects.count()}")
    print(f"Stock Additions: {StockAdditionHistory.objects.count()}")
    print(f"Sales: {Sale.objects.count()}")
    print(f"Sale Items: {SaleItem.objects.count()}")

if __name__ == '__main__':
    populate_data()

