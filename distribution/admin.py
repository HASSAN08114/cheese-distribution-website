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
	ReceiptSettings,
	StockAdditionHistory,
	CheeseType,
)


@admin.register(ReceiptSettings)
class ReceiptSettingsAdmin(admin.ModelAdmin):
    list_display = ('company_name', 'phone_number', 'updated_at')

    def has_add_permission(self, request):
        return not ReceiptSettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False


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

