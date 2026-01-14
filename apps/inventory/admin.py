from django.contrib import admin
from decimal import Decimal
from .models import StockItem, IngredientPriceHistory, GoodsReceipt, GoodsReceiptItem
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
