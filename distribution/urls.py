from django.urls import path
from . import views

urlpatterns = [
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('dashboard/', views.dashboard, name='dashboard'),
    
    path('manufacturers/', views.manufacturer_list, name='manufacturer_list'),
    path('manufacturers/add/', views.manufacturer_add, name='manufacturer_add'),
    path('manufacturers/<int:pk>/edit/', views.manufacturer_edit, name='manufacturer_edit'),
    path('manufacturers/<int:pk>/delete/', views.manufacturer_delete, name='manufacturer_delete'),
    
    path('cheese/', views.cheese_inventory, name='cheese_inventory'),
    path('cheese/add/', views.cheese_add, name='cheese_add'),
    path('cheese/<int:pk>/edit/', views.cheese_edit, name='cheese_edit'),
    path('cheese/<int:pk>/delete/', views.cheese_delete, name='cheese_delete'),
    
    path('clients/', views.client_list, name='client_list'),
    path('clients/add/', views.client_add, name='client_add'),
    path('clients/<int:pk>/edit/', views.client_edit, name='client_edit'),
    path('clients/<int:pk>/delete/', views.client_delete, name='client_delete'),
    
    path('sales/create/', views.sale_create, name='sale_create'),
    path('sales/', views.sale_history, name='sale_history'),
    path('sales/<int:pk>/', views.sale_detail, name='sale_detail'),
]

