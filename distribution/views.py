from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.contrib import messages
from django.conf import settings
from django.db import models
from django.db.models import Sum, Q, F, DecimalField, Subquery, OuterRef, Exists, Count, Max
from django.db import transaction, connections
from django.db.models.functions import Coalesce
from django.utils import timezone
from datetime import datetime, timedelta, time
from decimal import Decimal
from pathlib import Path
import shutil
import tempfile
import sqlite3
import os
import json
from io import StringIO
from django.core.management import call_command
from .models import (
    Manufacturer, CheeseProduct, Client, Sale, SaleItem, SaleAction, UserProfile, Payment, PaymentAction,
    DeliveryEmployee, DeliveryExpense, ExpenseAction, SiteActivity, ReceiptSettings,
)
from .forms import (
    ManufacturerForm, CheeseProductForm, ClientForm,
    SaleItemForm, SaleItemFormSet, UserForm, UserRoleForm,
    UserPasswordChangeForm,
    PaymentForm, DeliveryEmployeeForm, DeliveryExpenseForm,
)
from .forms import ReceiptSettingsForm
from .forms import CheeseTypeForm
from .decorators import owner_required, is_owner


from django.http import JsonResponse, FileResponse
from django.template.loader import render_to_string
from django.shortcuts import render
from .forms import CheeseTypeForm
from .models import CheeseType

# AJAX endpoint to process return for sale item
from django.views.decorators.http import require_POST


def _get_sale_action_actor(request):
    profile = getattr(request.user, 'userprofile', None)
    return profile if profile and hasattr(profile, 'pk') else None


def _record_sale_action(
    *,
    sale,
    action_type,
    sale_item=None,
    quantity_change=None,
    old_price=None,
    new_price=None,
    old_sale_date=None,
    new_sale_date=None,
    reason='',
    created_by=None,
    stock_addition=None,
):
    return SaleAction.objects.create(
        sale=sale,
        sale_item=sale_item,
        stock_addition=stock_addition,
        action_type=action_type,
        quantity_change=quantity_change,
        old_price=old_price,
        new_price=new_price,
        old_sale_date=old_sale_date,
        new_sale_date=new_sale_date,
        reason=reason,
        created_by=created_by,
    )


def _parse_ddmmyyyy_datetime(value):
    """Parse DD/MM/YYYY HH:MM or ISO datetime string into aware datetime."""
    if not value:
        raise ValueError('Datetime is required.')

    raw_value = value.strip()
    parsed = None

    try:
        parsed = datetime.fromisoformat(raw_value)
    except ValueError:
        parsed = datetime.strptime(raw_value, '%d/%m/%Y %H:%M')

    if timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed, timezone.get_current_timezone())

    return parsed


def _update_sale_total(sale):
    total_amount = Decimal('0.00')
    for item in sale.saleitem_set.all():
        total_amount += item.selling_price_per_packet * item.quantity_packets
        total_amount -= item.selling_price_per_packet * item.quantity_returned
    sale.total_amount = total_amount
    sale.save(update_fields=['total_amount'])
    return total_amount


class SaleStockError(Exception):
    pass


def _normalize_sale_forms(formset):
    valid_forms = [f for f in formset if f.cleaned_data and not f.cleaned_data.get('DELETE', False)]
    if not valid_forms:
        raise SaleStockError('Please add at least one item to the sale.')
    return valid_forms


def _reserve_sale_product_stock(product, quantity, *, allow_void=False):
    locked_product = CheeseProduct.objects.select_for_update().get(pk=product.pk)
    if quantity > locked_product.available_quantity_packets and not allow_void:
        raise SaleStockError(
            f'Insufficient stock for {locked_product}. Requested: {quantity}, available: {locked_product.available_quantity_packets}.'
        )
    return locked_product


def _create_sale_from_valid_forms(*, client, sale_datetime, valid_forms, request=None):
    with transaction.atomic():
        sale = Sale.objects.create(
            client=client,
            total_amount=Decimal('0.00'),
            sale_date=sale_datetime,
        )

        total_amount = Decimal('0.00')
        created_items = []

        try:
            for form in valid_forms:
                cheese_product = form.cleaned_data['cheese_product']
                quantity_packets = int(form.cleaned_data['quantity_packets'])
                selling_price_per_packet = form.cleaned_data['selling_price_per_packet']

                locked_product = _reserve_sale_product_stock(cheese_product, quantity_packets)
                sale_item = SaleItem.objects.create(
                    sale=sale,
                    cheese_product=locked_product,
                    quantity_packets=quantity_packets,
                    selling_price_per_packet=selling_price_per_packet,
                )
                created_items.append((sale_item, locked_product, quantity_packets))
                locked_product.available_quantity_packets -= quantity_packets
                locked_product.save(update_fields=['available_quantity_packets'])
                total_amount += selling_price_per_packet * quantity_packets

            sale.total_amount = total_amount
            sale.save(update_fields=['total_amount'])
            if request is not None:
                SiteActivity.update_activity(f'Sale created for {client.name}')
            return sale
        except Exception:
            sale.delete()
            raise


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


def _period_date_bounds(period, today):
    """Return start/end dates (inclusive) for a period token, or (None, None) for all/custom."""
    if period == 'today':
        return today, today
    if period == 'week':
        return today - timedelta(days=7), today
    if period == 'month':
        return today - timedelta(days=30), today
    if period == 'quarter':
        return today - timedelta(days=90), today
    if period == '6months':
        return today - timedelta(days=180), today
    if period == 'year':
        return today - timedelta(days=365), today
    return None, None


def _date_to_day_bounds(start_date, end_date):
    """Convert inclusive date bounds to aware datetime [start, end) for indexed datetime filtering."""
    if not start_date or not end_date:
        return None, None

    tz = timezone.get_current_timezone()
    start_dt = timezone.make_aware(datetime.combine(start_date, time.min), tz)
    end_dt = timezone.make_aware(datetime.combine(end_date + timedelta(days=1), time.min), tz)
    return start_dt, end_dt


def _get_receipt_settings():
    return ReceiptSettings.load()


def _receipt_datetime_parts(dt):
    local_dt = timezone.localtime(dt)
    return local_dt.strftime('%d/%m/%Y'), local_dt.strftime('%H:%M')


def _sale_receipt_context(sale):
    settings_obj = _get_receipt_settings()
    items = sale.saleitem_set.select_related('cheese_product').all()
    dated, timed = _receipt_datetime_parts(sale.sale_date)
    return {
        'receipt_settings': settings_obj,
        'sale': sale,
        'sale_items': [
            {
                'product_name': item.cheese_product.__str__(),
                'quantity_packets': item.quantity_packets,
                'selling_price_per_packet': item.selling_price_per_packet,
                'item_total': item.quantity_packets * item.selling_price_per_packet,
            }
            for item in items
        ],
        'receipt_date': dated,
        'receipt_time': timed,
        'client_name': sale.client.name,
        'client_phone': sale.client.phone or '',
        'invoice_number': sale.id,
        'total_amount': sale.total_amount,
    }


def _payment_receipt_context(payment):
    settings_obj = _get_receipt_settings()
    dated, timed = _receipt_datetime_parts(payment.date)
    return {
        'receipt_settings': settings_obj,
        'payment': payment,
        'receipt_date': dated,
        'receipt_time': timed,
        'client_name': payment.client.name,
        'client_phone': payment.client.phone or '',
        'payment_method': payment.get_mode_display(),
        'invoice_number': payment.id,
        'payment_bank': payment.bank or '',
        'payment_amount': payment.amount,
    }

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
        if item.sale.is_voided:
            del request.session[dedup_key]
            return JsonResponse({'success': False, 'error': 'This sale has been voided.'})
        quantity = int(quantity)
        
        # Check if quantity is valid
        if quantity <= 0:
            del request.session[dedup_key]
            return JsonResponse({'success': False, 'error': 'Return quantity must be greater than 0.'})
        
        # Check if return quantity exceeds available quantity
        available = item.quantity_packets - item.quantity_returned
        if quantity > available:
            del request.session[dedup_key]
            return JsonResponse({'success': False, 'error': f'Cannot return {quantity} packets. Only {available} available to return.'})
        
        # Create sale action record
        _record_sale_action(
            sale=item.sale,
            action_type='return',
            sale_item=item,
            quantity_change=-quantity,
            reason=reason,
            created_by=_get_sale_action_actor(request),
        )
        
        # Update SaleItem quantity_returned
        item.quantity_returned += quantity
        item.modified = True
        item.save()
        
        # Update cheese product stock
        item.cheese_product.available_quantity_packets += quantity
        item.cheese_product.save()

        _update_sale_total(item.sale)
        
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
        if sale.is_voided:
            request.session[dedup_key] = False
            return JsonResponse({'success': False, 'error': 'This sale has been voided.'})
        
        for item in sale.saleitem_set.all():
            # Only return items that haven't been fully returned
            if item.quantity_returned < item.quantity_packets:
                quantity_to_return = item.quantity_packets - item.quantity_returned
                
                # Create sale action record
                _record_sale_action(
                    sale=sale,
                    action_type='return',
                    sale_item=item,
                    quantity_change=-quantity_to_return,
                    reason=reason,
                    created_by=_get_sale_action_actor(request),
                )
                
                # Update SaleItem
                item.quantity_returned = item.quantity_packets
                item.modified = True
                item.save()
                
                # Update cheese product stock
                item.cheese_product.available_quantity_packets += quantity_to_return
                item.cheese_product.save()
        _update_sale_total(sale)
        
        SiteActivity.update_activity(f'All items returned from Sale #{sale.id}')
        
        # Clean up dedup key after 2 seconds
        request.session[dedup_key] = False
        
        return JsonResponse({'success': True, 'message': 'All items have been returned.'})
    except Exception as e:
        if dedup_key in request.session:
            del request.session[dedup_key]
        return JsonResponse({'success': False, 'error': str(e)})


@login_required
@require_POST
def sale_action_apply(request, pk):
    sale = get_object_or_404(Sale, pk=pk)
    action_type = request.POST.get('action_type', '').strip()
    reason = request.POST.get('reason', '').strip()
    created_by = _get_sale_action_actor(request)

    if sale.is_voided and action_type != 'void':
        return JsonResponse({'success': False, 'error': 'This sale has already been voided.'})

    try:
        with transaction.atomic():
            sale = Sale.objects.select_for_update().get(pk=pk)

            if action_type == 'return':
                item_id = request.POST.get('item_id')
                quantity = int(request.POST.get('quantity', '0'))
                item = get_object_or_404(SaleItem, pk=item_id, sale=sale)

                if quantity <= 0:
                    return JsonResponse({'success': False, 'error': 'Return quantity must be greater than 0.'})

                available = item.quantity_packets - item.quantity_returned
                if quantity > available:
                    return JsonResponse({'success': False, 'error': f'Cannot return {quantity} packets. Only {available} available to return.'})

                _record_sale_action(
                    sale=sale,
                    action_type='return',
                    sale_item=item,
                    quantity_change=-quantity,
                    reason=reason,
                    created_by=created_by,
                )
                item.quantity_returned += quantity
                item.modified = True
                item.save()
                item.cheese_product.available_quantity_packets += quantity
                item.cheese_product.save()
                _update_sale_total(sale)
                SiteActivity.update_activity(f'Returned {quantity} packets of {item.cheese_product} from Sale #{sale.id}')
                return JsonResponse({'success': True, 'message': f'Successfully returned {quantity} packets.'})

            if action_type == 'return_all':
                updated_any = False

                for item in sale.saleitem_set.select_related('cheese_product').all():
                    available_to_return = item.quantity_packets - item.quantity_returned
                    if available_to_return <= 0:
                        continue

                    _record_sale_action(
                        sale=sale,
                        action_type='return',
                        sale_item=item,
                        quantity_change=-available_to_return,
                        reason=reason,
                        created_by=created_by,
                    )
                    item.quantity_returned = item.quantity_packets
                    item.modified = True
                    item.save(update_fields=['quantity_returned', 'modified'])

                    locked_product = _reserve_sale_product_stock(item.cheese_product, 0, allow_void=True)
                    locked_product.available_quantity_packets += available_to_return
                    locked_product.save(update_fields=['available_quantity_packets'])
                    updated_any = True

                if not updated_any:
                    return JsonResponse({'success': False, 'error': 'All items are already fully returned.'})

                _update_sale_total(sale)
                SiteActivity.update_activity(f'All items returned from Sale #{sale.id}')
                return JsonResponse({'success': True, 'message': 'All items have been returned.'})

            if action_type == 'quantity_add':
                item_id = request.POST.get('item_id')
                quantity = int(request.POST.get('quantity', '0'))
                item = get_object_or_404(SaleItem, pk=item_id, sale=sale)
                locked_product = _reserve_sale_product_stock(item.cheese_product, quantity)

                if quantity <= 0:
                    return JsonResponse({'success': False, 'error': 'Quantity must be greater than 0.'})

                _record_sale_action(
                    sale=sale,
                    action_type='quantity_add',
                    sale_item=item,
                    quantity_change=quantity,
                    reason=reason,
                    created_by=created_by,
                )
                item.quantity_packets += quantity
                item.modified = True
                item.save()
                locked_product.available_quantity_packets -= quantity
                locked_product.save(update_fields=['available_quantity_packets'])
                _update_sale_total(sale)
                SiteActivity.update_activity(f'Added {quantity} packets to Sale #{sale.id} item {item.cheese_product}')
                return JsonResponse({'success': True, 'message': f'Added {quantity} packets successfully.'})

            if action_type == 'price_change':
                item_id = request.POST.get('item_id')
                new_price = Decimal(request.POST.get('new_price', '0'))
                item = get_object_or_404(SaleItem, pk=item_id, sale=sale)

                if new_price <= 0:
                    return JsonResponse({'success': False, 'error': 'Price must be greater than 0.'})

                old_price = item.selling_price_per_packet
                _record_sale_action(
                    sale=sale,
                    action_type='price_change',
                    sale_item=item,
                    old_price=old_price,
                    new_price=new_price,
                    reason=reason,
                    created_by=created_by,
                )
                item.selling_price_per_packet = new_price
                item.modified = True
                item.save()
                _update_sale_total(sale)
                SiteActivity.update_activity(f'Changed price for {item.cheese_product} on Sale #{sale.id}')
                return JsonResponse({'success': True, 'message': f'Packet price updated to PKR {new_price}.'})

            if action_type == 'date_change':
                new_sale_date_value = request.POST.get('new_sale_date', '').strip()
                if not new_sale_date_value:
                    return JsonResponse({'success': False, 'error': 'Please provide a new sale date and time.'})

                try:
                    new_sale_date = _parse_ddmmyyyy_datetime(new_sale_date_value)
                except ValueError:
                    return JsonResponse({'success': False, 'error': 'Invalid date format. Please use DD/MM/YYYY HH:MM.'})

                old_sale_date = sale.sale_date
                if old_sale_date == new_sale_date:
                    return JsonResponse({'success': False, 'error': 'New sale date must be different from current date.'})

                date_error = _validate_sale_date_not_before_client_creation(sale.client, new_sale_date)
                if date_error:
                    return JsonResponse({'success': False, 'error': date_error})

                sale.sale_date = new_sale_date
                sale.save(update_fields=['sale_date'])

                _record_sale_action(
                    sale=sale,
                    action_type='date_change',
                    old_sale_date=old_sale_date,
                    new_sale_date=new_sale_date,
                    reason=reason,
                    created_by=created_by,
                )
                SiteActivity.update_activity(f'Changed sale date for Sale #{sale.id}')
                return JsonResponse({'success': True, 'message': 'Sale date updated successfully.'})

            if action_type == 'item_add':
                product_id = request.POST.get('product_id')
                quantity = int(request.POST.get('quantity', '0'))
                selling_price = Decimal(request.POST.get('selling_price_per_packet', '0'))
                product = get_object_or_404(CheeseProduct, pk=product_id)
                locked_product = _reserve_sale_product_stock(product, quantity)

                if quantity <= 0:
                    return JsonResponse({'success': False, 'error': 'Quantity must be greater than 0.'})
                if selling_price <= 0:
                    return JsonResponse({'success': False, 'error': 'Selling price must be greater than 0.'})

                item = SaleItem.objects.create(
                    sale=sale,
                    cheese_product=locked_product,
                    quantity_packets=quantity,
                    selling_price_per_packet=selling_price,
                )
                locked_product.available_quantity_packets -= quantity
                locked_product.save(update_fields=['available_quantity_packets'])

                _record_sale_action(
                    sale=sale,
                    action_type='item_add',
                    sale_item=item,
                    quantity_change=quantity,
                    new_price=selling_price,
                    reason=reason,
                    created_by=created_by,
                )
                _update_sale_total(sale)
                SiteActivity.update_activity(f'Added {quantity} packets of {product} to Sale #{sale.id}')
                return JsonResponse({'success': True, 'message': f'Added {product} to the sale.'})

            if action_type == 'void':
                if sale.is_voided:
                    return JsonResponse({'success': False, 'error': 'This sale has already been voided.'})

                voided_items = []

                for item in sale.saleitem_set.select_related('cheese_product').all():
                    available_to_restore = item.quantity_packets - item.quantity_returned
                    if available_to_restore > 0:
                        locked_product = _reserve_sale_product_stock(item.cheese_product, 0, allow_void=True)
                        locked_product.available_quantity_packets += available_to_restore
                        locked_product.save(update_fields=['available_quantity_packets'])
                    item.quantity_returned = item.quantity_packets
                    item.modified = True
                    item.save(update_fields=['quantity_returned', 'modified'])
                    voided_items.append(item.id)

                sale.is_voided = True
                sale.voided_at = timezone.now()
                sale.void_reason = reason
                sale.voided_by = created_by
                _update_sale_total(sale)
                sale.save(update_fields=['is_voided', 'voided_at', 'void_reason', 'voided_by', 'total_amount'])

                _record_sale_action(
                    sale=sale,
                    action_type='void',
                    reason=reason,
                    created_by=created_by,
                )
                SiteActivity.update_activity(f'Sale #{sale.id} voided')
                return JsonResponse({'success': True, 'message': 'Sale voided successfully.'})

            return JsonResponse({'success': False, 'error': 'Unsupported sale action.'})
    except Exception as e:
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
    sale_actions = sale.actions.select_related('sale_item', 'created_by').all()
    products = CheeseProduct.objects.select_related('manufacturer', 'type').all()
    
    # Add total price for each item
    for item in sale_items:
        item.item_total = item.quantity_packets * item.selling_price_per_packet
    
    total_profit = sale.calculate_total_profit()
    return render(request, 'distribution/sales/partials/partial_sale_modal_details.html', {
        'sale': sale,
        'sale_items': sale_items,
        'sale_actions': sale_actions,
        'products': products,
        'total_profit': total_profit
    })


@login_required
@require_GET
def sale_print(request, pk):
    sale = get_object_or_404(Sale.objects.select_related('client'), pk=pk)
    return render(request, 'distribution/receipts/receipt_print.html', {
        'receipt_type': 'sale',
        **_sale_receipt_context(sale),
    })


@login_required
@require_GET
def payment_print(request, pk):
    payment = get_object_or_404(Payment.objects.select_related('client'), pk=pk)
    return render(request, 'distribution/receipts/receipt_print.html', {
        'receipt_type': 'payment',
        **_payment_receipt_context(payment),
    })

from .models import StockAdditionHistory


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
    daily_expenses = DeliveryExpense.objects.filter(expense_date=today, is_voided=False).aggregate(total=Sum('amount'))['total'] or 0

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
    start_date, end_date = _period_date_bounds(period, today)

    if period == 'custom' and from_date_str and to_date_str:
        custom_start_dt, custom_end_dt = _parse_custom_datetime_range(from_date_str, to_date_str)
        if not custom_start_dt or not custom_end_dt:
            return JsonResponse({'error': 'Invalid custom date/time range.'}, status=400)
        start_date = None
        end_date = None

    sales_filters = {'is_voided': False}
    payment_filters = {'is_voided': False}

    if custom_start_dt and custom_end_dt:
        sales_filters['sale_date__range'] = [custom_start_dt, custom_end_dt]
        payment_filters['date__range'] = [custom_start_dt, custom_end_dt]
    elif start_date and end_date:
        start_dt, end_dt = _date_to_day_bounds(start_date, end_date)
        sales_filters['sale_date__gte'] = start_dt
        sales_filters['sale_date__lt'] = end_dt
        payment_filters['date__gte'] = start_dt
        payment_filters['date__lt'] = end_dt

    sales_summary = Sale.objects.filter(**sales_filters).values('client_id').annotate(
        total_sales=Coalesce(Sum('total_amount'), Decimal('0.00')),
        total_transactions=Count('id'),
        last_sale_date=Max('sale_date'),
    )
    sales_map = {row['client_id']: row for row in sales_summary}

    profit_filters = {'sale__is_voided': False}
    if custom_start_dt and custom_end_dt:
        profit_filters['sale__sale_date__range'] = [custom_start_dt, custom_end_dt]
    elif start_date and end_date:
        start_dt, end_dt = _date_to_day_bounds(start_date, end_date)
        profit_filters['sale__sale_date__gte'] = start_dt
        profit_filters['sale__sale_date__lt'] = end_dt

    profit_summary = SaleItem.objects.filter(**profit_filters).values('sale__client_id').annotate(
        total_profit=Coalesce(
            Sum(F('profit_per_packet') * F('quantity_packets'), output_field=DecimalField()),
            Decimal('0.00')
        )
    )
    profit_map = {row['sale__client_id']: row['total_profit'] for row in profit_summary}

    all_time_sales_summary = Sale.objects.filter(client=OuterRef('pk'), is_voided=False).values('client').annotate(
        total_sales=Sum('total_amount')
    ).values('total_sales')

    all_time_payments_summary = Payment.objects.filter(client=OuterRef('pk'), is_voided=False).values('client').annotate(
        total_paid=Sum('amount')
    ).values('total_paid')

    client_ids = list(sales_map.keys())
    clients = Client.objects.filter(id__in=client_ids).annotate(
        all_time_sales=Coalesce(Subquery(all_time_sales_summary), Decimal('0.00')),
        all_time_paid=Coalesce(Subquery(all_time_payments_summary), Decimal('0.00')),
    ).values('id', 'name', 'previous_debt', 'all_time_sales', 'all_time_paid')

    client_data = []
    for client in clients:
        client_id = client['id']
        sales_row = sales_map.get(client_id)
        if not sales_row:
            continue

        total_sales = sales_row['total_sales'] or Decimal('0.00')
        total_transactions = sales_row['total_transactions'] or 0
        total_profit = profit_map.get(client_id, Decimal('0.00'))
        last_sale = sales_row['last_sale_date']
        all_time_due = (
            (client['all_time_sales'] or Decimal('0.00'))
            - (client['all_time_paid'] or Decimal('0.00'))
            + (client['previous_debt'] or Decimal('0.00'))
        )

        client_data.append({
            'id': client_id,
            'name': client['name'],
            'total_sales': float(total_sales),
            'total_profit': float(total_profit),
            'total_transactions': total_transactions,
            'last_sale_time': last_sale.strftime('%Y-%m-%d %H:%M') if last_sale else None,
            'avg_sale': float(total_sales / total_transactions) if total_transactions > 0 else 0,
            'debt': float(all_time_due),
        })

    # Sort by profit descending
    client_data.sort(key=lambda x: x['total_profit'], reverse=True)

    # Calculate summary stats
    total_clients = len(client_data)
    total_revenue = sum(client['total_sales'] for client in client_data)
    total_profit_all = sum(client['total_profit'] for client in client_data)
    total_transactions_all = sum(client['total_transactions'] for client in client_data)

    total_outstanding = Decimal('0.00')
    all_clients_financials = Client.objects.annotate(
        all_time_sales=Coalesce(Subquery(all_time_sales_summary), Decimal('0.00')),
        all_time_paid=Coalesce(Subquery(all_time_payments_summary), Decimal('0.00')),
    ).values('previous_debt', 'all_time_sales', 'all_time_paid')

    for client_data_row in all_clients_financials:
        outstanding_amount = (
            client_data_row['all_time_sales']
            - client_data_row['all_time_paid']
            + client_data_row['previous_debt']
        )
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
    start_date, end_date = _period_date_bounds(period, now.date())

    if period == 'custom' and from_date_str and to_date_str:
        custom_start_dt, custom_end_dt = _parse_custom_datetime_range(from_date_str, to_date_str)
        if not custom_start_dt or not custom_end_dt:
            return JsonResponse({'error': 'Invalid custom date/time range.'}, status=400)
        start_date = None
        end_date = None

    sale_item_filters = {'sale__is_voided': False}
    if custom_start_dt and custom_end_dt:
        sale_item_filters['sale__sale_date__range'] = [custom_start_dt, custom_end_dt]
    elif start_date and end_date:
        start_dt, end_dt = _date_to_day_bounds(start_date, end_date)
        sale_item_filters['sale__sale_date__gte'] = start_dt
        sale_item_filters['sale__sale_date__lt'] = end_dt

    product_sales_summary = SaleItem.objects.filter(**sale_item_filters).values('cheese_product_id').annotate(
        total_quantity=Coalesce(Sum('quantity_packets'), 0),
        total_revenue=Coalesce(
            Sum(F('quantity_packets') * F('selling_price_per_packet'), output_field=DecimalField()),
            Decimal('0.00')
        ),
        total_profit=Coalesce(
            Sum(F('quantity_packets') * F('profit_per_packet'), output_field=DecimalField()),
            Decimal('0.00')
        ),
        transaction_count=Count('id'),
    )

    summary_map = {row['cheese_product_id']: row for row in product_sales_summary}
    products = CheeseProduct.objects.select_related('manufacturer', 'type').filter(id__in=summary_map.keys())

    product_data = []
    for product in products:
        row = summary_map.get(product.id)
        if not row:
            continue

        total_quantity = Decimal(str(row['total_quantity'] or 0))
        total_revenue = row['total_revenue'] or Decimal('0.00')
        total_profit = row['total_profit'] or Decimal('0.00')
        transaction_count = row['transaction_count'] or 0
        current_stock = product.available_quantity_packets

        stock_turnover = float(total_quantity / current_stock) if current_stock > 0 else 0
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
    start_date, end_date = _period_date_bounds(period, today)

    if period == 'custom' and from_date_str and to_date_str:
        custom_start_dt, custom_end_dt = _parse_custom_datetime_range(from_date_str, to_date_str)
        if not custom_start_dt or not custom_end_dt:
            return JsonResponse({'error': 'Invalid custom date/time range.'}, status=400)
        start_date = None
        end_date = None

    # Get general metrics
    sale_filters = {'is_voided': False}
    payment_filters = {'is_voided': False}

    if custom_start_dt and custom_end_dt:
        sale_filters['sale_date__range'] = [custom_start_dt, custom_end_dt]
        payment_filters['date__range'] = [custom_start_dt, custom_end_dt]
        expenses_queryset = DeliveryExpense.objects.filter(
            expense_date__range=[custom_start_dt.date(), custom_end_dt.date()],
            is_voided=False,
        )
    elif start_date and end_date:
        start_dt, end_dt = _date_to_day_bounds(start_date, end_date)
        sale_filters['sale_date__gte'] = start_dt
        sale_filters['sale_date__lt'] = end_dt
        payment_filters['date__gte'] = start_dt
        payment_filters['date__lt'] = end_dt
        expenses_queryset = DeliveryExpense.objects.filter(expense_date__range=[start_date, end_date], is_voided=False)
    else:
        expenses_queryset = DeliveryExpense.objects.filter(is_voided=False)

    sales_queryset = Sale.objects.filter(**sale_filters)

    # Total Revenue
    total_revenue = sales_queryset.aggregate(total=Sum('total_amount'))['total'] or Decimal('0.00')

    # Total Expenses
    total_expenses = expenses_queryset.aggregate(total=Sum('amount'))['total'] or Decimal('0.00')

    sale_item_queryset = SaleItem.objects.filter(sale__in=sales_queryset)

    total_profit = sale_item_queryset.aggregate(
        total=Coalesce(
            Sum(F('profit_per_packet') * F('quantity_packets'), output_field=DecimalField()),
            Decimal('0.00')
        )
    )['total']
    
    # Net Profit (Profit - Expenses)
    net_profit = float(total_profit) - float(total_expenses)

    # Total Sales Count
    total_sales_count = sales_queryset.count()

    # Average Sale Value
    avg_sale_value = float(total_revenue) / total_sales_count if total_sales_count > 0 else 0

    # Total clients this period
    clients_this_period = sales_queryset.values('client').distinct().count()

    # Total products sold
    total_items_sold = sale_item_queryset.aggregate(
        total=Sum('quantity_packets')
    )['total'] or Decimal('0.00')

    # Total Paid this period
    total_paid_amount = Payment.objects.filter(**payment_filters).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')

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
    total_paid_amount = Payment.objects.filter(is_voided=False).aggregate(
        total=Coalesce(Sum('amount'), Decimal('0.00'))
    )['total']

    # Get all client financial summaries using aggregation
    # This avoids looping through all clients
    client_sales = Sale.objects.filter(client=OuterRef('pk'), is_voided=False).values('client').annotate(
        total=Sum('total_amount')
    ).values('total')
    
    client_payments = Payment.objects.filter(client=OuterRef('pk'), is_voided=False).values('client').annotate(
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
    ).values('total_sales', 'total_paid', 'previous_debt')
    
    # Calculate totals
    total_outstanding = Decimal('0.00')
    total_unpaid_amount = Decimal('0.00')
    
    for client_data in clients_with_financials:
        outstanding = client_data['total_sales'] - client_data['total_paid']
        all_time_due = outstanding + client_data['previous_debt']
        if all_time_due > 0:
            total_outstanding += all_time_due
            total_unpaid_amount += all_time_due

    summary = {
        'total_outstanding': float(total_outstanding),
        'total_all_time_due': float(total_unpaid_amount),
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
        sales = Sale.objects.filter(is_voided=False, sale_date__date__range=[start_date, end_date]).select_related('client')
    else:
        sales = Sale.objects.filter(is_voided=False).select_related('client')

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
            sale__is_voided=False,
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
        should_print = request.POST.get('print_receipt') in {'1', 'true', 'True', 'on', 'yes'}
        
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
            try:
                sale = _create_sale_from_valid_forms(
                    client=client,
                    sale_datetime=sale_datetime,
                    valid_forms=_normalize_sale_forms(formset),
                    request=request,
                )
            except SaleStockError as error:
                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return JsonResponse({'success': False, 'error': str(error)})
                messages.error(request, str(error))
                return redirect('sale_history')

            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
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
                    'total_sold_quantity': total_sold,
                    'receipt_url': f'/sales/{sale.id}/print/'
                })

            if should_print:
                return redirect('sale_print', pk=sale.id)

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


# ─────────────────────────────────────────────────────────────────────────────
# Shared PDF-building helper
# ─────────────────────────────────────────────────────────────────────────────

def _build_client_pdf(client, start_date, end_date, company_name):
    """
    Build and return a BytesIO containing a single client's PDF statement.
    start_date / end_date are datetime objects or None.
    """
    from reportlab.lib.pagesizes import letter
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.platypus import (
        SimpleDocTemplate, Table, TableStyle,
        Paragraph, Spacer, HRFlowable,
    )
    from reportlab.lib.units import inch
    from io import BytesIO
    from decimal import Decimal
    from datetime import datetime

    # ── Opening Balance ───────────────────────────────────────────────────────
    if start_date:
        sales_before = Sale.objects.filter(
            client=client, is_voided=False, sale_date__date__lt=start_date
        ).aggregate(total=Sum('total_amount'))['total'] or Decimal('0.00')
        paid_before = Payment.objects.filter(
            client=client, is_voided=False, date__date__lt=start_date
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
        opening_balance = (client.previous_debt or Decimal('0.00')) + sales_before - paid_before
    else:
        opening_balance = client.previous_debt or Decimal('0.00')

    # ── Period filters ────────────────────────────────────────────────────────
    sales_filter    = {'client': client, 'is_voided': False}
    payments_filter = {'client': client, 'is_voided': False}
    if start_date:
        sales_filter['sale_date__date__gte']  = start_date
        payments_filter['date__date__gte']    = start_date
    if end_date:
        sales_filter['sale_date__date__lte']  = end_date
        payments_filter['date__date__lte']    = end_date

    invoiced_amount = Sale.objects.filter(**sales_filter).aggregate(
        total=Sum('total_amount'))['total'] or Decimal('0.00')
    amount_paid = Payment.objects.filter(**payments_filter).aggregate(
        total=Sum('amount'))['total'] or Decimal('0.00')
    balance_due = opening_balance + invoiced_amount - amount_paid

    # ── Period label ──────────────────────────────────────────────────────────
    if start_date and end_date:
        period_text = f"{start_date.strftime('%B %d, %Y')}  –  {end_date.strftime('%B %d, %Y')}"
    elif start_date:
        period_text = f"From {start_date.strftime('%B %d, %Y')}"
    elif end_date:
        period_text = f"Until {end_date.strftime('%B %d, %Y')}"
    else:
        period_text = "All Time"

    # ── Colour palette ────────────────────────────────────────────────────────
    C_DARK      = colors.HexColor('#1C2833')
    C_BLUE      = colors.HexColor('#2E86C1')
    C_GREEN     = colors.HexColor('#1E8449')
    C_RED       = colors.HexColor('#C0392B')
    C_STRIPE    = colors.HexColor('#EBF5FB')
    C_HEADER_FG = colors.white
    C_RULE      = colors.HexColor('#BDC3C7')

    # ── Document ──────────────────────────────────────────────────────────────
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=letter,
        rightMargin=54, leftMargin=54, topMargin=54, bottomMargin=36,
    )

    styles = getSampleStyleSheet()

    def S(name, **kw):
        return ParagraphStyle(name, parent=styles['Normal'], **kw)

    style_company = S('Company', fontSize=9,  textColor=colors.HexColor('#7F8C8D'), alignment=1, spaceAfter=2)
    style_title   = S('Title',   fontSize=22, textColor=C_DARK, alignment=1, spaceAfter=20, fontName='Helvetica-Bold')
    style_period  = S('Period',  fontSize=10, textColor=colors.HexColor('#555555'), alignment=1, spaceAfter=2)
    style_section = S('Section', fontSize=11, textColor=C_DARK, fontName='Helvetica-Bold', spaceBefore=14, spaceAfter=6)
    style_empty   = S('Empty',   fontSize=9,  textColor=colors.HexColor('#888888'))
    style_footer  = S('Footer',  fontSize=7,  textColor=colors.HexColor('#AAAAAA'), alignment=1, spaceBefore=4)

    def money(v):
        return f"Rs. {v:,.2f}"

    elements = []

    # ── Header ────────────────────────────────────────────────────────────────
    elements.append(Paragraph(company_name, style_company))
    elements.append(Paragraph(f"Account Statement — {client.name}", style_title))
    elements.append(Paragraph(f"Period: {period_text}", style_period))
    elements.append(Spacer(1, 4))
    elements.append(HRFlowable(width="100%", thickness=1.5, color=C_BLUE, spaceAfter=10))

    # ── Client info ───────────────────────────────────────────────────────────
    info_rows = [['Name', client.name or '—']]
    if client.phone:
        info_rows.append(['Phone', client.phone])
    if client.address:
        info_rows.append(['Address', client.address])

    info_table = Table(info_rows, colWidths=[1.1*inch, 5.9*inch])
    info_table.setStyle(TableStyle([
        ('FONTNAME',      (0, 0), (0, -1), 'Helvetica-Bold'),
        ('FONTNAME',      (1, 0), (1, -1), 'Helvetica'),
        ('FONTSIZE',      (0, 0), (-1, -1), 9),
        ('TEXTCOLOR',     (0, 0), (0, -1), colors.HexColor('#555555')),
        ('TEXTCOLOR',     (1, 0), (1, -1), C_DARK),
        ('TOPPADDING',    (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ('VALIGN',        (0, 0), (-1, -1), 'TOP'),
    ]))
    elements.append(info_table)
    elements.append(Spacer(1, 10))
    elements.append(HRFlowable(width="100%", thickness=0.5, color=C_RULE, spaceAfter=10))

    # ── Account Summary ───────────────────────────────────────────────────────
    elements.append(Paragraph("Account Summary", style_section))

    LABEL_W  = 3.5 * inch
    AMOUNT_W = 3.5 * inch

    summary_table = Table(
        [
            ['Opening Balance', money(opening_balance)],
            ['Invoiced Amount', money(invoiced_amount)],
            ['Amount Paid',     money(amount_paid)],
        ],
        colWidths=[LABEL_W, AMOUNT_W],
    )
    summary_table.setStyle(TableStyle([
        ('FONTNAME',      (0, 0), (-1, -1), 'Helvetica'),
        ('FONTSIZE',      (0, 0), (-1, -1), 10),
        ('TEXTCOLOR',     (0, 0), (-1, -1), C_DARK),
        ('ALIGN',         (1, 0), (1, -1),  'RIGHT'),
        ('TOPPADDING',    (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('LEFTPADDING',   (0, 0), (-1, -1), 8),
        ('RIGHTPADDING',  (0, 0), (-1, -1), 8),
        ('TEXTCOLOR',     (1, 2), (1, 2),   C_GREEN),
        ('LINEBELOW',     (0, 0), (-1, -1), 0.5, C_RULE),
    ]))
    elements.append(summary_table)

    elements.append(Spacer(0, -1))
    elements.append(HRFlowable(width="100%", thickness=1, color=C_DARK, spaceAfter=2))

    bal_color = C_RED if balance_due > 0 else C_GREEN
    balance_row = Table(
        [['Balance Due', money(balance_due)]],
        colWidths=[LABEL_W, AMOUNT_W],
    )
    balance_row.setStyle(TableStyle([
        ('FONTNAME',      (0, 0), (-1, -1), 'Helvetica-Bold'),
        ('FONTSIZE',      (0, 0), (-1, -1), 12),
        ('TEXTCOLOR',     (0, 0), (0, 0),   C_DARK),
        ('TEXTCOLOR',     (1, 0), (1, 0),   bal_color),
        ('ALIGN',         (1, 0), (1, 0),   'RIGHT'),
        ('TOPPADDING',    (0, 0), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ('LEFTPADDING',   (0, 0), (-1, -1), 8),
        ('RIGHTPADDING',  (0, 0), (-1, -1), 8),
        ('BACKGROUND',    (0, 0), (-1, -1), colors.HexColor('#FDFEFE')),
    ]))
    elements.append(balance_row)
    elements.append(HRFlowable(width="100%", thickness=1, color=C_DARK, spaceAfter=14))

    # ── Sales History ─────────────────────────────────────────────────────────
    elements.append(Paragraph("Sales History", style_section))
    sales = Sale.objects.filter(**sales_filter).prefetch_related('saleitem_set').order_by('sale_date')

    if sales.exists():
        COL_W = [0.55*inch, 0.9*inch, 2.2*inch, 0.55*inch, 1.1*inch, 1.2*inch]
        sales_data = [["#", "Date", "Product", "Qty", "Unit Price", "Amount"]]

        for sale in sales:
            items = list(sale.saleitem_set.all())
            for i, item in enumerate(items):
                sales_data.append([
                    str(sale.id) if i == 0 else "",
                    sale.sale_date.strftime('%d-%m-%Y') if i == 0 else "",
                    str(item.cheese_product),
                    str(item.quantity_packets),
                    f"{item.selling_price_per_packet:,.2f}",
                    f"{item.quantity_packets * item.selling_price_per_packet:,.2f}",
                ])
            sales_data.append(["", "", "", "", "Sale Total →", f"{sale.total_amount:,.2f}"])

        sales_table = Table(sales_data, colWidths=COL_W, repeatRows=1)
        sales_table.setStyle(TableStyle([
            ('BACKGROUND',    (0, 0), (-1, 0),  C_BLUE),
            ('TEXTCOLOR',     (0, 0), (-1, 0),  C_HEADER_FG),
            ('FONTNAME',      (0, 0), (-1, 0),  'Helvetica-Bold'),
            ('FONTSIZE',      (0, 0), (-1, 0),  9),
            ('BOTTOMPADDING', (0, 0), (-1, 0),  8),
            ('TOPPADDING',    (0, 0), (-1, 0),  8),
            ('FONTNAME',      (0, 1), (-1, -1), 'Helvetica'),
            ('FONTSIZE',      (0, 1), (-1, -1), 8),
            ('TOPPADDING',    (0, 1), (-1, -1), 4),
            ('BOTTOMPADDING', (0, 1), (-1, -1), 4),
            ('LEFTPADDING',   (0, 0), (-1, -1), 5),
            ('RIGHTPADDING',  (0, 0), (-1, -1), 5),
            ('TEXTCOLOR',     (0, 1), (-1, -1), C_DARK),
            ('ALIGN',         (3, 0), (-1, -1), 'RIGHT'),
            ('ALIGN',         (0, 0), (1,  -1), 'CENTER'),
            ('LINEBELOW',     (0, 0), (-1, -1), 0.3, C_RULE),
            ('BOX',           (0, 0), (-1, -1), 0.5, colors.HexColor('#AEB6BF')),
        ]))

        row_idx = 1
        for sale in sales:
            item_count = sale.saleitem_set.count()
            for j in range(item_count):
                if j % 2 == 0:
                    sales_table.setStyle(TableStyle([
                        ('BACKGROUND', (0, row_idx + j), (-1, row_idx + j), C_STRIPE),
                    ]))
            row_idx += item_count
            sales_table.setStyle(TableStyle([
                ('BACKGROUND', (0, row_idx), (-1, row_idx), colors.HexColor('#D5D8DC')),
                ('FONTNAME',   (0, row_idx), (-1, row_idx), 'Helvetica-Bold'),
                ('FONTSIZE',   (0, row_idx), (-1, row_idx), 8),
            ]))
            row_idx += 1

        elements.append(sales_table)
    else:
        elements.append(Paragraph("No sales recorded for this period.", style_empty))

    # ── Payments History ──────────────────────────────────────────────────────
    elements.append(Spacer(1, 14))
    elements.append(Paragraph("Payments Received", style_section))
    payments = Payment.objects.filter(**payments_filter).order_by('date')
 
    if payments.exists():
        PAY_COL_W = [1.7*inch, 1.8*inch, 1.5*inch, 2.0*inch]
        pay_data  = [["Date", "Mode", "Bank","Amount (Rs.)"]]
        for p in payments:
            pay_data.append([
                p.date.strftime('%d-%m-%Y'),
                p.get_mode_display(),
                p.bank or "—",
                f"{p.amount:,.2f}",
            ])
 
        pay_table = Table(pay_data, colWidths=PAY_COL_W, repeatRows=1)
        pay_ts = TableStyle([
            ('BACKGROUND',    (0, 0), (-1, 0),  C_GREEN),
            ('TEXTCOLOR',     (0, 0), (-1, 0),  C_HEADER_FG),
            ('FONTNAME',      (0, 0), (-1, 0),  'Helvetica-Bold'),
            ('FONTSIZE',      (0, 0), (-1, 0),  9),
            ('BOTTOMPADDING', (0, 0), (-1, 0),  8),
            ('TOPPADDING',    (0, 0), (-1, 0),  8),
            ('FONTNAME',      (0, 1), (-1, -1), 'Helvetica'),
            ('FONTSIZE',      (0, 1), (-1, -1), 9),
            ('TOPPADDING',    (0, 1), (-1, -1), 5),
            ('BOTTOMPADDING', (0, 1), (-1, -1), 5),
            ('LEFTPADDING',   (0, 0), (-1, -1), 6),
            ('RIGHTPADDING',  (0, 0), (-1, -1), 6),
            ('TEXTCOLOR',     (0, 1), (-1, -1), C_DARK),
            ('TEXTCOLOR',     (3, 1), (3, -1),  C_GREEN),
            ('FONTNAME',      (3, 1), (3, -1),  'Helvetica-Bold'),
            ('ALIGN',         (3, 0), (3, -1),  'RIGHT'),
            ('LINEBELOW',     (0, 0), (-1, -1), 0.3, C_RULE),
            ('BOX',           (0, 0), (-1, -1), 0.5, colors.HexColor('#AEB6BF')),
        ])
        for i in range(1, len(pay_data)):
            if i % 2 == 0:
                pay_ts.add('BACKGROUND', (0, i), (-1, i), C_STRIPE)
        pay_table.setStyle(pay_ts)
        elements.append(pay_table)
    else:
        elements.append(Paragraph("No payments recorded for this period.", style_empty))
 

    # ── Footer ────────────────────────────────────────────────────────────────
    elements.append(Spacer(1, 20))
    elements.append(HRFlowable(width="100%", thickness=0.5, color=C_RULE))
    elements.append(Paragraph(
        f"Generated on {datetime.now().strftime('%B %d, %Y')}",
        style_footer,
    ))

    doc.build(elements)
    buffer.seek(0)
    return buffer

@login_required
def export_client_pdf(request, pk):
    """Export a single client's account statement as a PDF download."""
    from datetime import datetime
    from django.http import HttpResponse

    client = get_object_or_404(Client, pk=pk)

    start_date = end_date = None
    try:
        if request.GET.get('start_date'):
            start_date = datetime.strptime(request.GET['start_date'], '%Y-%m-%d')
        if request.GET.get('end_date'):
            end_date = datetime.strptime(request.GET['end_date'], '%Y-%m-%d')
    except Exception:
        pass

    try:
        company_name = ReceiptSettings.load().company_name
    except Exception:
        company_name = "Zain Traders"

    buffer = _build_client_pdf(client, start_date, end_date, company_name)

    safe_name = client.name.replace(" ", "_")
    response = HttpResponse(buffer.getvalue(), content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="statement_{safe_name}.pdf"'
    return response


@login_required
def export_all_clients_pdf(request):
    """
    Generate one PDF per client and return them all as a ZIP archive.
    The same start_date / end_date query params are forwarded to every statement.
    """
    import zipfile
    from datetime import datetime
    from io import BytesIO
    from django.http import HttpResponse

    start_date = end_date = None
    try:
        if request.GET.get('start_date'):
            start_date = datetime.strptime(request.GET['start_date'], '%Y-%m-%d')
        if request.GET.get('end_date'):
            end_date = datetime.strptime(request.GET['end_date'], '%Y-%m-%d')
    except Exception:
        pass

    try:
        company_name = ReceiptSettings.load().company_name
    except Exception:
        company_name = "Zain Traders"

    clients = Client.objects.all().order_by('name')

    zip_buffer = BytesIO()
    with zipfile.ZipFile(zip_buffer, mode='w', compression=zipfile.ZIP_DEFLATED) as zf:
        for client in clients:
            pdf_buffer = _build_client_pdf(client, start_date, end_date, company_name)
            safe_name  = client.name.replace(" ", "_")
            zf.writestr(f"statement_{safe_name}.pdf", pdf_buffer.getvalue())

    zip_buffer.seek(0)

    timestamp = datetime.now().strftime('%Y%m%d_%H%M')
    response = HttpResponse(zip_buffer.getvalue(), content_type='application/zip')
    response['Content-Disposition'] = f'attachment; filename="all_client_statements_{timestamp}.zip"'
    return response


@login_required
def sale_create(request):
    if request.method == 'POST':
        client_id = request.POST.get('client')
        sale_date_str = request.POST.get('sale_date')
        should_print = request.POST.get('print_receipt') in {'1', 'true', 'True', 'on', 'yes'}

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
            try:
                sale = _create_sale_from_valid_forms(
                    client=client,
                    sale_datetime=sale_datetime,
                    valid_forms=_normalize_sale_forms(formset),
                    request=request,
                )
            except SaleStockError as error:
                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return JsonResponse({'success': False, 'error': str(error)})
                messages.error(request, str(error))
                return render(request, 'distribution/sales/sale_create.html', {
                    'formset': formset,
                    'clients': Client.objects.all(),
                    'selected_client_id': int(client_id)
                })

            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({
                    'success': True,
                    'message': 'Sale created successfully.',
                    'receipt_url': f'/sales/{sale.id}/print/' if should_print else ''
                })

            if should_print:
                return redirect('sale_print', pk=sale.id)

            messages.success(request, 'Sale created successfully.')
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
    sales = Sale.objects.select_related('client').prefetch_related('saleitem_set__cheese_product').annotate(
        has_actions=Exists(SaleAction.objects.filter(sale_id=OuterRef('pk'))),
        has_modified_items=Exists(SaleItem.objects.filter(sale_id=OuterRef('pk'), modified=True)),
    ).all()
    sales_with_profit = []
    for sale in sales:
        sales_with_profit.append({
            'sale': sale,
            'total_profit': sale.calculate_total_profit(),
            'has_modified_items': sale.has_modified_items,
            'has_actions': sale.has_actions,
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
        should_print = request.POST.get('print_receipt') in {'1', 'true', 'True', 'on', 'yes'}
        if form.is_valid():
            payment = form.save()
            SiteActivity.update_activity(f'Payment of PKR {payment.amount} recorded for {payment.client.name}')
            
            # Handle AJAX requests
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({
                    'success': True,
                    'message': 'Payment recorded successfully.',
                    'receipt_url': f'/payments/{payment.id}/print/' if should_print else ''
                })

            if should_print:
                return redirect('payment_print', pk=payment.id)
            
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
    payments = Payment.objects.select_related('client').annotate(
        has_actions=Exists(PaymentAction.objects.filter(payment_id=OuterRef('pk')))
    ).all().order_by('-date')
    clients = Client.objects.all()
    return render(request, 'distribution/clients/payment_history.html', {
        'payments': payments,
        'clients': clients,
        'user_is_owner': is_owner(request.user),
    })


@login_required
def payment_modal_details(request, pk):
    payment = get_object_or_404(Payment.objects.select_related('client'), pk=pk)
    payment_actions = payment.actions.select_related('created_by__user').all()
    return render(request, 'distribution/clients/partials/partial_payment_modal_details.html', {
        'payment': payment,
        'payment_actions': payment_actions,
        'payment_modes': Payment.PAYMENT_MODES,
        'user_is_owner': is_owner(request.user),
    })


@login_required
@require_POST
def payment_action_apply(request, pk):
    payment = get_object_or_404(Payment, pk=pk)
    action_type = request.POST.get('action_type', '').strip()
    reason = request.POST.get('reason', '').strip()
    created_by = getattr(request.user, 'userprofile', None)

    if payment.is_voided and action_type != 'void':
        return JsonResponse({'success': False, 'error': 'This payment has already been voided.'})

    try:
        with transaction.atomic():
            payment = Payment.objects.select_for_update().get(pk=pk)

            if action_type == 'amount_change':
                new_amount = Decimal(request.POST.get('new_amount', '0'))
                if new_amount <= 0:
                    return JsonResponse({'success': False, 'error': 'Amount must be greater than 0.'})

                old_amount = payment.amount
                if old_amount == new_amount:
                    return JsonResponse({'success': False, 'error': 'New amount must be different from current amount.'})

                payment.amount = new_amount
                payment.save(update_fields=['amount'])

                PaymentAction.objects.create(
                    payment=payment,
                    action_type='amount_change',
                    old_amount=old_amount,
                    new_amount=new_amount,
                    reason=reason,
                    created_by=created_by,
                )
                SiteActivity.update_activity(f'Changed amount for Payment #{payment.id}')
                return JsonResponse({'success': True, 'message': 'Payment amount updated successfully.'})

            if action_type == 'date_change':
                new_date_value = request.POST.get('new_date', '').strip()
                if not new_date_value:
                    return JsonResponse({'success': False, 'error': 'Please provide a new payment date and time.'})

                try:
                    new_date = _parse_ddmmyyyy_datetime(new_date_value)
                except ValueError:
                    return JsonResponse({'success': False, 'error': 'Invalid date format. Please use DD/MM/YYYY HH:MM.'})

                date_error = _validate_sale_date_not_before_client_creation(payment.client, new_date)
                if date_error:
                    return JsonResponse({'success': False, 'error': date_error.replace('Sale date', 'Payment date')})

                old_date = payment.date
                if old_date == new_date:
                    return JsonResponse({'success': False, 'error': 'New date must be different from current date.'})

                payment.date = new_date
                payment.save(update_fields=['date'])

                PaymentAction.objects.create(
                    payment=payment,
                    action_type='date_change',
                    old_date=old_date,
                    new_date=new_date,
                    reason=reason,
                    created_by=created_by,
                )
                SiteActivity.update_activity(f'Changed date for Payment #{payment.id}')
                return JsonResponse({'success': True, 'message': 'Payment date updated successfully.'})

            if action_type == 'mode_change':
                new_mode = request.POST.get('new_mode', '').strip()
                new_bank = request.POST.get('new_bank', '').strip()
                valid_modes = {choice[0] for choice in Payment.PAYMENT_MODES}

                if new_mode not in valid_modes:
                    return JsonResponse({'success': False, 'error': 'Please select a valid payment mode.'})
                if new_mode == 'online' and not new_bank:
                    return JsonResponse({'success': False, 'error': 'Bank/Wallet is required for online mode.'})
                if new_mode == 'cash':
                    new_bank = ''

                old_mode = payment.mode
                old_bank = payment.bank or ''

                if old_mode == new_mode and old_bank == new_bank:
                    return JsonResponse({'success': False, 'error': 'Payment mode details are unchanged.'})

                payment.mode = new_mode
                payment.bank = new_bank
                payment.save(update_fields=['mode', 'bank'])

                PaymentAction.objects.create(
                    payment=payment,
                    action_type='mode_change',
                    old_mode=old_mode,
                    new_mode=new_mode,
                    old_bank=old_bank,
                    new_bank=new_bank,
                    reason=reason,
                    created_by=created_by,
                )
                SiteActivity.update_activity(f'Changed mode for Payment #{payment.id}')
                return JsonResponse({'success': True, 'message': 'Payment mode updated successfully.'})

            if action_type == 'void':
                if payment.is_voided:
                    return JsonResponse({'success': False, 'error': 'This payment has already been voided.'})

                payment.is_voided = True
                payment.voided_at = timezone.now()
                payment.void_reason = reason
                payment.voided_by = created_by
                payment.save(update_fields=['is_voided', 'voided_at', 'void_reason', 'voided_by'])

                PaymentAction.objects.create(
                    payment=payment,
                    action_type='void',
                    reason=reason,
                    created_by=created_by,
                )
                SiteActivity.update_activity(f'Payment #{payment.id} voided')
                return JsonResponse({'success': True, 'message': 'Payment voided successfully.'})

            return JsonResponse({'success': False, 'error': 'Unsupported payment action.'})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})


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


@owner_required
def receipt_settings(request):
    receipt_settings_obj = ReceiptSettings.load()

    if request.method == 'POST':
        form = ReceiptSettingsForm(request.POST, instance=receipt_settings_obj)
        if form.is_valid():
            form.save()
            SiteActivity.update_activity('Receipt settings updated')
            messages.success(request, 'Receipt settings updated successfully.')
            return redirect('receipt_settings')
    else:
        form = ReceiptSettingsForm(instance=receipt_settings_obj)

    return render(request, 'distribution/receipt_settings.html', {
        'form': form,
        'receipt_settings': receipt_settings_obj,
    })


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
            'is_voided': payment.is_voided,
        })
        if not payment.is_voided:
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
    expenses = DeliveryExpense.objects.select_related('employee').annotate(
        has_actions=Exists(ExpenseAction.objects.filter(expense_id=OuterRef('pk')))
    ).all().order_by('-expense_date', '-id')
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
        'expense_types': DeliveryExpense.EXPENSE_TYPES,
        'employees': DeliveryEmployee.objects.all().order_by('name'),
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
def expense_modal_details(request, pk):
    expense = get_object_or_404(DeliveryExpense.objects.select_related('employee'), pk=pk)
    expense_actions = expense.actions.select_related('created_by__user').all()
    return render(request, 'distribution/expenses/partials/partial_expense_modal_details.html', {
        'expense': expense,
        'expense_actions': expense_actions,
        'expense_types': DeliveryExpense.EXPENSE_TYPES,
        'employees': DeliveryEmployee.objects.all().order_by('name'),
        'user_is_owner': is_owner(request.user),
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
@require_POST
def expense_action_apply(request, pk):
    """Handle expense modifications: date, type, amount, employee changes and voids."""

    expense = get_object_or_404(DeliveryExpense, pk=pk)
    action_type = request.POST.get('action_type', '').strip()
    reason = request.POST.get('reason', '').strip()
    created_by = getattr(request.user, 'userprofile', None)

    if expense.is_voided and action_type != 'void':
        return JsonResponse({'success': False, 'error': 'This expense has already been voided.'})

    try:
        with transaction.atomic():
            expense = DeliveryExpense.objects.select_for_update().get(pk=pk)

            if action_type == 'date_change':
                new_date_value = request.POST.get('new_date', '').strip()
                if not new_date_value:
                    return JsonResponse({'success': False, 'error': 'Please provide a new expense date.'})

                try:
                    # Parse date as DD/MM/YYYY
                    from datetime import datetime
                    new_date = datetime.strptime(new_date_value, '%d/%m/%Y').date()
                except ValueError:
                    return JsonResponse({'success': False, 'error': 'Invalid date format. Please use DD/MM/YYYY.'})

                old_date = expense.expense_date
                if old_date == new_date:
                    return JsonResponse({'success': False, 'error': 'New date must be different from current date.'})

                expense.expense_date = new_date
                expense.save(update_fields=['expense_date'])

                ExpenseAction.objects.create(
                    expense=expense,
                    action_type='date_change',
                    old_date=old_date,
                    new_date=new_date,
                    reason=reason,
                    created_by=created_by,
                )
                SiteActivity.update_activity(f'Changed date for Expense #{expense.id}')
                return JsonResponse({'success': True, 'message': 'Expense date updated successfully.'})

            if action_type == 'type_change':
                new_type = request.POST.get('new_type', '').strip()
                valid_types = {choice[0] for choice in DeliveryExpense.EXPENSE_TYPES}

                if new_type not in valid_types:
                    return JsonResponse({'success': False, 'error': 'Please select a valid expense type.'})

                old_type = expense.expense_type
                if old_type == new_type:
                    return JsonResponse({'success': False, 'error': 'New type must be different from current type.'})

                expense.expense_type = new_type
                expense.save(update_fields=['expense_type'])

                ExpenseAction.objects.create(
                    expense=expense,
                    action_type='type_change',
                    old_type=old_type,
                    new_type=new_type,
                    reason=reason,
                    created_by=created_by,
                )
                SiteActivity.update_activity(f'Changed type for Expense #{expense.id}')
                return JsonResponse({'success': True, 'message': 'Expense type updated successfully.'})

            if action_type == 'amount_change':
                new_amount = Decimal(request.POST.get('new_amount', '0'))
                if new_amount <= 0:
                    return JsonResponse({'success': False, 'error': 'Amount must be greater than 0.'})

                old_amount = expense.amount
                if old_amount == new_amount:
                    return JsonResponse({'success': False, 'error': 'New amount must be different from current amount.'})

                expense.amount = new_amount
                expense.save(update_fields=['amount'])

                ExpenseAction.objects.create(
                    expense=expense,
                    action_type='amount_change',
                    old_amount=old_amount,
                    new_amount=new_amount,
                    reason=reason,
                    created_by=created_by,
                )
                SiteActivity.update_activity(f'Changed amount for Expense #{expense.id}')
                return JsonResponse({'success': True, 'message': 'Expense amount updated successfully.'})

            if action_type == 'employee_change':
                new_employee_id = request.POST.get('new_employee_id', '').strip()
                if new_employee_id:
                    try:
                        new_employee = DeliveryEmployee.objects.get(pk=int(new_employee_id))
                    except (DeliveryEmployee.DoesNotExist, ValueError):
                        return JsonResponse({'success': False, 'error': 'Invalid employee selected.'})
                else:
                    new_employee = None

                old_employee_id = expense.employee_id
                new_employee_id_int = new_employee.id if new_employee else None

                if old_employee_id == new_employee_id_int:
                    return JsonResponse({'success': False, 'error': 'New employee must be different from current employee.'})

                expense.employee = new_employee
                expense.save(update_fields=['employee'])

                ExpenseAction.objects.create(
                    expense=expense,
                    action_type='employee_change',
                    old_employee_id=old_employee_id,
                    new_employee_id=new_employee_id_int,
                    reason=reason,
                    created_by=created_by,
                )
                SiteActivity.update_activity(f'Changed employee for Expense #{expense.id}')
                return JsonResponse({'success': True, 'message': 'Expense employee updated successfully.'})

            if action_type == 'void':
                if expense.is_voided:
                    return JsonResponse({'success': False, 'error': 'This expense has already been voided.'})

                expense.is_voided = True
                expense.voided_at = timezone.now()
                expense.void_reason = reason
                expense.voided_by = created_by
                expense.save(update_fields=['is_voided', 'voided_at', 'void_reason', 'voided_by'])

                ExpenseAction.objects.create(
                    expense=expense,
                    action_type='void',
                    reason=reason,
                    created_by=created_by,
                )
                SiteActivity.update_activity(f'Expense #{expense.id} voided')
                return JsonResponse({'success': True, 'message': 'Expense voided successfully.'})

            return JsonResponse({'success': False, 'error': 'Unsupported expense action.'})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})


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
                # Flush OUTSIDE transaction
                call_command('flush', verbosity=0, interactive=False)

                with transaction.atomic():
                    call_command('loaddata', temp_path, verbosity=0)

                    sequence_sql_buffer = StringIO()
                    call_command(
                        'sqlsequencereset',
                        'admin', 'auth', 'contenttypes', 'sessions', 'distribution',
                        stdout=sequence_sql_buffer,
                    )

                    sequence_sql = sequence_sql_buffer.getvalue().strip()

                    if sequence_sql:
                        with connections['default'].cursor() as cursor:
                            for stmt in sequence_sql.split(';'):
                                stmt = stmt.strip()
                                if stmt:
                                    cursor.execute(stmt)
                                    
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


@owner_required
def user_change_password(request, pk):
    """Change a user's password from user management."""
    from django.contrib.auth.models import User

    target_user = get_object_or_404(User, pk=pk)

    if request.method == 'POST':
        form = UserPasswordChangeForm(request.POST)
        if form.is_valid():
            target_user.set_password(form.cleaned_data['new_password'])
            target_user.save(update_fields=['password'])

            # If owner changes their own password, keep current session authenticated.
            if target_user == request.user:
                update_session_auth_hash(request, target_user)

            messages.success(request, f'Password updated successfully for "{target_user.username}".')
            return redirect('user_list')
    else:
        form = UserPasswordChangeForm()

    return render(request, 'distribution/user_password_form.html', {
        'form': form,
        'target_user': target_user,
        'title': f'Change Password for {target_user.username}'
    })
