from django.contrib import admin
from django.utils.html import format_html, mark_safe
from .models import (
    ProductionOrder, PickingList, MenuPlan, MenuPlanCoefficient, 
    PickingListDocument, MenuTemplate, ProductionOrderRecipeOverride,
    ProductionOrderIngredientOverride
)

# Tento admin modul umožňuje správu výrobních příkazů a zobrazení souvisejících výdejek.
# Výpočty cen používají metodu `calculate_portion_price` z modelu Recipe.

class PickingListInline(admin.TabularInline):
    model = PickingList
    fields = ('ingredient', 'warehouse', 'quantity_planned', 'quantity_actual', 'status', 'is_customized')
    readonly_fields = ('ingredient', 'quantity_planned', 'is_customized')
    autocomplete_fields = ['warehouse']
    extra = 0
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


class ProductionOrderIngredientOverrideInline(admin.TabularInline):
    model = ProductionOrderIngredientOverride
    fields = ('ingredient', 'quantity_per_portion', 'original_quantity', 'is_added', 'is_removed', 'notes')
    autocomplete_fields = ['ingredient']
    extra = 0
    
    def get_readonly_fields(self, request, obj=None):
        # original_quantity je readonly při editaci
        if obj:
            return ['original_quantity']
        return []


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
    inlines = [ProductionOrderIngredientOverrideInline, PickingListInline]
    list_display = ('recipe', 'meal_type', 'canteen', 'date', 'total_portions', 'customization_indicator', 'selling_vat_rate', 'created_at')
    list_filter = ('meal_type', 'canteen', 'date', 'menu_plan', 'selling_vat_rate')
    search_fields = ('recipe__name', 'canteen__name', 'menu_plan__name')
    autocomplete_fields = ['recipe', 'canteen', 'menu_plan']
    readonly_fields = ('price_per_portion', 'total_price')
    actions = ['reset_ingredient_overrides']
    
    fieldsets = (
        (None, {
            'fields': ('menu_plan', 'recipe', 'canteen', 'date', 'meal_type')
        }),
        ('Prodejní informace', {
            'fields': ('selling_vat_rate',),
            'description': 'DPH sazba pro prodej tohoto jídla (zkopíruje se automaticky z receptu)'
        }),
        ('Vypočtené ceny', {
            'fields': ('price_per_portion', 'total_price'),
            'description': 'Ceny jsou počítány ze všech variant porcí a respektují úpravy ingrediencí'
        }),
    )

    def get_queryset(self, request):
        # Optimalizace pro načítání souvisejících objektů
        return (super().get_queryset(request)
            .select_related('recipe', 'canteen', 'menu_plan')
            .prefetch_related('ingredient_overrides', 'portion_variants'))
    
    def customization_indicator(self, obj):
        """Zobrazí ikonu pokud má jídlo upravené ingredience"""
        if obj.has_overrides:
            return mark_safe(
                '<span title="Upravené ingredience" style="color: orange; font-weight: bold;">✏️</span>'
            )
        return ''
    customization_indicator.short_description = 'Úpravy'
    
    def reset_ingredient_overrides(self, request, queryset):
        """Admin action pro hromadné resetování overrides"""
        count = 0
        for order in queryset:
            if order.has_overrides and not order.has_issued_picking_list():
                # Smazat overrides
                order.ingredient_overrides.all().delete()
                ProductionOrderRecipeOverride.objects.filter(production_order=order).delete()
                
                # Regenerovat výdejku
                order.picking_list_items.all().delete()
                order.generate_picking_list()
                count += 1
        
        self.message_user(request, f'Úpravy byly resetovány u {count} výrobních příkazů.')
    reset_ingredient_overrides.short_description = 'Resetovat úpravy ingrediencí'

    def price_per_portion(self, obj):
        if obj.recipe and obj.canteen:
            # Použijeme nové metody, které respektují overrides
            if obj.has_overrides:
                prices = obj.calculate_selling_price()
                cost_info = f"Náklady: {prices['per_portion']} Kč"
                vat_info = f"<br>S DPH ({prices['vat_rate']}%): {prices['per_portion_with_vat']} Kč"
                warning = "<br><small style='color: orange;'>⚠️ Upravené ingredience</small>"
                return mark_safe(f"{cost_info}{vat_info}{warning}")
            else:
                # Původní výpočet z receptu
                prices = obj.recipe.calculate_portion_price(
                    obj.canteen, 
                    portions=1,
                    portion_coefficient=1.0,
                    vat_rate=obj.selling_vat_rate
                )
                cost_info = f"Náklady: {prices['per_portion']} Kč"
                if 'per_portion_with_vat' in prices:
                    vat_info = f"<br>S DPH ({prices['vat_rate']}%): {prices['per_portion_with_vat']} Kč"
                    return mark_safe(f"{cost_info}{vat_info}")
                return cost_info
        return "N/A"
    price_per_portion.short_description = "Cena/porce"

    def total_price(self, obj):
        if obj.recipe and obj.canteen:
            # Použijeme nové metody, které respektují overrides
            if obj.has_overrides:
                prices = obj.calculate_selling_price()
                cost_info = f"Náklady: {prices['total']} Kč"
                vat_info = f"<br>S DPH ({prices['vat_rate']}%): {prices['total_with_vat']} Kč<br>DPH: {prices['vat_amount']} Kč"
                warning = "<br><small style='color: orange;'>⚠️ Upravené ingredience</small>"
                return mark_safe(f"{cost_info}{vat_info}{warning}")
            else:
                # Původní výpočet z receptu
                prices = obj.recipe.calculate_portion_price(
                    obj.canteen,
                    portions=int(obj.total_effective_portions),
                    portion_coefficient=1.0,
                    vat_rate=obj.selling_vat_rate
                )
                cost_info = f"Náklady: {prices['total']} Kč"
                if 'total_with_vat' in prices:
                    vat_info = f"<br>S DPH ({prices['vat_rate']}%): {prices['total_with_vat']} Kč<br>DPH: {prices['vat_amount']} Kč"
                    return mark_safe(f"{cost_info}{vat_info}")
                return cost_info
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


@admin.register(ProductionOrderRecipeOverride)
class ProductionOrderRecipeOverrideAdmin(admin.ModelAdmin):
    """Admin pro override receptů"""
    list_display = ('production_order', 'is_customized', 'created_at', 'updated_at')
    list_filter = ('is_customized', 'created_at')
    search_fields = ('production_order__recipe__name', 'customization_note')
    readonly_fields = ('created_at', 'updated_at')
    
    fieldsets = (
        (None, {
            'fields': ('production_order', 'is_customized', 'customization_note')
        }),
        ('Metadata', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )


@admin.register(ProductionOrderIngredientOverride)
class ProductionOrderIngredientOverrideAdmin(admin.ModelAdmin):
    """Admin pro override ingrediencí"""
    list_display = ('production_order', 'ingredient', 'quantity_per_portion', 'original_quantity', 'is_added', 'is_removed')
    list_filter = ('is_added', 'is_removed', 'created_at')
    search_fields = ('production_order__recipe__name', 'ingredient__name')
    autocomplete_fields = ['production_order', 'ingredient']
    readonly_fields = ('created_at', 'updated_at')
    
    fieldsets = (
        (None, {
            'fields': ('production_order', 'ingredient')
        }),
        ('Množství', {
            'fields': ('quantity_per_portion', 'original_quantity')
        }),
        ('Typ úpravy', {
            'fields': ('is_added', 'is_removed', 'notes')
        }),
        ('Metadata', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

# admin.site.register(PickingList)
