from django.urls import path
from . import views

app_name = 'analytics'

urlpatterns = [
    # Seznam jídelníčků s průměrnými náklady
    path('', views.menu_analytics_list, name='menu_analytics_list'),
    
    # Detail jídelníčku s náklady jednotlivých jídel
    path('menu/<int:menu_id>/', views.menu_detail_analytics, name='menu_detail_analytics'),
    
    # Analýza nákladů receptů napříč časem
    path('recipe-costs/', views.recipe_cost_analysis, name='recipe_cost_analysis'),
    path('recipe-costs/<int:recipe_id>/', views.recipe_cost_detail, name='recipe_cost_detail'),
    
    # Analytika odepisování zboží
    path('write-offs/', views.write_off_analytics, name='write_off_analytics'),
]
