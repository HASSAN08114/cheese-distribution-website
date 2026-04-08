from django import forms
from django.utils import timezone
from ..models import Client, Payment


class ClientForm(forms.ModelForm):
    class Meta:
        model = Client
        fields = ['name', 'phone', 'address', 'date_added', 'previous_debt']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'phone': forms.TextInput(attrs={'class': 'form-control'}),
            'address': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'date_added': forms.DateTimeInput(
                attrs={
                    'class': 'form-control js-datetime-picker',
                    'type': 'text',
                    'placeholder': 'DD/MM/YYYY HH:MM'
                },
                format='%d/%m/%Y %H:%M'
            ),
            'previous_debt': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'min': '0', 'placeholder': 'Enter previous debt amount (if any)'}),
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['phone'].required = False
        self.fields['address'].required = False
        self.fields['date_added'].input_formats = ['%Y-%m-%dT%H:%M', '%d/%m/%Y %H:%M']
        if not self.is_bound:
            if self.instance.pk and self.instance.date_added:
                self.fields['date_added'].initial = timezone.localtime(self.instance.date_added).strftime('%d/%m/%Y %H:%M')
            else:
                self.fields['date_added'].initial = timezone.localtime().strftime('%d/%m/%Y %H:%M')


class PaymentForm(forms.ModelForm):
    class Meta:
        model = Payment
        fields = ['client', 'amount', 'date', 'mode', 'bank']
        widgets = {
            'client': forms.Select(attrs={'class': 'form-control'}),
            'amount': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'date': forms.DateTimeInput(
                attrs={'class': 'form-control', 'type': 'datetime-local'},
                format='%Y-%m-%dT%H:%M'
            ),
            'mode': forms.Select(attrs={'class': 'form-control'}),
            'bank': forms.TextInput(attrs={'class': 'form-control'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['date'].input_formats = ['%Y-%m-%dT%H:%M', '%d/%m/%Y %H:%M']
        if not self.is_bound:
            if self.instance.pk and self.instance.date:
                self.fields['date'].initial = timezone.localtime(self.instance.date).strftime('%Y-%m-%dT%H:%M')
            else:
                self.fields['date'].initial = timezone.localtime().strftime('%Y-%m-%dT%H:%M')

    def clean(self):
        cleaned_data = super().clean()
        client = cleaned_data.get('client')
        payment_date = cleaned_data.get('date')
        mode = cleaned_data.get('mode')
        bank = (cleaned_data.get('bank') or '').strip()

        if client and payment_date and client.date_added:
            client_created = client.date_added

            if timezone.is_naive(client_created):
                client_created = timezone.make_aware(client_created, timezone.get_current_timezone())
            if timezone.is_naive(payment_date):
                payment_date = timezone.make_aware(payment_date, timezone.get_current_timezone())
                cleaned_data['date'] = payment_date

            if payment_date < client_created:
                display_date = timezone.localtime(client_created).strftime('%d/%m/%Y %H:%M')
                self.add_error('date', f'Payment date cannot be earlier than client creation date ({display_date}).')

        # If payment is online, bank/wallet identifier is required.
        if mode == 'online' and not bank:
            self.add_error('bank', 'Bank/Wallet is required for online payments.')
        # For cash payments, clear bank to avoid misleading data.
        if mode == 'cash':
            cleaned_data['bank'] = ''

        return cleaned_data
