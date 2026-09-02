"""
Testy přesnosti cen ve skladu.

Ceny se ukládají na šest desetinných míst. Bez toho by surovina vedená
v gramech přišla zaokrouhlením o procenta hodnoty: 54,90 Kč/kg je
0,0549 Kč/g, což se na dvě desetinná místa uloží jako 0,05.

Uživateli se pořád zobrazují dvě místa – ukládaná přesnost a zobrazovaná
přesnost jsou dvě různé věci.
"""
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from apps.canteens.models import Canteen, Warehouse
from apps.core.models import Ingredient
from apps.inventory.forms import PriceInput
from apps.inventory.models import (
    GoodsReceipt, GoodsReceiptItem, IngredientPriceHistory, StockItem,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def sklad():
    canteen = Canteen.objects.create(name='Jídelna')
    return Warehouse.objects.create(name='Sklad', canteen=canteen)


@pytest.fixture
def mouka():
    return Ingredient.objects.create(name='Mouka', unit='g', base_unit='g')


@pytest.fixture
def prijemka(sklad):
    return GoodsReceipt.objects.create(
        warehouse=sklad, receipt_number='DL1',
        created_by=get_user_model().objects.create_user('skladnik-h'),
    )


# --- Uložená přesnost ---

def test_cena_za_gram_se_ulozi_presne(prijemka, sklad, mouka):
    """54,90 Kč/kg je 0,0549 Kč/g. Na dvě místa by z toho bylo 0,05."""
    item = GoodsReceiptItem.objects.create(
        goods_receipt=prijemka, ingredient=mouka, warehouse=sklad,
        quantity=Decimal('2000'), price_without_vat=Decimal('0.049'),
        vat_rate=Decimal('12'), vat_amount=Decimal('0.0059'),
        price=Decimal('0.0549'), source_unit='kg',
        source_quantity=Decimal('2'), unit_factor=Decimal('1000'),
    )

    item.refresh_from_db()
    assert item.price == Decimal('0.0549')
    # Celková cena řádku sedí s dokladem: 2 kg po 54,90 Kč.
    assert item.quantity * item.price == Decimal('109.8000')


def test_presnost_prezije_i_naskladneni(prijemka, sklad, mouka):
    """Potvrzení příjemky přenáší cenu do skladu i do historie."""
    GoodsReceiptItem.objects.create(
        goods_receipt=prijemka, ingredient=mouka, warehouse=sklad,
        quantity=Decimal('2000'), price_without_vat=Decimal('0.049'),
        vat_rate=Decimal('12'), vat_amount=Decimal('0.0059'),
        price=Decimal('0.0549'),
    )

    prijemka.confirm()

    assert StockItem.objects.get(ingredient=mouka).price == Decimal('0.0549')
    assert IngredientPriceHistory.objects.filter(
        ingredient=mouka, price=Decimal('0.0549'),
    ).exists()


def test_levne_sypke_zbozi_v_gramech(prijemka, sklad):
    """Brambory za 8 Kč/kg dají 0,008 Kč/g – na dvě místa by zbylo 0,01."""
    brambory = Ingredient.objects.create(name='Brambory', unit='g', base_unit='g')
    item = GoodsReceiptItem.objects.create(
        goods_receipt=prijemka, ingredient=brambory, warehouse=sklad,
        quantity=Decimal('25000'), price_without_vat=Decimal('0.00714'),
        vat_rate=Decimal('12'), price=Decimal('0.008'),
    )

    item.refresh_from_db()
    assert item.price == Decimal('0.008')
    assert item.quantity * item.price == Decimal('200.00000')


def test_bezna_cena_v_kilech_zustava_citelna(prijemka, sklad):
    """Rozšíření nesmí rozbít běžný případ."""
    rajce = Ingredient.objects.create(name='Rajče', unit='kg', base_unit='kg')
    item = GoodsReceiptItem.objects.create(
        goods_receipt=prijemka, ingredient=rajce, warehouse=sklad,
        quantity=Decimal('6.7'), price_without_vat=Decimal('54.90'),
        vat_rate=Decimal('12'), price=Decimal('61.49'),
    )

    item.refresh_from_db()
    assert item.price == Decimal('61.49')


def test_nejdrazsi_polozka_se_vejde():
    """max_digits=12 při šesti desetinných místech nechává šest míst vlevo."""
    field = StockItem._meta.get_field('price')

    assert (field.max_digits, field.decimal_places) == (12, 6)
    # Nejdražší položka v ostré databázi stojí 3 140 Kč.
    assert field.max_digits - field.decimal_places == 6


# --- Zobrazení ---

def test_formular_ukazuje_plnou_hodnotu():
    """
    Kdyby formulář zobrazil zaokrouhlenou cenu, stačilo by příjemku otevřít
    a uložit beze změny a přesnost by byla pryč.
    """
    assert PriceInput().format_value(Decimal('0.054900')) == '0.0549'


@pytest.mark.parametrize('hodnota,ocekavano', [
    (Decimal('54.900000'), '54.9'),
    (Decimal('54.90'), '54.9'),
    (Decimal('100.000000'), '100'),
    (Decimal('0'), '0'),
    (None, ''),
    ('', ''),
])
def test_formular_orezava_koncove_nuly(hodnota, ocekavano):
    """Kdo zadává haléře, nemá koukat na „54,900000"."""
    assert PriceInput().format_value(hodnota) == ocekavano


def test_seznam_skladu_ukazuje_dve_mista(client, sklad, mouka):
    """Uložená přesnost je šest míst, zobrazená dvě."""
    user = get_user_model().objects.create_superuser('skladnik-i', password='tajne')
    client.force_login(user)
    StockItem.objects.create(
        ingredient=mouka, warehouse=sklad, quantity=Decimal('2000'),
        price=Decimal('0.0549'), vat_rate=Decimal('12'),
        price_without_vat=Decimal('0.049'),
    )

    obsah = client.get(reverse('inventory:stock_list')).content.decode()

    assert '0,05' in obsah
    assert '0,0549' not in obsah


def test_prevod_kil_na_gramy_uz_neztraci_presnost(client, sklad, mouka):
    """
    Regrese k důvodu, proč se pole rozšiřovala: doklad na 2 kg mouky
    po 54,90 Kč musí po přepočtu na gramy sedět na haléře.
    """
    from apps.inventory.units import convert_line

    mnozstvi, cena = convert_line(Decimal('2'), Decimal('54.90'), Decimal('1000'))

    assert mnozstvi == Decimal('2000')
    assert cena == Decimal('0.054900')
    # Celková cena řádku se převodem změnit nesmí.
    assert mnozstvi * cena == Decimal('54.90') * Decimal('2')


def test_stara_presnost_by_ukrojila_procenta():
    """Ukazuje, o co šlo: na dvě desetinná místa je chyba přes devět procent."""
    presna = Decimal('54.90') / Decimal('1000')
    stara = presna.quantize(Decimal('0.01'))

    assert stara == Decimal('0.05')
    assert (presna - stara) / presna > Decimal('0.08')
