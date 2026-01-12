from django.urls import path
from . import views
from . import template_views

app_name = 'production'

urlpatterns = [
    # Jídelníčky - nový systém
    path('', views.MenuPlanListView.as_view(), name='menu_list'),
    path('jidelnicky/', views.MenuPlanListView.as_view(), name='menu_list'),
    path('jidelnicky/novy/', views.MenuPlanCreateView.as_view(), name='menu_create'),
    path('jidelnicky/<int:pk>/', views.MenuPlanDetailView.as_view(), name='menu_detail'),
    path('jidelnicky/<int:pk>/smazat/', views.MenuPlanDeleteView.as_view(), name='menu_delete'),
    
    # Šablony jídelníčků
    path('sablony/', template_views.MenuTemplateListView.as_view(), name='template_list'),
    path('sablony/nova/', template_views.MenuTemplateCreateView.as_view(), name='template_create'),
    path('sablony/<int:pk>/upravit/', template_views.MenuTemplateUpdateView.as_view(), name='template_edit'),
    path('sablony/<int:pk>/smazat/', template_views.MenuTemplateDeleteView.as_view(), name='template_delete'),
    path('sablony/<int:pk>/duplikovat/', template_views.duplicate_template, name='template_duplicate'),
    
    # Import jídelníčku ze šablony
    path('import-jidelnicku/', template_views.menu_import_step1, name='menu_import_step1'),
    path('import-jidelnicku/nahled/', template_views.menu_import_step2_preview, name='menu_import_step2'),
    path('import-jidelnicku/potvrdit/', template_views.menu_import_step3_confirm, name='menu_import_step3'),
    
    # AJAX endpointy pro jídelníčky
    path('jidelnicky/<int:menu_pk>/pridat-jidlo/', views.add_meal_to_menu, name='add_meal_to_menu'),
    path('jidelnicky/<int:menu_pk>/upravit-porce/', views.update_portions_bulk, name='update_portions_bulk'),
    
    # AJAX endpointy pro jednotlivé výrobní příkazy
    path('vyrobni-prikazy/<int:order_pk>/upravit-porce/', views.update_order_portions, name='update_order_portions'),
    path('vyrobni-prikazy/<int:order_pk>/upravit-varianty/', views.update_order_variants, name='update_order_variants'),
    path('vyrobni-prikazy/<int:order_pk>/smazat/', views.delete_order_ajax, name='delete_order_ajax'),
    
    # Denní výdejky
    path('vydejka-dne/', views.daily_picking_list, name='daily_picking_list'),
    
    # Generátor výdejek
    path('vydejky/', views.picking_list_generator, name='picking_list_generator'),
    path('vydejky/<int:document_id>/edit/', views.picking_list_edit, name='picking_list_edit'),
    path('vydejky/<int:document_id>/pdf/', views.picking_list_pdf, name='picking_list_pdf'),
    path('vydejky/<int:document_id>/archive/', views.archive_picking_list, name='archive_picking_list'),
    
    # Detail výrobního příkazu (read-only, přístupný z jídelníčku)
    path('jidlo/<int:order_pk>/vydejka/', views.picking_list_print, name='picking_list_print'),
]
