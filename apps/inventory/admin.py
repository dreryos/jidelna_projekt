from django.contrib import admin
from decimal import Decimal
from .models import (
    StockItem, IngredientPriceHistory, GoodsReceipt, GoodsReceiptItem,
    InventoryVerification, InventoryVerificationItem
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
