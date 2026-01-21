from django.urls import path
from django.views.generic import RedirectView
from . import views

app_name = 'inventory'

urlpatterns = [
    # Skladové položky (StockItem)
    path('', views.StockListView.as_view(), name='stock_list'),
    path('edit/<int:pk>/', views.StockUpdateView.as_view(), name='stock_edit'),
    path('delete/<int:pk>/', views.StockDeleteView.as_view(), name='stock_delete'),
    
    # Unified Management - Správa jídelen a skladů
    path('management/', views.CanteenWarehouseManagementView.as_view(), name='management'),
    
    # AJAX endpoints pro jídelny
    path('ajax/canteen/create/', views.canteen_ajax_create, name='canteen_ajax_create'),
    path('ajax/canteen/update/<int:pk>/', views.canteen_ajax_update, name='canteen_ajax_update'),
    path('ajax/canteen/delete/<int:pk>/', views.canteen_ajax_delete, name='canteen_ajax_delete'),
    
    # AJAX endpoints pro sklady
    path('ajax/warehouse/create/', views.warehouse_ajax_create, name='warehouse_ajax_create'),
    path('ajax/warehouse/update/<int:pk>/', views.warehouse_ajax_update, name='warehouse_ajax_update'),
    path('ajax/warehouse/delete/<int:pk>/', views.warehouse_ajax_delete, name='warehouse_ajax_delete'),
    
    # Sklady (Warehouse) - redirecty na unified management
    path('warehouses/', RedirectView.as_view(pattern_name='inventory:management', permanent=False), name='warehouse_list'),
    path('warehouses/add/', views.WarehouseCreateView.as_view(), name='warehouse_add'),
    path('warehouses/edit/<int:pk>/', views.WarehouseUpdateView.as_view(), name='warehouse_edit'),
    path('warehouses/delete/<int:pk>/', views.WarehouseDeleteView.as_view(), name='warehouse_delete'),
    
    # Jídelny (Canteen) - redirecty na unified management
    path('canteens/', RedirectView.as_view(pattern_name='inventory:management', permanent=False), name='canteen_list'),
    path('canteens/add/', views.CanteenCreateView.as_view(), name='canteen_add'),
    path('canteens/edit/<int:pk>/', views.CanteenUpdateView.as_view(), name='canteen_edit'),
    path('canteens/delete/<int:pk>/', views.CanteenDeleteView.as_view(), name='canteen_delete'),
    
    # Bidfood XML Import
    path('bidfood-import/', views.bidfood_xml_import_step1, name='bidfood_import_step1'),
    path('bidfood-import/preview/', views.bidfood_xml_import_step2, name='bidfood_import_step2'),
    path('bidfood-import/create/', views.bidfood_xml_import_step3, name='bidfood_import_step3'),
    
    # Příjem zboží (GoodsReceipt)
    path('goods-receipts/', views.GoodsReceiptListView.as_view(), name='goods_receipt_list'),
    path('goods-receipts/create/', views.goods_receipt_create, name='goods_receipt_create'),
    path('goods-receipts/<int:pk>/', views.GoodsReceiptDetailView.as_view(), name='goods_receipt_detail'),
    path('goods-receipts/<int:pk>/confirm/', views.goods_receipt_confirm, name='goods_receipt_confirm'),
    path('goods-receipts/<int:pk>/delete/', views.goods_receipt_delete, name='goods_receipt_delete'),
    
    # Inventura (InventoryVerification)
    path('inventory-verifications/', views.InventoryVerificationListView.as_view(), name='inventory_verification_list'),
    path('inventory-verifications/create/', views.InventoryVerificationCreateView.as_view(), name='inventory_verification_create'),
    path('inventory-verifications/<int:pk>/', views.InventoryVerificationDetailView.as_view(), name='inventory_verification_detail'),
    path('inventory-verifications/<int:pk>/count/', views.inventory_verification_count, name='inventory_verification_count'),
    path('inventory-verifications/<int:pk>/start/', views.inventory_verification_start, name='inventory_verification_start'),
    path('inventory-verifications/<int:pk>/complete/', views.inventory_verification_complete, name='inventory_verification_complete'),
    path('inventory-verifications/<int:pk>/cancel/', views.inventory_verification_cancel, name='inventory_verification_cancel'),
    path('inventory-verifications/<int:pk>/pdf/', views.inventory_verification_pdf, name='inventory_verification_pdf'),
    
    # Převodky (StockTransfer)
    path('stock-transfers/', views.StockTransferListView.as_view(), name='stock_transfer_list'),
    path('stock-transfers/create/', views.StockTransferCreateView.as_view(), name='stock_transfer_create'),
    path('stock-transfers/<int:pk>/', views.StockTransferDetailView.as_view(), name='stock_transfer_detail'),
    path('stock-transfers/<int:pk>/start/', views.stock_transfer_start, name='stock_transfer_start'),
    path('stock-transfers/<int:pk>/complete/', views.stock_transfer_complete, name='stock_transfer_complete'),
    path('stock-transfers/<int:pk>/start-and-complete/', views.stock_transfer_start_and_complete, name='stock_transfer_start_and_complete'),
    path('stock-transfers/<int:pk>/cancel/', views.stock_transfer_cancel, name='stock_transfer_cancel'),
    path('stock-transfers/<int:pk>/pdf/', views.stock_transfer_pdf, name='stock_transfer_pdf'),
    
    # AJAX endpoint pro načtení ceny suroviny ze skladu
    path('api/stock-item-price/', views.get_stock_item_price, name='stock_item_price'),
]
