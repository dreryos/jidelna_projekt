from django.urls import path
from . import views

app_name = 'core'

urlpatterns = [
    # Recepty
    path('recipes/', views.RecipeListView.as_view(), name='recipe_list'),
    path('recipes/add/', views.RecipeCreateView.as_view(), name='recipe_add'),
    path('recipes/edit/<int:pk>/', views.RecipeUpdateView.as_view(), name='recipe_edit'),
    path('recipes/delete/<int:pk>/', views.RecipeDeleteView.as_view(), name='recipe_delete'),
    
    # Suroviny
    path('ingredients/', views.IngredientListView.as_view(), name='ingredient_list'),
    path('ingredients/add/', views.IngredientCreateView.as_view(), name='ingredient_add'),
    path('ingredients/edit/<int:pk>/', views.IngredientUpdateView.as_view(), name='ingredient_edit'),
    path('ingredients/delete/<int:pk>/', views.IngredientDeleteView.as_view(), name='ingredient_delete'),
]
