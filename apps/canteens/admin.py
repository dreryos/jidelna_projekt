from django.contrib import admin
from .models import Canteen, Warehouse

class WarehouseInline(admin.TabularInline):
    model = Warehouse
    extra = 1

@admin.register(Canteen)
class CanteenAdmin(admin.ModelAdmin):
    inlines = [WarehouseInline]
    list_display = ('name', 'address')
    search_fields = ('name',)

@admin.register(Warehouse)
class WarehouseAdmin(admin.ModelAdmin):
    list_display = ('name', 'canteen')
    search_fields = ('name', 'canteen__name')
