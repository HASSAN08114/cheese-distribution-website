from django import forms
from ..models import Manufacturer, CheeseProduct, CheeseType


class ManufacturerForm(forms.ModelForm):
    class Meta:
        model = Manufacturer
        fields = ['name', 'contact_info', 'address']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'contact_info': forms.TextInput(attrs={'class': 'form-control'}),
            'address': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['contact_info'].required = False
        self.fields['address'].required = False


class CheeseTypeForm(forms.ModelForm):
    class Meta:
        model = CheeseType
        fields = ['name']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. Cheddar, Mozzarella'}),
        }


class CheeseProductForm(forms.ModelForm):
    class Meta:
        model = CheeseProduct
        fields = ['manufacturer', 'type', 'packet_size', 'purchase_price_per_packet', 'available_quantity_packets']
        widgets = {
            'manufacturer': forms.Select(attrs={'class': 'form-control'}),
            'type': forms.Select(attrs={'class': 'form-control'}),
            'packet_size': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'placeholder': 'e.g. 0.5 for 0.5 KG'}),
            'purchase_price_per_packet': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'available_quantity_packets': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
        }

