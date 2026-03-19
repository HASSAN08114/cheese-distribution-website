from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from django.utils import timezone
from decimal import Decimal
from datetime import timedelta
import random

from distribution.models import (
    Manufacturer, CheeseType, CheeseProduct, Client,
    Sale, SaleItem, StockAdditionHistory, UserProfile
)


class Command(BaseCommand):
    help = 'Populate database with test data for demonstration'

    def handle(self, *args, **options):
        self.stdout.write('Starting test data population...')

        # Create test user if not exists
        user, created = User.objects.get_or_create(
            username='testowner',
            defaults={
                'email': 'test@example.com',
                'first_name': 'Test',
                'last_name': 'Owner'
            }
        )
        if created:
            user.set_password('test123')
            user.save()

        # Create UserProfile
        profile, created = UserProfile.objects.get_or_create(
            user=user,
            defaults={'role': 'owner'}
        )

        # Create Manufacturers
        manufacturers_data = [
            {'name': 'Alpine Dairy', 'contact_info': 'John Smith - +92-300-1234567', 'address': '123 Mountain Road, Switzerland'},
            {'name': 'Valley Cheese Co.', 'contact_info': 'Sarah Johnson - +92-301-2345678', 'address': '456 Valley Street, USA'},
            {'name': 'Mountain Fresh', 'contact_info': 'Mike Wilson - +92-302-3456789', 'address': '789 Peak Avenue, Canada'},
            {'name': 'Premium Cheese Ltd.', 'contact_info': 'Lisa Brown - +92-303-4567890', 'address': '321 Quality Lane, Netherlands'},
        ]

        manufacturers = []
        for data in manufacturers_data:
            manufacturer, created = Manufacturer.objects.get_or_create(
                name=data['name'],
                defaults=data
            )
            manufacturers.append(manufacturer)
            if created:
                self.stdout.write(f'Created manufacturer: {manufacturer.name}')

        # Create Cheese Types
        cheese_types_data = [
            {'name': 'Cheddar'},
            {'name': 'Mozzarella'},
            {'name': 'Gouda'},
            {'name': 'Parmesan'},
            {'name': 'Blue Cheese'},
        ]

        cheese_types = []
        for data in cheese_types_data:
            cheese_type, created = CheeseType.objects.get_or_create(
                name=data['name']
            )
            cheese_types.append(cheese_type)
            if created:
                self.stdout.write(f'Created cheese type: {cheese_type.name}')

        # Create Cheese Products
        products_data = [
            {'manufacturer': manufacturers[0], 'type': cheese_types[0], 'packet_size': Decimal('0.5'), 'purchase_price_per_packet': Decimal('450.00')},
            {'manufacturer': manufacturers[0], 'type': cheese_types[1], 'packet_size': Decimal('0.25'), 'purchase_price_per_packet': Decimal('180.00')},
            {'manufacturer': manufacturers[1], 'type': cheese_types[2], 'packet_size': Decimal('1.0'), 'purchase_price_per_packet': Decimal('850.00')},
            {'manufacturer': manufacturers[1], 'type': cheese_types[3], 'packet_size': Decimal('0.2'), 'purchase_price_per_packet': Decimal('320.00')},
            {'manufacturer': manufacturers[2], 'type': cheese_types[0], 'packet_size': Decimal('0.75'), 'purchase_price_per_packet': Decimal('620.00')},
            {'manufacturer': manufacturers[2], 'type': cheese_types[4], 'packet_size': Decimal('0.3'), 'purchase_price_per_packet': Decimal('280.00')},
            {'manufacturer': manufacturers[3], 'type': cheese_types[1], 'packet_size': Decimal('0.5'), 'purchase_price_per_packet': Decimal('380.00')},
            {'manufacturer': manufacturers[3], 'type': cheese_types[2], 'packet_size': Decimal('0.4'), 'purchase_price_per_packet': Decimal('420.00')},
        ]

        products = []
        for data in products_data:
            defaults = data.copy()
            defaults['available_quantity_packets'] = Decimal('0.00')  # Start with zero stock
            product, created = CheeseProduct.objects.get_or_create(
                manufacturer=data['manufacturer'],
                type=data['type'],
                packet_size=data['packet_size'],
                defaults=defaults
            )
            products.append(product)
            if created:
                self.stdout.write(f'Created product: {product}')

        # Create Clients
        clients_data = [
            {'name': 'Ahmed Traders', 'phone': '+92-300-1111111', 'address': 'Shop #12, Main Market, Lahore'},
            {'name': 'Fatima Grocery', 'phone': '+92-301-2222222', 'address': 'Street 45, Gulberg, Lahore'},
            {'name': 'Karachi Foods Ltd.', 'phone': '+92-302-3333333', 'address': 'Plot 78, Industrial Area, Karachi'},
            {'name': 'Islamabad Wholesale', 'phone': '+92-303-4444444', 'address': 'Sector F-7, Blue Area, Islamabad'},
            {'name': 'Peshawar Distributors', 'phone': '+92-304-5555555', 'address': 'Qissa Khwani Road, Peshawar'},
            {'name': 'Quetta Supermarket', 'phone': '+92-305-6666666', 'address': 'Prince Road, Quetta'},
            {'name': 'Multan Traders', 'phone': '+92-306-7777777', 'address': 'Bosan Road, Multan'},
            {'name': 'Faisalabad Foods', 'phone': '+92-307-8888888', 'address': 'Railway Road, Faisalabad'},
        ]

        clients = []
        for data in clients_data:
            client, created = Client.objects.get_or_create(
                name=data['name'],
                defaults=data
            )
            clients.append(client)
            if created:
                self.stdout.write(f'Created client: {client.name}')

        # Create Stock Additions
        stock_data = [
            {'product': products[0], 'quantity_packets': 50, 'added_by': profile},
            {'product': products[1], 'quantity_packets': 75, 'added_by': profile},
            {'product': products[2], 'quantity_packets': 30, 'added_by': profile},
            {'product': products[3], 'quantity_packets': 60, 'added_by': profile},
            {'product': products[4], 'quantity_packets': 40, 'added_by': profile},
            {'product': products[5], 'quantity_packets': 80, 'added_by': profile},
            {'product': products[6], 'quantity_packets': 55, 'added_by': profile},
            {'product': products[7], 'quantity_packets': 45, 'added_by': profile},
        ]

        payment_methods = ['bank', 'jazzcash', 'easypaisa', 'cash']

        for i, data in enumerate(stock_data):
            # Add some time variation
            days_ago = random.randint(0, 30)
            stock_date = timezone.now() - timedelta(days=days_ago)

            # Create unique stock addition
            stock = StockAdditionHistory.objects.create(
                cheese_product=data['product'],
                quantity_packets=data['quantity_packets'],
                added_by=data['added_by'],
                date_added=stock_date,
            )

            # Update product stock
            data['product'].available_quantity_packets += data['quantity_packets']
            data['product'].save()
            self.stdout.write(f'Added {data["quantity_packets"]} packets of {data["product"]} to stock')

        # Create Sales
        sales_data = []
        for i in range(25):  # Create 25 sales
            client = random.choice(clients)
            sale_date = timezone.now() - timedelta(days=random.randint(0, 45))

            # Random payment status and method
            payment_status = random.choice(['paid', 'partial', 'unpaid'])
            payment_method = random.choice(payment_methods) if random.random() > 0.3 else ''

            # Calculate amounts
            num_items = random.randint(1, 4)
            total_amount = Decimal('0.00')

            sale_items_data = []
            for _ in range(num_items):
                product = random.choice(products)
                quantity = random.randint(1, 10)
                # Set selling price as purchase price + random profit margin (20-50%)
                profit_margin = random.uniform(0.2, 0.5)
                unit_price = product.purchase_price_per_packet * Decimal(str(1 + profit_margin))
                profit_per_packet = unit_price - product.purchase_price_per_packet
                total_item = unit_price * quantity

                sale_items_data.append({
                    'product': product,
                    'quantity_packets': quantity,
                    'selling_price_per_packet': unit_price,
                    'profit_per_packet': profit_per_packet,
                    'total_price': total_item,
                })
                total_amount += total_item

            # Calculate amount paid based on payment status
            if payment_status == 'paid':
                amount_paid = total_amount
            elif payment_status == 'partial':
                amount_paid = total_amount * Decimal(str(random.uniform(0.3, 0.8)))
            else:  # unpaid
                amount_paid = Decimal('0.00')

            # Create unique sale
            sale = Sale.objects.create(
                client=client,
                sale_date=sale_date,
                total_amount=total_amount,
                payment_status=payment_status,
                payment_method=payment_method,
                amount_paid=amount_paid,
            )

            # Create sale items
            for item_data in sale_items_data:
                SaleItem.objects.create(
                    sale=sale,
                    cheese_product=item_data['product'],
                    quantity_packets=item_data['quantity_packets'],
                    selling_price_per_packet=item_data['selling_price_per_packet'],
                )

                # Update product stock
                item_data['product'].available_quantity_packets -= item_data['quantity_packets']
                item_data['product'].save()

            sales_data.append(sale)
            self.stdout.write(f'Created sale: {sale.client.name} - PKR {total_amount} ({payment_status})')

        self.stdout.write(self.style.SUCCESS('Test data population completed successfully!'))
        self.stdout.write(f'Created {len(manufacturers)} manufacturers')
        self.stdout.write(f'Created {len(cheese_types)} cheese types')
        self.stdout.write(f'Created {len(products)} products')
        self.stdout.write(f'Created {len(clients)} clients')
        self.stdout.write(f'Created {len(sales_data)} sales')
        self.stdout.write(f'Created {StockAdditionHistory.objects.count()} stock additions')
        self.stdout.write('')
        self.stdout.write('Test user credentials:')
        self.stdout.write('Username: testowner')
        self.stdout.write('Password: test123')
        self.stdout.write('')
        self.stdout.write('To remove test data, run: python manage.py flush')