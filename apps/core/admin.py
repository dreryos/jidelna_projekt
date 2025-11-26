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
    list_display = ('code', 'name', 'category')
    list_filter = ('category',)
    search_fields = ('code', 'name')
    fields = ('category', 'name', 'description', 'code')
    readonly_fields = ('code',)
    
    def get_readonly_fields(self, request, obj=None):
        """Kód je read-only pouze u existujících objektů"""
        if obj:  # Editace existujícího receptu
            return self.readonly_fields
        return []  # Při vytváření nového receptu není kód zobrazený

@admin.register(Ingredient)
class IngredientAdmin(admin.ModelAdmin):
    list_display = ('name', 'base_unit', 'recipe_unit', 'conversion_factor')
    search_fields = ('name',)
    fields = ('name', 'unit', 'base_unit', 'recipe_unit', 'conversion_factor')

# Samostatná registrace RecipeIngredient je volitelná, protože je již v RecipeAdmin
# admin.site.register(RecipeIngredient)
