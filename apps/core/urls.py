from django.urls import path
from . import views

app_name = 'core'

urlpatterns = [
    path('recipes/', views.RecipeListView.as_view(), name='recipe_list'),
    path('recipes/add/', views.RecipeCreateView.as_view(), name='recipe_add'),
    path('recipes/edit/<int:pk>/', views.RecipeUpdateView.as_view(), name='recipe_edit'),
    path('recipes/delete/<int:pk>/', views.RecipeDeleteView.as_view(), name='recipe_delete'),
]
