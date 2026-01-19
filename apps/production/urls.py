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
    path('jidelnicky/<int:pk>/vizualni-editor/', views.MenuPlanVisualEditView.as_view(), name='menu_visual_edit'),

    
    # Šablony jídelníčků
    path('sablony/', template_views.MenuTemplateListView.as_view(), name='template_list'),
    path('sablony/nova/', template_views.MenuTemplateCreateVisualView.as_view(), name='template_create'),
    path('sablony/nova-xml/', template_views.MenuTemplateCreateView.as_view(), name='template_create_xml'),
    path('sablony/<int:pk>/upravit/', template_views.MenuTemplateUpdateView.as_view(), name='template_update'),
    path('sablony/<int:pk>/vizualni-editor/', template_views.MenuTemplateVisualEditView.as_view(), name='template_visual_edit'),
    path('sablony/<int:pk>/smazat/', template_views.MenuTemplateDeleteView.as_view(), name='template_delete'),
    path('sablony/<int:pk>/duplikovat/', template_views.duplicate_template, name='template_duplicate'),
    
    # AJAX endpointy pro vizuální vytváření šablon
    path('sablony/ajax/preview-xml/', template_views.template_preview_xml_ajax, name='template_preview_xml_ajax'),
    path('sablony/ajax/vytvorit/', template_views.template_create_ajax, name='template_create_ajax'),
    path('sablony/ajax/check-name/', template_views.template_check_name_ajax, name='template_check_name_ajax'),
    path('sablony/ajax/autosave/', template_views.template_autosave_ajax, name='template_autosave_ajax'),
    
    # AJAX endpointy pro vizuální editor šablon
    path('template/<int:pk>/add-meal/', template_views.template_add_meal_ajax, name='template_add_meal_ajax'),
    path('template/<int:pk>/remove-meal/', template_views.template_remove_meal_ajax, name='template_remove_meal_ajax'),
    path('template/<int:pk>/reorder/', template_views.template_reorder_ajax, name='template_reorder_ajax'),
    path('template/<int:pk>/copy-day/', template_views.template_copy_day_ajax, name='template_copy_day_ajax'),
    path('template/<int:pk>/clear-day/', template_views.template_clear_day_ajax, name='template_clear_day_ajax'),
    
    # Import jídelníčku ze šablony
    path('import-jidelnicku/', template_views.menu_import_step1, name='menu_import_step1'),
    path('import-jidelnicku/nahled/', template_views.menu_import_step2_preview, name='menu_import_step2'),
    path('import-jidelnicku/potvrdit/', template_views.menu_import_step3_confirm, name='menu_import_step3'),
    
    # AJAX endpointy pro jídelníčky
    path('jidelnicky/<int:menu_pk>/pridat-jidlo/', views.add_meal_to_menu, name='add_meal_to_menu'),
    path('jidelnicky/<int:menu_pk>/upravit-porce/', views.update_portions_bulk, name='update_portions_bulk'),

    # AJAX endpointy pro vizuální editor MenuPlan (adapter)
    path('jidelnicky/<int:menu_pk>/visual/add-meal/', views.menu_visual_add_meal_ajax, name='menu_visual_add_meal_ajax'),
    path('jidelnicky/<int:menu_pk>/visual/remove-meal/', views.menu_visual_remove_meal_ajax, name='menu_visual_remove_meal_ajax'),
    path('jidelnicky/<int:menu_pk>/visual/reorder/', views.menu_visual_reorder_ajax, name='menu_visual_reorder_ajax'),
    path('jidelnicky/<int:menu_pk>/visual/copy-day/', views.menu_visual_copy_day_ajax, name='menu_visual_copy_day_ajax'),
    path('jidelnicky/<int:menu_pk>/visual/clear-day/', views.menu_visual_clear_day_ajax, name='menu_visual_clear_day_ajax'),
    
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
