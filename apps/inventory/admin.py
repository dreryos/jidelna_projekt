from django.contrib import admin
from decimal import Decimal
from .models import (
    StockItem, IngredientPriceHistory, GoodsReceipt, GoodsReceiptItem,
    InventoryVerification, InventoryVerificationItem, StockTransfer, StockTransferItem,
    Supplier, SupplierIngredientTemplate
)
from .forms import VAT_RATE_CHOICES

# Admin pro skladové položky. Zde se nastavuje vyhledávání a filtr podle skladu.
# `autocomplete_fields` zlepšují UX při výběru surovin nebo skladu.

@admin.register(StockItem)
class StockItemAdmin(admin.ModelAdmin):
    list_display = ('ingredient', 'warehouse', 'quantity', 'price')
    list_filter = ('warehouse',)
    search_fields = ('ingredient__name', 'warehouse__name')
    autocomplete_fields = ['ingredient', 'warehouse']


@admin.register(IngredientPriceHistory)
class IngredientPriceHistoryAdmin(admin.ModelAdmin):
    list_display = ('ingredient', 'warehouse', 'price', 'valid_from', 'created_at')
    list_filter = ('warehouse', 'valid_from')
    search_fields = ('ingredient__name', 'warehouse__name')
    autocomplete_fields = ['ingredient', 'warehouse']
    date_hierarchy = 'valid_from'
    readonly_fields = ('created_at',)
    ordering = ('-valid_from',)


class GoodsReceiptItemInline(admin.TabularInline):
    model = GoodsReceiptItem
    extra = 1
    fields = ['ingredient', 'warehouse', 'quantity', 'price_without_vat', 'vat_rate', 'vat_amount', 'price', 'notes']
    readonly_fields = ['vat_amount', 'price']
    autocomplete_fields = ['ingredient', 'warehouse']
    
    def formfield_for_choice_field(self, db_field, request, **kwargs):
        """Nastavení výchozí DPH sazby na 12%"""
        if db_field.name == 'vat_rate':
            kwargs['choices'] = VAT_RATE_CHOICES
            kwargs['initial'] = Decimal('12')
        return super().formfield_for_choice_field(db_field, request, **kwargs)


@admin.register(GoodsReceipt)
class GoodsReceiptAdmin(admin.ModelAdmin):
    list_display = ('receipt_number', 'warehouse', 'receipt_date', 'supplier', 'status', 'created_at', 'created_by')
    list_filter = ('warehouse', 'status', 'receipt_date')
    search_fields = ('receipt_number', 'supplier', 'warehouse__name')
    autocomplete_fields = ['warehouse']
    date_hierarchy = 'receipt_date'
    readonly_fields = ('created_at', 'created_by', 'confirmed_at')
    inlines = [GoodsReceiptItemInline]
    
    def save_model(self, request, obj, form, change):
        if not change:  # Pouze při vytváření
            obj.created_by = request.user
        super().save_model(request, obj, form, change)


@admin.register(GoodsReceiptItem)
class GoodsReceiptItemAdmin(admin.ModelAdmin):
    list_display = ('goods_receipt', 'ingredient', 'quantity', 'price_without_vat', 'vat_rate', 'price', 'total_price')
    list_filter = ('goods_receipt__warehouse', 'vat_rate')
    search_fields = ('ingredient__name', 'goods_receipt__receipt_number')
    autocomplete_fields = ['ingredient', 'goods_receipt']
    readonly_fields = ('vat_amount', 'price', 'total_price')


class InventoryVerificationItemInline(admin.TabularInline):
    model = InventoryVerificationItem
    extra = 0
    fields = ['ingredient', 'system_quantity', 'counted_quantity', 'difference', 'is_newly_found', 'notes']
    readonly_fields = ['system_quantity', 'difference']
    autocomplete_fields = ['ingredient']
    
    def has_add_permission(self, request, obj=None):
        """Přidávání položek možné pouze když je inventura IN_PROGRESS"""
        if obj and obj.status == InventoryVerification.Status.IN_PROGRESS:
            return True
        return False
    
    def has_delete_permission(self, request, obj=None):
        """Mazání položek možné pouze když je inventura IN_PROGRESS"""
        if obj and obj.status == InventoryVerification.Status.IN_PROGRESS:
            return True
        return False


@admin.register(InventoryVerification)
class InventoryVerificationAdmin(admin.ModelAdmin):
    list_display = ('warehouse', 'status', 'started_at', 'started_by', 'completed_at', 'created_by')
    list_filter = ('status', 'warehouse', 'started_at', 'completed_at')
    search_fields = ('warehouse__name', 'started_by__username', 'created_by__username')
    autocomplete_fields = ['warehouse']
    date_hierarchy = 'started_at'
    readonly_fields = ('created_at', 'created_by', 'started_at', 'started_by', 'completed_at', 'completed_by', 'cancelled_at')
    inlines = [InventoryVerificationItemInline]
    
    fieldsets = (
        ('Základní informace', {
            'fields': ('warehouse', 'status', 'notes')
        }),
        ('Audit trail', {
            'fields': ('created_at', 'created_by', 'started_at', 'started_by', 'completed_at', 'completed_by', 'cancelled_at'),
            'classes': ('collapse',)
        }),
    )
    
    def save_model(self, request, obj, form, change):
        if not change:  # Pouze při vytváření
            obj.created_by = request.user
        super().save_model(request, obj, form, change)
    
    def has_delete_permission(self, request, obj=None):
        """Mazání inventury možné pouze když je ve stavu DRAFT nebo CANCELLED"""
        if obj and obj.status in [InventoryVerification.Status.DRAFT, InventoryVerification.Status.CANCELLED]:
            return super().has_delete_permission(request, obj)
        return False


@admin.register(InventoryVerificationItem)
class InventoryVerificationItemAdmin(admin.ModelAdmin):
    list_display = ('verification', 'ingredient', 'system_quantity', 'counted_quantity', 'difference', 'is_newly_found')
    list_filter = ('verification__warehouse', 'is_newly_found', 'verification__status')
    search_fields = ('ingredient__name', 'verification__warehouse__name')
    autocomplete_fields = ['ingredient', 'verification']
    readonly_fields = ('system_quantity', 'difference')


class StockTransferItemInline(admin.TabularInline):
    model = StockTransferItem
    extra = 1
    fields = ['ingredient', 'quantity', 'unit_price_with_vat']
    autocomplete_fields = ['ingredient']
    
    def has_add_permission(self, request, obj=None):
        """Přidávání položek možné pouze ve stavu DRAFT"""
        if obj and obj.status == 'DRAFT':
            return True
        return not obj  # Povolit při vytváření nového objektu
    
    def has_change_permission(self, request, obj=None):
        """Editace položek možná pouze ve stavu DRAFT"""
        if obj and obj.status == 'DRAFT':
            return True
        return not obj
    
    def has_delete_permission(self, request, obj=None):
        """Mazání položek možné pouze ve stavu DRAFT"""
        if obj and obj.status == 'DRAFT':
            return True
        return False


@admin.register(StockTransfer)
class StockTransferAdmin(admin.ModelAdmin):
    list_display = ('transfer_number', 'warehouse_from', 'warehouse_to', 'transfer_date', 'status', 'created_at', 'created_by')
    list_filter = ('status', 'warehouse_from', 'warehouse_to', 'transfer_date')
    search_fields = ('transfer_number', 'warehouse_from__name', 'warehouse_to__name')
    autocomplete_fields = ['warehouse_from', 'warehouse_to']
    date_hierarchy = 'transfer_date'
    readonly_fields = ('transfer_number', 'created_at', 'created_by', 'started_at', 'completed_at')
    inlines = [StockTransferItemInline]
    
    fieldsets = (
        ('Základní informace', {
            'fields': ('transfer_number', 'warehouse_from', 'warehouse_to', 'transfer_date', 'status', 'notes')
        }),
        ('Audit trail', {
            'fields': ('created_at', 'created_by', 'started_at', 'completed_at'),
            'classes': ('collapse',)
        }),
    )
    
    def get_readonly_fields(self, request, obj=None):
        """Dynamické readonly pole podle statusu"""
        readonly = list(self.readonly_fields)
        if obj and obj.status != 'DRAFT':
            # Po zahájení nelze měnit základní údaje
            readonly.extend(['warehouse_from', 'warehouse_to', 'transfer_date', 'status'])
        return readonly
    
    def save_model(self, request, obj, form, change):
        if not change:  # Pouze při vytváření
            obj.created_by = request.user
        super().save_model(request, obj, form, change)
    
    def has_delete_permission(self, request, obj=None):
        """Mazání převodky možné pouze ve stavu DRAFT nebo CANCELLED"""
        if obj and obj.status in ['DRAFT', 'CANCELLED']:
            return super().has_delete_permission(request, obj)
        return not obj  # Povolit při vytváření


@admin.register(StockTransferItem)
class StockTransferItemAdmin(admin.ModelAdmin):
    list_display = ('stock_transfer', 'ingredient', 'quantity', 'unit_price_with_vat', 'get_total_price')
    list_filter = ('stock_transfer__status', 'stock_transfer__warehouse_from', 'stock_transfer__warehouse_to')
    search_fields = ('ingredient__name', 'stock_transfer__transfer_number')
    autocomplete_fields = ['ingredient', 'stock_transfer']
    readonly_fields = ('get_total_price',)
    
    def get_total_price(self, obj):
        """Zobrazí celkovou cenu položky"""
        return obj.get_total_price()
    get_total_price.short_description = 'Celková cena'


# Admin pro dodavatele a šablony surovin
class SupplierIngredientTemplateInline(admin.TabularInline):
    model = SupplierIngredientTemplate
    extra = 0
    fields = ['ingredient', 'default_price_without_vat', 'default_vat_rate', 'sort_order']
    autocomplete_fields = ['ingredient']
    ordering = ['sort_order', 'ingredient__name']
    
    def formfield_for_choice_field(self, db_field, request, **kwargs):
        """Nastavení výchozí DPH sazby na 12%"""
        if db_field.name == 'default_vat_rate':
            kwargs['choices'] = VAT_RATE_CHOICES
            kwargs['initial'] = Decimal('12')
        return super().formfield_for_choice_field(db_field, request, **kwargs)


@admin.register(Supplier)
class SupplierAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug', 'is_active', 'template_count', 'template_cache_key')
    list_filter = ('is_active',)
    search_fields = ('name', 'slug')
    prepopulated_fields = {'slug': ('name',)}
    readonly_fields = ('template_cache_key',)
    inlines = [SupplierIngredientTemplateInline]
    
    fieldsets = (
        ('Základní údaje', {
            'fields': ('name', 'slug', 'is_active')
        }),
        ('Technické údaje', {
            'fields': ('template_cache_key',),
            'classes': ('collapse',)
        }),
    )
    
    def template_count(self, obj):
        """Počet surovin v šabloně"""
        return obj.template_ingredients.count()
    template_count.short_description = 'Počet surovin'
    
    def save_model(self, request, obj, form, change):
        """Při ukládání invaliduje cache"""
        super().save_model(request, obj, form, change)
        # Cache se automaticky invaliduje přes signál


@admin.register(SupplierIngredientTemplate)
class SupplierIngredientTemplateAdmin(admin.ModelAdmin):
    list_display = ('supplier', 'ingredient', 'default_price_without_vat', 'default_vat_rate', 'default_price_with_vat', 'sort_order')
    list_filter = ('supplier', 'default_vat_rate')
    search_fields = ('supplier__name', 'ingredient__name')
    autocomplete_fields = ['supplier', 'ingredient']
    ordering = ['supplier__name', 'sort_order', 'ingredient__name']
    
    fieldsets = (
        ('Základní údaje', {
            'fields': ('supplier', 'ingredient', 'sort_order')
        }),
        ('Výchozí ceny', {
            'fields': ('default_price_without_vat', 'default_vat_rate'),
            'description': 'Přednastavené ceny pro rychlejší vyplnění příjmu zboží'
        }),
    )
    
    def formfield_for_choice_field(self, db_field, request, **kwargs):
        """Nastavení výchozí DPH sazby na 12%"""
        if db_field.name == 'default_vat_rate':
            kwargs['choices'] = VAT_RATE_CHOICES
            kwargs['initial'] = Decimal('12')
        return super().formfield_for_choice_field(db_field, request, **kwargs)
    
    def save_model(self, request, obj, form, change):
        """Při ukládání invaliduje cache dodavatele"""
        super().save_model(request, obj, form, change)
        # Cache se automaticky invaliduje přes signál
