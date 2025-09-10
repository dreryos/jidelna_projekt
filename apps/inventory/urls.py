from django.urls import path
from . import views

app_name = 'inventory'

urlpatterns = [
    path('', views.StockListView.as_view(), name='stock_list'),
    path('add/', views.StockCreateView.as_view(), name='stock_add'),
    path('edit/<int:pk>/', views.StockUpdateView.as_view(), name='stock_edit'),
    path('delete/<int:pk>/', views.StockDeleteView.as_view(), name='stock_delete'),
]
