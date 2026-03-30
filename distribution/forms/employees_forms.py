from django import forms
from ..models import DeliveryEmployee, DeliveryExpense


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
        
        # Validate ID card number: must have exactly 13 digits
        id_card_number = cleaned_data.get('id_card_number', '').strip()
        if id_card_number:
            digits_only = ''.join(c for c in id_card_number if c.isdigit())
            if len(digits_only) != 13:
                self.add_error('id_card_number', 'ID card number must be exactly 13 digits.')
        
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
