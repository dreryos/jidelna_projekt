#!/usr/bin/env python
import os
import django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'spiz_project.settings')
django.setup()

from apps.inventory.models import StockItem, Ingredient, Warehouse
from apps.canteens.models import Canteen
from apps.inventory.forms import StockItemForm
from decimal import Decimal

# Vytvořit testovací data
canteen = Canteen.objects.create(name='Test')
warehouse = Warehouse.objects.create(name='Sklad', canteen=canteen)
ingredient = Ingredient.objects.create(name='Test', base_unit='kg')
stock = StockItem.objects.create(
    ingredient=ingredient,
    warehouse=warehouse,
    quantity=Decimal('10'),
    price=Decimal('30'),
    vat_rate=Decimal('12'),
    price_without_vat=Decimal('26.79')
)

print(f'Před: vat_rate={stock.vat_rate}, price_without_vat={stock.price_without_vat}')

# Pokus změnit přes form
data = {
    'ingredient': ingredient.pk,
    'warehouse': warehouse.pk,
    'quantity': '15',
    'quantity_blocked': '0',
    'price': '35',
    'vat_rate': '0',  # Pokus změnit readonly
    'price_without_vat': '35'  # Pokus změnit readonly
}

form = StockItemForm(data, instance=stock)
print(f'\nForm valid: {form.is_valid()}')
if not form.is_valid():
    print(f'Errors: {form.errors}')
print(f'Changed data: {form.changed_data}')
print(f'Has _original_vat_rate: {hasattr(form, "_original_vat_rate")}')
if hasattr(form, '_original_vat_rate'):
    print(f'Original vat_rate: {form._original_vat_rate}')

saved = form.save()
print(f'\nPo save(): vat_rate={saved.vat_rate}, price_without_vat={saved.price_without_vat}')

saved.refresh_from_db()
print(f'Po refresh: vat_rate={saved.vat_rate}, price_without_vat={saved.price_without_vat}')

# Kontrola v DB
db_stock = StockItem.objects.get(pk=stock.pk)
print(f'Z DB: vat_rate={db_stock.vat_rate}, price_without_vat={db_stock.price_without_vat}')
