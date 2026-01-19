from django.contrib import admin
from .models import Manufacturer, CheeseProduct, Client, Sale, SaleItem, UserProfile, StockAdditionHistory, Return, CheeseType

admin.site.register(Manufacturer)
admin.site.register(CheeseProduct)
admin.site.register(Client)
admin.site.register(Sale)
admin.site.register(SaleItem)
admin.site.register(UserProfile)
admin.site.register(StockAdditionHistory)
admin.site.register(Return)
admin.site.register(CheeseType)

