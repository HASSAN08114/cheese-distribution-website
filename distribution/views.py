from .forms_payment import PaymentForm
from .models import Payment
# Payment views
from django.contrib.auth.decorators import login_required
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
from .models import Manufacturer, CheeseProduct, Client, Sale, SaleItem, UserProfile
from .forms import (
    ManufacturerForm, CheeseProductForm, ClientForm,
    SaleItemForm, SaleItemFormSet, UserForm, UserRoleForm, AddStockForm, AddStockFormSet
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
def make_payment(request):
    if request.method == 'POST':
        form = PaymentForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'Payment recorded successfully.')
            return redirect('payment_history')
    else:
        form = PaymentForm()
    return render(request, 'distribution/make_payment.html', {'form': form})

@login_required
def payment_history(request):
    payments = Payment.objects.select_related('client').all()
    return render(request, 'distribution/payment_history.html', {'payments': payments})

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
            messages.success(request, 'Cheese type added successfully.')
            return redirect('inventory_management')
    else:
        form = CheeseTypeForm()
    html = render_to_string('distribution/partials/edit_cheese_type_form.html', {'form': form}, request=request)
    return JsonResponse({'html': html})

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

    # Calculate statistics
    total_sales = Sale.objects.aggregate(total=Sum('total_amount'))['total'] or Decimal('0.00')
    total_payments = Payment.objects.aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
    total_clients = Client.objects.count()
    total_credits_owed = sum(client.amount_owed for client in Client.objects.all())
    total_profit = sum(sale.calculate_total_profit() for sale in Sale.objects.all())
    total_products = CheeseProduct.objects.count()

    context = {
        'user_is_owner': user_is_owner,
        'total_sales': total_sales,
        'total_payments': total_payments,
        'total_clients': total_clients,
        'total_credits_owed': total_credits_owed,
        'total_profit': total_profit,
        'total_products': total_products,
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

    summary = {
        'total_clients': total_clients,
        'total_revenue': float(total_revenue),
        'total_profit': float(total_profit_all),
        'total_transactions': total_transactions_all,
        'avg_client_value': float(total_revenue / total_clients) if total_clients > 0 else 0,
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
            # Total quantity sold
            total_quantity = product_sales.aggregate(
                total=Sum('quantity_packets')
            )['total'] or Decimal('0.00')

            # Total revenue
            total_revenue = product_sales.aggregate(
                total=Sum(models.F('quantity_packets') * models.F('selling_price_per_packet'))
            )['total'] or Decimal('0.00')

            # Total profit
            total_profit = sum(
                (item.selling_price_per_packet - item.cheese_product.purchase_price_per_packet) * item.quantity_packets
                for item in product_sales
            )

            # Transaction count
            transaction_count = product_sales.count()

            # Current stock level
            current_stock = product.available_quantity_packets

            # Stock turnover (sold / current stock)
            stock_turnover = float(total_quantity / current_stock) if current_stock > 0 else 0

            # Profit margin percentage
            total_cost = total_quantity * product.purchase_price_per_packet
            profit_margin = (total_profit / total_revenue * Decimal('100.0')) if total_revenue > 0 else Decimal('0.0')

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
            messages.success(request, 'Manufacturer added successfully.')
            return redirect('inventory_management')
    else:
        form = ManufacturerForm()
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
            messages.success(request, 'Cheese product added successfully.')
            return redirect('inventory_management')
    else:
        form = CheeseProductForm()
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
            valid_forms = [f for f in formset if f.cleaned_data and not f.cleaned_data.get('DELETE', False)]
            if not valid_forms:
                messages.error(request, 'Please add at least one stock item.')
                return render(request, 'distribution/add_stock.html', {
                    'formset': formset
                })
            for form in valid_forms:
                cheese_product = form.cleaned_data['cheese_product']
                quantity_packets = form.cleaned_data['quantity_packets']
                purchase_price_per_packet = form.cleaned_data['purchase_price_per_packet']
                # Update cheese product stock and price
                cheese_product.available_quantity_packets += quantity_packets
                cheese_product.purchase_price_per_packet = purchase_price_per_packet
                cheese_product.save()
                # Create stock addition history
                StockAdditionHistory.objects.create(
                    cheese_product=cheese_product,
                    added_by=request.user.userprofile,
                    quantity_packets=quantity_packets
                )
            messages.success(request, 'Stock added successfully.')
            return redirect('stock_history')
        else:
            messages.error(request, 'Please correct the errors below.')
    else:
        formset = AddStockFormSet()

    return render(request, 'distribution/add_stock.html', {
        'formset': formset
    })

@login_required
def client_list(request):
    clients = Client.objects.all()
    user_is_owner = is_owner(request.user)
    from .forms import ClientForm
    client_form = ClientForm()
    return render(request, 'distribution/client_list.html', {
        'clients': clients,
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
                
                sale.total_amount = total_amount
                sale.save()
                
                messages.success(request, 'Sale created successfully.')
                return redirect('sale_history')
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
    return render(request, 'distribution/user_list.html', {'users_with_roles': users_with_roles})


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
