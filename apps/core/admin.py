from django.contrib import admin
from .models import Recipe, Ingredient, RecipeIngredient

# Tento admin modul poskytuje jednoduché rozhraní pro správu receptů a surovin.
# Inline `RecipeIngredientInline` umožňuje editovat normy přímo v editaci receptu.

class RecipeIngredientInline(admin.TabularInline):
    model = RecipeIngredient
    extra = 1  # Počet prázdných řádků pro přidání nových surovin

@admin.register(Recipe)
class RecipeAdmin(admin.ModelAdmin):
    inlines = [RecipeIngredientInline]
    list_display = ('name',)
    search_fields = ('name',)

@admin.register(Ingredient)
class IngredientAdmin(admin.ModelAdmin):
    list_display = ('name', 'unit')
    search_fields = ('name',)

# Samostatná registrace RecipeIngredient je volitelná, protože je již v RecipeAdmin
# admin.site.register(RecipeIngredient)
