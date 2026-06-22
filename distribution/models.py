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
    contact_info = models.CharField(max_length=200, blank=True, null=True, default='')
    address = models.TextField(blank=True, null=True, default='')

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
    available_quantity_packets = models.IntegerField(
        default=0,
        validators=[MinValueValidator(0)]
    )
    date_added = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.manufacturer.name} {self.type.name} {self.packet_size} kg"

    class Meta:
        ordering = ['manufacturer', 'type', 'packet_size']



class Client(models.Model):
    name = models.CharField(max_length=200)
    phone = models.CharField(max_length=20, blank=True, null=True, default='')
    address = models.TextField(blank=True, null=True, default='')
    previous_debt = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text="Initial debt brought forward from before system implementation"
    )
    date_added = models.DateTimeField(default=timezone.now, null=True)

    def __str__(self):
        return self.name

    @property
    def amount_owed(self):
        # Calculate total sales minus returned value, minus total payments, plus previous debt
        from django.db.models import Sum, F, DecimalField
        from django.db.models.functions import Coalesce
        
        # Get total sale amount
        total_sales = self.sale_set.filter(is_voided=False).aggregate(total=Sum('total_amount'))['total'] or Decimal('0.00')
        
        # Get total returned value (price per packet × quantity returned for each item)
        total_returned = Decimal('0.00')
        for sale in self.sale_set.filter(is_voided=False):
            for item in sale.saleitem_set.all():
                total_returned += item.selling_price_per_packet * item.quantity_returned
        
        # Get total paid
        total_paid = self.payment_set.filter(is_voided=False).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
        
        # Calculate: (total sales - returned value) - total paid + previous debt
        return total_sales - total_returned - total_paid + self.previous_debt

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
    date = models.DateTimeField(default=timezone.now)
    is_voided = models.BooleanField(default=False)
    voided_at = models.DateTimeField(null=True, blank=True)
    void_reason = models.TextField(blank=True)
    voided_by = models.ForeignKey(UserProfile, on_delete=models.SET_NULL, null=True, blank=True, related_name='voided_payments')
    mode = models.CharField(max_length=10, choices=PAYMENT_MODES)
    bank = models.CharField(max_length=100, blank=True, help_text="Required if mode is online")

    def __str__(self):
        status = 'VOID' if self.is_voided else f"{self.amount}"
        return f"{self.client.name} - {status} ({self.get_mode_display()}) on {self.date.date()}"

    class Meta:
        ordering = ['-date']


class ReceiptSettings(models.Model):
    company_name = models.CharField(max_length=200, default='Zain Traders')
    phone_number = models.CharField(max_length=30, default='03134628929')
    address = models.TextField(default='')
    updated_at = models.DateTimeField(auto_now=True)

    def save(self, *args, **kwargs):
        # Keep this as a single-row settings table.
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def load(cls):
        obj, _ = cls.objects.get_or_create(
            pk=1,
            defaults={
                'company_name': 'Zain Traders',
                'phone_number': '03134628929',
                'address': '',
            }
        )
        return obj

    def __str__(self):
        return self.company_name

    class Meta:
        verbose_name = 'Receipt Settings'
        verbose_name_plural = 'Receipt Settings'


class Sale(models.Model):
    client = models.ForeignKey(Client, on_delete=models.CASCADE)
    sale_date = models.DateTimeField(default=timezone.now)
    is_voided = models.BooleanField(default=False)
    voided_at = models.DateTimeField(null=True, blank=True)
    void_reason = models.TextField(blank=True)
    voided_by = models.ForeignKey(UserProfile, on_delete=models.SET_NULL, null=True, blank=True, related_name='voided_sales')
    total_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal('0.00')
    )

    def __str__(self):
        status = 'VOID' if self.is_voided else f'PKR {self.total_amount}'
        return f"Sale #{self.id} - {self.client.name} - {self.sale_date.date()} - {status}"

    def calculate_total_profit(self):
        if self.is_voided:
            return Decimal('0.00')
        return sum(item.profit_per_packet * item.quantity_packets for item in self.saleitem_set.all())

    class Meta:
        ordering = ['-sale_date']



class SaleItem(models.Model):
    sale = models.ForeignKey(Sale, on_delete=models.CASCADE)
    cheese_product = models.ForeignKey(CheeseProduct, on_delete=models.CASCADE)
    quantity_packets = models.IntegerField(
        validators=[MinValueValidator(1)]
    )
    quantity_returned = models.IntegerField(
        default=0,
        help_text="Quantity that has been returned"
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
    
    @property
    def quantity_available(self):
        """Get available quantity (sold - returned)"""
        return self.quantity_packets - self.quantity_returned

    def __str__(self):
        return f"{self.cheese_product} - {self.quantity_packets} packets"

    class Meta:
        ordering = ['id']


# Tracks each stock operation event (add/remove/price_change)
class StockAdditionHistory(models.Model):
    OPERATION_CHOICES = [
        ('add', 'Add Stock'),
        ('remove', 'Remove Stock'),
        ('price_change', 'Price Change'),
    ]
    
    operation_type = models.CharField(max_length=20, choices=OPERATION_CHOICES, default='add')
    added_by = models.ForeignKey(UserProfile, on_delete=models.SET_NULL, null=True)
    date_last_updated = models.DateTimeField(default=timezone.now)

    def __str__(self):
        item_count = self.stockadditionitem_set.count()
        return f"Stock {self.get_operation_type_display()} #{self.id} - {item_count} product(s) on {self.date_last_updated}" 

    def calculate_total_value(self):
        """Calculate total value of all items in this stock operation"""
        from decimal import Decimal
        total = Decimal('0.00')
        for item in self.stockadditionitem_set.all():
            total += item.get_total_value()
        return total

    class Meta:
        ordering = ['-date_last_updated']


# Individual items within a stock operation (add/remove/price_change)
class StockAdditionItem(models.Model):
    stock_addition = models.ForeignKey(StockAdditionHistory, on_delete=models.CASCADE)
    cheese_product = models.ForeignKey(CheeseProduct, on_delete=models.CASCADE)
    quantity_packets = models.IntegerField()  # Integer only
    old_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    new_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)

    def get_total_value(self):
        return self.quantity_packets * self.cheese_product.purchase_price_per_packet

    def __str__(self):
        return f"{self.cheese_product} - {self.quantity_packets} packets"

    class Meta:
        ordering = ['id']


# Track all actions on sales: returns, quantity changes, price changes, item additions
class SaleAction(models.Model):
    """
    Unified model to track all modifications to a sale and its items.
    Supports: returns, quantity additions, price changes, and item additions.
    """
    ACTION_TYPES = [
        ('return', 'Return Items'),
        ('quantity_add', 'Add Quantity'),
        ('price_change', 'Change Price'),
        ('item_add', 'Add New Item'),
        ('date_change', 'Change Sale Date'),
        ('void', 'Void Sale'),
    ]
    
    sale = models.ForeignKey(Sale, on_delete=models.CASCADE, related_name='actions', null=True, blank=True)
    sale_item = models.ForeignKey(SaleItem, on_delete=models.CASCADE, null=True, blank=True, related_name='actions')
    stock_addition = models.ForeignKey(StockAdditionHistory, on_delete=models.CASCADE, null=True, blank=True)
    
    action_type = models.CharField(max_length=20, choices=ACTION_TYPES)
    quantity_change = models.IntegerField(null=True, blank=True)  # Can be positive or negative
    old_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    new_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    old_sale_date = models.DateTimeField(null=True, blank=True)
    new_sale_date = models.DateTimeField(null=True, blank=True)
    
    reason = models.TextField(blank=True, help_text="Reason for the action (e.g., customer return reason)")
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(UserProfile, on_delete=models.SET_NULL, null=True, blank=True)

    def __str__(self):
        action_label = self.get_action_type_display()
        if self.sale_item and self.sale:
            return f"{action_label} - Sale Item #{self.sale_item.id} on Sale #{self.sale.id}"
        if self.sale:
            return f"{action_label} - Sale #{self.sale.id}"
        if self.stock_addition:
            return f"{action_label} - Stock Addition #{self.stock_addition.id}"
        return action_label

    class Meta:
        ordering = ['-created_at']
        verbose_name_plural = 'Sale Actions'


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


class PaymentAction(models.Model):
    ACTION_TYPES = [
        ('amount_change', 'Change Amount'),
        ('date_change', 'Change Payment Date'),
        ('mode_change', 'Change Payment Mode'),
        ('void', 'Void Payment'),
    ]

    payment = models.ForeignKey(Payment, on_delete=models.CASCADE, related_name='actions')
    action_type = models.CharField(max_length=20, choices=ACTION_TYPES)

    old_amount = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    new_amount = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    old_date = models.DateTimeField(null=True, blank=True)
    new_date = models.DateTimeField(null=True, blank=True)
    old_mode = models.CharField(max_length=10, blank=True)
    new_mode = models.CharField(max_length=10, blank=True)
    old_bank = models.CharField(max_length=100, blank=True)
    new_bank = models.CharField(max_length=100, blank=True)

    reason = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(UserProfile, on_delete=models.SET_NULL, null=True, blank=True)

    def __str__(self):
        return f"{self.get_action_type_display()} - Payment #{self.payment_id}"

    class Meta:
        ordering = ['-created_at']
        verbose_name_plural = 'Payment Actions'


class DeliveryExpense(models.Model):
    EXPENSE_TYPES = [
        ('bike_maintenance', 'Bike Maintenance'),
        ('fuel', 'Fuel'),
        ('food', 'Food'),
        ('salary', 'Salary'),
        ('general', 'General'),
    ]

    employee = models.ForeignKey(DeliveryEmployee, on_delete=models.CASCADE, null=True, blank=True)
    expense_type = models.CharField(max_length=30, choices=EXPENSE_TYPES)
    amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal('0.00'),
        validators=[MinValueValidator(Decimal('0.00'))]
    )
    note = models.TextField(blank=True)
    expense_date = models.DateField(default=timezone.localdate)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    is_voided = models.BooleanField(default=False)
    voided_at = models.DateTimeField(null=True, blank=True)
    void_reason = models.TextField(blank=True)
    voided_by = models.ForeignKey(UserProfile, on_delete=models.SET_NULL, null=True, blank=True, related_name='voided_expenses')

    def __str__(self):
        employee_name = self.employee.name if self.employee else 'N/A'
        status = 'VOID' if self.is_voided else f'{self.amount}'
        return f"{employee_name} - {self.get_expense_type_display()} - {status}"

    class Meta:
        ordering = ['-expense_date', '-id']


class ExpenseAction(models.Model):
    """Track all modifications to expenses: date, type, amount, employee changes and voids."""
    ACTION_TYPES = [
        ('date_change', 'Change Expense Date'),
        ('type_change', 'Change Expense Type'),
        ('amount_change', 'Change Amount'),
        ('employee_change', 'Change Employee'),
        ('void', 'Void Expense'),
    ]

    expense = models.ForeignKey(DeliveryExpense, on_delete=models.CASCADE, related_name='actions')
    action_type = models.CharField(max_length=20, choices=ACTION_TYPES)

    old_date = models.DateField(null=True, blank=True)
    new_date = models.DateField(null=True, blank=True)
    old_type = models.CharField(max_length=30, blank=True)
    new_type = models.CharField(max_length=30, blank=True)
    old_amount = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    new_amount = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    old_employee_id = models.IntegerField(null=True, blank=True)
    new_employee_id = models.IntegerField(null=True, blank=True)

    reason = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(UserProfile, on_delete=models.SET_NULL, null=True, blank=True)

    def __str__(self):
        return f"{self.get_action_type_display()} - Expense #{self.expense_id}"

    class Meta:
        ordering = ['-created_at']
        verbose_name_plural = 'Expense Actions'


class SiteActivity(models.Model):
    """Track the last activity/action on the site for display purposes"""
    last_activity_time = models.DateTimeField(auto_now=True)
    last_activity_description = models.CharField(max_length=255, default='')
    
    class Meta:
        verbose_name_plural = "Site Activity"
    
    def __str__(self):
        return f"Last activity: {self.last_activity_time}"
    
    @classmethod
    def update_activity(cls, description):
        """Update the last activity timestamp and description"""
        activity, created = cls.objects.get_or_create(pk=1)
        activity.last_activity_description = description
        activity.save(update_fields=['last_activity_description', 'last_activity_time'])

