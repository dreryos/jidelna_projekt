from django.contrib import admin
from .models import Recipe, Ingredient, RecipeIngredient, Category

# Tento admin modul poskytuje jednoduché rozhraní pro správu receptů a surovin.
# Inline `RecipeIngredientInline` umožňuje editovat normy přímo v editaci receptu.

class RecipeIngredientInline(admin.TabularInline):
    model = RecipeIngredient
    extra = 1  # Počet prázdných řádků pro přidání nových surovin
    fields = ('ingredient', 'quantity_per_portion', 'notes')

@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ('code', 'name')
    search_fields = ('code', 'name')
    ordering = ('code',)

@admin.register(Recipe)
class RecipeAdmin(admin.ModelAdmin):
    inlines = [RecipeIngredientInline]
    list_display = ('code', 'name', 'category', 'base_portions')
    list_filter = ('category',)
    search_fields = ('code', 'name')
    fields = ('code', 'category', 'name', 'base_portions', 'description')

@admin.register(Ingredient)
class IngredientAdmin(admin.ModelAdmin):
    list_display = ('name', 'base_unit', 'recipe_unit', 'conversion_factor')
    search_fields = ('name',)
    fields = ('name', 'unit', 'base_unit', 'recipe_unit', 'conversion_factor')

# Samostatná registrace RecipeIngredient je volitelná, protože je již v RecipeAdmin
# admin.site.register(RecipeIngredient)
