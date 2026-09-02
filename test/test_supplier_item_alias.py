"""
Testy datového modelu pro mapování dodavatelských názvů na suroviny.

Pokrývá:
- IČO dodavatele jako spolehlivý identifikátor na dokladu
- dopočítávání klíčů aliasu z názvu
- pravidlo „buď surovina, nebo nezbožní řádek, ne obojí"
- jedinečnost aliasu v rámci dodavatele i globálně
- přepočet množství na skladovou jednotku
- životnost skenu: fotka se maže, anotace zůstává
"""
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.files.storage import default_storage
from django.db import IntegrityError
from django.test import override_settings

from apps.canteens.models import Canteen, Warehouse
from apps.core.models import Ingredient
from apps.inventory.models import (
    GoodsReceipt, GoodsReceiptScan, Supplier, SupplierItemAlias,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def dodavatel():
    return Supplier.objects.create(name='BOLERO Fruit', slug='bolero', ico='11122233')


@pytest.fixture
def surovina():
    return Ingredient.objects.create(name='Jablko', unit='kg', base_unit='kg')


# --- IČO dodavatele ---

def test_ico_se_ocisti_od_mezer_a_teckek():
    # Slugy 'pekarna' a 'zelinar' zabírá seed z migrace, bereme si vlastní.
    dodavatel = Supplier.objects.create(
        name='Pekárna Podlesí', slug='pekarna-podlesi', ico='777 888 99',
    )

    dodavatel.refresh_from_db()
    assert dodavatel.ico == '77788899'


def test_prazdne_ico_se_uklada_jako_null():
    """Prázdné řetězce by si kolidovaly v unikátním indexu, NULL ne."""
    prvni = Supplier.objects.create(name='A', slug='a')
    druhy = Supplier.objects.create(name='B', slug='b', ico='')

    assert prvni.ico is None and druhy.ico is None


def test_dva_dodavatele_nemohou_sdilet_ico(dodavatel):
    with pytest.raises(IntegrityError):
        Supplier.objects.create(name='Podvrh', slug='podvrh', ico='11122233')


def test_ico_musi_mit_osm_cislic():
    dodavatel = Supplier(name='Krátké', slug='kratke', ico='123')

    with pytest.raises(ValidationError, match='8 číslic'):
        dodavatel.clean()


def test_vyhledani_dodavatele_podle_ica_z_dokladu(dodavatel):
    """OCR vrací IČO i s mezerami nebo s předponou, hledání to musí přežít."""
    assert Supplier.find_by_ico('11122233') == dodavatel
    assert Supplier.find_by_ico('111 222 33') == dodavatel
    assert Supplier.find_by_ico('IČ: 11122233') == dodavatel
    assert Supplier.find_by_ico('') is None
    assert Supplier.find_by_ico('11111111') is None


# --- Alias položky ---

def test_klice_se_dopocitaji_z_nazvu(dodavatel, surovina):
    alias = SupplierItemAlias.objects.create(
        supplier=dodavatel, raw_name='Jablko Gala IT', ingredient=surovina,
    )

    assert alias.raw_key == 'jablko gala it'
    assert alias.core_key == 'jablko gala'


def test_klice_se_prepocitaji_pri_zmene_nazvu(dodavatel, surovina):
    """Klíč se nesmí rozejít s názvem, ze kterého vznikl."""
    alias = SupplierItemAlias.objects.create(
        supplier=dodavatel, raw_name='Jablko Gala IT', ingredient=surovina,
    )

    alias.raw_name = 'Hruška Triumph NL'
    alias.save()

    assert alias.core_key == 'hruska triumph'


def test_nezbozni_radek_nesmi_mit_surovinu(dodavatel, surovina):
    alias = SupplierItemAlias(
        supplier=dodavatel, raw_name='Zaokrouhlení',
        ingredient=surovina, is_ignored=True,
    )

    with pytest.raises(ValidationError, match='nemůže mít přiřazenou surovinu'):
        alias.clean()


def test_alias_musi_mit_surovinu_nebo_byt_nezbozni(dodavatel):
    alias = SupplierItemAlias(supplier=dodavatel, raw_name='Něco')

    with pytest.raises(ValidationError, match='nezbožní řádek'):
        alias.clean()


def test_nezbozni_alias_bez_suroviny_projde(dodavatel):
    alias = SupplierItemAlias(
        supplier=dodavatel, raw_name='Doprava', is_ignored=True,
    )

    alias.clean()
    alias.save()
    assert alias.pk is not None


def test_dodavatel_nemuze_mit_dva_aliasy_stejneho_nazvu(dodavatel, surovina):
    SupplierItemAlias.objects.create(
        supplier=dodavatel, raw_name='Jablko Gala IT', ingredient=surovina,
    )

    with pytest.raises(IntegrityError):
        # Liší se jen diakritikou a velikostí písmen, klíč vyjde stejný.
        SupplierItemAlias.objects.create(
            supplier=dodavatel, raw_name='JABLKO GALA IT', ingredient=surovina,
        )


def test_dva_dodavatele_smi_mit_stejny_nazev(dodavatel, surovina):
    """Každý dodavatel má vlastní jmenný prostor."""
    jiny = Supplier.objects.create(name='Makro', slug='makro')

    SupplierItemAlias.objects.create(
        supplier=dodavatel, raw_name='Jablko Gala IT', ingredient=surovina,
    )
    SupplierItemAlias.objects.create(
        supplier=jiny, raw_name='Jablko Gala IT', ingredient=surovina,
    )

    assert SupplierItemAlias.objects.count() == 2


def test_globalni_alias_je_jedinecny(surovina):
    """Alias bez dodavatele platí pro všechny, takže smí být jen jeden."""
    SupplierItemAlias.objects.create(raw_name='Jablko Gala', ingredient=surovina)

    with pytest.raises(IntegrityError):
        SupplierItemAlias.objects.create(raw_name='Jablko Gala', ingredient=surovina)


def test_zaznam_pouziti(dodavatel, surovina):
    alias = SupplierItemAlias.objects.create(
        supplier=dodavatel, raw_name='Jablko Gala IT', ingredient=surovina,
    )
    assert alias.times_used == 0 and alias.last_used_at is None

    alias.register_use()
    alias.register_use()
    alias.refresh_from_db()

    assert alias.times_used == 2
    assert alias.last_used_at is not None


def test_prepocet_mnozstvi_na_skladovou_jednotku(dodavatel, surovina):
    """Dodavatel fakturuje kartony, sklad vede kusy."""
    alias = SupplierItemAlias.objects.create(
        supplier=dodavatel, raw_name='Rohlík karton', ingredient=surovina,
        unit='bal', unit_factor=Decimal('12'),
    )

    assert alias.convert_quantity(Decimal('3')) == Decimal('36')


def test_vychozi_prepocet_nic_nemeni(dodavatel, surovina):
    alias = SupplierItemAlias.objects.create(
        supplier=dodavatel, raw_name='Jablko Gala IT', ingredient=surovina,
    )

    assert alias.convert_quantity(Decimal('6.7')) == Decimal('6.7')


# --- Sken dokladu ---

@pytest.fixture
def prijemka():
    canteen = Canteen.objects.create(name='Jídelna')
    warehouse = Warehouse.objects.create(name='Sklad', canteen=canteen)
    user = get_user_model().objects.create_user('skladnik')
    return GoodsReceipt.objects.create(
        warehouse=warehouse, receipt_number='DL1', created_by=user,
    )


def test_smazani_fotky_ponecha_anotaci(tmp_path, prijemka):
    with override_settings(MEDIA_ROOT=tmp_path):
        from apps.inventory.ocr.storage import save_scan

        path = save_scan(b'fotka', 'image/jpeg')
        scan = GoodsReceiptScan.objects.create(
            goods_receipt=prijemka, file_path=path,
            annotation={'doklad': {'cislo_dokladu': 'DL1'}},
            markdown='# DL1', ocr_model='mistral-ocr-latest',
        )
        assert scan.has_file is True

        assert scan.delete_file() is True

        scan.refresh_from_db()
        assert scan.has_file is False
        assert scan.file_path == ''
        assert scan.file_deleted_at is not None
        assert not default_storage.exists(path)
        # To podstatné zůstává.
        assert scan.annotation['doklad']['cislo_dokladu'] == 'DL1'
        assert scan.markdown == '# DL1'


def test_opakovane_smazani_fotky_nespadne(tmp_path, prijemka):
    """Potvrzení příjemky se může zopakovat, mazání to musí přežít."""
    with override_settings(MEDIA_ROOT=tmp_path):
        scan = GoodsReceiptScan.objects.create(goods_receipt=prijemka)

        assert scan.delete_file() is False
        assert scan.delete_file() is False


def test_sken_muze_existovat_bez_prijemky():
    """Sken vzniká při nahrání, příjemka až po potvrzení importu."""
    scan = GoodsReceiptScan.objects.create(original_filename='IMG_4821.HEIC')

    assert scan.goods_receipt is None
    assert 'Nedokončený sken' in str(scan)


def test_smazani_prijemky_smaze_i_sken(prijemka):
    GoodsReceiptScan.objects.create(goods_receipt=prijemka)

    prijemka.delete()

    assert GoodsReceiptScan.objects.count() == 0
