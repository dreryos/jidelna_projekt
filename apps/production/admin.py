from django.contrib import admin
from .models import ProductionOrder, PickingList, MenuPlan

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

@admin.register(MenuPlan)
class MenuPlanAdmin(admin.ModelAdmin):
    list_display = ('name', 'canteen', 'date_from', 'date_to', 'get_days_count', 'get_total_orders')
    list_filter = ('canteen', 'date_from', 'date_to')
    search_fields = ('name',)
    autocomplete_fields = ['canteen']
    
    fieldsets = (
        (None, {
            'fields': ('name', 'canteen', 'date_from', 'date_to')
        }),
        ('Výchozí počty porcí', {
            'fields': ('default_portions_adult', 'default_portions_child'),
        }),
    )

@admin.register(ProductionOrder)
class ProductionOrderAdmin(admin.ModelAdmin):
    inlines = [PickingListInline]
    list_display = ('recipe', 'canteen', 'date', 'total_portions', 'portion_coefficient', 'created_at')
    list_filter = ('canteen', 'date', 'menu_plan')
    autocomplete_fields = ['recipe', 'canteen', 'menu_plan']
    readonly_fields = ('price_per_portion', 'total_price')
    
    fieldsets = (
        (None, {
            'fields': ('menu_plan', 'recipe', 'canteen', 'date')
        }),
        ('Počty porcí', {
            'fields': ('portions_adult', 'portions_child', 'portion_coefficient'),
            'description': 'Koeficient porce: 1.0 = normální porce, 0.5 = poloviční, 1.5 = větší'
        }),
        ('Vypočtené ceny', {
            'fields': ('price_per_portion', 'total_price'),
        }),
    )

    def get_queryset(self, request):
        # Optimalizace pro načítání souvisejících objektů
        return super().get_queryset(request).select_related('recipe', 'canteen', 'menu_plan')

    def price_per_portion(self, obj):
        if obj.recipe and obj.canteen:
            prices = obj.recipe.calculate_portion_price(
                obj.canteen, 
                portions=1,
                portion_coefficient=float(obj.portion_coefficient)
            )
            return f"{prices['per_portion']} Kč"
        return "N/A"
    price_per_portion.short_description = "Cena/porce"

    def total_price(self, obj):
        if obj.recipe and obj.canteen:
            prices = obj.recipe.calculate_portion_price(
                obj.canteen,
                portions=obj.total_portions,
                portion_coefficient=float(obj.portion_coefficient)
            )
            return f"{prices['total']} Kč"
        return "N/A"
    total_price.short_description = "Celková cena výroby"

# admin.site.register(PickingList)
