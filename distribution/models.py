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


class CheeseType(models.Model):
    name = models.CharField(max_length=100, unique=True)

    def __str__(self):
        return self.name

    class Meta:
        ordering = ['name']

class CheeseProduct(models.Model):
    manufacturer = models.ForeignKey(Manufacturer, on_delete=models.CASCADE)
    type = models.ForeignKey(CheeseType, on_delete=models.CASCADE)
    packet_size = models.DecimalField(
        max_digits=4,
        decimal_places=2,
        validators=[MinValueValidator(Decimal('0.01'))],
        help_text="Packet size in KG"
    )
    purchase_price_per_packet = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(Decimal('0.01'))]
    )
    available_quantity_packets = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(Decimal('0.00'))]
    )
    date_added = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.manufacturer.name} {self.type.name} {self.packet_size} kg"

    class Meta:
        ordering = ['manufacturer', 'type', 'packet_size']



class Client(models.Model):
    name = models.CharField(max_length=200)
    phone = models.CharField(max_length=20)
    address = models.TextField()

    def __str__(self):
        return self.name

    @property
    def amount_owed(self):
        # Total sales minus total payments
        from django.db.models import Sum
        total_sales = self.sale_set.aggregate(total=Sum('total_amount'))['total'] or Decimal('0.00')
        total_paid = self.payment_set.aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
        return total_sales - total_paid

    class Meta:
        ordering = ['name']


# Payment model for client payments
class Payment(models.Model):
    PAYMENT_MODES = [
        ('cash', 'Cash'),
        ('online', 'Online'),
    ]
    client = models.ForeignKey(Client, on_delete=models.CASCADE)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    date = models.DateTimeField(auto_now_add=True)
    mode = models.CharField(max_length=10, choices=PAYMENT_MODES)
    bank = models.CharField(max_length=100, blank=True, help_text="Required if mode is online")

    def __str__(self):
        return f"{self.client.name} - {self.amount} ({self.get_mode_display()}) on {self.date.date()}"

    class Meta:
        ordering = ['-date']


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
        return sum(item.profit_per_packet * item.quantity_packets for item in self.saleitem_set.all())

    class Meta:
        ordering = ['-sale_date']



class SaleItem(models.Model):
    sale = models.ForeignKey(Sale, on_delete=models.CASCADE)
    cheese_product = models.ForeignKey(CheeseProduct, on_delete=models.CASCADE)
    quantity_packets = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(Decimal('0.01'))]
    )
    selling_price_per_packet = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(Decimal('0.01'))]
    )
    profit_per_packet = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal('0.00')
    )
    modified = models.BooleanField(default=False, help_text="True if item was returned or modified")

    def save(self, *args, **kwargs):
        self.profit_per_packet = self.selling_price_per_packet - self.cheese_product.purchase_price_per_packet
        super().save(*args, **kwargs)

    def get_total_profit(self):
        return self.profit_per_packet * self.quantity_packets

    def __str__(self):
        return f"{self.cheese_product.name} - {self.quantity_packets} packets"

    class Meta:
        ordering = ['id']


# Tracks each stock addition event
class StockAdditionHistory(models.Model):
    cheese_product = models.ForeignKey(CheeseProduct, on_delete=models.CASCADE)
    added_by = models.ForeignKey(UserProfile, on_delete=models.SET_NULL, null=True)
    quantity_packets = models.DecimalField(max_digits=10, decimal_places=2)
    date_added = models.DateTimeField(auto_now_add=True)
    modified = models.BooleanField(default=False, help_text="True if stock addition was returned or modified")

    def __str__(self):
        return f"{self.cheese_product} - {self.quantity_packets} packets on {self.date_added}" 

    class Meta:
        ordering = ['-date_added']


# Tracks returns for both sales and stock additions
class Return(models.Model):
    sale_item = models.ForeignKey(SaleItem, on_delete=models.CASCADE, null=True, blank=True)
    stock_addition = models.ForeignKey(StockAdditionHistory, on_delete=models.CASCADE, null=True, blank=True)
    quantity_packets = models.DecimalField(max_digits=10, decimal_places=2)
    date_returned = models.DateTimeField(auto_now_add=True)
    reason = models.TextField(blank=True)

    def __str__(self):
        if self.sale_item:
            return f"Return for SaleItem {self.sale_item.id} - {self.quantity_packets} packets"
        elif self.stock_addition:
            return f"Return for StockAddition {self.stock_addition.id} - {self.quantity_packets} packets"
        return "Return"

    class Meta:
        ordering = ['-date_returned']

