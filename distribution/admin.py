from django.contrib import admin
from .models import (
	Manufacturer,
	CheeseProduct,
	Client,
	Sale,
	SaleItem,
	SaleAction,
	Payment,
	PaymentAction,
	UserProfile,
	StockAdditionHistory,
	CheeseType,
)

admin.site.register(Manufacturer)
admin.site.register(CheeseProduct)
admin.site.register(Client)
admin.site.register(Sale)
admin.site.register(SaleItem)
admin.site.register(SaleAction)
admin.site.register(Payment)
admin.site.register(PaymentAction)
admin.site.register(UserProfile)
admin.site.register(StockAdditionHistory)
admin.site.register(CheeseType)

