from django.contrib import admin
from .models import ProductionOrder, PickingList, MenuPlan, MenuPlanCoefficient, PickingListDocument, MenuTemplate

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


class MenuPlanCoefficientInline(admin.TabularInline):
    model = MenuPlanCoefficient
    fields = ('name', 'coefficient', 'order')
    extra = 1
    ordering = ['order']


@admin.register(MenuPlan)
class MenuPlanAdmin(admin.ModelAdmin):
    inlines = [MenuPlanCoefficientInline]
    list_display = ('name', 'canteen', 'date_from', 'date_to', 'get_days_count', 'get_total_orders')
    list_filter = ('canteen', 'date_from', 'date_to')
    search_fields = ('name',)
    autocomplete_fields = ['canteen']
    
    fieldsets = (
        (None, {
            'fields': ('name', 'canteen', 'date_from', 'date_to')
        }),
    )

@admin.register(ProductionOrder)
class ProductionOrderAdmin(admin.ModelAdmin):
    inlines = [PickingListInline]
    list_display = ('recipe', 'meal_type', 'canteen', 'date', 'total_portions', 'created_at')
    list_filter = ('meal_type', 'canteen', 'date', 'menu_plan')
    autocomplete_fields = ['recipe', 'canteen', 'menu_plan']
    readonly_fields = ('price_per_portion', 'total_price')
    
    fieldsets = (
        (None, {
            'fields': ('menu_plan', 'recipe', 'canteen', 'date', 'meal_type')
        }),
        ('Vypočtené ceny', {
            'fields': ('price_per_portion', 'total_price'),
            'description': 'Ceny jsou počítány ze všech variant porcí'
        }),
    )

    def get_queryset(self, request):
        # Optimalizace pro načítání souvisejících objektů
        return super().get_queryset(request).select_related('recipe', 'canteen', 'menu_plan')

    def price_per_portion(self, obj):
        if obj.recipe and obj.canteen:
            # Průměrná cena na porci (bez koeficientů)
            prices = obj.recipe.calculate_portion_price(
                obj.canteen, 
                portions=1,
                portion_coefficient=1.0
            )
            return f"{prices['per_portion']} Kč"
        return "N/A"
    price_per_portion.short_description = "Cena/porce"

    def total_price(self, obj):
        if obj.recipe and obj.canteen:
            # Celková cena ze všech efektivních porcí (s koeficienty)
            prices = obj.recipe.calculate_portion_price(
                obj.canteen,
                portions=int(obj.total_effective_portions),
                portion_coefficient=1.0
            )
            return f"{prices['total']} Kč"
        return "N/A"
    total_price.short_description = "Celková cena výroby"


@admin.register(PickingListDocument)
class PickingListDocumentAdmin(admin.ModelAdmin):
    list_display = ('name', 'canteen', 'date_from', 'date_to', 'created_at', 'created_by')
    list_filter = ('canteen', 'date_from', 'created_at')
    search_fields = ('name', 'canteen__name')
    readonly_fields = ('created_at', 'created_by')
    autocomplete_fields = ['canteen']
    
    fieldsets = (
        (None, {
            'fields': ('name', 'canteen', 'date_from', 'date_to')
        }),
        ('Metadata', {
            'fields': ('created_at', 'created_by'),
            'classes': ('collapse',)
        }),
    )
    
    def save_model(self, request, obj, form, change):
        if not change:  # Pokud je nový objekt
            obj.created_by = request.user
        super().save_model(request, obj, form, change)


@admin.register(MenuTemplate)
class MenuTemplateAdmin(admin.ModelAdmin):
    """Admin pro šablony jídelníčků"""
    list_display = ('name', 'created_at', 'updated_at')
    search_fields = ('name', 'description')
    readonly_fields = ('created_at', 'updated_at')
    
    fieldsets = (
        ('Základní informace', {
            'fields': ('name', 'description')
        }),
        ('XML obsah', {
            'fields': ('xml_content',)
        }),
        ('Metadata', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

# admin.site.register(PickingList)
