"""
Testy pojistky proti naskladnění v cizí měrné jednotce.

Kontrola sedí v `GoodsReceipt.confirm()`, protože potvrzení je jediné místo,
kde se mění stav skladu. Kdyby seděla jen v importech, obešlo by ji ruční
založení položky i import, který někdo přidá později.

Obrazovku pro doplnění přepočtu testuje `test_unit_conflict_views.py`.
"""
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError

from apps.canteens.models import Canteen, Warehouse
from apps.core.models import Ingredient
from apps.inventory.models import (
    GoodsReceipt, GoodsReceiptItem, StockItem, Supplier,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def sklad():
    canteen = Canteen.objects.create(name='Jídelna')
    return Warehouse.objects.create(name='Sklad', canteen=canteen)


@pytest.fixture
def uzivatel(client):
    user = get_user_model().objects.create_superuser('skladnik-g', password='tajne')
    client.force_login(user)
    return user


@pytest.fixture
def pekarna():
    # Název „Pekárna" a slug „pekarna" zabírá seed z migrace.
    return Supplier.objects.create(
        name='Pekárna Podlesí', slug='pekarna-guard', ico='25171284',
    )


@pytest.fixture
def rohlik():
    return Ingredient.objects.create(name='Rohlík', unit='ks', base_unit='ks')


@pytest.fixture
def prijemka(sklad, uzivatel, pekarna):
    return GoodsReceipt.objects.create(
        warehouse=sklad, receipt_number='DL1', supplier='Pekárna Podlesí',
        supplier_obj=pekarna, created_by=uzivatel,
    )


def polozka(prijemka, sklad, ingredient, **kwargs):
    hodnoty = {
        'quantity': Decimal('3'), 'price_without_vat': Decimal('120'),
        'vat_rate': Decimal('12'), 'vat_amount': Decimal('14.40'),
        'price': Decimal('134.40'), 'source_name': 'Rohlík karton',
        'source_unit': 'bal', 'source_quantity': Decimal('3'),
        'unit_factor': Decimal('1'),
    }
    hodnoty.update(kwargs)
    return GoodsReceiptItem.objects.create(
        goods_receipt=prijemka, ingredient=ingredient, warehouse=sklad, **hodnoty,
    )


# --- Rozpoznání konfliktu ---

def test_nejednoznacna_jednotka_je_konflikt(prijemka, sklad, rohlik):
    assert polozka(prijemka, sklad, rohlik).has_unit_conflict is True


def test_shodna_jednotka_konflikt_neni(prijemka, sklad, rohlik):
    assert polozka(prijemka, sklad, rohlik, source_unit='ks').has_unit_conflict is False


def test_jednoznacny_prevod_konflikt_neni(prijemka, sklad):
    """Kilogramy na gramy jsou daný poměr, ne konflikt."""
    mouka = Ingredient.objects.create(name='Mouka', unit='g', base_unit='g')

    assert polozka(prijemka, sklad, mouka, source_unit='kg').has_unit_conflict is False


def test_doplneny_prepocet_konflikt_rusi(prijemka, sklad, rohlik):
    item = polozka(prijemka, sklad, rohlik, unit_factor=Decimal('12'))

    assert item.has_unit_conflict is False


def test_rucne_zadana_polozka_konflikt_mit_nemuze(prijemka, sklad, rohlik):
    """Ruční zadání je rovnou ve skladové jednotce, `source_unit` nemá."""
    item = polozka(prijemka, sklad, rohlik, source_unit='', source_quantity=None)

    assert item.has_unit_conflict is False


# --- Blokace potvrzení ---

def test_potvrzeni_s_konfliktem_selze(prijemka, sklad, rohlik):
    polozka(prijemka, sklad, rohlik)

    with pytest.raises(ValidationError, match='měrné jednotky'):
        prijemka.confirm()

    prijemka.refresh_from_db()
    assert prijemka.status == GoodsReceipt.Status.DRAFT
    assert not StockItem.objects.exists()


def test_potvrzeni_po_srovnani_projde(prijemka, sklad, rohlik):
    item = polozka(prijemka, sklad, rohlik)
    item.apply_unit_factor(Decimal('12'))

    prijemka.confirm()

    prijemka.refresh_from_db()
    assert prijemka.status == GoodsReceipt.Status.CONFIRMED
    assert StockItem.objects.get(ingredient=rohlik).quantity == Decimal('36')


def test_seznam_konfliktu_na_prijemce(prijemka, sklad, rohlik):
    polozka(prijemka, sklad, rohlik)
    mouka = Ingredient.objects.create(name='Mouka', unit='g', base_unit='g')
    polozka(prijemka, sklad, mouka, source_unit='kg')

    assert len(prijemka.unit_conflicts) == 1


# --- Přepočet položky ---

def test_prepocet_zachova_celkovou_cenu(prijemka, sklad, rohlik):
    """3 kartony po 134,40 Kč = 403,20 Kč. Po přepočtu 36 kusů po 11,20 Kč."""
    item = polozka(prijemka, sklad, rohlik)
    puvodni_celkem = item.quantity * item.price

    item.apply_unit_factor(Decimal('12'))

    assert item.quantity == Decimal('36')
    assert item.price == Decimal('11.20')
    assert item.quantity * item.price == puvodni_celkem
    assert item.source_quantity == Decimal('3')
    assert item.unit_factor == Decimal('12')


def test_opakovany_prepocet_pocita_z_dokladu_ne_z_prepoctu(prijemka, sklad, rohlik):
    """Oprava překlepu nesmí násobit už jednou přepočtené množství."""
    item = polozka(prijemka, sklad, rohlik)
    item.apply_unit_factor(Decimal('120'))

    item.apply_unit_factor(Decimal('12'))

    assert item.quantity == Decimal('36')


@pytest.mark.parametrize('faktor', [Decimal('0'), Decimal('-3')])
def test_nekladny_prepocet_se_odmitne(prijemka, sklad, rohlik, faktor):
    item = polozka(prijemka, sklad, rohlik)

    with pytest.raises(ValidationError, match='kladné'):
        item.apply_unit_factor(faktor)
