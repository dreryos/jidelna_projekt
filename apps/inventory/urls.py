from django.urls import path
from . import views

app_name = 'inventory'

urlpatterns = [
    # Skladové položky (StockItem)
    path('', views.StockListView.as_view(), name='stock_list'),
    path('add/', views.StockCreateView.as_view(), name='stock_add'),
    path('edit/<int:pk>/', views.StockUpdateView.as_view(), name='stock_edit'),
    path('delete/<int:pk>/', views.StockDeleteView.as_view(), name='stock_delete'),
    
    # Sklady (Warehouse)
    path('warehouses/', views.WarehouseListView.as_view(), name='warehouse_list'),
    path('warehouses/add/', views.WarehouseCreateView.as_view(), name='warehouse_add'),
    path('warehouses/edit/<int:pk>/', views.WarehouseUpdateView.as_view(), name='warehouse_edit'),
    path('warehouses/delete/<int:pk>/', views.WarehouseDeleteView.as_view(), name='warehouse_delete'),
    
    # Jídelny (Canteen)
    path('canteens/', views.CanteenListView.as_view(), name='canteen_list'),
    path('canteens/add/', views.CanteenCreateView.as_view(), name='canteen_add'),
    path('canteens/edit/<int:pk>/', views.CanteenUpdateView.as_view(), name='canteen_edit'),
    path('canteens/delete/<int:pk>/', views.CanteenDeleteView.as_view(), name='canteen_delete'),
    
    # Import CSV
    path('import/', views.import_csv_step1, name='import_csv_step1'),
    path('import/confirm/', views.import_csv_step2_confirm, name='import_csv_step2_confirm'),
    
    # Příjem zboží (GoodsReceipt)
    path('goods-receipts/', views.GoodsReceiptListView.as_view(), name='goods_receipt_list'),
    path('goods-receipts/create/', views.goods_receipt_create, name='goods_receipt_create'),
    path('goods-receipts/<int:pk>/', views.GoodsReceiptDetailView.as_view(), name='goods_receipt_detail'),
    path('goods-receipts/<int:pk>/confirm/', views.goods_receipt_confirm, name='goods_receipt_confirm'),
    path('goods-receipts/<int:pk>/delete/', views.goods_receipt_delete, name='goods_receipt_delete'),
]
