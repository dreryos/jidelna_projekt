from django.urls import path
from . import views

app_name = 'production'

urlpatterns = [
    # Jídelníčky - nový systém
    path('', views.MenuPlanListView.as_view(), name='menu_list'),
    path('jidelnicky/', views.MenuPlanListView.as_view(), name='menu_list'),
    path('jidelnicky/novy/', views.MenuPlanCreateView.as_view(), name='menu_create'),
    path('jidelnicky/<int:pk>/', views.MenuPlanDetailView.as_view(), name='menu_detail'),
    path('jidelnicky/<int:pk>/smazat/', views.MenuPlanDeleteView.as_view(), name='menu_delete'),
    
    # AJAX endpointy pro jídelníčky
    path('jidelnicky/<int:menu_pk>/pridat-jidlo/', views.add_meal_to_menu, name='add_meal_to_menu'),
    path('jidelnicky/<int:menu_pk>/upravit-porce/', views.update_portions_bulk, name='update_portions_bulk'),
    
    # AJAX endpointy pro jednotlivé výrobní příkazy
    path('vyrobni-prikazy/<int:order_pk>/upravit-porce/', views.update_order_portions, name='update_order_portions'),
    path('vyrobni-prikazy/<int:order_pk>/upravit-varianty/', views.update_order_variants, name='update_order_variants'),
    path('vyrobni-prikazy/<int:order_pk>/smazat/', views.delete_order_ajax, name='delete_order_ajax'),
    
    # Denní výdejky
    path('vydejka-dne/', views.daily_picking_list, name='daily_picking_list'),
    
    # Detail výrobního příkazu (read-only, přístupný z jídelníčku)
    path('jidlo/<int:pk>/', views.production_order_detail, name='order_detail'),
    path('jidlo/<int:order_pk>/vydejka/', views.picking_list_print, name='picking_list_print'),
]
