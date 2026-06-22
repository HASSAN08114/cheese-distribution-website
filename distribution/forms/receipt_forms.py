from django import forms
from ..models import ReceiptSettings


class ReceiptSettingsForm(forms.ModelForm):
    class Meta:
        model = ReceiptSettings
        fields = ['company_name', 'phone_number', 'address']
        widgets = {
            'company_name': forms.TextInput(attrs={'class': 'form-control'}),
            'phone_number': forms.TextInput(attrs={'class': 'form-control'}),
            'address': forms.Textarea(attrs={'class': 'form-control', 'rows': 4}),
        }
