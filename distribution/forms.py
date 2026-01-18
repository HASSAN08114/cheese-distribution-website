from django import forms
from django.contrib.auth.models import User
from .models import Manufacturer, CheeseProduct, Client, Sale, SaleItem, UserProfile
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
        fields = ['name', 'manufacturer', 'purchase_price_per_packet', 'available_quantity_packets']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'manufacturer': forms.Select(attrs={'class': 'form-control'}),
            'purchase_price_per_packet': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'available_quantity_packets': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
        }


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

