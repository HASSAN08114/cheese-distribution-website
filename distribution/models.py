from django.db import models
from django.core.validators import MinValueValidator
from django.contrib.auth.models import User
from decimal import Decimal
from django.utils import timezone


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
    name = models.CharField(max_length=200, unique=True)
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
    PAYMENT_STATUS_CHOICES = [
        ('unpaid', 'Unpaid'),
        ('partial', 'Partial'),
        ('paid', 'Paid'),
    ]

    PAYMENT_METHOD_CHOICES = [
        ('cash', 'Cash'),
        ('bank_transfer', 'Bank Transfer'),
        ('jazzcash', 'JazzCash'),
        ('easypaisa', 'EasyPaisa'),
        ('sadapay', 'SadaPay'),
        ('online_banking', 'Online Banking'),
        ('other', 'Other'),
    ]

    client = models.ForeignKey(Client, on_delete=models.CASCADE)
    sale_date = models.DateTimeField(auto_now_add=True)
    total_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal('0.00')
    )
    payment_status = models.CharField(
        max_length=10,
        choices=PAYMENT_STATUS_CHOICES,
        default='unpaid'
    )
    payment_method = models.CharField(
        max_length=20,
        choices=PAYMENT_METHOD_CHOICES,
        blank=True,
        null=True
    )
    amount_paid = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal('0.00')
    )
    payment_date = models.DateTimeField(blank=True, null=True)

    def __str__(self):
        return f"Sale #{self.id} - {self.client.name} - {self.sale_date.date()} - {self.get_payment_status_display()}"

    def calculate_total_profit(self):
        return sum(item.profit_per_packet * item.quantity_packets for item in self.saleitem_set.all())

    def get_outstanding_amount(self):
        """Calculate how much is still owed"""
        return self.total_amount - self.amount_paid

    def is_fully_paid(self):
        """Check if the sale is fully paid"""
        return self.amount_paid >= self.total_amount

    def update_payment_status(self):
        """Automatically update payment status based on amount paid"""
        if self.amount_paid == 0:
            self.payment_status = 'unpaid'
        elif self.amount_paid >= self.total_amount:
            self.payment_status = 'paid'
            if not self.payment_date:
                self.payment_date = timezone.now()
        else:
            self.payment_status = 'partial'

        self.save()

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


class DeliveryEmployee(models.Model):
    """Delivery boy / employee who works with routes."""
    name = models.CharField(max_length=200)
    id_card_number = models.CharField(max_length=50)
    joining_date = models.DateField()

    # Split route into From/To so UI can ask "from where to where".
    # Stored as optional at DB level to allow existing rows created earlier to migrate.
    route_from = models.CharField(max_length=200, blank=True, default='')
    route_to = models.CharField(max_length=200, blank=True, default='')

    # Backwards-compatible single route string (used if route_from/to are empty).
    route = models.CharField(max_length=200)

    def __str__(self):
        if self.route_from and self.route_to:
            return f"{self.name} ({self.route_from} -> {self.route_to})"
        return f"{self.name} ({self.route})"

    class Meta:
        ordering = ['name']


class DeliveryExpense(models.Model):
    EXPENSE_TYPES = [
        ('bike_maintenance', 'Bike Maintenance'),
        ('fuel', 'Fuel'),
        ('food', 'Food'),
        ('salary', 'Salary'),
        ('note', 'Note'),
    ]

    employee = models.ForeignKey(DeliveryEmployee, on_delete=models.CASCADE)
    expense_type = models.CharField(max_length=30, choices=EXPENSE_TYPES)
    amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal('0.00'),
        validators=[MinValueValidator(Decimal('0.00'))],
        help_text="Set 0 for note-only expenses."
    )
    note = models.TextField(blank=True)
    expense_date = models.DateField(default=timezone.localdate)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)

    def __str__(self):
        return f"{self.employee.name} - {self.get_expense_type_display()} - {self.amount}"

    class Meta:
        ordering = ['-expense_date', '-id']

