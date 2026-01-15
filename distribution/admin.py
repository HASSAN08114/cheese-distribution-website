from django.contrib import admin
from .models import Manufacturer, CheeseProduct, Client, Sale, SaleItem

admin.site.register(Manufacturer)
admin.site.register(CheeseProduct)
admin.site.register(Client)
admin.site.register(Sale)
admin.site.register(SaleItem)

