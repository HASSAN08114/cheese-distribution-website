from django.db import models
from django.core.validators import MinValueValidator
from django.contrib.auth.models import User
from decimal import Decimal


class UserProfile(models.Model):
    ROLE_CHOICES = [
        ('owner', 'Owner'),
        ('employee', 'Employee'),
    ]
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    role = models.CharField(max_length=10, choices=ROLE_CHOICES, default='employee')
    
    def __str__(self):
        return f"{self.user.username} - {self.get_role_display()}"
    
    def is_owner(self):
        return self.role == 'owner'
    
    def is_employee(self):
        return self.role == 'employee'


class Manufacturer(models.Model):
    name = models.CharField(max_length=200)
    contact_info = models.CharField(max_length=200)
    address = models.TextField()

    def __str__(self):
        return self.name

    class Meta:
        ordering = ['name']


class CheeseProduct(models.Model):
    name = models.CharField(max_length=200)
    manufacturer = models.ForeignKey(Manufacturer, on_delete=models.CASCADE)
    purchase_price_per_kg = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(Decimal('0.01'))]
    )
    available_quantity_kg = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(Decimal('0.00'))]
    )
    date_added = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.name} - {self.manufacturer.name}"

    class Meta:
        ordering = ['name']


class Client(models.Model):
    name = models.CharField(max_length=200)
    phone = models.CharField(max_length=20)
    address = models.TextField()

    def __str__(self):
        return self.name

    class Meta:
        ordering = ['name']


class Sale(models.Model):
    client = models.ForeignKey(Client, on_delete=models.CASCADE)
    sale_date = models.DateTimeField(auto_now_add=True)
    total_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal('0.00')
    )

    def __str__(self):
        return f"Sale #{self.id} - {self.client.name} - {self.sale_date.date()}"

    def calculate_total_profit(self):
        return sum(item.profit_per_kg * item.quantity_kg for item in self.saleitem_set.all())

    class Meta:
        ordering = ['-sale_date']


class SaleItem(models.Model):
    sale = models.ForeignKey(Sale, on_delete=models.CASCADE)
    cheese_product = models.ForeignKey(CheeseProduct, on_delete=models.CASCADE)
    quantity_kg = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(Decimal('0.01'))]
    )
    selling_price_per_kg = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(Decimal('0.01'))]
    )
    profit_per_kg = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal('0.00')
    )

    def save(self, *args, **kwargs):
        self.profit_per_kg = self.selling_price_per_kg - self.cheese_product.purchase_price_per_kg
        super().save(*args, **kwargs)

    def get_total_profit(self):
        return self.profit_per_kg * self.quantity_kg

    def __str__(self):
        return f"{self.cheese_product.name} - {self.quantity_kg}kg"

    class Meta:
        ordering = ['id']

