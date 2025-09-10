from django.contrib import admin
from .models import ProductionOrder, PickingList

# Tento admin modul umožňuje správu výrobních příkazů a zobrazení souvisejících výdejek.
# Výpočty cen používají metodu `calculate_portion_price` z modelu Recipe.

class PickingListInline(admin.TabularInline):
    model = PickingList
    fields = ('ingredient', 'warehouse', 'quantity_planned', 'quantity_actual', 'status')
    readonly_fields = ('ingredient', 'quantity_planned')
    autocomplete_fields = ['warehouse']
    extra = 0
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False

@admin.register(ProductionOrder)
class ProductionOrderAdmin(admin.ModelAdmin):
    inlines = [PickingListInline]
    list_display = ('recipe', 'canteen', 'date', 'created_at')
    list_filter = ('canteen', 'date')
    autocomplete_fields = ['recipe', 'canteen']
    readonly_fields = ('price_per_adult_portion', 'price_per_child_portion', 'total_price')
    
    fieldsets = (
        (None, {
            'fields': ('recipe', 'canteen', 'date', 'portions_adult', 'portions_child')
        }),
        ('Vypočtené ceny', {
            'fields': ('price_per_adult_portion', 'price_per_child_portion', 'total_price'),
        }),
    )

    def get_queryset(self, request):
        # Optimalizace pro načítání souvisejících objektů
        return super().get_queryset(request).select_related('recipe', 'canteen')

    def price_per_adult_portion(self, obj):
        if obj.recipe and obj.canteen:
            prices = obj.recipe.calculate_portion_price(obj.canteen)
            return f"{prices['adult']} Kč"
        return "N/A"
    price_per_adult_portion.short_description = "Cena/dospělá porce"

    def price_per_child_portion(self, obj):
        if obj.recipe and obj.canteen:
            prices = obj.recipe.calculate_portion_price(obj.canteen)
            return f"{prices['child']} Kč"
        return "N/A"
    price_per_child_portion.short_description = "Cena/dětská porce"

    def total_price(self, obj):
        if obj.recipe and obj.canteen:
            prices = obj.recipe.calculate_portion_price(obj.canteen)
            total = (prices['adult'] * obj.portions_adult) + (prices['child'] * obj.portions_child)
            return f"{round(total, 2)} Kč"
        return "N/A"
    total_price.short_description = "Celková cena výroby"

# admin.site.register(PickingList)
