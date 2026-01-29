from django.urls import path
from . import views

app_name = 'reports'

urlpatterns = [
    path('order-report/', views.order_report, name='order_report'),
    path('order-report/export/', views.order_report_download, name='order_report_download'),
]
