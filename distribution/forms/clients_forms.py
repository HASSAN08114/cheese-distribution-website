from django import forms
from ..models import Client, Payment


class ClientForm(forms.ModelForm):
    class Meta:
        model = Client
        fields = ['name', 'phone', 'address']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'phone': forms.TextInput(attrs={'class': 'form-control'}),
            'address': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }


class PaymentForm(forms.ModelForm):
    class Meta:
        model = Payment
        fields = ['client', 'amount', 'mode', 'bank']
        widgets = {
            'client': forms.Select(attrs={'class': 'form-control'}),
            'amount': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'mode': forms.Select(attrs={'class': 'form-control'}),
            'bank': forms.TextInput(attrs={'class': 'form-control'}),
        }

    def clean(self):
        cleaned_data = super().clean()
        mode = cleaned_data.get('mode')
        bank = (cleaned_data.get('bank') or '').strip()

        # If payment is online, bank/wallet identifier is required.
        if mode == 'online' and not bank:
            self.add_error('bank', 'Bank/Wallet is required for online payments.')
        # For cash payments, clear bank to avoid misleading data.
        if mode == 'cash':
            cleaned_data['bank'] = ''

        return cleaned_data
