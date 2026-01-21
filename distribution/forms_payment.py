from django import forms
from .models import Payment, Client

class PaymentForm(forms.ModelForm):
    class Meta:
        model = Payment
        fields = ['client', 'amount', 'mode', 'bank']
        widgets = {
            'client': forms.Select(attrs={'class': 'form-control'}),
            'amount': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'mode': forms.Select(attrs={'class': 'form-control', 'onchange': 'toggleBankField(this)'}),
            'bank': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Bank/Wallet name (if online)'}),
        }

    def clean(self):
        cleaned_data = super().clean()
        mode = cleaned_data.get('mode')
        bank = cleaned_data.get('bank')
        if mode == 'online' and not bank:
            self.add_error('bank', 'Bank/Wallet is required for online payments.')
        return cleaned_data
