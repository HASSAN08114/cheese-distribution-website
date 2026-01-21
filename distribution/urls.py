from django.urls import path
from . import views

urlpatterns = [
    path('cheese-types/', views.cheese_type_list, name='cheese_type_list'),
    path('cheese-type/add/', views.cheese_type_add, name='cheese_type_add'),
    path('cheese-type/<int:pk>/edit/', views.cheese_type_edit, name='cheese_type_edit'),
    path('cheese-type/<int:pk>/delete/', views.cheese_type_delete, name='cheese_type_delete'),
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('dashboard/', views.dashboard, name='dashboard'),
    path('api/client-analytics/', views.get_client_analytics, name='get_client_analytics'),
    path('api/product-analytics/', views.get_product_analytics, name='get_product_analytics'),
    
    # Merged inventory management (manufacturers + cheese)
    path('inventory/', views.inventory_management, name='inventory_management'),
    path('manufacturers/add/', views.manufacturer_add, name='manufacturer_add'),
    path('manufacturers/<int:pk>/edit/', views.manufacturer_edit, name='manufacturer_edit'),
    path('manufacturers/<int:pk>/delete/', views.manufacturer_delete, name='manufacturer_delete'),
    
    path('cheese/add/', views.cheese_add, name='cheese_add'),
    path('cheese/<int:pk>/edit/', views.cheese_edit, name='cheese_edit'),
    path('cheese/<int:pk>/delete/', views.cheese_delete, name='cheese_delete'),
    path('stock/add/', views.add_stock, name='add_stock'),
    
    path('clients/', views.client_list, name='client_list'),
    path('clients/add/', views.client_add, name='client_add'),
    path('clients/<int:pk>/edit/', views.client_edit, name='client_edit'),
    path('clients/<int:pk>/delete/', views.client_delete, name='client_delete'),
    
    path('sales/create/', views.sale_create, name='sale_create'),
    path('sales/', views.sale_history, name='sale_history'),
    path('sales/<int:pk>/modal/', views.sale_modal_details, name='sale_modal_details'),
    path('stock/history/', views.stock_history, name='stock_history'),
    path('stock/<int:pk>/modal/', views.stock_modal_details, name='stock_modal_details'),
    path('sales/modal/<int:pk>/', views.sale_modal_details, name='sale_modal_details_alt'),
    path('stock/modal/<int:pk>/', views.stock_modal_details, name='stock_modal_details_alt'),
    path('returns/sale-item/', views.return_sale_item, name='return_sale_item'),
    path('returns/sale-all/', views.return_all_sale_items, name='return_all_sale_items'),
    path('returns/stock/', views.return_stock_addition, name='return_stock_addition'),
    
    #Payment Management
    path('payments/make/', views.make_payment, name='make_payment'),
    path('payments/history/', views.payment_history, name='payment_history'),
    
    # User Management (Owner only)
    path('users/', views.user_list, name='user_list'),
    path('users/add/', views.user_add, name='user_add'),
    path('users/<int:pk>/edit-role/', views.user_edit_role, name='user_edit_role'),
    path('users/<int:pk>/delete/', views.user_delete, name='user_delete'),
]

