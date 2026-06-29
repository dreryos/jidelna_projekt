from django.urls import path
from . import views

app_name = 'bufet'

urlpatterns = [
    path('', views.bufet_list, name='list'),
    path('upload/', views.bufet_upload_step1, name='upload_step1'),
    path('upload/nahled/', views.bufet_upload_step2, name='upload_step2'),
    path('upload/potvrdit/', views.bufet_upload_step3, name='upload_step3'),
    path('<int:pk>/', views.bufet_detail, name='detail'),
]
