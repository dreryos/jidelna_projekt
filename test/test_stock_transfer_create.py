"""
Testy vytváření převodky (StockTransferCreateView) - fáze 1 oprav.

Pokrývají chyby, kvůli kterým se formulář cyklil v chybách a nezapisoval data:
- A1: nevalidní formset nesmí uložit sirotčí hlavičku převodky
- A2: readonly cena se doplňuje autoritativně na serveru (prázdná/podvržená hodnota)
- min_num: převodka bez položek se odmítne
"""
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from apps.canteens.models import Canteen, Warehouse
from apps.core.models import Ingredient
from apps.inventory.models import StockItem, StockTransfer, StockTransferItem


@pytest.fixture
def user(db):
    return get_user_model().objects.create_superuser(username='zuzka', password='x')


@pytest.fixture
def warehouses(db):
    canteen_from = Canteen.objects.create(name='Růžená')
    canteen_to = Canteen.objects.create(name='Černá hora')
    wh_from = Warehouse.objects.create(name='Sklad Růžená', canteen=canteen_from)
    wh_to = Warehouse.objects.create(name='Sklad Černá hora', canteen=canteen_to)
    return wh_from, wh_to


@pytest.fixture
def ingredient(db):
    return Ingredient.objects.create(
        name='Mouka', unit='kg', base_unit='kg', recipe_unit='g',
        conversion_factor=Decimal('1000'),
    )


@pytest.fixture
def stock_item(warehouses, ingredient):
    wh_from, _ = warehouses
    return StockItem.objects.create(
        ingredient=ingredient,
        warehouse=wh_from,
        quantity=Decimal('10.000'),
        price=Decimal('25.50'),
    )


def _post_data(wh_from, wh_to, rows):
    """POST data pro StockTransferForm + inline formset položek."""
    data = {
        'warehouse_from': str(wh_from.pk),
        'warehouse_to': str(wh_to.pk),
        'transfer_date': '2026-07-08',
        'notes': '',
        'items-TOTAL_FORMS': str(len(rows)),
        'items-INITIAL_FORMS': '0',
        'items-MIN_NUM_FORMS': '1',
        'items-MAX_NUM_FORMS': '100',
    }
    for i, row in enumerate(rows):
        data[f'items-{i}-id'] = ''
        data[f'items-{i}-ingredient'] = str(row.get('ingredient', ''))
        data[f'items-{i}-quantity'] = str(row.get('quantity', ''))
        data[f'items-{i}-unit_price_with_vat'] = str(row.get('price', ''))
    return data


@pytest.fixture
def logged_client(client, user):
    client.force_login(user)
    return client


def test_valid_submit_creates_transfer_and_items(logged_client, warehouses, ingredient, stock_item):
    wh_from, wh_to = warehouses
    data = _post_data(wh_from, wh_to, [
        {'ingredient': ingredient.pk, 'quantity': '2.000', 'price': ''},
    ])

    response = logged_client.post(reverse('inventory:stock_transfer_create'), data)

    assert response.status_code == 302
    transfer = StockTransfer.objects.get()
    item = transfer.items.get()
    assert item.ingredient == ingredient
    assert item.quantity == Decimal('2.000')
    # Cena doplněna serverem ze skladu, přestože pole přišlo prázdné (readonly widget)
    assert item.unit_price_with_vat == Decimal('25.50')


def test_submitted_price_is_overridden_by_stock_price(logged_client, warehouses, ingredient, stock_item):
    """Server je pro cenu autoritativní - podvržená hodnota z readonly pole se ignoruje."""
    wh_from, wh_to = warehouses
    data = _post_data(wh_from, wh_to, [
        {'ingredient': ingredient.pk, 'quantity': '1.000', 'price': '999.99'},
    ])

    response = logged_client.post(reverse('inventory:stock_transfer_create'), data)

    assert response.status_code == 302
    item = StockTransferItem.objects.get()
    assert item.unit_price_with_vat == Decimal('25.50')


def test_invalid_quantity_does_not_create_orphan_transfer(logged_client, warehouses, ingredient, stock_item):
    """Požadavek nad dostupné množství: chyba formuláře, ale žádná sirotčí hlavička v DB."""
    wh_from, wh_to = warehouses
    data = _post_data(wh_from, wh_to, [
        {'ingredient': ingredient.pk, 'quantity': '999.000', 'price': ''},
    ])

    response = logged_client.post(reverse('inventory:stock_transfer_create'), data)

    assert response.status_code == 200
    assert StockTransfer.objects.count() == 0
    assert StockTransferItem.objects.count() == 0
    assert 'Nedostatečné množství' in response.content.decode()


def test_ingredient_not_in_warehouse_does_not_create_orphan(logged_client, warehouses, stock_item):
    wh_from, wh_to = warehouses
    other = Ingredient.objects.create(
        name='Cukr', unit='kg', base_unit='kg', recipe_unit='g',
        conversion_factor=Decimal('1000'),
    )
    data = _post_data(wh_from, wh_to, [
        {'ingredient': other.pk, 'quantity': '1.000', 'price': ''},
    ])

    response = logged_client.post(reverse('inventory:stock_transfer_create'), data)

    assert response.status_code == 200
    assert StockTransfer.objects.count() == 0
    assert 'není na skladu' in response.content.decode()


def test_empty_formset_is_rejected(logged_client, warehouses, stock_item):
    """Převodka bez položek se nesmí vytvořit (min_num=1)."""
    wh_from, wh_to = warehouses
    data = _post_data(wh_from, wh_to, [
        {'ingredient': '', 'quantity': '', 'price': ''},
    ])

    response = logged_client.post(reverse('inventory:stock_transfer_create'), data)

    assert response.status_code == 200
    assert StockTransfer.objects.count() == 0


def test_same_warehouse_rejected_without_orphan(logged_client, warehouses, ingredient, stock_item):
    wh_from, _ = warehouses
    data = _post_data(wh_from, wh_from, [
        {'ingredient': ingredient.pk, 'quantity': '1.000', 'price': ''},
    ])

    response = logged_client.post(reverse('inventory:stock_transfer_create'), data)

    assert response.status_code == 200
    assert StockTransfer.objects.count() == 0
