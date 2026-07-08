"""
Testy workflow převodky a integrity dat - fáze 3 oprav.

- C1: generátor čísla převodky (číselné, ne stringové řazení; neresetuje se)
- C2: detail převodky jen pro uživatele s přístupem k jídelně
- C3: dokončení vyžaduje přístup k cílové jídelně
- C4: cancel() vrací jen to, co v meziskladu skutečně je
- C5: záporné/nulové množství položky se odmítne
- C6: vážený průměr nespadne na dělení nulou
"""
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.urls import reverse
from django.utils import timezone

from apps.canteens.models import Canteen, Warehouse
from apps.core.models import Ingredient
from apps.inventory.models import StockItem, StockTransfer, StockTransferItem


@pytest.fixture
def setup(db):
    canteen_from = Canteen.objects.create(name='Růžená')
    canteen_to = Canteen.objects.create(name='Černá hora')
    wh_from = Warehouse.objects.create(name='Sklad Růžená', canteen=canteen_from)
    wh_to = Warehouse.objects.create(name='Sklad Černá hora', canteen=canteen_to)
    ingredient = Ingredient.objects.create(
        name='Mouka', unit='kg', base_unit='kg', recipe_unit='g',
        conversion_factor=Decimal('1000'),
    )
    stock = StockItem.objects.create(
        ingredient=ingredient, warehouse=wh_from,
        quantity=Decimal('10.000'), price=Decimal('25.50'),
    )
    return canteen_from, canteen_to, wh_from, wh_to, ingredient, stock


def _make_transfer(wh_from, wh_to, ingredient, quantity=Decimal('2.000')):
    transfer = StockTransfer.objects.create(
        warehouse_from=wh_from, warehouse_to=wh_to,
    )
    StockTransferItem.objects.create(
        stock_transfer=transfer, ingredient=ingredient,
        quantity=quantity, unit_price_with_vat=Decimal('25.50'),
    )
    return transfer


# --- C1: generátor čísla ---

def test_transfer_number_survives_1000(setup):
    """Stringové řazení by po -0999 vygenerovalo duplicitní číslo."""
    _, _, wh_from, wh_to, ingredient, _ = setup
    prefix = f"PRE-{timezone.localdate().strftime('%Y%m%d')}"
    StockTransfer.objects.create(
        warehouse_from=wh_from, warehouse_to=wh_to,
        transfer_number=f'{prefix}-999',
    )
    StockTransfer.objects.create(
        warehouse_from=wh_from, warehouse_to=wh_to,
        transfer_number=f'{prefix}-1000',
    )

    transfer = StockTransfer.objects.create(warehouse_from=wh_from, warehouse_to=wh_to)

    assert transfer.transfer_number == f'{prefix}-1001'


def test_transfer_number_ignores_unparsable(setup):
    """Neparsovatelné číslo nesmí resetovat číslování na 1 (= kolize)."""
    _, _, wh_from, wh_to, ingredient, _ = setup
    prefix = f"PRE-{timezone.localdate().strftime('%Y%m%d')}"
    StockTransfer.objects.create(
        warehouse_from=wh_from, warehouse_to=wh_to,
        transfer_number=f'{prefix}-005',
    )
    StockTransfer.objects.create(
        warehouse_from=wh_from, warehouse_to=wh_to,
        transfer_number=f'{prefix}-XYZ',
    )

    transfer = StockTransfer.objects.create(warehouse_from=wh_from, warehouse_to=wh_to)

    assert transfer.transfer_number == f'{prefix}-006'


# --- C2/C3: oprávnění ---

def _user_with_canteens(username, canteens):
    user = get_user_model().objects.create_user(username=username, password='x')
    user.profile.canteens.set(canteens)
    return user


def test_detail_hidden_from_foreign_user(client, setup):
    _, _, wh_from, wh_to, ingredient, _ = setup
    transfer = _make_transfer(wh_from, wh_to, ingredient)
    outsider = get_user_model().objects.create_user(username='cizi', password='x')
    client.force_login(outsider)

    response = client.get(reverse('inventory:stock_transfer_detail', args=[transfer.pk]))

    assert response.status_code == 404


def test_complete_requires_target_canteen_access(client, setup):
    """Uživatel jen se zdrojovou jídelnou nesmí naskladnit do cizího cíle."""
    canteen_from, _, wh_from, wh_to, ingredient, _ = setup
    transfer = _make_transfer(wh_from, wh_to, ingredient)
    transfer.start_transfer()
    source_only = _user_with_canteens('zdrojovy', [canteen_from])
    client.force_login(source_only)

    response = client.post(reverse('inventory:stock_transfer_complete', args=[transfer.pk]))

    transfer.refresh_from_db()
    assert transfer.status == 'IN_TRANSIT'  # nedokončeno


# --- C4: cancel vrací jen to, co v meziskladu je ---

def test_cancel_does_not_inflate_source_when_transit_missing(setup):
    canteen_from, _, wh_from, wh_to, ingredient, stock = setup
    transfer = _make_transfer(wh_from, wh_to, ingredient, quantity=Decimal('4.000'))
    transfer.start_transfer()
    stock.refresh_from_db()
    assert stock.quantity == Decimal('6.000')

    # Simulace: mezisklad mezitím někdo vyprázdnil
    transit = canteen_from.get_or_create_transit_warehouse()
    StockItem.objects.filter(warehouse=transit).delete()

    transfer.cancel()

    stock.refresh_from_db()
    # Zboží v meziskladu nebylo, do zdroje se nesmí nic přičíst
    assert stock.quantity == Decimal('6.000')
    assert transfer.status == 'CANCELLED'


def test_cancel_returns_goods_from_transit(setup):
    canteen_from, _, wh_from, wh_to, ingredient, stock = setup
    transfer = _make_transfer(wh_from, wh_to, ingredient, quantity=Decimal('4.000'))
    transfer.start_transfer()

    transfer.cancel()

    stock.refresh_from_db()
    assert stock.quantity == Decimal('10.000')
    transit = canteen_from.get_or_create_transit_warehouse()
    transit_stock = StockItem.objects.get(warehouse=transit, ingredient=ingredient)
    assert transit_stock.quantity == Decimal('0.000')


# --- C5: validace množství ---

def test_negative_quantity_rejected_by_model_validation(setup):
    _, _, wh_from, wh_to, ingredient, _ = setup
    transfer = StockTransfer.objects.create(warehouse_from=wh_from, warehouse_to=wh_to)
    item = StockTransferItem(
        stock_transfer=transfer, ingredient=ingredient,
        quantity=Decimal('-1.000'), unit_price_with_vat=Decimal('10.00'),
    )
    with pytest.raises(ValidationError):
        item.full_clean()


# --- C6: vážený průměr bez dělení nulou ---

def test_complete_with_negative_target_stock_does_not_crash(setup):
    """Záporný zůstatek v cíli: součet může vyjít 0, průměr nelze spočítat."""
    _, _, wh_from, wh_to, ingredient, _ = setup
    StockItem.objects.create(
        ingredient=ingredient, warehouse=wh_to,
        quantity=Decimal('-2.000'), price=Decimal('30.00'),
    )
    transfer = _make_transfer(wh_from, wh_to, ingredient, quantity=Decimal('2.000'))

    transfer.start_and_complete()

    target = StockItem.objects.get(ingredient=ingredient, warehouse=wh_to)
    assert target.quantity == Decimal('0.000')
    # Průměrovat nešlo - převzata cena položky
    assert target.price == Decimal('25.50')
    assert transfer.status == 'COMPLETED'
