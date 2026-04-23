from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib.auth import authenticate, login, logout
from django.contrib import messages
from django.conf import settings
from django.db import models
from django.db.models import Sum, Q, F, DecimalField, Subquery, OuterRef
from django.db import transaction, connections
from django.utils import timezone
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
import shutil
import tempfile
import sqlite3
import os
import json
from django.core.management import call_command
from .models import (
    Manufacturer, CheeseProduct, Client, Sale, SaleItem, UserProfile, Payment,
    DeliveryEmployee, DeliveryExpense, SiteActivity,
)
from .forms import (
    ManufacturerForm, CheeseProductForm, ClientForm,
    SaleItemForm, SaleItemFormSet, UserForm, UserRoleForm,
    PaymentForm, DeliveryEmployeeForm, DeliveryExpenseForm,
)
from .forms import CheeseTypeForm
from .decorators import owner_required, is_owner


from django.http import JsonResponse, FileResponse
from django.template.loader import render_to_string
from django.shortcuts import render
from .forms import CheeseTypeForm
from .models import CheeseType

# AJAX endpoint to process return for sale item
from django.views.decorators.http import require_POST


def _resolve_sale_datetime(sale_date_str):
    """Parse submitted sale datetime; fallback to current time if missing/invalid."""
    if not sale_date_str:
        return timezone.now()

    try:
        parsed = datetime.fromisoformat(sale_date_str)
        return timezone.make_aware(parsed) if timezone.is_naive(parsed) else parsed
    except ValueError:
        return timezone.now()


def _validate_sale_date_not_before_client_creation(client, sale_datetime):
    """Return an error message if sale datetime is before client creation; otherwise None."""
    if not client.date_added:
        return None

    client_created = client.date_added
    if timezone.is_naive(client_created):
        client_created = timezone.make_aware(client_created)

    if sale_datetime < client_created:
        return (
            f"Sale date cannot be earlier than client creation date "
            f"({timezone.localtime(client_created).strftime('%d/%m/%Y %H:%M')})."
        )

    return None


def _parse_custom_datetime_range(from_value, to_value):
    """Parse custom range from query params and return aware datetimes (start, end)."""
    if not from_value or not to_value:
        return None, None

    def parse_single(value, is_end=False):
        value = value.strip()

        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            try:
                parsed = datetime.strptime(value, '%Y-%m-%d')
                if is_end:
                    parsed = parsed.replace(hour=23, minute=59, second=59, microsecond=999999)
            except ValueError:
                return None

        if timezone.is_naive(parsed):
            parsed = timezone.make_aware(parsed, timezone.get_current_timezone())

        return parsed

    start_dt = parse_single(from_value, is_end=False)
    end_dt = parse_single(to_value, is_end=True)

    if not start_dt or not end_dt or end_dt < start_dt:
        return None, None

    return start_dt, end_dt

@login_required
@require_POST
def return_sale_item(request):
    """Handle partial return of a sale item with deduplication"""
    item_id = request.POST.get('item_id')
    quantity = request.POST.get('quantity')
    reason = request.POST.get('reason', '')
    
    # Deduplication check
    dedup_key = f"return_sale_item_{item_id}_{quantity}_{int(timezone.now().timestamp())}"
    if request.session.get(dedup_key):
        return JsonResponse({'success': False, 'error': 'This return is already being processed.'})
    request.session[dedup_key] = True
    
    try:
        item = get_object_or_404(SaleItem, pk=item_id)
        quantity = Decimal(quantity)
        
        # Check if quantity is valid
        if quantity <= 0:
            del request.session[dedup_key]
            return JsonResponse({'success': False, 'error': 'Return quantity must be greater than 0.'})
        
        # Check if return quantity exceeds available quantity
        available = item.quantity_packets - item.quantity_returned
        if quantity > available:
            del request.session[dedup_key]
            return JsonResponse({'success': False, 'error': f'Cannot return {quantity} packets. Only {available} available to return.'})
        
        # Create return record
        Return.objects.create(sale_item=item, quantity_packets=quantity, reason=reason)
        
        # Update SaleItem quantity_returned
        item.quantity_returned += quantity
        item.modified = True
        item.save()
        
        # Update cheese product stock
        item.cheese_product.available_quantity_packets += quantity
        item.cheese_product.save()
        
        SiteActivity.update_activity(f'Returned {quantity} packets of {item.cheese_product} from Sale #{item.sale.id}')
        
        # Clean up dedup key after 2 seconds
        request.session[dedup_key] = False
        
        return JsonResponse({'success': True, 'message': f'Successfully returned {quantity} packets.'})
    except Exception as e:
        if dedup_key in request.session:
            del request.session[dedup_key]
        return JsonResponse({'success': False, 'error': str(e)})

# AJAX endpoint to process return for all sale items in a sale
@login_required
@require_POST
def return_all_sale_items(request):
    """Handle return of all items in a sale with deduplication"""
    sale_id = request.POST.get('sale_id')
    reason = request.POST.get('reason', '')
    
    # Deduplication check
    dedup_key = f"return_all_sale_items_{sale_id}_{int(timezone.now().timestamp())}"
    if request.session.get(dedup_key):
        return JsonResponse({'success': False, 'error': 'This return is already being processed.'})
    request.session[dedup_key] = True
    
    try:
        sale = get_object_or_404(Sale, pk=sale_id)
        
        for item in sale.saleitem_set.all():
            # Only return items that haven't been fully returned
            if item.quantity_returned < item.quantity_packets:
                quantity_to_return = item.quantity_packets - item.quantity_returned
                
                # Create return record
                Return.objects.create(sale_item=item, quantity_packets=quantity_to_return, reason=reason)
                
                # Update SaleItem
                item.quantity_returned = item.quantity_packets
                item.modified = True
                item.save()
                
                # Update cheese product stock
                item.cheese_product.available_quantity_packets += quantity_to_return
                item.cheese_product.save()
        
        SiteActivity.update_activity(f'All items returned from Sale #{sale.id}')
        
        # Clean up dedup key after 2 seconds
        request.session[dedup_key] = False
        
        return JsonResponse({'success': True, 'message': 'All items have been returned.'})
    except Exception as e:
        if dedup_key in request.session:
            del request.session[dedup_key]
        return JsonResponse({'success': False, 'error': str(e)})

# AJAX endpoint to add stock to a product
@login_required
@require_POST
def add_stock_quantity(request):
    """Add stock with deduplication to prevent double requests"""
    from .models import StockAdditionItem
    product_id = request.POST.get('product_id')
    quantity = request.POST.get('quantity')
    
    # Deduplication check
    dedup_key = f"add_stock_{product_id}_{quantity}_{int(timezone.now().timestamp())}"
    if request.session.get(dedup_key):
        return JsonResponse({'success': False, 'error': 'This request is already being processed.'})
    request.session[dedup_key] = True
    
    try:
        product = get_object_or_404(CheeseProduct, pk=product_id)
        quantity = int(quantity)
        
        if quantity <= 0:
            del request.session[dedup_key]
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
        
        # Clean up dedup key
        del request.session[dedup_key]
        
        return JsonResponse({'success': True, 'message': f'Added {quantity} packets to {product}'})
    except Exception as e:
        if dedup_key in request.session:
            del request.session[dedup_key]
        return JsonResponse({'success': False, 'error': str(e)})

# AJAX endpoint to remove stock from a product
@login_required
@require_POST
def remove_stock_quantity(request):
    """Remove stock with deduplication to prevent double requests"""
    from .models import StockAdditionItem
    product_id = request.POST.get('product_id')
    quantity = request.POST.get('quantity')
    
    # Deduplication check
    dedup_key = f"remove_stock_{product_id}_{quantity}_{int(timezone.now().timestamp())}"
    if request.session.get(dedup_key):
        return JsonResponse({'success': False, 'error': 'This request is already being processed.'})
    request.session[dedup_key] = True
    
    try:
        product = get_object_or_404(CheeseProduct, pk=product_id)
        quantity = int(quantity)
        
        if quantity <= 0:
            del request.session[dedup_key]
            return JsonResponse({'success': False, 'error': 'Quantity must be greater than 0'})
        
        if product.available_quantity_packets < quantity:
            del request.session[dedup_key]
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
        
        # Clean up dedup key
        del request.session[dedup_key]
        
        return JsonResponse({'success': True, 'message': f'Removed {quantity} packets from {product}'})
    except Exception as e:
        if dedup_key in request.session:
            del request.session[dedup_key]
        return JsonResponse({'success': False, 'error': str(e)})

# AJAX endpoint to change product price
@login_required
@owner_required
@require_POST
def change_stock_price(request):
    """Change stock price with deduplication to prevent double requests"""
    from .models import StockAdditionItem
    product_id = request.POST.get('product_id')
    new_price = request.POST.get('new_price')
    
    # Deduplication check
    dedup_key = f"change_stock_price_{product_id}_{new_price}_{int(timezone.now().timestamp())}"
    if request.session.get(dedup_key):
        return JsonResponse({'success': False, 'error': 'This request is already being processed.'})
    request.session[dedup_key] = True
    
    try:
        product = get_object_or_404(CheeseProduct, pk=product_id)
        old_price = product.purchase_price_per_packet
        new_price = Decimal(new_price)
        
        if new_price <= 0:
            del request.session[dedup_key]
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
        
        # Clean up dedup key
        del request.session[dedup_key]
        
        return JsonResponse({'success': True, 'message': f'Price updated from {old_price} to {new_price}'})
    except Exception as e:
        if dedup_key in request.session:
            del request.session[dedup_key]
        return JsonResponse({'success': False, 'error': str(e)})

from django.views.decorators.http import require_GET

@login_required
@require_GET
def sale_modal_details(request, pk):
    sale = get_object_or_404(Sale, pk=pk)
    sale_items = sale.saleitem_set.select_related('cheese_product').all()
    
    # Add total price for each item
    for item in sale_items:
        item.item_total = item.quantity_packets * item.selling_price_per_packet
    
    total_profit = sale.calculate_total_profit()
    return render(request, 'distribution/sales/partials/partial_sale_modal_details.html', {
        'sale': sale,
        'sale_items': sale_items,
        'total_profit': total_profit
    })

from .models import StockAdditionHistory, Return


@login_required
def stock_history(request):
    from .models import StockAdditionItem
    from decimal import Decimal
    
    stock_additions = StockAdditionHistory.objects.prefetch_related('stockadditionitem_set__cheese_product', 'added_by').all()
    
    # Calculate total value for each stock addition
    for addition in stock_additions:
        first_item = addition.stockadditionitem_set.first()
        if first_item:
            addition.total_value = first_item.quantity_packets * first_item.cheese_product.purchase_price_per_packet
        else:
            addition.total_value = Decimal('0.00')
    
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
        'products_with_value': products_with_value,
    })

@login_required
def cheese_type_add(request):
    """Add a new cheese type - accessible to employees"""
    if request.method == 'POST':
        form = CheeseTypeForm(request.POST)
        if form.is_valid():
            cheese_type = form.save()
            messages.success(request, 'Cheese type added successfully.')
            return redirect('inventory_management')
    else:
        form = CheeseTypeForm()
    return render(request, 'distribution/cheese_type_form.html', {'form': form})

@login_required
def cheese_type_edit(request, pk):
    """Edit cheese type - accessible to employees"""
    cheese_type = CheeseType.objects.get(pk=pk)
    if request.method == 'POST':
        form = CheeseTypeForm(request.POST, instance=cheese_type)
        if form.is_valid():
            form.save()
            if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                return JsonResponse({'success': True, 'message': 'Cheese type updated successfully.'})
            messages.success(request, 'Cheese type updated successfully.')
            return redirect('inventory_management')
    else:
        form = CheeseTypeForm(instance=cheese_type)
    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        html = render_to_string('distribution/inventory/partials/partial_edit_cheese_type_form.html', {'form': form, 'cheese_type': cheese_type}, request=request)
        return JsonResponse({'html': html})
    # Non-AJAX GET requests should not hit this, but fallback to form page
    return render(request, 'distribution/cheese_type_form.html', {'form': form, 'title': 'Edit Cheese Type'})

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
    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')
        user = authenticate(request, username=username, password=password)
        if user is not None:
            login(request, user)
            # Redirect based on user role
            if user.userprofile.role == 'owner':
                return redirect('dashboard')
            else:
                return redirect('inventory_management')
        else:
            messages.error(request, 'Invalid username or password.')
    return render(request, 'distribution/login.html')


def logout_view(request):
    logout(request)
    return redirect('login')


@login_required
@owner_required
def dashboard(request):
    user_is_owner = is_owner(request.user)

    # Calculate today's expenses
    today = timezone.localdate()
    from django.db.models import Sum
    daily_expenses = DeliveryExpense.objects.filter(expense_date=today).aggregate(total=Sum('amount'))['total'] or 0

    context = {
        'user_is_owner': user_is_owner,
        'daily_expenses': daily_expenses,
    }
    return render(request, 'distribution/dashboard.html', context)


@login_required
def get_client_analytics(request):
    """AJAX endpoint to get client analytics based on time period"""
    period = request.GET.get('period', 'all')
    from_date_str = request.GET.get('from_date')
    to_date_str = request.GET.get('to_date')

    # Use localtime to get the date in the configured timezone (Asia/Karachi)
    now_local = timezone.localtime(timezone.now())
    today = now_local.date()

    custom_start_dt = None
    custom_end_dt = None

    if period == 'custom' and from_date_str and to_date_str:
        custom_start_dt, custom_end_dt = _parse_custom_datetime_range(from_date_str, to_date_str)
        if not custom_start_dt or not custom_end_dt:
            return JsonResponse({'error': 'Invalid custom date/time range.'}, status=400)

        start_date = None
        end_date = None
    elif period == 'today':
        start_date = today
        end_date = today
    elif period == 'week':
        start_date = today - timedelta(days=7)
        end_date = today
    elif period == 'month':
        start_date = today - timedelta(days=30)
        end_date = today
    elif period == 'quarter':
        start_date = today - timedelta(days=90)
        end_date = today
    elif period == '6months':
        start_date = today - timedelta(days=180)
        end_date = today
    elif period == 'year':
        start_date = today - timedelta(days=365)
        end_date = today
    else:  # 'all'
        start_date = None
        end_date = None

    # Get all clients
    clients = Client.objects.all()
    client_data = []

    for client in clients:
        # Filter sales by date range for period-based metrics
        if custom_start_dt and custom_end_dt:
            client_sales = Sale.objects.filter(client=client, sale_date__range=[custom_start_dt, custom_end_dt])
        elif start_date and end_date:
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

            # Get last sale date and time
            last_sale = client_sales.order_by('-sale_date').first()
            last_sale_time = last_sale.sale_date.strftime('%Y-%m-%d %H:%M') if last_sale else None

            # DEBT IS PERIOD-BASED: Sales in period - Payments in period
            # Filter payments by date range for period-based debt calculation
            if custom_start_dt and custom_end_dt:
                client_payments = Payment.objects.filter(client=client, date__range=[custom_start_dt, custom_end_dt])
            elif start_date and end_date:
                client_payments = Payment.objects.filter(client=client, date__date__range=[start_date, end_date])
            else:
                client_payments = Payment.objects.filter(client=client)
            
            # Calculate period-based payments
            period_payments = client_payments.aggregate(
                total=Sum('amount')
            )['total'] or Decimal('0.00')
            
            # Debt = sales in period - payments in period
            client_debt = total_sales - period_payments

            client_data.append({
                'id': client.id,
                'name': client.name,
                'total_sales': float(total_sales),
                'total_profit': float(total_profit),
                'total_transactions': total_transactions,
                'last_sale_time': last_sale_time,
                'avg_sale': float(total_sales / total_transactions) if total_transactions > 0 else 0,
                'debt': float(client_debt),
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
    from_date_str = request.GET.get('from_date')
    to_date_str = request.GET.get('to_date')

    now = timezone.now()

    custom_start_dt = None
    custom_end_dt = None

    if period == 'custom' and from_date_str and to_date_str:
        custom_start_dt, custom_end_dt = _parse_custom_datetime_range(from_date_str, to_date_str)
        if not custom_start_dt or not custom_end_dt:
            return JsonResponse({'error': 'Invalid custom date/time range.'}, status=400)

        start_date = None
        end_date = None
    elif period == 'today':
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
        if custom_start_dt and custom_end_dt:
            product_sales = SaleItem.objects.filter(
                cheese_product=product,
                sale__sale_date__range=[custom_start_dt, custom_end_dt]
            )
        elif start_date and end_date:
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
    from_date_str = request.GET.get('from_date')
    to_date_str = request.GET.get('to_date')

    # Use localtime to get the date in the configured timezone (Asia/Karachi)
    now_local = timezone.localtime(timezone.now())
    today = now_local.date()

    custom_start_dt = None
    custom_end_dt = None

    if period == 'custom' and from_date_str and to_date_str:
        custom_start_dt, custom_end_dt = _parse_custom_datetime_range(from_date_str, to_date_str)
        if not custom_start_dt or not custom_end_dt:
            return JsonResponse({'error': 'Invalid custom date/time range.'}, status=400)

        start_date = None
        end_date = None
    elif period == 'today':
        start_date = today
        end_date = today
    elif period == 'week':
        start_date = today - timedelta(days=7)
        end_date = today
    elif period == 'month':
        start_date = today - timedelta(days=30)
        end_date = today
    elif period == 'quarter':
        start_date = today - timedelta(days=90)
        end_date = today
    elif period == '6months':
        start_date = today - timedelta(days=180)
        end_date = today
    elif period == 'year':
        start_date = today - timedelta(days=365)
        end_date = today
    else:  # 'all'
        start_date = None
        end_date = None

    # Get general metrics
    if custom_start_dt and custom_end_dt:
        sales_queryset = Sale.objects.filter(sale_date__range=[custom_start_dt, custom_end_dt])
        expenses_queryset = DeliveryExpense.objects.filter(
            expense_date__range=[custom_start_dt.date(), custom_end_dt.date()]
        )
    elif start_date and end_date:
        sales_queryset = Sale.objects.filter(sale_date__date__range=[start_date, end_date])
        expenses_queryset = DeliveryExpense.objects.filter(expense_date__range=[start_date, end_date])
    else:
        sales_queryset = Sale.objects.all()
        expenses_queryset = DeliveryExpense.objects.all()

    # Total Revenue
    total_revenue = sales_queryset.aggregate(total=Sum('total_amount'))['total'] or Decimal('0.00')

    # Total Expenses
    total_expenses = expenses_queryset.aggregate(total=Sum('amount'))['total'] or Decimal('0.00')

    # Total Profit (from sales) - OPTIMIZED: calculated at DB level instead of looping
    # profit = (selling_price - purchase_price) * quantity
    profit_queryset = SaleItem.objects.filter(
        sale__in=sales_queryset
    ).values('sale').annotate(
        sale_profit=Sum(
            F('profit_per_packet') * F('quantity_packets'),
            output_field=DecimalField()
        )
    )
    total_profit = sum(
        item['sale_profit'] or Decimal('0.00') 
        for item in profit_queryset
    )
    
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

    # Total Paid this period
    if custom_start_dt and custom_end_dt:
        total_paid_amount = Payment.objects.filter(date__range=[custom_start_dt, custom_end_dt]).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
    elif start_date and end_date:
        total_paid_amount = Payment.objects.filter(date__date__range=[start_date, end_date]).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
    else:
        total_paid_amount = Payment.objects.aggregate(total=Sum('amount'))['total'] or Decimal('0.00')

    summary = {
        'total_revenue': float(total_revenue),
        'total_expenses': float(total_expenses),
        'total_profit': float(total_profit),
        'net_profit': float(net_profit),
        'total_sales_count': total_sales_count,
        'avg_sale_value': avg_sale_value,
        'clients_this_period': clients_this_period,
        'total_items_sold': float(total_items_sold),
        'total_paid_amount': float(total_paid_amount),
    }

    return JsonResponse({
        'summary': summary,
        'period': period
    })


@login_required
def get_dashboard_overview(request):
    """Endpoint to get general dashboard overview metrics (not time-dependent)
    OPTIMIZED: Uses database aggregations instead of Python loops
    """
    from django.db.models.functions import Coalesce
    
    # Total Clients
    total_clients_count = Client.objects.count()

    # Total Products
    total_products_count = CheeseProduct.objects.count()

    # Total Stock Value (current stock * price) - using database aggregation
    total_stock_value = CheeseProduct.objects.aggregate(
        total=Coalesce(
            Sum(F('available_quantity_packets') * F('purchase_price_per_packet'), 
                output_field=DecimalField()),
            Decimal('0.00')
        )
    )['total']

    # Total Paid
    total_paid_amount = Payment.objects.aggregate(
        total=Coalesce(Sum('amount'), Decimal('0.00'))
    )['total']

    # Get all client financial summaries using aggregation
    # This avoids looping through all clients
    client_sales = Sale.objects.filter(client=OuterRef('pk')).values('client').annotate(
        total=Sum('total_amount')
    ).values('total')
    
    client_payments = Payment.objects.filter(client=OuterRef('pk')).values('client').annotate(
        total=Sum('amount')
    ).values('total')
    
    clients_with_financials = Client.objects.annotate(
        total_sales=Coalesce(
            Subquery(client_sales),
            Decimal('0.00')
        ),
        total_paid=Coalesce(
            Subquery(client_payments),
            Decimal('0.00')
        )
    ).values('total_sales', 'total_paid')
    
    # Calculate totals
    total_outstanding = Decimal('0.00')
    total_unpaid_amount = Decimal('0.00')
    
    for client_data in clients_with_financials:
        outstanding = client_data['total_sales'] - client_data['total_paid']
        if outstanding > 0:
            total_outstanding += outstanding
            total_unpaid_amount += outstanding

    summary = {
        'total_outstanding': float(total_outstanding),
        'total_clients': total_clients_count,
        'total_products': total_products_count,
        'total_stock_value': float(total_stock_value),
        'total_paid_amount': float(total_paid_amount),
        'total_partial_amount': 0.0,  # Simplified: partial is now included in unpaid
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

@login_required
def get_manufacturer_details(request, manufacturer_id):
    """API endpoint to get manufacturer contact details"""
    try:
        manufacturer = Manufacturer.objects.get(pk=manufacturer_id)
        return JsonResponse({
            'id': manufacturer.id,
            'name': manufacturer.name,
            'contact_info': manufacturer.contact_info or 'N/A',
            'address': manufacturer.address or 'N/A',
        })
    except Manufacturer.DoesNotExist:
        return JsonResponse({'error': 'Manufacturer not found'}, status=404)

@login_required
def get_filtered_products(request):
    """API endpoint to get products filtered by type and/or manufacturer"""
    type_id = request.GET.get('type_id')
    manufacturer_id = request.GET.get('manufacturer_id')
    
    products = CheeseProduct.objects.select_related('manufacturer', 'type').all()
    
    if type_id:
        try:
            products = products.filter(type_id=int(type_id))
        except (ValueError, TypeError):
            pass
    
    if manufacturer_id:
        try:
            products = products.filter(manufacturer_id=int(manufacturer_id))
        except (ValueError, TypeError):
            pass
    
    product_list = [
        {
            'id': p.id,
            'name': f"{p.manufacturer.name} - {p.type.name} ({p.packet_size}KG)",
            'manufacturer_id': p.manufacturer_id,
            'type_id': p.type_id,
            'packet_size': float(p.packet_size),
            'purchase_price': float(p.purchase_price_per_packet),
            'available_quantity': float(p.available_quantity_packets),
        }
        for p in products
    ]
    
    return JsonResponse({'products': product_list})

@login_required
def inventory_management(request):
    """Merged page for manufacturers and cheese inventory"""
    manufacturers = Manufacturer.objects.all()
    products = CheeseProduct.objects.select_related('manufacturer').all()
    cheese_types = CheeseType.objects.all()
    # Calculate stock value for each product
    products_with_value = []
    total_stock_quantity = 0
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
        'formset': sale_item_formset,
        'cheese_types': cheese_types,
        'low_stock_products': low_stock_products,
        'inventory_summary': inventory_summary,
        'clients': Client.objects.all(),
        'user_is_owner': user_is_owner,
    })


@login_required
def manufacturer_add(request):
    if request.method == 'POST':
        form = ManufacturerForm(request.POST)
        if form.is_valid():
            manufacturer = form.save()
            messages.success(request, 'Manufacturer added successfully.')
            return redirect('inventory_management')
    else:
        form = ManufacturerForm()
    return render(request, 'distribution/manufacturer_form.html', {'form': form, 'title': 'Add Manufacturer'})


@login_required
def manufacturer_edit(request, pk):
    manufacturer = get_object_or_404(Manufacturer, pk=pk)
    if request.method == 'POST':
        form = ManufacturerForm(request.POST, instance=manufacturer)
        if form.is_valid():
            form.save()
            SiteActivity.update_activity(f'Manufacturer updated: {manufacturer.name}')
            if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                return JsonResponse({'success': True, 'message': 'Manufacturer updated successfully.'})
            messages.success(request, 'Manufacturer updated successfully.')
            return redirect('inventory_management')
    else:
        form = ManufacturerForm(instance=manufacturer)
    # Return partial form for AJAX requests
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


@login_required
def cheese_add(request):
    if request.method == 'POST':
        form = CheeseProductForm(request.POST)
        if form.is_valid():
            cheese_product = form.save()
            # Create stock addition history if initial quantity was added
            initial_quantity = form.cleaned_data['available_quantity_packets']
            if initial_quantity > 0:
                from .models import StockAdditionItem
                stock_addition = StockAdditionHistory.objects.create(
                    operation_type='add',
                    added_by=request.user.userprofile
                )
                StockAdditionItem.objects.create(
                    stock_addition=stock_addition,
                    cheese_product=cheese_product,
                    quantity_packets=int(initial_quantity)
                )
            messages.success(request, 'Cheese product added successfully.')
            return redirect('inventory_management')
    else:
        form = CheeseProductForm()
    return render(request, 'distribution/cheese_form.html', {'form': form, 'title': 'Add Cheese Product'})


@login_required
def cheese_edit(request, pk):
    product = get_object_or_404(CheeseProduct, pk=pk)
    if request.method == 'POST':
        form = CheeseProductForm(request.POST, instance=product)
        if form.is_valid():
            form.save()
            if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                return JsonResponse({'success': True, 'message': 'Cheese product updated successfully.'})
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
@require_GET
def get_client_product_price(request, client_id, product_id):
    """Get the last selling price for a product for a specific client."""
    try:
        # Get the most recent sale item for this client and product
        sale_item = SaleItem.objects.filter(
            sale__client_id=client_id,
            cheese_product_id=product_id
        ).select_related('sale').order_by('-sale__sale_date').first()
        
        if sale_item:
            return JsonResponse({
                'success': True,
                'price': str(sale_item.selling_price_per_packet)
            })
        else:
            return JsonResponse({
                'success': False,
                'message': 'No previous sales found for this client-product combination'
            })
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        })

@login_required
def quick_sale_create(request):
    """Quick sale creation from inventory page - same logic as sale_create"""
    if request.method == 'POST':
        client_id = request.POST.get('client')
        sale_date_str = request.POST.get('sale_date')
        
        if not client_id:
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'success': False, 'error': 'Please select a client.'})
            messages.error(request, 'Please select a client.')
            return redirect('sale_history')

        client = get_object_or_404(Client, pk=client_id)
        formset = SaleItemFormSet(request.POST)
        sale_datetime = _resolve_sale_datetime(sale_date_str)
        sale_date_error = _validate_sale_date_not_before_client_creation(client, sale_datetime)

        if sale_date_error:
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'success': False, 'error': sale_date_error})
            messages.error(request, sale_date_error)
            return redirect('sale_history')

        if formset.is_valid():
            valid_forms = [f for f in formset if f.cleaned_data and not f.cleaned_data.get('DELETE', False)]

            if not valid_forms:
                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return JsonResponse({'success': False, 'error': 'Please add at least one item to the sale.'})
                messages.error(request, 'Please add at least one item to the sale.')
                return redirect('sale_history')

            with transaction.atomic():
                sale = Sale.objects.create(
                    client=client,
                    total_amount=Decimal('0.00'),
                    sale_date=sale_datetime,
                )
                
                total_amount = Decimal('0.00')

                for form in valid_forms:
                    cheese_product = form.cleaned_data['cheese_product']
                    quantity_packets = form.cleaned_data['quantity_packets']
                    selling_price_per_packet = form.cleaned_data['selling_price_per_packet']

                    if quantity_packets > cheese_product.available_quantity_packets:
                        sale.delete()
                        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                            return JsonResponse({'success': False, 'error': f'Insufficient stock for {cheese_product}.'})
                        messages.error(request, f'Insufficient stock for {cheese_product}')
                        return redirect('sale_history')

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

                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    # Return sold items details for manual page update
                    sold_items = [
                        {
                            'product_id': item.cheese_product.id,
                            'quantity': item.quantity_packets
                        }
                        for item in sale.saleitem_set.all()
                    ]
                    total_sold = sum(item.quantity_packets for item in sale.saleitem_set.all())
                    return JsonResponse({
                        'success': True,
                        'message': 'Sale created successfully.',
                        'sold_items': sold_items,
                        'total_sold_quantity': total_sold
                    })
                
                messages.success(request, 'Sale created successfully.')
                return redirect('sale_history')
        else:
            # Get detailed error message
            error_msg = 'Please correct the errors below.'
            for form in formset:
                if form.errors:
                    first_error = list(form.errors.values())[0][0] if form.errors else None
                    if first_error:
                        error_msg = str(first_error)
                        break
            
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'success': False, 'error': error_msg})
            
            messages.error(request, error_msg)
            return redirect('sale_history')
    else:
        formset = SaleItemFormSet()

    html = render_to_string('distribution/sales/partials/partial_add_sale_modal.html', {
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
            
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({
                    'success': True,
                    'message': 'Client added successfully.',
                    'object': {
                        'id': client.id,
                        'name': client.name,
                        'phone': client.phone or '',
                        'address': client.address or ''
                    }
                })
            
            messages.success(request, 'Client added successfully.')
            return redirect('client_list')
        else:
            error_msg = ''
            if form.errors:
                error_msg = list(form.errors.values())[0][0]
            
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'success': False, 'error': error_msg or 'Invalid form data'})
            
            messages.error(request, error_msg or 'Invalid form data')
            return render(request, 'distribution/client_form.html', {'form': form, 'title': 'Add Client'})
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
def export_client_pdf(request, pk):
    """Export client data as PDF"""
    from reportlab.lib.pagesizes import letter
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from reportlab.lib.units import inch
    from io import BytesIO
    from django.http import HttpResponse
    from decimal import Decimal
    
    client = get_object_or_404(Client, pk=pk)
    
    # Calculate client statistics
    total_sales = Sale.objects.filter(client=client).aggregate(total=Sum('total_amount'))['total'] or Decimal('0.00')
    total_paid = Payment.objects.filter(client=client).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
    due_payment = total_sales - total_paid
    
    # Create PDF in memory
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, rightMargin=72, leftMargin=72, topMargin=72, bottomMargin=18)
    
    # Container for PDF elements
    elements = []
    
    # Define styles
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=24,
        textColor=colors.HexColor('#1a1a1a'),
        spaceAfter=30,
        alignment=1  # Center alignment
    )
    
    heading_style = ParagraphStyle(
        'CustomHeading',
        parent=styles['Heading2'],
        fontSize=14,
        textColor=colors.HexColor('#333333'),
        spaceAfter=12,
        spaceBefore=12
    )
    
    normal_style = ParagraphStyle(
        'CustomNormal',
        parent=styles['Normal'],
        fontSize=11,
        spaceAfter=6
    )
    
    # Add title
    title = Paragraph(f"Client Report: {client.name}", title_style)
    elements.append(title)
    elements.append(Spacer(1, 0.3*inch))
    
    # Get time period from query params
    from datetime import datetime
    start_date_str = request.GET.get('start_date')
    end_date_str = request.GET.get('end_date')
    
    # Add Report Period Section
    period_text = "Full Report (All-Time)"
    if start_date_str or end_date_str:
        try:
            if start_date_str and end_date_str:
                start_dt = datetime.strptime(start_date_str, '%Y-%m-%d')
                end_dt = datetime.strptime(end_date_str, '%Y-%m-%d')
                period_text = f"Report Period: {start_dt.strftime('%B %d, %Y')} to {end_dt.strftime('%B %d, %Y')}"
            elif start_date_str:
                start_dt = datetime.strptime(start_date_str, '%Y-%m-%d')
                period_text = f"Report Period: From {start_dt.strftime('%B %d, %Y')}"
            elif end_date_str:
                end_dt = datetime.strptime(end_date_str, '%Y-%m-%d')
                period_text = f"Report Period: Until {end_dt.strftime('%B %d, %Y')}"
        except Exception:
            pass
    
    period_style = ParagraphStyle(
        'PeriodStyle',
        parent=styles['Normal'],
        fontSize=10,
        textColor=colors.HexColor('#666666'),
        spaceAfter=12,
        alignment=1  # Center alignment
    )
    elements.append(Paragraph(period_text, period_style))
    elements.append(Spacer(1, 0.2*inch))
    
    # Client Information Section
    elements.append(Paragraph("Client Information", heading_style))
    
    client_info_data = [
        ['Field', 'Value'],
        ['Name', client.name],
        ['Phone', client.phone],
        ['Address', client.address],
    ]
    
    client_info_table = Table(client_info_data, colWidths=[2*inch, 4*inch])
    client_info_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#3498db')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 12),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
        ('GRID', (0, 0), (-1, -1), 1, colors.black),
        ('FONTSIZE', (0, 1), (-1, -1), 11),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f5f5f5')]),
    ]))
    
    elements.append(client_info_table)
    elements.append(Spacer(1, 0.3*inch))
    
    # Financial Summary Section
    elements.append(Paragraph("Financial Summary", heading_style))
    
    financial_data = [
        ['Metric', 'Amount'],
        ['All-Time Sales', f'Rs. {total_sales:,.2f}'],
        ['All-Time Payments Made', f'Rs. {total_paid:,.2f}'],
        ['Outstanding Due', f'Rs. {due_payment:,.2f}'],
    ]
    
    financial_table = Table(financial_data, colWidths=[3*inch, 3*inch])
    financial_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#27ae60')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 12),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
        ('GRID', (0, 0), (-1, -1), 1, colors.black),
        ('FONTSIZE', (0, 1), (-1, -1), 11),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f5f5f5')]),
        ('ALIGN', (1, 1), (1, -1), 'RIGHT'),
    ]))
    
    elements.append(financial_table)
    elements.append(Spacer(1, 0.3*inch))
    
    # Prepare filters for sales and payments
    sales_filter = {'client': client}
    payments_filter = {'client': client}
    if start_date_str:
        try:
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d')
            sales_filter['sale_date__date__gte'] = start_date
            payments_filter['date__date__gte'] = start_date
        except Exception:
            pass
    if end_date_str:
        try:
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d')
            sales_filter['sale_date__date__lte'] = end_date
            payments_filter['date__date__lte'] = end_date
        except Exception:
            pass

    # Sales History Section
    elements.append(Spacer(1, 0.4*inch))
    elements.append(Paragraph("Sales History", heading_style))
    sales = Sale.objects.filter(**sales_filter).prefetch_related('saleitem_set').order_by('-sale_date')
    
    if sales.exists():
        sales_data = [["ID", "Date", "Product", "Qty", "Packet Price", "Total"]]
        for sale in sales:
            sale_items = sale.saleitem_set.all()
            is_first_item = True
            for item in sale_items:
                if is_first_item:
                    sales_data.append([
                        f"{sale.id}",
                        sale.sale_date.strftime('%d-%m-%Y'),
                        f"{item.cheese_product}",
                        str(item.quantity_packets),
                        f"{item.selling_price_per_packet:,.2f}",
                        f"{item.quantity_packets * item.selling_price_per_packet:,.2f}"
                    ])
                    is_first_item = False
                else:
                    sales_data.append([
                        "",
                        "",
                        f"{item.cheese_product}",
                        str(item.quantity_packets),
                        f"{item.selling_price_per_packet:,.2f}",
                        f"{item.quantity_packets * item.selling_price_per_packet:,.2f}"
                    ])
            # Add total row for this sale
            sales_data.append([
                "",
                "SALE TOTAL",
                "",
                "",
                f"{sale.total_amount:,.2f}"
            ])
        
        sales_table = Table(sales_data, colWidths=[1*inch,1.2*inch, 1.8*inch, 0.8*inch, 1.2*inch, 1.2*inch])
        sales_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2980b9')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 11),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 10),
            ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
            ('GRID', (0, 0), (-1, -1), 1, colors.black),
            ('FONTSIZE', (0, 1), (-1, -1), 9),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f5f5f5')]),
            ('ALIGN', (1, 1), (1, -1), 'RIGHT'),
            ('ALIGN', (2, 1), (4, -1), 'RIGHT'),
            ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
            # Highlight sale total rows
        ]))
        
        # Highlight sale total rows
        row_idx = 1
        for sale in sales:
            sale_items = sale.saleitem_set.all()
            row_idx += len(sale_items)
            sales_table.setStyle(TableStyle([
                ('BACKGROUND', (0, row_idx), (-1, row_idx), colors.HexColor('#d5dbdb')),
                ('FONTNAME', (0, row_idx), (-1, row_idx), 'Helvetica-Bold'),
            ]))
            row_idx += 1
        
        elements.append(sales_table)
    else:
        elements.append(Paragraph("No sales found for the selected period.", 
                                ParagraphStyle('Normal', parent=styles['Normal'], fontSize=10, textColor=colors.HexColor('#666666'))))

    # Payments History Section
    elements.append(Spacer(1, 0.4*inch))
    elements.append(Paragraph("Payments History", heading_style))
    payments = Payment.objects.filter(**payments_filter).order_by('-date')
    payments_data = [["Date", "Amount (Rs.)", "Mode", "Bank"]]
    for payment in payments:
        payments_data.append([
            payment.date.strftime('%Y-%m-%d'),
            f"{payment.amount:,.2f}",
            payment.get_mode_display(),
            payment.bank or "-"
        ])
    payments_table = Table(payments_data, colWidths=[1.5*inch, 1.5*inch, 1.5*inch, 1.5*inch])
    payments_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#8e44ad')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 12),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 10),
        ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
        ('GRID', (0, 0), (-1, -1), 1, colors.black),
        ('FONTSIZE', (0, 1), (-1, -1), 11),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f5f5f5')]),
        ('ALIGN', (1, 1), (1, -1), 'RIGHT'),
    ]))
    elements.append(payments_table)

    # Build PDF
    doc.build(elements)

    # Get PDF data
    buffer.seek(0)

    # Create HTTP response
    response = HttpResponse(buffer.getvalue(), content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="client_{client.name.replace(" ", "_")}.pdf"'

    return response


@login_required
def export_all_clients_pdf(request):
    """Export all clients' data as combined PDF"""
    from reportlab.lib.pagesizes import letter
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageBreak
    from reportlab.lib.units import inch
    from io import BytesIO
    from django.http import HttpResponse
    from decimal import Decimal
    
    clients = Client.objects.all().order_by('name')
    
    # Create PDF in memory
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, rightMargin=72, leftMargin=72, topMargin=72, bottomMargin=18)
    
    # Container for PDF elements
    elements = []
    
    # Define styles
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=24,
        textColor=colors.HexColor('#1a1a1a'),
        spaceAfter=30,
        alignment=1
    )
    
    heading_style = ParagraphStyle(
        'CustomHeading',
        parent=styles['Heading2'],
        fontSize=14,
        textColor=colors.HexColor('#333333'),
        spaceAfter=12,
        spaceBefore=12
    )
    
    # Add main title
    title = Paragraph("All Clients Report", title_style)
    elements.append(title)
    elements.append(Spacer(1, 0.3*inch))
    
    # Add each client's data on a separate page
    for idx, client in enumerate(clients):
        if idx > 0:
            elements.append(PageBreak())
        
        # Client title
        client_title = Paragraph(f"Client: {client.name}", heading_style)
        elements.append(client_title)
        
        # Client Information
        elements.append(Paragraph("Information", ParagraphStyle('ClientHeading', parent=styles['Heading3'], fontSize=11, spaceAfter=8)))
        
        client_info_data = [
            ['Field', 'Value'],
            ['Name', client.name],
            ['Phone', client.phone],
            ['Address', client.address],
        ]
        
        client_info_table = Table(client_info_data, colWidths=[1.5*inch, 4.5*inch])
        client_info_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#3498db')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 10),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 10),
            ('BACKGROUND', (0, 1), (-1, -1), colors.HexColor('#ecf0f1')),
            ('GRID', (0, 0), (-1, -1), 1, colors.black),
            ('FONTSIZE', (0, 1), (-1, -1), 9),
        ]))
        elements.append(client_info_table)
        elements.append(Spacer(1, 0.2*inch))
        
        # Financial Summary
        total_sales = Sale.objects.filter(client=client).aggregate(total=Sum('total_amount'))['total'] or Decimal('0.00')
        total_paid = Payment.objects.filter(client=client).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
        due_payment = total_sales - total_paid
        
        elements.append(Paragraph("Financial Summary", ParagraphStyle('ClientHeading', parent=styles['Heading3'], fontSize=11, spaceAfter=8)))
        
        financial_data = [
            ['Metric', 'Amount'],
            ['All-Time Sales', f'Rs. {total_sales:,.2f}'],
            ['All-Time Payments', f'Rs. {total_paid:,.2f}'],
            ['Outstanding Due', f'Rs. {due_payment:,.2f}'],
        ]
        
        financial_table = Table(financial_data, colWidths=[2.5*inch, 3.5*inch])
        financial_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#27ae60')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 10),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 10),
            ('BACKGROUND', (0, 1), (-1, -1), colors.HexColor('#ecf0f1')),
            ('GRID', (0, 0), (-1, -1), 1, colors.black),
            ('FONTSIZE', (0, 1), (-1, -1), 9),
            ('ALIGN', (1, 1), (1, -1), 'RIGHT'),
        ]))
        elements.append(financial_table)
        elements.append(Spacer(1, 0.2*inch))
    
    # Build PDF
    doc.build(elements)
    
    # Get PDF data
    buffer.seek(0)
    
    # Create HTTP response
    response = HttpResponse(buffer.getvalue(), content_type='application/pdf')
    response['Content-Disposition'] = 'attachment; filename="all_clients_report.pdf"'
    
    return response


@login_required
def sale_create(request):
    if request.method == 'POST':
        client_id = request.POST.get('client')
        sale_date_str = request.POST.get('sale_date')

        if not client_id:
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'success': False, 'error': 'Please select a client.'})
            messages.error(request, 'Please select a client.')
            formset = SaleItemFormSet(request.POST)
            return render(request, 'distribution/sales/sale_create.html', {
                'formset': formset,
                'clients': Client.objects.all(),
                'selected_client_id': None
            })

        client = get_object_or_404(Client, pk=client_id)
        formset = SaleItemFormSet(request.POST)
        sale_datetime = _resolve_sale_datetime(sale_date_str)
        sale_date_error = _validate_sale_date_not_before_client_creation(client, sale_datetime)

        if sale_date_error:
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'success': False, 'error': sale_date_error})
            messages.error(request, sale_date_error)
            return render(request, 'distribution/sales/sale_create.html', {
                'formset': formset,
                'clients': Client.objects.all(),
                'selected_client_id': int(client_id)
            })

        if formset.is_valid():
            valid_forms = [f for f in formset if f.cleaned_data and not f.cleaned_data.get('DELETE', False)]

            if not valid_forms:
                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return JsonResponse({'success': False, 'error': 'Please add at least one item to the sale.'})
                messages.error(request, 'Please add at least one item to the sale.')
                return render(request, 'distribution/sales/sale_create.html', {
                    'formset': formset,
                    'clients': Client.objects.all(),
                    'selected_client_id': int(client_id)
                })

            with transaction.atomic():
                # Create sale (initially with current time)
                sale = Sale.objects.create(
                    client=client,
                    total_amount=Decimal('0.00'),
                    sale_date=sale_datetime,
                )
                
                total_amount = Decimal('0.00')

                for form in valid_forms:
                    cheese_product = form.cleaned_data['cheese_product']
                    quantity_packets = form.cleaned_data['quantity_packets']
                    selling_price_per_packet = form.cleaned_data['selling_price_per_packet']

                    if quantity_packets > cheese_product.available_quantity_packets:
                        sale.delete()
                        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                            return JsonResponse({'success': False, 'error': f'Insufficient stock for {cheese_product}.'})
                        messages.error(request, f'Insufficient stock for {cheese_product}.')
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

                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return JsonResponse({'success': True, 'message': 'Sale created successfully.'})
                
                messages.success(request, 'Sale created successfully.')
                # Reset formset for same-page submission
                formset = SaleItemFormSet()
                return render(request, 'distribution/sales/sale_create.html', {
                    'formset': formset,
                    'clients': Client.objects.all(),
                    'selected_client_id': None
                })
        else:
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                # Get first error from formset
                error_msg = 'Please correct the errors below.'
                for form in formset:
                    if form.errors:
                        error_msg = str(list(form.errors.values())[0][0])
                        break
                return JsonResponse({'success': False, 'error': error_msg})
            
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


@login_required
def add_payment(request):
    """Record a client payment."""
    if request.method == 'POST':
        form = PaymentForm(request.POST)
        if form.is_valid():
            payment = form.save()
            SiteActivity.update_activity(f'Payment of PKR {payment.amount} recorded for {payment.client.name}')
            
            # Handle AJAX requests
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'success': True, 'message': 'Payment recorded successfully.'})
            
            messages.success(request, 'Payment recorded successfully.')
            return redirect('payment_history')
        else:
            # Handle form errors
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                error_msg = ''
                if form.errors:
                    error_msg = list(form.errors.values())[0][0]
                return JsonResponse({'success': False, 'error': error_msg or 'Invalid form data'})
    else:
        form = PaymentForm()

    return render(request, 'distribution/clients/add_payment.html', {'form': form})


@login_required
def payment_history(request):
    payments = Payment.objects.select_related('client').all().order_by('-date')
    clients = Client.objects.all()
    return render(request, 'distribution/clients/payment_history.html', {
        'payments': payments,
        'clients': clients,
        'user_is_owner': is_owner(request.user),
    })


@login_required
def payment_edit(request, pk):
    payment = get_object_or_404(Payment, pk=pk)

    if request.method == 'POST':
        form = PaymentForm(request.POST, instance=payment)
        if form.is_valid():
            updated_payment = form.save()
            SiteActivity.update_activity(f'Payment updated for {updated_payment.client.name}')

            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'success': True, 'message': 'Payment updated successfully.'})

            messages.success(request, 'Payment updated successfully.')
            return redirect('payment_history')
        
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            html = render_to_string('distribution/clients/partials/partial_edit_payment_form.html', {
                'payment': payment,
                'form': form,
            }, request=request)
            return JsonResponse({'success': False, 'html': html})
    else:
        form = PaymentForm(instance=payment)

    return render(request, 'distribution/clients/partials/partial_edit_payment_form.html', {
        'payment': payment,
        'form': form,
    })


@owner_required
@require_POST
def payment_delete(request, pk):
    payment = get_object_or_404(Payment, pk=pk)
    client_name = payment.client.name
    amount = payment.amount
    payment.delete()
    SiteActivity.update_activity(f'Payment deleted for {client_name} (PKR {amount})')
    messages.success(request, 'Payment deleted successfully.')
    return redirect('payment_history')


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
            message = 'Employee added successfully.'
            
            # Check if AJAX request
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({
                    'success': True,
                    'message': message,
                    'object': {
                        'id': employee.id,
                        'name': employee.name,
                        'id_card': employee.id_card,
                        'joining_date': employee.joining_date.strftime('%Y-%m-%d'),
                        'route_from': employee.route_from or '',
                        'route_to': employee.route_to or '',
                        'phone': employee.phone or ''
                    }
                })
            
            messages.success(request, message)
            return redirect('employee_management')
        else:
            # Extract error messages
            error_messages = []
            for field, errors in form.errors.items():
                if field != '__all__':
                    error_messages.extend(errors)
                else:
                    error_messages.extend(errors)
            error_text = ', '.join(error_messages) if error_messages else 'Please correct the errors below.'
            
            # Check if AJAX request
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'success': False, 'error': error_text})
            
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
            message = 'Expense added successfully.'
            SiteActivity.update_activity(f'Expense added: {expense.get_expense_type_display()}')
            
            # Check if AJAX request
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({
                    'success': True,
                    'message': message,
                    'object': {
                        'id': expense.id,
                        'expense_date': expense.expense_date.strftime('%Y-%m-%d'),
                        'employee': {
                            'id': expense.employee.id,
                            'name': expense.employee.name
                        },
                        'expense_type': expense.expense_type,
                        'expense_type_display': expense.get_expense_type_display(),
                        'amount': float(expense.amount),
                        'note': expense.note or ''
                    }
                })
            
            messages.success(request, message)
            return redirect('expense_management')
        else:
            # Extract error messages
            error_messages = []
            for field, errors in form.errors.items():
                if field != '__all__':
                    error_messages.extend(errors)
                else:
                    error_messages.extend(errors)
            error_text = ', '.join(error_messages) if error_messages else 'Please correct the errors below.'
            
            # Check if AJAX request
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'success': False, 'error': error_text})
            
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


@login_required
def sale_edit(request, pk):
    """Edit sale with client, date, and items with inventory management"""
    sale = get_object_or_404(Sale, pk=pk)
    original_items = list(sale.saleitem_set.all())  # Store original items
    
    if request.method == 'GET':
        # Return JSON data for modal population
        return JsonResponse({
            'success': True,
            'sale': {
                'id': sale.id,
                'client_id': sale.client_id,
                'client_name': sale.client.name,
                'sale_date_iso': sale.sale_date.strftime('%Y-%m-%dT%H:%M') if sale.sale_date else '',
                'total_amount': str(sale.total_amount)
            },
            'items': [
                {
                    'id': item.id,
                    'cheese_product_id': item.cheese_product_id,
                    'cheese_product_name': f"{item.cheese_product.manufacturer.name} {item.cheese_product.type.name} {item.cheese_product.packet_size}kg",
                    'quantity_packets': item.quantity_packets,
                    'selling_price_per_packet': str(item.selling_price_per_packet)
                }
                for item in original_items
            ],
            'clients': [
                {'id': c.id, 'name': c.name}
                for c in Client.objects.all()
            ],
            'products': [
                {'id': p.id, 'name': f"{p.manufacturer.name} {p.type.name} {p.packet_size}kg"}
                for p in CheeseProduct.objects.all()
            ]
        })
    
    if request.method == 'POST':
        client_id = request.POST.get('client')
        sale_date_str = request.POST.get('sale_date')
        formset = SaleItemFormSet(request.POST)
        
        # Validate client
        if not client_id:
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'success': False, 'error': 'Please select a client.'})
            messages.error(request, 'Please select a client.')
            return redirect('sale_history')
        
        client = get_object_or_404(Client, pk=client_id)
        sale_datetime = _resolve_sale_datetime(sale_date_str) if sale_date_str else sale.sale_date
        sale_date_error = _validate_sale_date_not_before_client_creation(client, sale_datetime)
        if sale_date_error:
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'success': False, 'error': sale_date_error})
            messages.error(request, sale_date_error)
            return redirect('sale_history')

        
        # Validate formset
        if formset.is_valid():
            valid_forms = [f for f in formset if f.cleaned_data and not f.cleaned_data.get('DELETE', False)]
            
            if not valid_forms:
                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return JsonResponse({'success': False, 'error': 'Please add at least one item to the sale.'})
                messages.error(request, 'Please add at least one item to the sale.')
                return redirect('sale_history')
            
            with transaction.atomic():
                # Step 1: Restore original stock
                for original_item in original_items:
                    original_item.cheese_product.available_quantity_packets += original_item.quantity_packets
                    original_item.cheese_product.save()
                
                # Step 2: Check if new quantities are available
                for form in valid_forms:
                    cheese_product = form.cleaned_data['cheese_product']
                    quantity_packets = form.cleaned_data['quantity_packets']
                    
                    if quantity_packets > cheese_product.available_quantity_packets:
                        # Roll back the atomic transaction so restored stock changes are not committed.
                        transaction.set_rollback(True)
                        
                        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                            return JsonResponse({'success': False, 'error': f'Insufficient stock for {cheese_product}. Requested: {quantity_packets}, available: {cheese_product.available_quantity_packets}.'})
                        messages.error(request, f'Insufficient stock for {cheese_product}.')
                        return redirect('sale_history')
                
                # Step 3: Delete old sale items
                sale.saleitem_set.all().delete()
                
                # Step 4: Create new sale items and deduct stock
                total_amount = Decimal('0.00')
                
                for form in valid_forms:
                    cheese_product = form.cleaned_data['cheese_product']
                    quantity_packets = form.cleaned_data['quantity_packets']
                    selling_price_per_packet = form.cleaned_data['selling_price_per_packet']
                    
                    SaleItem.objects.create(
                        sale=sale,
                        cheese_product=cheese_product,
                        quantity_packets=quantity_packets,
                        selling_price_per_packet=selling_price_per_packet
                    )
                    
                    cheese_product.available_quantity_packets -= quantity_packets
                    cheese_product.save()
                    
                    total_amount += selling_price_per_packet * quantity_packets
                
                # Step 5: Update sale with new client, date, and total
                sale.client = client
                sale.sale_date = sale_datetime
                
                sale.total_amount = total_amount
                sale.save()
                
                SiteActivity.update_activity(f'Sale #{sale.id} edited for {client.name}')
                
                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return JsonResponse({'success': True, 'message': 'Sale updated successfully.'})
                
                messages.success(request, 'Sale updated successfully.')
                return redirect('sale_history')
        else:
            # Formset validation failed - get detailed error message
            error_msg = 'Form validation failed:'
            error_count = 0
            for idx, form in enumerate(formset):
                if form.errors:
                    error_count += 1
                    for field, errors in form.errors.items():
                        if error_count == 1:  # Only show first error
                            error_msg = f"Item {idx + 1}: {errors[0]}"
                            break
                    if error_count == 1:
                        break
            
            if not error_msg or error_msg == 'Form validation failed:':
                error_msg = 'Please check the form data and try again.'
            
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'success': False, 'error': error_msg})
            messages.error(request, error_msg)
            return redirect('sale_history')


@login_required
def sale_delete(request, pk):
    """Delete a sale"""
    sale = get_object_or_404(Sale, pk=pk)
    
    if request.method == 'POST':
        sale_id = sale.id
        sale.delete()
        SiteActivity.update_activity(f'Sale #{sale_id} deleted')
        
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'success': True, 'message': 'Sale deleted successfully.'})
        
        messages.success(request, 'Sale deleted successfully.')
        return redirect('sale_history')
    
    return render(request, 'distribution/sales/sale_confirm_delete.html', {'sale': sale})


@owner_required
def database_management(request):
    """Owner-only database backup and restore page (SQLite and PostgreSQL)."""
    db_settings = settings.DATABASES.get('default', {})
    engine = db_settings.get('ENGINE', '')
    db_name = db_settings.get('NAME', '')
    is_sqlite = 'sqlite3' in engine
    is_postgres = 'postgresql' in engine

    if not (is_sqlite or is_postgres):
        messages.error(request, 'Database backup/restore is supported only for SQLite and PostgreSQL.')
        return redirect('dashboard')

    db_path = None
    if is_sqlite:
        db_path = Path(str(db_name))
        if not db_path.is_absolute():
            db_path = settings.BASE_DIR / db_path

        if not db_path.exists():
            messages.error(request, 'Database file was not found on disk.')
            return redirect('dashboard')

    backup_dir = settings.BASE_DIR / 'db_backups'
    backup_dir.mkdir(parents=True, exist_ok=True)

    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'backup':
            timestamp = timezone.localtime().strftime('%Y%m%d_%H%M%S')

            if is_sqlite:
                backup_name = f'backup_{timestamp}.sqlite3'
                backup_path = backup_dir / backup_name
                connections.close_all()
                shutil.copy2(db_path, backup_path)
                SiteActivity.update_activity(f'SQLite database backup downloaded by {request.user.username}')
                return FileResponse(open(backup_path, 'rb'), as_attachment=True, filename=backup_name)

            # PostgreSQL logical backup via Django fixture serialization.
            backup_name = f'backup_{timestamp}.json'
            backup_path = backup_dir / backup_name
            try:
                with open(backup_path, 'w', encoding='utf-8') as backup_file:
                    call_command(
                        'dumpdata',
                        natural_foreign=True,
                        natural_primary=True,
                        indent=2,
                        stdout=backup_file,
                    )
                SiteActivity.update_activity(f'PostgreSQL fixture backup downloaded by {request.user.username}')
                return FileResponse(open(backup_path, 'rb'), as_attachment=True, filename=backup_name)
            except Exception as exc:
                messages.error(request, f'Backup generation failed: {exc}')
                return redirect('database_management')

        if action == 'restore':
            uploaded_file = request.FILES.get('database_file')
            confirm_restore = request.POST.get('confirm_restore') == 'on'

            if not uploaded_file:
                messages.error(request, 'Please choose a database file to restore.')
                return redirect('database_management')

            if not confirm_restore:
                messages.error(request, 'Please confirm restore before continuing.')
                return redirect('database_management')

            if is_sqlite:
                allowed_suffixes = ('.sqlite3', '.db', '.sqlite', '.backup')
                if not uploaded_file.name.lower().endswith(allowed_suffixes):
                    messages.error(request, 'Invalid file type. Upload a SQLite database file.')
                    return redirect('database_management')

                temp_fd, temp_path = tempfile.mkstemp(suffix='.sqlite3')
                os.close(temp_fd)
                try:
                    with open(temp_path, 'wb') as destination:
                        for chunk in uploaded_file.chunks():
                            destination.write(chunk)

                    # Basic SQLite integrity check.
                    with sqlite3.connect(temp_path) as conn:
                        cursor = conn.cursor()
                        cursor.execute("PRAGMA integrity_check;")
                        integrity_result = cursor.fetchone()
                        if not integrity_result or integrity_result[0] != 'ok':
                            messages.error(request, 'Uploaded file failed SQLite integrity check.')
                            return redirect('database_management')

                        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='django_migrations';")
                        if cursor.fetchone() is None:
                            messages.error(request, 'Uploaded file is not a valid Django database backup.')
                            return redirect('database_management')

                    backup_name = f'pre_restore_{timezone.localtime().strftime("%Y%m%d_%H%M%S")}.sqlite3'
                    backup_path = backup_dir / backup_name

                    connections.close_all()
                    shutil.copy2(db_path, backup_path)
                    shutil.copy2(temp_path, db_path)

                    SiteActivity.update_activity(
                        f'SQLite database restored by {request.user.username}; previous DB saved as {backup_name}'
                    )
                    messages.success(
                        request,
                        f'Database restored successfully. A safety backup was saved to db_backups/{backup_name}.'
                    )
                    return redirect('database_management')
                except sqlite3.Error:
                    messages.error(request, 'Uploaded file is not a valid SQLite database.')
                    return redirect('database_management')
                except Exception as exc:
                    messages.error(request, f'Database restore failed: {exc}')
                    return redirect('database_management')
                finally:
                    try:
                        Path(temp_path).unlink(missing_ok=True)
                    except OSError:
                        pass

            # PostgreSQL restore from JSON fixture.
            if not uploaded_file.name.lower().endswith('.json'):
                messages.error(request, 'Invalid file type. Upload a JSON fixture backup file.')
                return redirect('database_management')

            temp_fd, temp_path = tempfile.mkstemp(suffix='.json')
            os.close(temp_fd)
            try:
                with open(temp_path, 'wb') as destination:
                    for chunk in uploaded_file.chunks():
                        destination.write(chunk)

                # Validate JSON before any destructive operation.
                with open(temp_path, 'r', encoding='utf-8') as source_file:
                    data = json.load(source_file)
                    if not isinstance(data, list):
                        messages.error(request, 'Invalid fixture format: expected a JSON list.')
                        return redirect('database_management')

                # Create safety backup before restore.
                safety_backup_name = f'pre_restore_{timezone.localtime().strftime("%Y%m%d_%H%M%S")}.json'
                safety_backup_path = backup_dir / safety_backup_name
                with open(safety_backup_path, 'w', encoding='utf-8') as safety_file:
                    call_command(
                        'dumpdata',
                        natural_foreign=True,
                        natural_primary=True,
                        indent=2,
                        stdout=safety_file,
                    )

                # Reset data and load uploaded fixture.
                with transaction.atomic():
                    call_command('flush', verbosity=0, interactive=False)
                    call_command('loaddata', temp_path, verbosity=0)

                SiteActivity.update_activity(
                    f'PostgreSQL database restored by {request.user.username}; previous data saved as {safety_backup_name}'
                )
                messages.success(
                    request,
                    f'Database restored successfully. A safety backup was saved to db_backups/{safety_backup_name}.'
                )
                return redirect('database_management')
            except json.JSONDecodeError:
                messages.error(request, 'Uploaded file is not valid JSON.')
                return redirect('database_management')
            except Exception as exc:
                messages.error(request, f'PostgreSQL restore failed: {exc}')
                return redirect('database_management')
            finally:
                try:
                    Path(temp_path).unlink(missing_ok=True)
                except OSError:
                    pass

    if is_sqlite:
        recent_backups = sorted(backup_dir.glob('*.sqlite3'), reverse=True)
        db_label = 'SQLite'
        restore_accept = '.sqlite3,.sqlite,.db,.backup'
        restore_label = 'SQLite backup file'
    else:
        recent_backups = sorted(backup_dir.glob('*.json'), reverse=True)
        db_label = 'PostgreSQL'
        restore_accept = '.json'
        restore_label = 'PostgreSQL JSON fixture'

    backup_names = [p.name for p in recent_backups[:10]]

    return render(request, 'distribution/database_management.html', {
        'database_name': db_path.name if db_path else db_name,
        'database_path': str(db_path) if db_path else db_name,
        'database_type': db_label,
        'is_sqlite': is_sqlite,
        'is_postgres': is_postgres,
        'restore_accept': restore_accept,
        'restore_label': restore_label,
        'backup_files': backup_names,
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
