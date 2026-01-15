import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'cheese_distribution.settings')
django.setup()

from distribution.models import Manufacturer, CheeseProduct, Client
from decimal import Decimal

def populate_data():
    print("Creating test data...")
    
    Manufacturer.objects.all().delete()
    CheeseProduct.objects.all().delete()
    Client.objects.all().delete()
    
    manufacturer1 = Manufacturer.objects.create(
        name="Alpine Dairy Co.",
        contact_info="+92-300-1234567",
        address="123 Dairy Street, Lahore, Pakistan"
    )
    
    manufacturer2 = Manufacturer.objects.create(
        name="Swiss Cheese Masters",
        contact_info="+92-300-2345678",
        address="456 Cheese Avenue, Karachi, Pakistan"
    )
    
    manufacturer3 = Manufacturer.objects.create(
        name="Premium Cheese Factory",
        contact_info="+92-300-3456789",
        address="789 Factory Road, Islamabad, Pakistan"
    )
    
    print("Manufacturers created")
    
    CheeseProduct.objects.create(
        name="Cheddar Cheese",
        manufacturer=manufacturer1,
        purchase_price_per_kg=Decimal('1200.00'),
        available_quantity_kg=Decimal('50.00')
    )
    
    CheeseProduct.objects.create(
        name="Mozzarella Cheese",
        manufacturer=manufacturer1,
        purchase_price_per_kg=Decimal('1100.00'),
        available_quantity_kg=Decimal('75.00')
    )
    
    CheeseProduct.objects.create(
        name="Swiss Cheese",
        manufacturer=manufacturer2,
        purchase_price_per_kg=Decimal('1500.00'),
        available_quantity_kg=Decimal('40.00')
    )
    
    CheeseProduct.objects.create(
        name="Gouda Cheese",
        manufacturer=manufacturer2,
        purchase_price_per_kg=Decimal('1300.00'),
        available_quantity_kg=Decimal('60.00')
    )
    
    CheeseProduct.objects.create(
        name="Feta Cheese",
        manufacturer=manufacturer3,
        purchase_price_per_kg=Decimal('1000.00'),
        available_quantity_kg=Decimal('55.00')
    )
    
    CheeseProduct.objects.create(
        name="Parmesan Cheese",
        manufacturer=manufacturer3,
        purchase_price_per_kg=Decimal('1800.00'),
        available_quantity_kg=Decimal('30.00')
    )
    
    print("Cheese products created")
    
    Client.objects.create(
        name="City Supermarket",
        phone="+92-300-1111111",
        email="contact@citysupermarket.com",
        address="Main Market, Lahore"
    )
    
    Client.objects.create(
        name="Gourmet Restaurant",
        phone="+92-300-2222222",
        email="info@gourmetrest.com",
        address="Food Street, Karachi"
    )
    
    Client.objects.create(
        name="Wholesale Distributors",
        phone="+92-300-3333333",
        email="sales@wholesale.pk",
        address="Industrial Area, Islamabad"
    )
    
    Client.objects.create(
        name="Delicious Bakery",
        phone="+92-300-4444444",
        email="orders@deliciousbakery.com",
        address="Bakery Lane, Rawalpindi"
    )
    
    Client.objects.create(
        name="Fast Food Chain",
        phone="+92-300-5555555",
        email="procurement@fastfood.pk",
        address="Commercial Plaza, Faisalabad"
    )
    
    print("Clients created")
    print("\nTest data populated successfully!")
    print("\nSummary:")
    print(f"Manufacturers: {Manufacturer.objects.count()}")
    print(f"Cheese Products: {CheeseProduct.objects.count()}")
    print(f"Clients: {Client.objects.count()}")

if __name__ == '__main__':
    populate_data()

