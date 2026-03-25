from django import forms
from django.contrib.auth.models import User
from .models import (
    Manufacturer, CheeseProduct, Client, Sale, SaleItem, UserProfile, CheeseType, Payment,
    DeliveryEmployee, DeliveryExpense,
)
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


class AddStockForm(forms.Form):
    cheese_product = forms.ModelChoiceField(
        queryset=CheeseProduct.objects.all(),
        widget=forms.Select(attrs={'class': 'form-control'}),
        label="Select Product"
    )
    quantity_packets = forms.DecimalField(
        max_digits=10,
        decimal_places=2,
        min_value=0.01,
        widget=forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
        label="Quantity to Add (Packets)"
    )
    purchase_price_per_packet = forms.DecimalField(
        max_digits=10,
        decimal_places=2,
        min_value=0.01,
        widget=forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
        label="Purchase Price (PKR/Packet)"
    )

AddStockFormSet = forms.formset_factory(AddStockForm, extra=1, can_delete=True)


class ClientForm(forms.ModelForm):
    class Meta:
        model = Client
        fields = ['name', 'phone', 'address']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'phone': forms.TextInput(attrs={'class': 'form-control'}),
            'address': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }


class SaleItemForm(forms.ModelForm):
    class Meta:
        model = SaleItem
        fields = ['cheese_product', 'quantity_packets', 'selling_price_per_packet']
        widgets = {
            'cheese_product': forms.Select(attrs={'class': 'form-control'}),
            'quantity_packets': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'selling_price_per_packet': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
        }

    def clean_quantity_packets(self):
        quantity = self.cleaned_data.get('quantity_packets')
        cheese_product = self.cleaned_data.get('cheese_product')
        
        if cheese_product and quantity:
            if quantity > cheese_product.available_quantity_packets:
                raise forms.ValidationError(
                    f"Insufficient stock. Available: {cheese_product.available_quantity_packets} packets"
                )
        return quantity


SaleItemFormSet = forms.formset_factory(SaleItemForm, extra=1, can_delete=True)

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


class DeliveryEmployeeForm(forms.ModelForm):
    class Meta:
        model = DeliveryEmployee
        fields = ['name', 'id_card_number', 'joining_date', 'route_from', 'route_to']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'id_card_number': forms.TextInput(attrs={'class': 'form-control'}),
            'joining_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'route_from': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'From where'}),
            'route_to': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'To where'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Backfill new From/To fields from the legacy `route` field when editing
        # employees that were created before this change.
        instance = kwargs.get("instance")
        if instance and not (getattr(instance, "route_from", "") and getattr(instance, "route_to", "")):
            legacy = (getattr(instance, "route", "") or "").strip()
            if "->" in legacy:
                parts = legacy.split("->", 1)
                self.initial.setdefault("route_from", parts[0].strip())
                self.initial.setdefault("route_to", parts[1].strip())

    def clean(self):
        cleaned_data = super().clean()
        
        # Validate ID card number: must have at least 13 digits
        id_card_number = cleaned_data.get('id_card_number', '').strip()
        if id_card_number:
            digits_only = ''.join(c for c in id_card_number if c.isdigit())
            if len(digits_only) < 13:
                self.add_error('id_card_number', 'ID card number must contain at least 13 digits.')
        
        # Validate route fields
        rf = (cleaned_data.get('route_from') or '').strip()
        rt = (cleaned_data.get('route_to') or '').strip()

        if not rf:
            self.add_error('route_from', 'Please enter where the delivery route starts (From where).')
        if not rt:
            self.add_error('route_to', 'Please enter where the delivery route ends (To where).')

        return cleaned_data

    def save(self, commit=True):
        # Keep the legacy `route` string synchronized for display/search compatibility.
        instance = super().save(commit=False)
        route_from = (self.cleaned_data.get('route_from') or '').strip()
        route_to = (self.cleaned_data.get('route_to') or '').strip()
        if route_from and route_to:
            instance.route = f'{route_from} -> {route_to}'
        if commit:
            instance.save()
        return instance


class DeliveryExpenseForm(forms.ModelForm):
    employee = forms.ModelChoiceField(
        queryset=DeliveryEmployee.objects.all(),
        required=False,
        empty_label="Select an employee",
        widget=forms.Select(attrs={'class': 'form-control'})
    )
    
    class Meta:
        model = DeliveryExpense
        fields = ['employee', 'expense_type', 'amount', 'note', 'expense_date']
        widgets = {
            'expense_type': forms.Select(attrs={'class': 'form-control'}),
            'amount': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'note': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'expense_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
        }

    def clean(self):
        cleaned_data = super().clean()
        # Employee is optional for all expense types
        return cleaned_data


class SaleForm(forms.ModelForm):
    """Form for creating sales with payment information"""
    class Meta:
        model = Sale
        fields = ['client', 'payment_method', 'amount_paid']
        widgets = {
            'client': forms.Select(attrs={'class': 'form-control'}),
        }

    payment_method = forms.ChoiceField(
        choices=Sale.PAYMENT_METHOD_CHOICES,
        widget=forms.Select(attrs={'class': 'form-control'}),
        required=False,
        label="Payment Method"
    )

    amount_paid = forms.DecimalField(
        max_digits=10,
        decimal_places=2,
        min_value=0,
        widget=forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
        initial=0,
        label="Amount Paid Now"
    )


class UserForm(forms.ModelForm):
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={'class': 'form-control'}),
        required=True,
        help_text='Enter a secure password'
    )
    password_confirm = forms.CharField(
        widget=forms.PasswordInput(attrs={'class': 'form-control'}),
        required=True,
        label='Confirm Password'
    )
    role = forms.ChoiceField(
        choices=UserProfile.ROLE_CHOICES,
        widget=forms.Select(attrs={'class': 'form-control'}),
        required=True,
        initial='employee'
    )
    
    class Meta:
        model = User
        fields = ['username', 'first_name', 'last_name', 'email']
        widgets = {
            'username': forms.TextInput(attrs={'class': 'form-control'}),
            'first_name': forms.TextInput(attrs={'class': 'form-control'}),
            'last_name': forms.TextInput(attrs={'class': 'form-control'}),
            'email': forms.EmailInput(attrs={'class': 'form-control'}),
        }
    
    def clean(self):
        cleaned_data = super().clean()
        password = cleaned_data.get('password')
        password_confirm = cleaned_data.get('password_confirm')
        
        if password and password_confirm:
            if password != password_confirm:
                raise forms.ValidationError("Passwords do not match.")
        
        return cleaned_data
    
    def save(self, commit=True):
        user = super().save(commit=False)
        user.set_password(self.cleaned_data['password'])
        if commit:
            user.save()
            # Create or update user profile
            profile, created = UserProfile.objects.get_or_create(user=user)
            profile.role = self.cleaned_data['role']
            profile.save()
        return user


class UserRoleForm(forms.ModelForm):
    class Meta:
        model = UserProfile
        fields = ['role']
        widgets = {
            'role': forms.Select(attrs={'class': 'form-control'}),
        }

