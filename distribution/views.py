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
    DeliveryEmployee, DeliveryExpense,
)
from .forms import (
    ManufacturerForm, CheeseProductForm, ClientForm,
    SaleItemForm, SaleItemFormSet, UserForm, UserRoleForm, AddStockForm, AddStockFormSet,
    PaymentForm, DeliveryEmployeeForm, DeliveryExpenseForm,
)
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

# AJAX endpoint to process return for stock addition
@login_required
@require_POST
def return_stock_addition(request):
    addition_id = request.POST.get('addition_id')
    quantity = request.POST.get('quantity')
    reason = request.POST.get('reason', '')
    addition = get_object_or_404(StockAdditionHistory, pk=addition_id)
    quantity = Decimal(quantity)
    if quantity > addition.quantity_packets:
        return JsonResponse({'success': False, 'error': 'Return quantity exceeds added quantity.'})
    Return.objects.create(stock_addition=addition, quantity_packets=quantity, reason=reason)
    addition.modified = True
    addition.save()
    # Optionally, update cheese product stock
    addition.cheese_product.available_quantity_packets -= quantity
    addition.cheese_product.save()
    return JsonResponse({'success': True})

# AJAX endpoint for sale modal details
from django.views.decorators.http import require_GET

@login_required
@require_GET
def sale_modal_details(request, pk):
    sale = get_object_or_404(Sale, pk=pk)
    sale_items = sale.saleitem_set.select_related('cheese_product').all()
    total_profit = sale.calculate_total_profit()
    return render(request, 'distribution/partials/sale_modal_details.html', {
        'sale': sale,
        'sale_items': sale_items,
        'total_profit': total_profit
    })

# AJAX endpoint for stock modal details
@login_required
@require_GET
def stock_modal_details(request, pk):
    addition = get_object_or_404(StockAdditionHistory, pk=pk)
    returns = addition.return_set.all()
    return render(request, 'distribution/partials/stock_modal_details.html', {
        'addition': addition,
        'returns': returns
    })

from .models import StockAdditionHistory, Return


@login_required
def stock_history(request):
    stock_additions = StockAdditionHistory.objects.select_related('cheese_product', 'added_by').all()
    return render(request, 'distribution/stock_history.html', {
        'stock_additions': stock_additions,
        'add_stock_formset': AddStockFormSet(),
    })

def cheese_type_list(request):
    types = CheeseType.objects.all()
    return render(request, 'distribution/cheese_type_list.html', {'types': types})

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
                html = render_to_string('distribution/partials/edit_cheese_type_form.html', {'form': form}, request=request)
                return JsonResponse({'success': False, 'html': html, 'error': error_msg})
    else:
        form = CheeseTypeForm()
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        html = render_to_string('distribution/partials/edit_cheese_type_form.html', {'form': form}, request=request)
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
    html = render_to_string('distribution/partials/edit_cheese_type_form.html', {'form': form, 'cheese_type': cheese_type}, request=request)
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
        return redirect('dashboard')
    
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

    context = {
        'user_is_owner': user_is_owner,
        'now': timezone.now(),
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

    # Get payment analytics
    if start_date and end_date:
        sales_queryset = Sale.objects.filter(sale_date__date__range=[start_date, end_date])
    else:
        sales_queryset = Sale.objects.all()

    total_outstanding = sum(sale.get_outstanding_amount() for sale in sales_queryset)
    payment_status_counts = {
        'paid': sales_queryset.filter(payment_status='paid').count(),
        'partial': sales_queryset.filter(payment_status='partial').count(),
        'unpaid': sales_queryset.filter(payment_status='unpaid').count(),
    }

    summary = {
        'total_clients': total_clients,
        'total_revenue': float(total_revenue),
        'total_profit': float(total_profit_all),
        'total_transactions': total_transactions_all,
        'avg_client_value': float(total_revenue / total_clients) if total_clients > 0 else 0,
        'total_outstanding': float(total_outstanding),
        'payment_status_counts': payment_status_counts,
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
@login_required
def sales_stock_history(request):
    """Page for Sales and Stock History with toggle functionality"""
    user_is_owner = is_owner(request.user)

    # Get sales data
    sales = Sale.objects.select_related('client').order_by('-sale_date')[:50]  # Last 50 sales

    # Get stock history data
    from .models import StockAdditionHistory
    stock_history = StockAdditionHistory.objects.select_related(
        'cheese_product__manufacturer', 'cheese_product__type', 'added_by__user'
    ).order_by('-date_added')[:50]  # Last 50 stock additions

    # Format stock history for template
    formatted_stock_history = []
    for stock in stock_history:
        formatted_stock_history.append({
            'id': stock.id,
            'product_name': f"{stock.cheese_product.manufacturer.name} {stock.cheese_product.type.name} {stock.cheese_product.packet_size}kg",
            'quantity_packets': stock.quantity_packets,
            'date_added': stock.date_added,
            'added_by': stock.added_by.user.username if stock.added_by else 'Unknown',
        })

    return render(request, 'distribution/sales_stock_history.html', {
        'user_is_owner': user_is_owner,
        'sales': sales,
        'stock_history': formatted_stock_history,
        'clients': Client.objects.all(),
        'formset': SaleItemFormSet(),
    })


@login_required
def add_stock_page(request):
    """Dedicated page for adding stock to products"""
    user_is_owner = is_owner(request.user)
    if not user_is_owner:
        messages.error(request, 'Only owners can add stock.')
        return redirect('dashboard')

    add_stock_formset = AddStockFormSet()
    return render(request, 'distribution/add_stock.html', {
        'user_is_owner': user_is_owner,
        'add_stock_formset': add_stock_formset,
    })


@login_required
def get_sales_history(request):
    """AJAX endpoint to get sales history with payment status"""
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

    # Get sales with payment information
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
            'amount_paid': float(sale.amount_paid),
            'outstanding_amount': float(sale.get_outstanding_amount()),
            'payment_status': sale.payment_status,
            'payment_method': sale.get_payment_method_display() if sale.payment_method else None,
            'payment_date': sale.payment_date.strftime('%Y-%m-%d %H:%M') if sale.payment_date else None,
            'total_profit': float(sale.calculate_total_profit()),
        })

    # Sort by date descending
    sales_data.sort(key=lambda x: x['sale_date'], reverse=True)

    # Calculate summary stats
    total_sales = len(sales_data)
    total_revenue = sum(sale['total_amount'] for sale in sales_data)
    total_paid = sum(sale['amount_paid'] for sale in sales_data)
    total_outstanding = sum(sale['outstanding_amount'] for sale in sales_data)
    total_profit = sum(sale['total_profit'] for sale in sales_data)

    # Payment status breakdown
    unpaid_count = sum(1 for sale in sales_data if sale['payment_status'] == 'unpaid')
    partial_count = sum(1 for sale in sales_data if sale['payment_status'] == 'partial')
    paid_count = sum(1 for sale in sales_data if sale['payment_status'] == 'paid')

    summary = {
        'total_sales': total_sales,
        'total_revenue': float(total_revenue),
        'total_paid': float(total_paid),
        'total_outstanding': float(total_outstanding),
        'total_profit': float(total_profit),
        'unpaid_count': unpaid_count,
        'partial_count': partial_count,
        'paid_count': paid_count,
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

    # Get stock addition history
    from .models import StockAdditionHistory
    if start_date and end_date:
        stock_history = StockAdditionHistory.objects.filter(
            date_added__date__range=[start_date, end_date]
        ).select_related('cheese_product__manufacturer', 'cheese_product__type', 'added_by__user')
    else:
        stock_history = StockAdditionHistory.objects.all().select_related(
            'cheese_product__manufacturer', 'cheese_product__type', 'added_by__user'
        )

    stock_data = []
    for stock_item in stock_history:
        stock_data.append({
            'id': stock_item.id,
            'product_name': f"{stock_item.cheese_product.manufacturer.name} {stock_item.cheese_product.type.name} {stock_item.cheese_product.packet_size}kg",
            'quantity_packets': float(stock_item.quantity_packets),
            'date_added': stock_item.date_added.strftime('%Y-%m-%d %H:%M'),
            'added_by': stock_item.added_by.user.username if stock_item.added_by else 'Unknown',
            'modified': stock_item.modified,
        })

    # Sort by date descending
    stock_data.sort(key=lambda x: x['date_added'], reverse=True)

    # Calculate summary stats
    total_stock_additions = len(stock_data)
    total_packets_added = sum(item['quantity_packets'] for item in stock_data)

    # Group by product for summary
    product_summary = {}
    for item in stock_data:
        if item['product_name'] not in product_summary:
            product_summary[item['product_name']] = 0
        product_summary[item['product_name']] += item['quantity_packets']

    summary = {
        'total_stock_additions': total_stock_additions,
        'total_packets_added': float(total_packets_added),
        'unique_products': len(product_summary),
        'product_summary': product_summary,
    }

    return JsonResponse({
        'stock_history': stock_data,
        'summary': summary,
        'period': period
    })


@login_required
def get_client_debt(request):
    """AJAX endpoint to get client outstanding debt information"""
    # Get all clients with their outstanding debt
    clients = Client.objects.all()
    client_debt_data = []
    total_outstanding = Decimal('0.00')
    
    for client in clients:
        # Get all sales for this client
        client_sales = Sale.objects.filter(client=client)
        
        if client_sales.exists():
            # Calculate totals
            total_sales_amount = client_sales.aggregate(total=Sum('total_amount'))['total'] or Decimal('0.00')
            total_amount_paid = client_sales.aggregate(total=Sum('amount_paid'))['total'] or Decimal('0.00')
            
            outstanding_amount = total_sales_amount - total_amount_paid
            
            if outstanding_amount > 0:
                client_debt_data.append({
                    'client_id': client.id,
                    'client_name': client.name,
                    'client_phone': client.phone,
                    'total_sales': float(total_sales_amount),
                    'total_paid': float(total_amount_paid),
                    'outstanding_amount': float(outstanding_amount),
                })
                total_outstanding += outstanding_amount
    
    # Sort by outstanding amount descending
    client_debt_data.sort(key=lambda x: x['outstanding_amount'], reverse=True)
    
    summary = {
        'total_clients_with_debt': len(client_debt_data),
        'total_outstanding_debt': float(total_outstanding),
        'total_clients': Client.objects.count(),
    }
    
    return JsonResponse({
        'client_debt': client_debt_data,
        'summary': summary,
    })


@login_required
def client_debt_page(request):
    """Dedicated page for viewing and managing client debt"""
    clients = Client.objects.all()
    user_is_owner = is_owner(request.user)
    
    # Get client debt data
    client_debt_data = []
    total_outstanding = Decimal('0.00')
    
    for client in clients:
        # Get all sales for this client
        client_sales = Sale.objects.filter(client=client)
        
        if client_sales.exists():
            # Calculate totals
            total_sales_amount = client_sales.aggregate(total=Sum('total_amount'))['total'] or Decimal('0.00')
            total_amount_paid = client_sales.aggregate(total=Sum('amount_paid'))['total'] or Decimal('0.00')
            
            outstanding_amount = total_sales_amount - total_amount_paid
            
            if outstanding_amount > 0:
                client_debt_data.append({
                    'client_id': client.id,
                    'client_name': client.name,
                    'client_phone': client.phone,
                    'total_sales': total_sales_amount,
                    'total_paid': total_amount_paid,
                    'outstanding_amount': outstanding_amount,
                })
                total_outstanding += outstanding_amount
    
    # Sort by outstanding amount descending
    client_debt_data.sort(key=lambda x: x['outstanding_amount'], reverse=True)
    
    summary = {
        'total_clients_with_debt': len(client_debt_data),
        'total_outstanding_debt': total_outstanding,
        'total_clients': Client.objects.count(),
    }
    
    return render(request, 'distribution/client_debt.html', {
        'client_debt_data': client_debt_data,
        'summary': summary,
        'user_is_owner': user_is_owner,
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
    for product in products:
        stock_value = product.available_quantity_packets * product.purchase_price_per_packet
        products_with_value.append({
            'product': product,
            'stock_value': stock_value
        })

    from .forms import ManufacturerForm, CheeseProductForm
    manufacturer_form = ManufacturerForm()
    cheese_product_form = CheeseProductForm()
    cheese_type_form = CheeseTypeForm()
    add_stock_formset = AddStockFormSet()
    return render(request, 'distribution/inventory_management.html', {
        'manufacturers': manufacturers,
        'products_with_value': products_with_value,
        'manufacturer_form': manufacturer_form,
        'cheese_product_form': cheese_product_form,
        'cheese_type_form': cheese_type_form,
        'add_stock_formset': add_stock_formset,
        'cheese_types': cheese_types,
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
                html = render_to_string('distribution/partials/edit_manufacturer_form.html', {'form': form}, request=request)
                return JsonResponse({'success': False, 'html': html, 'error': error_msg})
    else:
        form = ManufacturerForm()
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        html = render_to_string('distribution/partials/edit_manufacturer_form.html', {'form': form}, request=request)
        return JsonResponse({'success': False, 'html': html})
    return render(request, 'distribution/manufacturer_form.html', {'form': form, 'title': 'Add Manufacturer'})


@owner_required
def manufacturer_edit(request, pk):
    manufacturer = get_object_or_404(Manufacturer, pk=pk)
    if request.method == 'POST':
        form = ManufacturerForm(request.POST, instance=manufacturer)
        if form.is_valid():
            form.save()
            if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                return render(request, 'distribution/partials/edit_success.html', {'object': manufacturer, 'type': 'manufacturer'})
            messages.success(request, 'Manufacturer updated successfully.')
            return redirect('inventory_management')
    else:
        form = ManufacturerForm(instance=manufacturer)
    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        html = render_to_string('distribution/partials/edit_manufacturer_form.html', {'form': form, 'manufacturer': manufacturer}, request=request)
        return JsonResponse({'html': html})
    return render(request, 'distribution/manufacturer_form.html', {'form': form, 'title': 'Edit Manufacturer'})


@owner_required
def manufacturer_delete(request, pk):
    manufacturer = get_object_or_404(Manufacturer, pk=pk)
    if request.method == 'POST':
        manufacturer.delete()
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
                html = render_to_string('distribution/partials/edit_cheese_form.html', {'form': form}, request=request)
                return JsonResponse({'success': False, 'html': html, 'error': error_msg})
    else:
        form = CheeseProductForm()
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        html = render_to_string('distribution/partials/edit_cheese_form.html', {'form': form}, request=request)
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
                return render(request, 'distribution/partials/edit_success.html', {'object': product, 'type': 'cheese'})
            messages.success(request, 'Cheese product updated successfully.')
            return redirect('inventory_management')
    else:
        form = CheeseProductForm(instance=product)
    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        html = render_to_string('distribution/partials/edit_cheese_form.html', {'form': form, 'product': product}, request=request)
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
    if request.method == 'POST':
        formset = AddStockFormSet(request.POST)
        if formset.is_valid():
            valid_forms = [f for f in formset if f.cleaned_data]

            if not valid_forms:
                return JsonResponse({'success': False, 'error': 'Please add at least one stock item.'})

            stock_added = []
            for form in valid_forms:
                cheese_product = form.cleaned_data['cheese_product']
                quantity_packets = form.cleaned_data['quantity_packets']
                purchase_price_per_packet = form.cleaned_data['purchase_price_per_packet']

                cheese_product.available_quantity_packets += quantity_packets
                # Update the product's purchase price to the newly added price
                cheese_product.purchase_price_per_packet = purchase_price_per_packet
                cheese_product.save()

                # Create stock addition history
                StockAdditionHistory.objects.create(
                    cheese_product=cheese_product,
                    added_by=request.user.userprofile,
                    quantity_packets=quantity_packets
                )

                stock_added.append(f"{quantity_packets} packets to {cheese_product}")

            messages.success(request, f'Successfully added stock: {", ".join(stock_added)}.')
            return JsonResponse({'success': True})
        else:
            return JsonResponse({'success': False, 'error': 'Please correct the errors below.'})
    else:
        formset = AddStockFormSet()

    html = render_to_string('distribution/partials/add_stock_form.html', {'formset': formset}, request=request)
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

                return JsonResponse({'success': True, 'message': 'Sale created successfully.'})
        else:
            return JsonResponse({'success': False, 'error': 'Please correct the errors below.'})
    else:
        formset = SaleItemFormSet()

    html = render_to_string('distribution/partials/quick_sale_form.html', {
        'formset': formset,
        'clients': Client.objects.all()
    }, request=request)
    return JsonResponse({'html': html})


@login_required
def client_list(request):
    clients = Client.objects.all()
    user_is_owner = is_owner(request.user)

    # Calculate outstanding dues for each client
    clients_with_dues = []
    for client in clients:
        # Get all sales for this client
        client_sales = Sale.objects.filter(client=client)

        if client_sales.exists():
            # Calculate totals
            total_sales_amount = client_sales.aggregate(
                total=Sum('total_amount')
            )['total'] or Decimal('0.00')

            total_amount_paid = client_sales.aggregate(
                total=Sum('amount_paid')
            )['total'] or Decimal('0.00')

            outstanding_amount = total_sales_amount - total_amount_paid

            # Get unique payment methods used by this client
            payment_methods = client_sales.exclude(payment_method__isnull=True).exclude(payment_method='').values_list('payment_method', flat=True).distinct()

            clients_with_dues.append({
                'client': client,
                'outstanding_dues': outstanding_amount,
                'payment_methods': list(payment_methods),
                'total_sales': total_sales_amount,
                'total_paid': total_amount_paid,
            })
        else:
            # Client with no sales
            clients_with_dues.append({
                'client': client,
                'outstanding_dues': Decimal('0.00'),
                'payment_methods': [],
                'total_sales': Decimal('0.00'),
                'total_paid': Decimal('0.00'),
            })

    from .forms import ClientForm
    client_form = ClientForm()
    return render(request, 'distribution/clients.html', {
        'clients_with_dues': clients_with_dues,
        'user_is_owner': user_is_owner,
        'client_form': client_form,
    })


@login_required
def client_add(request):
    if request.method == 'POST':
        form = ClientForm(request.POST)
        if form.is_valid():
            form.save()
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
            if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                return render(request, 'distribution/partials/edit_success.html', {'object': client, 'type': 'client'})
            messages.success(request, 'Client updated successfully.')
            return redirect('client_list')
    else:
        form = ClientForm(instance=client)
    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        return render(request, 'distribution/partials/edit_client_form.html', {'form': form, 'client': client})
    return render(request, 'distribution/client_form.html', {'form': form, 'title': 'Edit Client'})


@owner_required
def client_delete(request, pk):
    client = get_object_or_404(Client, pk=pk)
    if request.method == 'POST':
        client.delete()
        messages.success(request, 'Client deleted successfully.')
        return redirect('client_list')
    return render(request, 'distribution/client_delete.html', {'client': client})


@login_required
def sale_create(request):
    if request.method == 'POST':
        client_id = request.POST.get('client')
        payment_method = request.POST.get('payment_method')
        amount_paid_str = request.POST.get('amount_paid', '0').strip()
        
        # Convert amount_paid to Decimal with proper quantization
        try:
            if amount_paid_str:
                amount_paid = Decimal(amount_paid_str).quantize(Decimal('0.01'))
            else:
                amount_paid = Decimal('0.00')
        except:
            amount_paid = Decimal('0.00')

        if not client_id:
            messages.error(request, 'Please select a client.')
            formset = SaleItemFormSet(request.POST)
            return render(request, 'distribution/sale_create.html', {
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
                return render(request, 'distribution/sale_create.html', {
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
                        return render(request, 'distribution/sale_create.html', {
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

                # Update sale with payment information
                sale.total_amount = total_amount
                sale.amount_paid = amount_paid
                if payment_method:
                    sale.payment_method = payment_method
                sale.update_payment_status()
                sale.save()

                messages.success(request, 'Sale created successfully.')
                return redirect('sales_stock_history')
        else:
            messages.error(request, 'Please correct the errors below.')
            return render(request, 'distribution/sale_create.html', {
                'formset': formset,
                'clients': Client.objects.all(),
                'selected_client_id': int(client_id) if client_id else None
            })
    else:
        formset = SaleItemFormSet()

    return render(request, 'distribution/sale_create.html', {
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
    
    return render(request, 'distribution/sale_history.html', {
        'sales_data': sales_with_profit,
        'user_is_owner': user_is_owner,
        'clients': Client.objects.all(),
        'formset': SaleItemFormSet(),
    })


@owner_required
def make_payment(request):
    """Record a client payment and apply it to the client's oldest unpaid sales."""
    if request.method == 'POST':
        form = PaymentForm(request.POST)
        if form.is_valid():
            client = form.cleaned_data['client']
            amount = form.cleaned_data['amount']
            mode = form.cleaned_data['mode']
            bank = form.cleaned_data.get('bank') or ''

            remaining = Decimal(amount)

            # Apply payments to the client's sales in chronological order.
            sales = Sale.objects.filter(client=client).order_by('sale_date', 'id')
            for sale in sales:
                outstanding = sale.get_outstanding_amount()
                if outstanding <= 0:
                    continue

                apply_amount = min(outstanding, remaining)
                if apply_amount <= 0:
                    continue

                sale.amount_paid = sale.amount_paid + apply_amount
                sale.payment_date = timezone.now()
                sale.payment_method = 'online_banking' if mode == 'online' else 'cash'

                # Update payment status manually (avoid calling Sale.update_payment_status()).
                if sale.amount_paid == 0:
                    sale.payment_status = 'unpaid'
                elif sale.amount_paid >= sale.total_amount:
                    sale.payment_status = 'paid'
                else:
                    sale.payment_status = 'partial'

                sale.save()
                remaining -= apply_amount
                if remaining <= 0:
                    break

            Payment.objects.create(client=client, amount=amount, mode=mode, bank=bank)
            messages.success(request, 'Payment recorded successfully.')
            return redirect('payment_history')
    else:
        form = PaymentForm()

    return render(request, 'distribution/make_payment.html', {'form': form})


@login_required
@login_required
def payment_history(request):
    payments = Payment.objects.select_related('client').all().order_by('-date')
    return render(request, 'distribution/payment_history.html', {'payments': payments})


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
            form.save()
            messages.success(request, 'Employee added successfully.')
            return redirect('employee_management')
        else:
            # Keep errors only inline with form fields.
            pass
    else:
        form = DeliveryEmployeeForm()

    return render(request, 'distribution/employee_management.html', {
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
            messages.success(request, 'Employee updated successfully.')
            return redirect('employee_management')
        # Keep errors only inline with form fields.
        pass

    else:
        form = DeliveryEmployeeForm(instance=employee)

    return render(request, 'distribution/partials/edit_employee_form.html', {
        'employee': employee,
        'form': form,
    })


@login_required
@require_POST
def employee_delete(request, pk):
    employee = get_object_or_404(DeliveryEmployee, pk=pk)
    employee.delete()
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
            messages.success(request, 'Expense added successfully.')
            return redirect('expense_management')
        # Keep errors only inline with form fields.
        pass

    return render(request, 'distribution/expense_management.html', {
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
            messages.success(request, 'Expense updated successfully.')
            return redirect('expense_management')
        # Keep errors only inline with form fields.
        pass
    else:
        form = DeliveryExpenseForm(instance=expense)

    return render(request, 'distribution/partials/edit_expense_form.html', {
        'expense': expense,
        'form': form,
    })


@login_required
@require_POST
def expense_delete(request, pk):
    expense = get_object_or_404(DeliveryExpense, pk=pk)
    expense.delete()
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
def setup_owner(request):
    """Setup page to make first user owner if no owners exist"""
    # Check if any owner exists
    owners = UserProfile.objects.filter(role='owner')
    if owners.exists():
        messages.info(request, 'An owner already exists. Please contact them to change your role.')
        return redirect('dashboard')
    
    # If current user doesn't have profile, create one
    try:
        profile = UserProfile.objects.get(user=request.user)
    except UserProfile.DoesNotExist:
        profile = UserProfile.objects.create(user=request.user, role='employee')
    
    if request.method == 'POST':
        profile.role = 'owner'
        profile.save()
        messages.success(request, 'You have been set as the owner. You now have full access to all features!')
        return redirect('user_list')
    
    return render(request, 'distribution/setup_owner.html', {'user': request.user})


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
