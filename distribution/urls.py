from django.urls import path
from . import views 

urlpatterns = [
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('dashboard/', views.dashboard, name='dashboard'),

    path('api/client-analytics/', views.get_client_analytics, name='get_client_analytics'),
    path('api/product-analytics/', views.get_product_analytics, name='get_product_analytics'),
    path('api/general-metrics/', views.get_general_metrics, name='get_general_metrics'),
    path('api/dashboard-overview/', views.get_dashboard_overview, name='get_dashboard_overview'),
    path('api/sales-history/', views.get_sales_history, name='get_sales_history'),
    path('api/stock-history/', views.get_stock_history, name='get_stock_history'),
    path('api/payment-history/', views.get_payment_history, name='get_payment_history'),
    path('api/product-stock/<int:product_id>/', views.get_product_stock, name='get_product_stock'),
    path('api/manufacturer/<int:manufacturer_id>/', views.get_manufacturer_details, name='get_manufacturer_details'),
    path('api/filtered-products/', views.get_filtered_products, name='get_filtered_products'),
    path('api/client-product-price/<int:client_id>/<int:product_id>/', views.get_client_product_price, name='get_client_product_price'),
    
    # Merged inventory management (manufacturers + cheese)
    path('inventory/', views.inventory_management, name='inventory_management'),
    path('inventory/manufacturers/add/', views.manufacturer_add, name='manufacturer_add'),
    path('inventory/manufacturers/<int:pk>/edit/', views.manufacturer_edit, name='manufacturer_edit'),
    path('inventory/manufacturers/<int:pk>/delete/', views.manufacturer_delete, name='manufacturer_delete'),
    
    path('inventory/cheese-product/add/', views.cheese_add, name='cheese_add'),
    path('inventory/cheese-product/<int:pk>/edit/', views.cheese_edit, name='cheese_edit'),
    path('inventory/cheese-product/<int:pk>/delete/', views.cheese_delete, name='cheese_delete'),
    
    path('inventory/cheese-type/add/', views.cheese_type_add, name='cheese_type_add'),
    path('inventory/cheese-type/<int:pk>/edit/', views.cheese_type_edit, name='cheese_type_edit'),
    path('inventory/cheese-type/<int:pk>/delete/', views.cheese_type_delete, name='cheese_type_delete'),

    path('inventory/stock/history/', views.stock_history, name='stock_history'),

    path('clients/', views.client_list, name='client_list'),
    path('clients/add/', views.client_add, name='client_add'),
    path('clients/export-all-pdf/', views.export_all_clients_pdf, name='export_all_clients_pdf'),
    path('clients/<int:pk>/edit/', views.client_edit, name='client_edit'),
    path('clients/<int:pk>/delete/', views.client_delete, name='client_delete'),
    path('clients/<int:pk>/export-pdf/', views.export_client_pdf, name='export_client_pdf'),
    
    path('sales/history/', views.sale_history, name='sale_history'),  # Now points to individual sale history page
    path('sales/create/', views.sale_create, name='sale_create'),
    path('sales/quick-create/', views.quick_sale_create, name='quick_sale_create'),
    path('sales/<int:pk>/', views.sale_detail, name='sale_detail'),
    path('sales/<int:pk>/edit/', views.sale_edit, name='sale_edit'),
    path('sales/<int:pk>/delete/', views.sale_delete, name='sale_delete'),
    path('sales/<int:pk>/modal/', views.sale_modal_details, name='sale_modal_details_alt'),
    path('sales/<int:pk>/actions/', views.sale_action_apply, name='sale_action_apply'),

    path('returns/sale-item/', views.return_sale_item, name='return_sale_item'),
    path('returns/sale-all/', views.return_all_sale_items, name='return_all_sale_items'),
    
    # Stock operations
    path('stock/add/', views.add_stock_quantity, name='add_stock_quantity'),
    path('stock/remove/', views.remove_stock_quantity, name='remove_stock_quantity'),
    path('stock/change-price/', views.change_stock_price, name='change_stock_price'),
    
    #Payment Management
    path('payments/add/', views.add_payment, name='add_payment'),
    path('payments/history/', views.payment_history, name='payment_history'),
    path('payments/<int:pk>/modal/', views.payment_modal_details, name='payment_modal_details'),
    path('payments/<int:pk>/print/', views.payment_print, name='payment_print'),
    path('payments/<int:pk>/actions/', views.payment_action_apply, name='payment_action_apply'),
    path('payments/<int:pk>/edit/', views.payment_edit, name='payment_edit'),
    path('payments/<int:pk>/delete/', views.payment_delete, name='payment_delete'),

    # Delivery employee management
    path('employees/', views.employee_management, name='employee_management'),
    path('employees/<int:pk>/edit/', views.employee_edit, name='employee_edit'),
    path('employees/<int:pk>/delete/', views.employee_delete, name='employee_delete'),

    # Delivery expense management
    path('expenses/', views.expense_management, name='expense_management'),
    path('expenses/<int:pk>/modal/', views.expense_modal_details, name='expense_modal_details'),
    path('expenses/<int:pk>/edit/', views.expense_edit, name='expense_edit'),
    path('expenses/<int:pk>/delete/', views.expense_delete, name='expense_delete'),
    path('expenses/<int:pk>/action/', views.expense_action_apply, name='expense_action_apply'),
    
    # User Management (Owner only)
    path('users/', views.user_list, name='user_list'),
    path('users/add/', views.user_add, name='user_add'),
    path('users/<int:pk>/edit-role/', views.user_edit_role, name='user_edit_role'),
    path('users/<int:pk>/change-password/', views.user_change_password, name='user_change_password'),
    path('users/<int:pk>/delete/', views.user_delete, name='user_delete'),
    path('receipt-settings/', views.receipt_settings, name='receipt_settings'),
    path('sales/<int:pk>/print/', views.sale_print, name='sale_print'),
    path('database/', views.database_management, name='database_management'),
]

