from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib.auth import authenticate, login, logout
from django.contrib import messages
from django.db.models import Sum, Q
from django.db import transaction
from django.utils import timezone
from datetime import datetime, timedelta
from decimal import Decimal
from .models import Manufacturer, CheeseProduct, Client, Sale, SaleItem, UserProfile
from .forms import (
    ManufacturerForm, CheeseProductForm, ClientForm,
    SaleItemForm, SaleItemFormSet, UserForm, UserRoleForm
)
from .decorators import owner_required, is_owner


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
        remaining_stock_value += product.available_quantity_packets * product.purchase_price_per_packet
    
    user_is_owner = is_owner(request.user)
    
    context = {
        'total_profit': total_profit,
        'total_sales': total_sales,
        'remaining_stock_value': remaining_stock_value,
        'total_products': products.count(),
        'total_clients': Client.objects.count(),
        'total_manufacturers': Manufacturer.objects.count(),
        'user_is_owner': user_is_owner,
    }
    return render(request, 'distribution/dashboard.html', context)


@owner_required
def inventory_management(request):
    """Merged page for manufacturers and cheese inventory"""
    manufacturers = Manufacturer.objects.all()
    products = CheeseProduct.objects.select_related('manufacturer').all()
    
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
    cheese_form = CheeseProductForm()
    # Create edit forms for each manufacturer and cheese product
    manufacturer_edit_forms = {m.pk: ManufacturerForm(instance=m) for m in manufacturers}
    cheese_edit_forms = {p.pk: CheeseProductForm(instance=p) for p in products}
    return render(request, 'distribution/inventory_management.html', {
        'manufacturers': manufacturers,
        'products_with_value': products_with_value,
        'manufacturer_form': manufacturer_form,
        'cheese_form': cheese_form,
        'manufacturer_edit_forms': manufacturer_edit_forms,
        'cheese_edit_forms': cheese_edit_forms,
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
            messages.success(request, 'Manufacturer updated successfully.')
            return redirect('inventory_management')
    else:
        form = ManufacturerForm(instance=manufacturer)
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
            form.save()
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
            messages.success(request, 'Cheese product updated successfully.')
            return redirect('inventory_management')
    else:
        form = CheeseProductForm(instance=product)
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
def client_list(request):
    clients = Client.objects.all()
    user_is_owner = is_owner(request.user)
    return render(request, 'distribution/client_list.html', {
        'clients': clients,
        'user_is_owner': user_is_owner
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
            messages.success(request, 'Client updated successfully.')
            return redirect('client_list')
    else:
        form = ClientForm(instance=client)
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
        sales_with_profit.append({
            'sale': sale,
            'total_profit': sale.calculate_total_profit()
        })
    
    # Calculate analytics
    now = timezone.now()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    year_start = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
    
    # Daily sales
    daily_sales = Sale.objects.filter(sale_date__gte=today_start)
    daily_total = sum(sale.total_amount for sale in daily_sales)
    daily_profit = sum(sale.calculate_total_profit() for sale in daily_sales)
    
    # Monthly sales
    monthly_sales = Sale.objects.filter(sale_date__gte=month_start)
    monthly_total = sum(sale.total_amount for sale in monthly_sales)
    monthly_profit = sum(sale.calculate_total_profit() for sale in monthly_sales)
    
    # Yearly sales
    yearly_sales = Sale.objects.filter(sale_date__gte=year_start)
    yearly_total = sum(sale.total_amount for sale in yearly_sales)
    yearly_profit = sum(sale.calculate_total_profit() for sale in yearly_sales)
    
    user_is_owner = is_owner(request.user)
    
    return render(request, 'distribution/sale_history.html', {
        'sales_data': sales_with_profit,
        'daily_total': daily_total,
        'daily_profit': daily_profit,
        'monthly_total': monthly_total,
        'monthly_profit': monthly_profit,
        'yearly_total': yearly_total,
        'yearly_profit': yearly_profit,
        'user_is_owner': user_is_owner,
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
