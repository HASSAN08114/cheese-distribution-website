import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'cheese_distribution.settings')
django.setup()

from distribution.models import Manufacturer, CheeseProduct, Client, Sale, SaleItem

def clear_all_data():
    print("Clearing all test data...")
    
    SaleItem.objects.all().delete()
    Sale.objects.all().delete()
    CheeseProduct.objects.all().delete()
    Client.objects.all().delete()
    Manufacturer.objects.all().delete()
    
    print("All test data cleared successfully!")
    print("You can now add your real data through the web interface.")

if __name__ == '__main__':
    confirm = input("Are you sure you want to delete ALL data? (yes/no): ")
    if confirm.lower() == 'yes':
        clear_all_data()
    else:
        print("Operation cancelled.")

