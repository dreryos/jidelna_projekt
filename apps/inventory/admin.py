from django.contrib import admin
from .models import StockItem

@admin.register(StockItem)
class StockItemAdmin(admin.ModelAdmin):
    list_display = ('ingredient', 'warehouse', 'quantity', 'price')
    list_filter = ('warehouse',)
    search_fields = ('ingredient__name', 'warehouse__name')
    autocomplete_fields = ['ingredient', 'warehouse']
