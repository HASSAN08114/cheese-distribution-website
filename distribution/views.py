from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib.auth import authenticate, login, logout
from django.contrib import messages
from django.db.models import Sum, Q
from django.db import transaction
from decimal import Decimal
from .models import Manufacturer, CheeseProduct, Client, Sale, SaleItem
from .forms import (
    ManufacturerForm, CheeseProductForm, ClientForm,
    SaleItemForm, SaleItemFormSet
)


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
    total_profit = Decimal('0.00')
    total_sales = Decimal('0.00')
    remaining_stock_value = Decimal('0.00')
    
    sales = Sale.objects.all()
    for sale in sales:
        total_profit += sale.calculate_total_profit()
        total_sales += sale.total_amount
    
    products = CheeseProduct.objects.all()
    for product in products:
        remaining_stock_value += product.available_quantity_kg * product.purchase_price_per_kg
    
    context = {
        'total_profit': total_profit,
        'total_sales': total_sales,
        'remaining_stock_value': remaining_stock_value,
        'total_products': products.count(),
        'total_clients': Client.objects.count(),
        'total_manufacturers': Manufacturer.objects.count(),
    }
    return render(request, 'distribution/dashboard.html', context)


@login_required
def manufacturer_list(request):
    manufacturers = Manufacturer.objects.all()
    return render(request, 'distribution/manufacturer_list.html', {'manufacturers': manufacturers})


@login_required
def manufacturer_add(request):
    if request.method == 'POST':
        form = ManufacturerForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'Manufacturer added successfully.')
            return redirect('manufacturer_list')
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
            messages.success(request, 'Manufacturer updated successfully.')
            return redirect('manufacturer_list')
    else:
        form = ManufacturerForm(instance=manufacturer)
    return render(request, 'distribution/manufacturer_form.html', {'form': form, 'title': 'Edit Manufacturer'})


@login_required
def manufacturer_delete(request, pk):
    manufacturer = get_object_or_404(Manufacturer, pk=pk)
    if request.method == 'POST':
        manufacturer.delete()
        messages.success(request, 'Manufacturer deleted successfully.')
        return redirect('manufacturer_list')
    return render(request, 'distribution/manufacturer_delete.html', {'manufacturer': manufacturer})


@login_required
def cheese_inventory(request):
    products = CheeseProduct.objects.select_related('manufacturer').all()
    return render(request, 'distribution/cheese_inventory.html', {'products': products})


@login_required
def cheese_add(request):
    if request.method == 'POST':
        form = CheeseProductForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'Cheese product added successfully.')
            return redirect('cheese_inventory')
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
            messages.success(request, 'Cheese product updated successfully.')
            return redirect('cheese_inventory')
    else:
        form = CheeseProductForm(instance=product)
    return render(request, 'distribution/cheese_form.html', {'form': form, 'title': 'Edit Cheese Product'})


@login_required
def cheese_delete(request, pk):
    product = get_object_or_404(CheeseProduct, pk=pk)
    if request.method == 'POST':
        product.delete()
        messages.success(request, 'Cheese product deleted successfully.')
        return redirect('cheese_inventory')
    return render(request, 'distribution/cheese_delete.html', {'product': product})


@login_required
def client_list(request):
    clients = Client.objects.all()
    return render(request, 'distribution/client_list.html', {'clients': clients})


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
            messages.success(request, 'Client updated successfully.')
            return redirect('client_list')
    else:
        form = ClientForm(instance=client)
    return render(request, 'distribution/client_form.html', {'form': form, 'title': 'Edit Client'})


@login_required
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
                    quantity_kg = form.cleaned_data['quantity_kg']
                    selling_price_per_kg = form.cleaned_data['selling_price_per_kg']
                    
                    if quantity_kg > cheese_product.available_quantity_kg:
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
                        quantity_kg=quantity_kg,
                        selling_price_per_kg=selling_price_per_kg
                    )
                    
                    cheese_product.available_quantity_kg -= quantity_kg
                    cheese_product.save()
                    
                    total_amount += selling_price_per_kg * quantity_kg
                
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
        sales_with_profit.append({
            'sale': sale,
            'total_profit': sale.calculate_total_profit()
        })
    return render(request, 'distribution/sale_history.html', {'sales_data': sales_with_profit})


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

