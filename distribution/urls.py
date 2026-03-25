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
    path('sales-stock-history/', views.sales_stock_history, name='sales_stock_history'),
    path('client-debt/', views.client_debt_page, name='client_debt_page'),
    path('add-stock/', views.add_stock_page, name='add_stock_page'),
    path('api/client-analytics/', views.get_client_analytics, name='get_client_analytics'),
    path('api/product-analytics/', views.get_product_analytics, name='get_product_analytics'),
    path('api/sales-history/', views.get_sales_history, name='get_sales_history'),
    path('api/stock-history/', views.get_stock_history, name='get_stock_history'),
    path('api/client-debt/', views.get_client_debt, name='get_client_debt'),
    path('api/payment-history/', views.get_payment_history, name='get_payment_history'),
    path('api/product-stock/<int:product_id>/', views.get_product_stock, name='get_product_stock'),
    
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
    path('sales/quick-create/', views.quick_sale_create, name='quick_sale_create'),
    path('sales/', views.sales_stock_history, name='sale_history'),  # Redirects to consolidated page
    path('sales/<int:pk>/', views.sale_detail, name='sale_detail'),
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

    # Delivery employee management
    path('employees/', views.employee_management, name='employee_management'),
    path('employees/<int:pk>/edit/', views.employee_edit, name='employee_edit'),
    path('employees/<int:pk>/delete/', views.employee_delete, name='employee_delete'),

    # Delivery expense management
    path('expenses/', views.expense_management, name='expense_management'),
    path('expenses/<int:pk>/edit/', views.expense_edit, name='expense_edit'),
    path('expenses/<int:pk>/delete/', views.expense_delete, name='expense_delete'),
    
    # User Management (Owner only)
    path('users/', views.user_list, name='user_list'),
    path('users/add/', views.user_add, name='user_add'),
    path('users/<int:pk>/edit-role/', views.user_edit_role, name='user_edit_role'),
    path('users/<int:pk>/delete/', views.user_delete, name='user_delete'),
]

