from django.contrib import admin
from .models import ProductionOrder, PickingList

class PickingListInline(admin.TabularInline):
    model = PickingList
    extra = 0  # Položky se budou generovat automaticky, nechceme prázdné řádky
    readonly_fields = ('ingredient', 'quantity_planned') # Tyto pole se vypočítají
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False

@admin.register(ProductionOrder)
class ProductionOrderAdmin(admin.ModelAdmin):
    inlines = [PickingListInline]
    list_display = ('recipe', 'canteen', 'date', 'created_at')
    list_filter = ('canteen', 'date')
    autocomplete_fields = ['recipe', 'canteen']

# admin.site.register(PickingList)
