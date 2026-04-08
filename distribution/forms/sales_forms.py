from django import forms
from ..models import SaleItem


class SaleItemForm(forms.ModelForm):
    class Meta:
        model = SaleItem
        fields = ['cheese_product', 'quantity_packets', 'selling_price_per_packet']
        widgets = {
            'cheese_product': forms.Select(attrs={'class': 'form-control'}),
            'quantity_packets': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'selling_price_per_packet': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
        }


SaleItemFormSet = forms.formset_factory(SaleItemForm, extra=1, can_delete=True)
