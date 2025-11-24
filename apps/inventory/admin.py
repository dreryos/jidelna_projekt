from django.contrib import admin
from .models import StockItem, IngredientPriceHistory

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
