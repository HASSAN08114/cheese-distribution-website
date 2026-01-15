from django import forms
from .models import Manufacturer, CheeseProduct, Client, Sale, SaleItem
from decimal import Decimal


class ManufacturerForm(forms.ModelForm):
    class Meta:
        model = Manufacturer
        fields = ['name', 'contact_info', 'address']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'contact_info': forms.TextInput(attrs={'class': 'form-control'}),
            'address': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }


class CheeseProductForm(forms.ModelForm):
    class Meta:
        model = CheeseProduct
        fields = ['name', 'manufacturer', 'purchase_price_per_kg', 'available_quantity_kg']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'manufacturer': forms.Select(attrs={'class': 'form-control'}),
            'purchase_price_per_kg': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'available_quantity_kg': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
        }


class ClientForm(forms.ModelForm):
    class Meta:
        model = Client
        fields = ['name', 'phone', 'email', 'address']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'phone': forms.TextInput(attrs={'class': 'form-control'}),
            'email': forms.EmailInput(attrs={'class': 'form-control'}),
            'address': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }


class SaleItemForm(forms.ModelForm):
    class Meta:
        model = SaleItem
        fields = ['cheese_product', 'quantity_kg', 'selling_price_per_kg']
        widgets = {
            'cheese_product': forms.Select(attrs={'class': 'form-control'}),
            'quantity_kg': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'selling_price_per_kg': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
        }

    def clean_quantity_kg(self):
        quantity = self.cleaned_data.get('quantity_kg')
        cheese_product = self.cleaned_data.get('cheese_product')
        
        if cheese_product and quantity:
            if quantity > cheese_product.available_quantity_kg:
                raise forms.ValidationError(
                    f"Insufficient stock. Available: {cheese_product.available_quantity_kg} kg"
                )
        return quantity


SaleItemFormSet = forms.formset_factory(SaleItemForm, extra=1, can_delete=True)

