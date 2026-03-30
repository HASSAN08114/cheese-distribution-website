from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib.auth import authenticate, login, logout
from django.contrib import messages
from django.db import models
from django.db.models import Sum, Q
from django.db import transaction
from django.utils import timezone
from datetime import datetime, timedelta
from decimal import Decimal
from .models import (
    Manufacturer, CheeseProduct, Client, Sale, SaleItem, UserProfile, Payment,
    DeliveryEmployee, DeliveryExpense, SiteActivity,
)
from .forms import (
    ManufacturerForm, CheeseProductForm, ClientForm,
    SaleItemForm, SaleItemFormSet, UserForm, UserRoleForm, AddStockForm, AddStockFormSet,
    PaymentForm, DeliveryEmployeeForm, DeliveryExpenseForm,
)
from .forms import CheeseTypeForm
from .decorators import owner_required, is_owner


from django.http import JsonResponse
from django.template.loader import render_to_string
from django.shortcuts import render
from .forms import CheeseTypeForm
from .models import CheeseType

# AJAX endpoint to process return for sale item
from django.views.decorators.http import require_POST

@login_required
@require_POST
def return_sale_item(request):
    item_id = request.POST.get('item_id')
    quantity = request.POST.get('quantity')
    reason = request.POST.get('reason', '')
    item = get_object_or_404(SaleItem, pk=item_id)
    quantity = Decimal(quantity)
    if quantity > item.quantity_packets:
        return JsonResponse({'success': False, 'error': 'Return quantity exceeds sold quantity.'})
    Return.objects.create(sale_item=item, quantity_packets=quantity, reason=reason)
    item.modified = True
    item.save()
    # Optionally, update cheese product stock
    item.cheese_product.available_quantity_packets += quantity
    item.cheese_product.save()
    return JsonResponse({'success': True})

# AJAX endpoint to process return for all sale items in a sale
@login_required
@require_POST
def return_all_sale_items(request):
    sale_id = request.POST.get('sale_id')
    reason = request.POST.get('reason', '')
    sale = get_object_or_404(Sale, pk=sale_id)
    for item in sale.saleitem_set.all():
        Return.objects.create(sale_item=item, quantity_packets=item.quantity_packets, reason=reason)
        item.modified = True
        item.cheese_product.available_quantity_packets += item.quantity_packets
        item.cheese_product.save()
        item.save()
    return JsonResponse({'success': True})

# AJAX endpoint to add stock to a product
@login_required
@require_POST
def add_stock_quantity(request):
    from .models import StockAdditionItem
    product_id = request.POST.get('product_id')
    quantity = request.POST.get('quantity')
    
    product = get_object_or_404(CheeseProduct, pk=product_id)
    quantity = int(quantity)
    
    if quantity <= 0:
        return JsonResponse({'success': False, 'error': 'Quantity must be greater than 0'})
    
    # Create stock addition event
    stock_addition = StockAdditionHistory.objects.create(
        operation_type='add',
        added_by=request.user.userprofile
    )
    
    # Create stock item
    StockAdditionItem.objects.create(
        stock_addition=stock_addition,
        cheese_product=product,
        quantity_packets=quantity
    )
    
    # Update product stock
    product.available_quantity_packets += quantity
    product.save()
    
    SiteActivity.update_activity(f'Added {quantity} packets to {product}')
    return JsonResponse({'success': True, 'message': f'Added {quantity} packets to {product}'})

# AJAX endpoint to remove stock from a product
@login_required
@require_POST
def remove_stock_quantity(request):
    from .models import StockAdditionItem
    product_id = request.POST.get('product_id')
    quantity = request.POST.get('quantity')
    
    product = get_object_or_404(CheeseProduct, pk=product_id)
    quantity = int(quantity)
    
    if quantity <= 0:
        return JsonResponse({'success': False, 'error': 'Quantity must be greater than 0'})
    
    if product.available_quantity_packets < quantity:
        return JsonResponse({'success': False, 'error': f'Insufficient stock. Available: {product.available_quantity_packets}'})
    
    # Create stock removal event
    stock_addition = StockAdditionHistory.objects.create(
        operation_type='remove',
        added_by=request.user.userprofile
    )
    
    # Create stock item (negative quantity for removal)
    StockAdditionItem.objects.create(
        stock_addition=stock_addition,
        cheese_product=product,
        quantity_packets=-quantity
    )
    
    # Update product stock
    product.available_quantity_packets -= quantity
    product.save()
    
    SiteActivity.update_activity(f'Removed {quantity} packets from {product}')
    return JsonResponse({'success': True, 'message': f'Removed {quantity} packets from {product}'})

# AJAX endpoint to change product price
@login_required
@require_POST
def change_stock_price(request):
    from .models import StockAdditionItem
    product_id = request.POST.get('product_id')
    new_price = request.POST.get('new_price')
    
    product = get_object_or_404(CheeseProduct, pk=product_id)
    old_price = product.purchase_price_per_packet
    new_price = Decimal(new_price)
    
    if new_price <= 0:
        return JsonResponse({'success': False, 'error': 'Price must be greater than 0'})
    
    # Create price change event
    stock_addition = StockAdditionHistory.objects.create(
        operation_type='price_change',
        added_by=request.user.userprofile
    )
    
    # Create stock item with price info
    StockAdditionItem.objects.create(
        stock_addition=stock_addition,
        cheese_product=product,
        quantity_packets=0,  # No quantity change for price updates
        old_price=old_price,
        new_price=new_price
    )
    
    # Update product price
    product.purchase_price_per_packet = new_price
    product.save()
    
    SiteActivity.update_activity(f'Changed price of {product}: {old_price} → {new_price}')
    return JsonResponse({'success': True, 'message': f'Price updated from {old_price} to {new_price}'})

from django.views.decorators.http import require_GET

@login_required
@require_GET
def sale_modal_details(request, pk):
    sale = get_object_or_404(Sale, pk=pk)
    sale_items = sale.saleitem_set.select_related('cheese_product').all()
    total_profit = sale.calculate_total_profit()
    return render(request, 'distribution/sales/partials/partial_sale_modal_details.html', {
        'sale': sale,
        'sale_items': sale_items,
        'total_profit': total_profit
    })

# AJAX endpoint for stock modal details
@login_required
@require_GET
def stock_modal_details(request, pk):
    addition = get_object_or_404(StockAdditionHistory, pk=pk)
    items = addition.stockadditionitem_set.select_related('cheese_product').all()
    total_value = addition.calculate_total_value()
    
    return render(request, 'distribution/inventory/partials/partial_stock_modal_details.html', {
        'addition': addition,
        'items': items,
        'total_value': total_value,
    })

from .models import StockAdditionHistory, Return


@login_required
def stock_history(request):
    from .models import StockAdditionItem
    stock_additions = StockAdditionHistory.objects.prefetch_related('stockadditionitem_set__cheese_product', 'added_by').all()
    
    # Get products for quick stock form
    products = CheeseProduct.objects.select_related('manufacturer', 'type').all()
    products_with_value = []
    for product in products:
        stock_value = product.available_quantity_packets * product.purchase_price_per_packet
        products_with_value.append({
            'product': product,
            'stock_value': stock_value
        })
    
    return render(request, 'distribution/inventory/stock_history.html', {
        'stock_additions': stock_additions,
        'add_stock_formset': AddStockFormSet(),
        'products_with_value': products_with_value,
    })

@login_required
def cheese_type_add(request):
    if request.method == 'POST':
        form = CheeseTypeForm(request.POST)
        if form.is_valid():
            form.save()
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'success': True})
            messages.success(request, 'Cheese type added successfully.')
            return redirect('inventory_management')
        else:
            # Extract error message
            error_msg = ''
            if 'name' in form.errors:
                error_msg = form.errors['name'][0]
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                html = render_to_string('distribution/inventory/partials/partial_edit_cheese_type_form.html', {'form': form}, request=request)
                return JsonResponse({'success': False, 'html': html, 'error': error_msg})
    else:
        form = CheeseTypeForm()
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        html = render_to_string('distribution/inventory/partials/partial_edit_cheese_type_form.html', {'form': form}, request=request)
        return JsonResponse({'success': False, 'html': html})
    return render(request, 'distribution/cheese_type_form.html', {'form': form})

@login_required
def cheese_type_edit(request, pk):
    cheese_type = CheeseType.objects.get(pk=pk)
    if request.method == 'POST':
        form = CheeseTypeForm(request.POST, instance=cheese_type)
        if form.is_valid():
            form.save()
            messages.success(request, 'Cheese type updated successfully.')
            return redirect('inventory_management')
    else:
        form = CheeseTypeForm(instance=cheese_type)
    html = render_to_string('distribution/inventory/partials/partial_edit_cheese_type_form.html', {'form': form, 'cheese_type': cheese_type}, request=request)
    return JsonResponse({'html': html})

@login_required
def cheese_type_delete(request, pk):
    cheese_type = CheeseType.objects.get(pk=pk)
    if request.method == 'POST':
        cheese_type.delete()
        messages.success(request, 'Cheese type deleted successfully.')
        return redirect('inventory_management')
    html = render_to_string('distribution/cheese_type_delete.html', {'cheese_type': cheese_type}, request=request)
    return JsonResponse({'html': html})

def login_view(request):
    if request.user.is_authenticated:
        if request.user.userprofile.role == 'owner':
            return redirect('dashboard')
        return redirect('inventory_management')
    
    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')
        user = authenticate(request, username=username, password=password)
        if user is not None:
            login(request, user)
            return redirect('dashboard')
        else:
            messages.error(request, 'Invalid username or password.')
    return render(request, 'distribution/login.html')


def logout_view(request):
    logout(request)
    return redirect('login')


@login_required
def dashboard(request):
    user_is_owner = is_owner(request.user)
    
    # Get last activity
    last_activity = SiteActivity.objects.filter(pk=1).first()

    # Calculate today's expenses
    today = timezone.localdate()
    from django.db.models import Sum
    daily_expenses = DeliveryExpense.objects.filter(expense_date=today).aggregate(total=Sum('amount'))['total'] or 0

    context = {
        'user_is_owner': user_is_owner,
        'last_activity': last_activity,
        'daily_expenses': daily_expenses,
    }
    return render(request, 'distribution/dashboard.html', context)


@login_required
def get_client_analytics(request):
    """AJAX endpoint to get client analytics based on time period"""
    period = request.GET.get('period', 'all')

    now = timezone.now()

    if period == 'today':
        start_date = now.date()
        end_date = now.date()
    elif period == 'week':
        start_date = now.date() - timedelta(days=7)
        end_date = now.date()
    elif period == 'month':
        start_date = now.date() - timedelta(days=30)
        end_date = now.date()
    elif period == 'quarter':
        start_date = now.date() - timedelta(days=90)
        end_date = now.date()
    elif period == '6months':
        start_date = now.date() - timedelta(days=180)
        end_date = now.date()
    elif period == 'year':
        start_date = now.date() - timedelta(days=365)
        end_date = now.date()
    else:  # 'all'
        start_date = None
        end_date = None

    # Get all clients
    clients = Client.objects.all()
    client_data = []

    for client in clients:
        # Filter sales by date range
        if start_date and end_date:
            client_sales = Sale.objects.filter(client=client, sale_date__date__range=[start_date, end_date])
        else:
            client_sales = Sale.objects.filter(client=client)

        if client_sales.exists():
            total_sales = client_sales.aggregate(
                total=Sum('total_amount')
            )['total'] or Decimal('0.00')

            total_profit = sum(sale.calculate_total_profit() for sale in client_sales)

            # Count total sales transactions
            total_transactions = client_sales.count()

            # Get last sale date
            last_sale_date = client_sales.order_by('-sale_date').first().sale_date.date() if client_sales.exists() else None

            client_data.append({
                'id': client.id,
                'name': client.name,
                'phone': client.phone,
                'total_sales': float(total_sales),
                'total_profit': float(total_profit),
                'total_transactions': total_transactions,
                'last_sale_date': last_sale_date.strftime('%Y-%m-%d') if last_sale_date else None,
                'avg_sale': float(total_sales / total_transactions) if total_transactions > 0 else 0,
            })

    # Sort by profit descending
    client_data.sort(key=lambda x: x['total_profit'], reverse=True)

    # Calculate summary stats
    total_clients = len(client_data)
    total_revenue = sum(client['total_sales'] for client in client_data)
    total_profit_all = sum(client['total_profit'] for client in client_data)
    total_transactions_all = sum(client['total_transactions'] for client in client_data)

    # Calculate total outstanding debt from ALL sales
    # Using Payment model to find what has been paid
    clients_all = Client.objects.all()
    total_outstanding = Decimal('0.00')
    for client in clients_all:
        client_sales = Sale.objects.filter(client=client)
        if client_sales.exists():
            total_sales_amount = client_sales.aggregate(total=Sum('total_amount'))['total'] or Decimal('0.00')
            total_amount_paid = Payment.objects.filter(client=client).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
            outstanding_amount = total_sales_amount - total_amount_paid
            if outstanding_amount > 0:
                total_outstanding += outstanding_amount

    summary = {
        'total_clients': total_clients,
        'total_revenue': float(total_revenue),
        'total_profit': float(total_profit_all),
        'total_transactions': total_transactions_all,
        'avg_client_value': float(total_revenue / total_clients) if total_clients > 0 else 0,
        'total_outstanding': float(total_outstanding),
    }

    return JsonResponse({
        'clients': client_data,
        'summary': summary,
        'period': period
    })


@login_required
def get_product_analytics(request):
    """AJAX endpoint to get product analytics based on time period"""
    period = request.GET.get('period', 'all')

    now = timezone.now()

    if period == 'today':
        start_date = now.date()
        end_date = now.date()
    elif period == 'week':
        start_date = now.date() - timedelta(days=7)
        end_date = now.date()
    elif period == 'month':
        start_date = now.date() - timedelta(days=30)
        end_date = now.date()
    elif period == 'quarter':
        start_date = now.date() - timedelta(days=90)
        end_date = now.date()
    elif period == '6months':
        start_date = now.date() - timedelta(days=180)
        end_date = now.date()
    elif period == 'year':
        start_date = now.date() - timedelta(days=365)
        end_date = now.date()
    else:  # 'all'
        start_date = None
        end_date = None

    # Get all products with sales data
    products = CheeseProduct.objects.all()
    product_data = []

    for product in products:
        # Filter sale items by date range
        if start_date and end_date:
            product_sales = SaleItem.objects.filter(
                cheese_product=product,
                sale__sale_date__date__range=[start_date, end_date]
            )
        else:
            product_sales = SaleItem.objects.filter(cheese_product=product)

        if product_sales.exists():
            # Calculate totals by iterating through sales items
            total_quantity = Decimal('0.00')
            total_revenue = Decimal('0.00')
            total_profit = Decimal('0.00')
            
            for item in product_sales:
                total_quantity += item.quantity_packets
                item_revenue = item.quantity_packets * item.selling_price_per_packet
                total_revenue += item_revenue
                item_profit = (item.selling_price_per_packet - product.purchase_price_per_packet) * item.quantity_packets
                total_profit += item_profit

            # Transaction count
            transaction_count = product_sales.count()

            # Current stock level
            current_stock = product.available_quantity_packets

            # Stock turnover (sold / current stock)
            stock_turnover = float(total_quantity / current_stock) if current_stock > 0 else 0

            # Profit margin percentage
            profit_margin = (float(total_profit) / float(total_revenue) * 100) if total_revenue > 0 else 0

            product_data.append({
                'id': product.id,
                'name': f"{product.manufacturer.name} {product.type.name} {product.packet_size}kg",
                'manufacturer': product.manufacturer.name,
                'type': product.type.name,
                'packet_size': float(product.packet_size),
                'purchase_price': float(product.purchase_price_per_packet),
                'total_quantity_sold': float(total_quantity),
                'total_revenue': float(total_revenue),
                'total_profit': float(total_profit),
                'transaction_count': transaction_count,
                'current_stock': float(current_stock),
                'stock_turnover': stock_turnover,
                'profit_margin': profit_margin,
                'avg_sale_price': float(total_revenue / total_quantity) if total_quantity > 0 else 0,
            })

    # Sort by revenue descending (most sold)
    product_data.sort(key=lambda x: x['total_revenue'], reverse=True)

    # Calculate summary stats
    total_products = len(product_data)
    total_revenue = sum(product['total_revenue'] for product in product_data)
    total_profit = sum(product['total_profit'] for product in product_data)
    total_quantity = sum(product['total_quantity_sold'] for product in product_data)

    # Get top and bottom performers
    top_performers = product_data[:5] if len(product_data) >= 5 else product_data
    bottom_performers = product_data[-5:] if len(product_data) >= 5 else product_data[-len(product_data):]

    # Stock alerts
    low_stock_products = [p for p in product_data if p['current_stock'] < 10]
    out_of_stock_products = [p for p in product_data if p['current_stock'] == 0]

    summary = {
        'total_products': total_products,
        'total_revenue': float(total_revenue),
        'total_profit': float(total_profit),
        'total_quantity_sold': float(total_quantity),
        'avg_product_revenue': float(total_revenue / total_products) if total_products > 0 else 0,
        'low_stock_count': len(low_stock_products),
        'out_of_stock_count': len(out_of_stock_products),
    }

    return JsonResponse({
        'products': product_data,
        'top_performers': top_performers,
        'bottom_performers': bottom_performers,
        'low_stock_products': low_stock_products,
        'out_of_stock_products': out_of_stock_products,
        'summary': summary,
        'period': period
    })


@login_required
def get_general_metrics(request):
    """AJAX endpoint to get general business metrics based on time period"""
    period = request.GET.get('period', 'all')

    now = timezone.now()

    if period == 'today':
        start_date = now.date()
        end_date = now.date()
    elif period == 'week':
        start_date = now.date() - timedelta(days=7)
        end_date = now.date()
    elif period == 'month':
        start_date = now.date() - timedelta(days=30)
        end_date = now.date()
    elif period == 'quarter':
        start_date = now.date() - timedelta(days=90)
        end_date = now.date()
    elif period == '6months':
        start_date = now.date() - timedelta(days=180)
        end_date = now.date()
    elif period == 'year':
        start_date = now.date() - timedelta(days=365)
        end_date = now.date()
    else:  # 'all'
        start_date = None
        end_date = None

    # Get general metrics
    if start_date and end_date:
        sales_queryset = Sale.objects.filter(sale_date__date__range=[start_date, end_date])
        expenses_queryset = DeliveryExpense.objects.filter(expense_date__range=[start_date, end_date])
    else:
        sales_queryset = Sale.objects.all()
        expenses_queryset = DeliveryExpense.objects.all()

    # Total Revenue
    total_revenue = sales_queryset.aggregate(total=Sum('total_amount'))['total'] or Decimal('0.00')

    # Total Expenses
    total_expenses = expenses_queryset.aggregate(total=Sum('amount'))['total'] or Decimal('0.00')

    # Total Profit (from sales)
    total_profit = sum(sale.calculate_total_profit() for sale in sales_queryset)
    
    # Net Profit (Profit - Expenses)
    net_profit = float(total_profit) - float(total_expenses)

    # Total Sales Count
    total_sales_count = sales_queryset.count()

    # Average Sale Value
    avg_sale_value = float(total_revenue) / total_sales_count if total_sales_count > 0 else 0

    # Total clients this period
    clients_this_period = sales_queryset.values('client').distinct().count()

    # Total products sold
    total_items_sold = SaleItem.objects.filter(sale__in=sales_queryset).aggregate(
        total=Sum('quantity_packets')
    )['total'] or Decimal('0.00')

    summary = {
        'total_revenue': float(total_revenue),
        'total_expenses': float(total_expenses),
        'total_profit': float(total_profit),
        'net_profit': float(net_profit),
        'total_sales_count': total_sales_count,
        'avg_sale_value': avg_sale_value,
        'clients_this_period': clients_this_period,
        'total_items_sold': float(total_items_sold),
    }

    return JsonResponse({
        'summary': summary,
        'period': period
    })


@login_required
def get_dashboard_overview(request):
    """Endpoint to get general dashboard overview metrics (not time-dependent)"""
    # Total Outstanding Debt
    total_outstanding = Decimal('0.00')
    clients_all = Client.objects.all()
    for client in clients_all:
        client_sales = Sale.objects.filter(client=client)
        if client_sales.exists():
            total_sales_amount = client_sales.aggregate(total=Sum('total_amount'))['total'] or Decimal('0.00')
            total_amount_paid = Payment.objects.filter(client=client).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
            outstanding_amount = total_sales_amount - total_amount_paid
            if outstanding_amount > 0:
                total_outstanding += outstanding_amount

    # Total Clients
    total_clients_count = Client.objects.count()

    # Total Products
    total_products_count = CheeseProduct.objects.count()

    # Total Stock Value (current stock * price)
    total_stock_value = Decimal('0.00')
    for product in CheeseProduct.objects.all():
        stock_value = product.available_quantity_packets * product.purchase_price_per_packet
        total_stock_value += stock_value

    # Payment amounts by status
    # Total Paid: sum of all payments
    total_paid_amount = Payment.objects.aggregate(total=Sum('amount'))['total'] or Decimal('0.00')

    # Total Partial Pending: sales that have some but not full payment
    total_partial_pending = Decimal('0.00')
    for client in clients_all:
        client_sales = Sale.objects.filter(client=client)
        client_total_sales = client_sales.aggregate(total=Sum('total_amount'))['total'] or Decimal('0.00')
        client_total_paid = Payment.objects.filter(client=client).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
        
        if Decimal('0.00') < client_total_paid < client_total_sales:
            outstanding = client_total_sales - client_total_paid
            total_partial_pending += outstanding

    # Total Unpaid: unpaid portion of all sales (total_sales - total_paid, but only count if > 0 and <= sales)
    total_unpaid_amount = Decimal('0.00')
    for client in clients_all:
        client_sales = Sale.objects.filter(client=client)
        client_total_sales = client_sales.aggregate(total=Sum('total_amount'))['total'] or Decimal('0.00')
        client_total_paid = Payment.objects.filter(client=client).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
        
        outstanding = client_total_sales - client_total_paid
        if outstanding > 0:
            total_unpaid_amount += outstanding

    summary = {
        'total_outstanding': float(total_outstanding),
        'total_clients': total_clients_count,
        'total_products': total_products_count,
        'total_stock_value': float(total_stock_value),
        'total_paid_amount': float(total_paid_amount),
        'total_partial_amount': float(total_partial_pending),
        'total_unpaid_amount': float(total_unpaid_amount),
    }

    return JsonResponse({
        'summary': summary
    })


@login_required
def get_sales_history(request):
    """AJAX endpoint to get sales history"""
    period = request.GET.get('period', 'all')

    now = timezone.now()

    if period == 'today':
        start_date = now.date()
        end_date = now.date()
    elif period == 'week':
        start_date = now.date() - timedelta(days=7)
        end_date = now.date()
    elif period == 'month':
        start_date = now.date() - timedelta(days=30)
        end_date = now.date()
    elif period == 'quarter':
        start_date = now.date() - timedelta(days=90)
        end_date = now.date()
    elif period == '6months':
        start_date = now.date() - timedelta(days=180)
        end_date = now.date()
    elif period == 'year':
        start_date = now.date() - timedelta(days=365)
        end_date = now.date()
    else:  # 'all'
        start_date = None
        end_date = None

    # Get sales
    if start_date and end_date:
        sales = Sale.objects.filter(sale_date__date__range=[start_date, end_date]).select_related('client')
    else:
        sales = Sale.objects.all().select_related('client')

    sales_data = []
    for sale in sales:
        sales_data.append({
            'id': sale.id,
            'client_name': sale.client.name,
            'client_phone': sale.client.phone,
            'sale_date': sale.sale_date.strftime('%Y-%m-%d %H:%M'),
            'total_amount': float(sale.total_amount),
            'total_profit': float(sale.calculate_total_profit()),
        })

    # Sort by date descending
    sales_data.sort(key=lambda x: x['sale_date'], reverse=True)

    # Calculate summary stats
    total_sales = len(sales_data)
    total_revenue = sum(sale['total_amount'] for sale in sales_data)
    total_profit = sum(sale['total_profit'] for sale in sales_data)

    summary = {
        'total_sales': total_sales,
        'total_revenue': float(total_revenue),
        'total_profit': float(total_profit),
    }

    return JsonResponse({
        'sales': sales_data,
        'summary': summary,
        'period': period
    })


@login_required
def get_stock_history(request):
    """AJAX endpoint to get stock addition history"""
    period = request.GET.get('period', 'all')

    now = timezone.now()

    if period == 'today':
        start_date = now.date()
        end_date = now.date()
    elif period == 'week':
        start_date = now.date() - timedelta(days=7)
        end_date = now.date()
    elif period == 'month':
        start_date = now.date() - timedelta(days=30)
        end_date = now.date()
    elif period == 'quarter':
        start_date = now.date() - timedelta(days=90)
        end_date = now.date()
    elif period == '6months':
        start_date = now.date() - timedelta(days=180)
        end_date = now.date()
    elif period == 'year':
        start_date = now.date() - timedelta(days=365)
        end_date = now.date()
    else:  # 'all'
        start_date = None
        end_date = None

    # Get stock addition history with items
    from .models import StockAdditionHistory, StockAdditionItem
    if start_date and end_date:
        stock_additions = StockAdditionHistory.objects.filter(
            date_added__date__range=[start_date, end_date]
        ).prefetch_related('stockadditionitem_set__cheese_product__manufacturer', 'stockadditionitem_set__cheese_product__type', 'added_by__user')
    else:
        stock_additions = StockAdditionHistory.objects.all().prefetch_related(
            'stockadditionitem_set__cheese_product__manufacturer', 'stockadditionitem_set__cheese_product__type', 'added_by__user'
        )

    stock_data = []
    for stock_addition in stock_additions:
        for item in stock_addition.stockadditionitem_set.all():
            stock_data.append({
                'id': item.id,
                'addition_id': stock_addition.id,
                'product_name': f"{item.cheese_product.manufacturer.name} {item.cheese_product.type.name} {item.cheese_product.packet_size}kg",
                'quantity_packets': float(item.quantity_packets),
                'quantity_returned': float(item.quantity_returned),
                'date_added': stock_addition.date_added.strftime('%Y-%m-%d %H:%M'),
                'added_by': stock_addition.added_by.user.username if stock_addition.added_by else 'Unknown',
                'modified': stock_addition.modified,
            })

    # Sort by date descending
    stock_data.sort(key=lambda x: x['date_added'], reverse=True)

    # Calculate summary stats
    total_stock_additions = len(stock_data)
    total_packets_added = sum(item['quantity_packets'] for item in stock_data)
    total_packets_returned = sum(item['quantity_returned'] for item in stock_data)

    # Group by product for summary
    product_summary = {}
    for item in stock_data:
        if item['product_name'] not in product_summary:
            product_summary[item['product_name']] = {'added': 0, 'returned': 0}
        product_summary[item['product_name']]['added'] += item['quantity_packets']
        product_summary[item['product_name']]['returned'] += item['quantity_returned']

    summary = {
        'total_stock_additions': total_stock_additions,
        'total_packets_added': float(total_packets_added),
        'total_packets_returned': float(total_packets_returned),
        'unique_products': len(product_summary),
        'product_summary': product_summary,
    }

    return JsonResponse({
        'stock_history': stock_data,
        'summary': summary,
        'period': period
    })


@login_required
def get_product_stock(request, product_id):
    """API endpoint to get stock information for a specific product"""
    try:
        product = CheeseProduct.objects.get(pk=product_id)
        return JsonResponse({
            'id': product.id,
            'name': f"{product.manufacturer.name} {product.type.name} {product.packet_size}kg",
            'available_quantity': float(product.available_quantity_packets),
            'purchase_price': float(product.purchase_price_per_packet),
        })
    except CheeseProduct.DoesNotExist:
        return JsonResponse({'error': 'Product not found'}, status=404)


@owner_required
def inventory_management(request):
    """Merged page for manufacturers and cheese inventory"""
    manufacturers = Manufacturer.objects.all()
    products = CheeseProduct.objects.select_related('manufacturer').all()
    cheese_types = CheeseType.objects.all()
    # Calculate stock value for each product
    products_with_value = []
    total_stock_quantity = Decimal('0.00')
    low_stock_products = []
    
    for product in products:
        stock_value = product.available_quantity_packets * product.purchase_price_per_packet
        total_stock_quantity += product.available_quantity_packets
        products_with_value.append({
            'product': product,
            'stock_value': stock_value
        })
        # Track low stock products (less than 10 packets)
        if product.available_quantity_packets < 10:
            low_stock_products.append({
                'product': product,
                'stock_value': stock_value,
                'quantity': product.available_quantity_packets
            })
    
    # Sort low stock products by quantity (lowest first)
    low_stock_products.sort(key=lambda x: x['quantity'])

    from .forms import ManufacturerForm, CheeseProductForm, SaleItemFormSet
    manufacturer_form = ManufacturerForm()
    cheese_product_form = CheeseProductForm()
    cheese_type_form = CheeseTypeForm()
    add_stock_formset = AddStockFormSet()
    sale_item_formset = SaleItemFormSet()
    
    inventory_summary = {
        'total_products': len(products),
        'total_stock_quantity': float(total_stock_quantity),
        'low_stock_count': len(low_stock_products),
    }
    
    user_is_owner = is_owner(request.user)
    
    return render(request, 'distribution/inventory/management.html', {
        'manufacturers': manufacturers,
        'products_with_value': products_with_value,
        'products': products,
        'manufacturer_form': manufacturer_form,
        'cheese_product_form': cheese_product_form,
        'cheese_type_form': cheese_type_form,
        'add_stock_formset': add_stock_formset,
        'formset': sale_item_formset,
        'cheese_types': cheese_types,
        'low_stock_products': low_stock_products,
        'inventory_summary': inventory_summary,
        'clients': Client.objects.all(),
        'user_is_owner': user_is_owner,
    })


@owner_required
def manufacturer_add(request):
    if request.method == 'POST':
        form = ManufacturerForm(request.POST)
        if form.is_valid():
            form.save()
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'success': True})
            messages.success(request, 'Manufacturer added successfully.')
            return redirect('inventory_management')
        else:
            # Extract error message
            error_msg = ''
            if 'name' in form.errors:
                error_msg = form.errors['name'][0]
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                html = render_to_string('distribution/inventory/partials/partial_edit_manufacturer_form.html', {'form': form}, request=request)
                return JsonResponse({'success': False, 'html': html, 'error': error_msg})
    else:
        form = ManufacturerForm()
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        html = render_to_string('distribution/inventory/partials/partial_edit_manufacturer_form.html', {'form': form}, request=request)
        return JsonResponse({'success': False, 'html': html})
    return render(request, 'distribution/manufacturer_form.html', {'form': form, 'title': 'Add Manufacturer'})


@owner_required
def manufacturer_edit(request, pk):
    manufacturer = get_object_or_404(Manufacturer, pk=pk)
    if request.method == 'POST':
        form = ManufacturerForm(request.POST, instance=manufacturer)
        if form.is_valid():
            form.save()
            SiteActivity.update_activity(f'Manufacturer updated: {manufacturer.name}')
            if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                return render(request, 'distribution/shared/partial_edit_success.html', {'object': manufacturer, 'type': 'manufacturer'})
            messages.success(request, 'Manufacturer updated successfully.')
            return redirect('inventory_management')
    else:
        form = ManufacturerForm(instance=manufacturer)
    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        html = render_to_string('distribution/inventory/partials/partial_edit_manufacturer_form.html', {'form': form, 'manufacturer': manufacturer}, request=request)
        return JsonResponse({'html': html})
    return render(request, 'distribution/manufacturer_form.html', {'form': form, 'title': 'Edit Manufacturer'})


@owner_required
def manufacturer_delete(request, pk):
    manufacturer = get_object_or_404(Manufacturer, pk=pk)
    if request.method == 'POST':
        manufacturer_name = manufacturer.name
        manufacturer.delete()
        SiteActivity.update_activity(f'Manufacturer deleted: {manufacturer_name}')
        messages.success(request, 'Manufacturer deleted successfully.')
        return redirect('inventory_management')
    return render(request, 'distribution/manufacturer_delete.html', {'manufacturer': manufacturer})


@owner_required
def cheese_add(request):
    if request.method == 'POST':
        form = CheeseProductForm(request.POST)
        if form.is_valid():
            cheese_product = form.save()
            # Create stock addition history if initial quantity was added
            initial_quantity = form.cleaned_data['available_quantity_packets']
            if initial_quantity > 0:
                StockAdditionHistory.objects.create(
                    cheese_product=cheese_product,
                    added_by=request.user.userprofile,
                    quantity_packets=initial_quantity
                )
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'success': True})
            messages.success(request, 'Cheese product added successfully.')
            return redirect('inventory_management')
        else:
            # Extract error messages
            error_msg = ''
            if form.errors:
                error_msg = list(form.errors.values())[0][0]
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                html = render_to_string('distribution/inventory/partials/partial_edit_cheese_form.html', {'form': form}, request=request)
                return JsonResponse({'success': False, 'html': html, 'error': error_msg})
    else:
        form = CheeseProductForm()
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        html = render_to_string('distribution/inventory/partials/partial_edit_cheese_form.html', {'form': form}, request=request)
        return JsonResponse({'success': False, 'html': html})
    return render(request, 'distribution/cheese_form.html', {'form': form, 'title': 'Add Cheese Product'})


@owner_required
def cheese_edit(request, pk):
    product = get_object_or_404(CheeseProduct, pk=pk)
    if request.method == 'POST':
        form = CheeseProductForm(request.POST, instance=product)
        if form.is_valid():
            form.save()
            if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                return render(request, 'distribution/shared/partial_edit_success.html', {'object': product, 'type': 'cheese'})
            messages.success(request, 'Cheese product updated successfully.')
            return redirect('inventory_management')
    else:
        form = CheeseProductForm(instance=product)
    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        html = render_to_string('distribution/inventory/partials/partial_edit_cheese_form.html', {'form': form, 'product': product}, request=request)
        return JsonResponse({'html': html})
    return render(request, 'distribution/cheese_form.html', {'form': form, 'title': 'Edit Cheese Product'})


@owner_required
def cheese_delete(request, pk):
    product = get_object_or_404(CheeseProduct, pk=pk)
    if request.method == 'POST':
        product.delete()
        messages.success(request, 'Cheese product deleted successfully.')
        return redirect('inventory_management')
    return render(request, 'distribution/cheese_delete.html', {'product': product})


@login_required
def add_stock(request):
    from .models import StockAdditionItem
    if request.method == 'POST':
        formset = AddStockFormSet(request.POST)
        if formset.is_valid():
            valid_forms = [f for f in formset if f.cleaned_data]

            if not valid_forms:
                return JsonResponse({'success': False, 'error': 'Please add at least one stock item.'})

            # Create a single stock addition event
            stock_addition = StockAdditionHistory.objects.create(
                added_by=request.user.userprofile
            )
            
            stock_added = []
            for form in valid_forms:
                cheese_product = form.cleaned_data['cheese_product']
                quantity_packets = form.cleaned_data['quantity_packets']
                purchase_price_per_packet = form.cleaned_data['purchase_price_per_packet']

                cheese_product.available_quantity_packets += quantity_packets
                # Update the product's purchase price to the newly added price
                cheese_product.purchase_price_per_packet = purchase_price_per_packet
                cheese_product.save()

                # Create stock addition item
                StockAdditionItem.objects.create(
                    stock_addition=stock_addition,
                    cheese_product=cheese_product,
                    quantity_packets=quantity_packets
                )

                stock_added.append(f"{quantity_packets} packets to {cheese_product}")

            SiteActivity.update_activity(f'Stock added: {len(stock_added)} product(s)')
            messages.success(request, f'Successfully added stock: {", ".join(stock_added)}.')
            return JsonResponse({'success': True})
        else:
            return JsonResponse({'success': False, 'error': 'Please correct the errors below.'})
    else:
        formset = AddStockFormSet()

    html = render_to_string('distribution/inventory/partials/partial_add_stock_form.html', {'formset': formset}, request=request)
    return JsonResponse({'html': html})


@login_required
def quick_sale_create(request):
    """Quick sale creation from inventory page - same logic as sale_create"""
    if request.method == 'POST':
        client_id = request.POST.get('client')
        if not client_id:
            return JsonResponse({'success': False, 'error': 'Please select a client.'})

        client = get_object_or_404(Client, pk=client_id)
        formset = SaleItemFormSet(request.POST)

        if formset.is_valid():
            valid_forms = [f for f in formset if f.cleaned_data and not f.cleaned_data.get('DELETE', False)]

            if not valid_forms:
                return JsonResponse({'success': False, 'error': 'Please add at least one item to the sale.'})

            with transaction.atomic():
                sale = Sale.objects.create(client=client, total_amount=Decimal('0.00'))
                total_amount = Decimal('0.00')

                for form in valid_forms:
                    cheese_product = form.cleaned_data['cheese_product']
                    quantity_packets = form.cleaned_data['quantity_packets']
                    selling_price_per_packet = form.cleaned_data['selling_price_per_packet']

                    if quantity_packets > cheese_product.available_quantity_packets:
                        sale.delete()
                        return JsonResponse({'success': False, 'error': f'Insufficient stock for {cheese_product.name}.'})

                    sale_item = SaleItem.objects.create(
                        sale=sale,
                        cheese_product=cheese_product,
                        quantity_packets=quantity_packets,
                        selling_price_per_packet=selling_price_per_packet
                    )

                    cheese_product.available_quantity_packets -= quantity_packets
                    cheese_product.save()

                    total_amount += selling_price_per_packet * quantity_packets

                sale.total_amount = total_amount
                sale.save()
                SiteActivity.update_activity(f'Sale created for {client.name}')

                return JsonResponse({'success': True, 'message': 'Sale created successfully.'})
        else:
            return JsonResponse({'success': False, 'error': 'Please correct the errors below.'})
    else:
        formset = SaleItemFormSet()

    html = render_to_string('distribution/sales/partials/partial_quick_sale_form.html', {
        'formset': formset,
        'clients': Client.objects.all()
    }, request=request)
    return JsonResponse({'html': html})


@login_required
def client_list(request):
    clients = Client.objects.all()
    user_is_owner = is_owner(request.user)

    from .forms import ClientForm
    client_form = ClientForm()
    
    return render(request, 'distribution/clients/clients.html', {
        'clients': clients,
        'user_is_owner': user_is_owner,
        'client_form': client_form,
    })


@login_required
def client_add(request):
    if request.method == 'POST':
        form = ClientForm(request.POST)
        if form.is_valid():
            client = form.save()
            SiteActivity.update_activity(f'Client added: {client.name}')
            messages.success(request, 'Client added successfully.')
            return redirect('client_list')
    else:
        form = ClientForm()
    return render(request, 'distribution/client_form.html', {'form': form, 'title': 'Add Client'})


@login_required
def client_edit(request, pk):
    client = get_object_or_404(Client, pk=pk)
    if request.method == 'POST':
        form = ClientForm(request.POST, instance=client)
        if form.is_valid():
            form.save()
            SiteActivity.update_activity(f'Client updated: {client.name}')
            if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                return render(request, 'distribution/shared/partial_edit_success.html', {'object': client, 'type': 'client'})
            messages.success(request, 'Client updated successfully.')
            return redirect('client_list')
    else:
        form = ClientForm(instance=client)
    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        return render(request, 'distribution/clients/partials/partial_edit_client_form.html', {'form': form, 'client': client})
    return render(request, 'distribution/client_form.html', {'form': form, 'title': 'Edit Client'})


@owner_required
def client_delete(request, pk):
    client = get_object_or_404(Client, pk=pk)
    if request.method == 'POST':
        client_name = client.name
        client.delete()
        SiteActivity.update_activity(f'Client deleted: {client_name}')
        messages.success(request, 'Client deleted successfully.')
        return redirect('client_list')
    return render(request, 'distribution/client_delete.html', {'client': client})


@login_required
def sale_create(request):
    if request.method == 'POST':
        client_id = request.POST.get('client')

        if not client_id:
            messages.error(request, 'Please select a client.')
            formset = SaleItemFormSet(request.POST)
            return render(request, 'distribution/sales/sale_create.html', {
                'formset': formset,
                'clients': Client.objects.all(),
                'selected_client_id': None
            })

        client = get_object_or_404(Client, pk=client_id)
        formset = SaleItemFormSet(request.POST)

        if formset.is_valid():
            valid_forms = [f for f in formset if f.cleaned_data and not f.cleaned_data.get('DELETE', False)]

            if not valid_forms:
                messages.error(request, 'Please add at least one item to the sale.')
                return render(request, 'distribution/sales/sale_create.html', {
                    'formset': formset,
                    'clients': Client.objects.all(),
                    'selected_client_id': int(client_id)
                })

            with transaction.atomic():
                sale = Sale.objects.create(client=client, total_amount=Decimal('0.00'))
                total_amount = Decimal('0.00')

                for form in valid_forms:
                    cheese_product = form.cleaned_data['cheese_product']
                    quantity_packets = form.cleaned_data['quantity_packets']
                    selling_price_per_packet = form.cleaned_data['selling_price_per_packet']

                    if quantity_packets > cheese_product.available_quantity_packets:
                        messages.error(request, f'Insufficient stock for {cheese_product.name}.')
                        sale.delete()
                        return render(request, 'distribution/sales/sale_create.html', {
                            'formset': formset,
                            'clients': Client.objects.all(),
                            'selected_client_id': int(client_id)
                        })

                    sale_item = SaleItem.objects.create(
                        sale=sale,
                        cheese_product=cheese_product,
                        quantity_packets=quantity_packets,
                        selling_price_per_packet=selling_price_per_packet
                    )

                    cheese_product.available_quantity_packets -= quantity_packets
                    cheese_product.save()

                    total_amount += selling_price_per_packet * quantity_packets

                # Update sale with total amount
                sale.total_amount = total_amount
                sale.save()
                SiteActivity.update_activity(f'Sale created for {client.name}')

                messages.success(request, 'Sale created successfully.')
                return redirect('sale_history')
        else:
            messages.error(request, 'Please correct the errors below.')
            return render(request, 'distribution/sales/sale_create.html', {
                'formset': formset,
                'clients': Client.objects.all(),
                'selected_client_id': int(client_id) if client_id else None
            })
    else:
        formset = SaleItemFormSet()

    return render(request, 'distribution/sales/sale_create.html', {
        'formset': formset,
        'clients': Client.objects.all(),
        'selected_client_id': None
    })


@login_required
def sale_history(request):
    sales = Sale.objects.select_related('client').prefetch_related('saleitem_set__cheese_product').all()
    sales_with_profit = []
    for sale in sales:
        has_modified_items = sale.saleitem_set.filter(modified=True).exists()
        sales_with_profit.append({
            'sale': sale,
            'total_profit': sale.calculate_total_profit(),
            'has_modified_items': has_modified_items
        })
    
    # Calculate analytics
    now = timezone.now()
    user_is_owner = is_owner(request.user)
    
    return render(request, 'distribution/sales/sale_history.html', {
        'sales_data': sales_with_profit,
        'user_is_owner': user_is_owner,
        'clients': Client.objects.all(),
        'formset': SaleItemFormSet(),
    })


@owner_required
def add_payment(request):
    """Record a client payment."""
    if request.method == 'POST':
        form = PaymentForm(request.POST)
        if form.is_valid():
            client = form.cleaned_data['client']
            amount = form.cleaned_data['amount']
            mode = form.cleaned_data['mode']
            bank = form.cleaned_data.get('bank') or ''

            # Record payment - debt is calculated at query time
            Payment.objects.create(client=client, amount=amount, mode=mode, bank=bank)
            SiteActivity.update_activity(f'Payment of PKR {amount} recorded for {client.name}')
            messages.success(request, 'Payment recorded successfully.')
            return redirect('payment_history')
    else:
        form = PaymentForm()

    return render(request, 'distribution/clients/add_payment.html', {'form': form})


@login_required
def payment_history(request):
    payments = Payment.objects.select_related('client').all().order_by('-date')
    clients = Client.objects.all()
    return render(request, 'distribution/clients/payment_history.html', {'payments': payments, 'clients': clients})


@login_required
def get_payment_history(request):
    """AJAX endpoint to get payment history data"""
    payments = Payment.objects.select_related('client').all().order_by('-date')[:100]
    
    payment_data = []
    total_amount = Decimal('0.00')
    
    for payment in payments:
        payment_data.append({
            'id': payment.id,
            'client_name': payment.client.name,
            'client_phone': payment.client.phone,
            'amount': float(payment.amount),
            'mode': payment.get_mode_display(),
            'bank': payment.bank or 'N/A',
            'date': payment.date.strftime('%Y-%m-%d %H:%M'),
        })
        total_amount += payment.amount
    
    summary = {
        'total_payments': len(payment_data),
        'total_amount': float(total_amount),
        'average_payment': float(total_amount / len(payment_data)) if payment_data else 0,
    }
    
    return JsonResponse({
        'payments': payment_data,
        'summary': summary,
    })


# =========================
# Delivery employee management
# =========================

@login_required
def employee_management(request):
    employees = DeliveryEmployee.objects.all().order_by('name')

    if request.method == 'POST':
        form = DeliveryEmployeeForm(request.POST)
        if form.is_valid():
            employee = form.save()
            SiteActivity.update_activity(f'Employee added: {employee.name}')
            messages.success(request, 'Employee added successfully.')
            return redirect('employee_management')
        else:
            # Keep errors only inline with form fields.
            pass
    else:
        form = DeliveryEmployeeForm()

    return render(request, 'distribution/expenses/employee_management.html', {
        'employees': employees,
        'form': form,
    })


@login_required
def employee_edit(request, pk):
    employee = get_object_or_404(DeliveryEmployee, pk=pk)

    if request.method == 'POST':
        form = DeliveryEmployeeForm(request.POST, instance=employee)
        if form.is_valid():
            form.save()
            SiteActivity.update_activity(f'Employee updated: {employee.name}')
            messages.success(request, 'Employee updated successfully.')
            return redirect('employee_management')
        # Keep errors only inline with form fields.
        pass

    else:
        form = DeliveryEmployeeForm(instance=employee)

    return render(request, 'distribution/expenses/partials/partial_edit_employee_form.html', {
        'employee': employee,
        'form': form,
    })


@login_required
@require_POST
def employee_delete(request, pk):
    employee = get_object_or_404(DeliveryEmployee, pk=pk)
    employee_name = employee.name
    employee.delete()
    SiteActivity.update_activity(f'Employee deleted: {employee_name}')
    messages.success(request, 'Employee removed successfully.')
    return redirect('employee_management')


# =========================
# Delivery expense management
# =========================

@login_required
def expense_management(request):
    expenses = DeliveryExpense.objects.select_related('employee').all().order_by('-expense_date', '-id')
    form = DeliveryExpenseForm()

    if request.method == 'POST':
        form = DeliveryExpenseForm(request.POST)
        if form.is_valid():
            expense = form.save(commit=False)
            expense.created_by = request.user
            expense.save()
            SiteActivity.update_activity(f'Expense added: {expense.get_expense_type_display()}')
            messages.success(request, 'Expense added successfully.')
            return redirect('expense_management')
        # Keep errors only inline with form fields.
        pass

    return render(request, 'distribution/expenses/expense_management.html', {
        'expenses': expenses,
        'form': form,
    })


@login_required
def expense_edit(request, pk):
    expense = get_object_or_404(DeliveryExpense, pk=pk)

    if request.method == 'POST':
        form = DeliveryExpenseForm(request.POST, instance=expense)
        if form.is_valid():
            exp = form.save(commit=False)
            exp.created_by = expense.created_by or request.user
            exp.save()
            SiteActivity.update_activity(f'Expense updated: {exp.get_expense_type_display()}')
            messages.success(request, 'Expense updated successfully.')
            return redirect('expense_management')
        # Keep errors only inline with form fields.
        pass
    else:
        form = DeliveryExpenseForm(instance=expense)

    return render(request, 'distribution/expenses/partials/partial_edit_expense_form.html', {
        'expense': expense,
        'form': form,
    })


@login_required
@require_POST
def expense_delete(request, pk):
    expense = get_object_or_404(DeliveryExpense, pk=pk)
    expense_type = expense.get_expense_type_display()
    expense.delete()
    SiteActivity.update_activity(f'Expense deleted: {expense_type}')
    messages.success(request, 'Expense deleted successfully.')
    return redirect('expense_management')


@login_required
def sale_detail(request, pk):
    sale = get_object_or_404(Sale, pk=pk)
    sale_items = sale.saleitem_set.select_related('cheese_product').all()
    total_profit = sale.calculate_total_profit()
    
    return render(request, 'distribution/sale_detail.html', {
        'sale': sale,
        'sale_items': sale_items,
        'total_profit': total_profit
    })


@owner_required
def user_list(request):
    """List all users with their roles"""
    from django.contrib.auth.models import User
    users = User.objects.all().order_by('username')
    users_with_roles = []
    for user_obj in users:
        try:
            profile = UserProfile.objects.get(user=user_obj)
            role = profile.role
        except UserProfile.DoesNotExist:
            role = 'employee'
            # Create profile if it doesn't exist
            profile = UserProfile.objects.create(user=user_obj, role='employee')
        users_with_roles.append({
            'user': user_obj,
            'role': role,
            'profile': profile
        })
    return render(request, 'distribution/users.html', {'users_with_roles': users_with_roles})


@owner_required
def user_add(request):
    """Create a new user"""
    from django.contrib.auth.models import User
    if request.method == 'POST':
        form = UserForm(request.POST)
        if form.is_valid():
            user = form.save()
            messages.success(request, f'User "{user.username}" created successfully with {form.cleaned_data["role"]} role.')
            return redirect('user_list')
    else:
        form = UserForm()
    return render(request, 'distribution/user_form.html', {'form': form, 'title': 'Add User'})


@owner_required
def user_edit_role(request, pk):
    """Edit user role"""
    from django.contrib.auth.models import User
    user = get_object_or_404(User, pk=pk)
    try:
        profile = UserProfile.objects.get(user=user)
    except UserProfile.DoesNotExist:
        profile = UserProfile.objects.create(user=user, role='employee')
    
    if request.method == 'POST':
        form = UserRoleForm(request.POST, instance=profile)
        if form.is_valid():
            form.save()
            messages.success(request, f'Role updated successfully for "{user.username}".')
            return redirect('user_list')
    else:
        form = UserRoleForm(instance=profile)
    return render(request, 'distribution/user_role_form.html', {
        'form': form,
        'user': user,
        'title': f'Edit Role for {user.username}'
    })


@owner_required
def user_delete(request, pk):
    """Delete a user"""
    from django.contrib.auth.models import User
    user = get_object_or_404(User, pk=pk)
    
    # Prevent deleting yourself
    if user == request.user:
        messages.error(request, 'You cannot delete your own account.')
        return redirect('user_list')
    
    if request.method == 'POST':
        username = user.username
        user.delete()
        messages.success(request, f'User "{username}" deleted successfully.')
        return redirect('user_list')
    return render(request, 'distribution/user_delete.html', {'user': user})
