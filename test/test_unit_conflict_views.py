"""
Testy obrazovky pro doplnění přepočtu měrných jednotek.

Blokace potvrzení nesmí být slepá ulička – uživatel musí skončit tam,
kde se přepočet dá doplnit. Samotnou pojistku testuje
`test_unit_conflict_guard.py`.
"""
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from apps.canteens.models import Canteen, Warehouse
from apps.core.models import Ingredient
from apps.inventory.matching import IngredientResolver
from apps.inventory.models import (
    GoodsReceipt, GoodsReceiptItem, Supplier, SupplierItemAlias,
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
        name='Pekárna Podlesí', slug='pekarna-guard', ico='77788899',
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


# --- Obrazovka pro srovnání ---

def test_potvrzeni_presmeruje_na_srovnani(client, uzivatel, prijemka, sklad, rohlik):
    polozka(prijemka, sklad, rohlik)

    response = client.get(
        reverse('inventory:goods_receipt_confirm', args=[prijemka.pk]), follow=True,
    )

    assert response.redirect_chain[-1][0] == reverse(
        'inventory:goods_receipt_resolve_units', args=[prijemka.pk]
    )


def test_srovnani_ulozi_prepocet_i_alias(client, uzivatel, prijemka, sklad,
                                         rohlik, pekarna):
    item = polozka(prijemka, sklad, rohlik)

    client.post(reverse('inventory:goods_receipt_resolve_units', args=[prijemka.pk]),
                {f'factor_{item.pk}': '12'}, follow=True)

    item.refresh_from_db()
    assert item.quantity == Decimal('36')
    assert not prijemka.unit_conflicts

    # Podruhé se systém ptát nebude.
    alias = SupplierItemAlias.objects.get(raw_name='Rohlík karton')
    assert alias.supplier == pekarna
    assert alias.unit_factor == Decimal('12')


def test_srovnani_prijima_desetinnou_carku(client, uzivatel, prijemka, sklad, rohlik):
    """Uživatel píše česky."""
    item = polozka(prijemka, sklad, rohlik)

    client.post(reverse('inventory:goods_receipt_resolve_units', args=[prijemka.pk]),
                {f'factor_{item.pk}': '0,25'}, follow=True)

    item.refresh_from_db()
    assert item.quantity == Decimal('0.75')


def test_srovnani_odmitne_nesmysl(client, uzivatel, prijemka, sklad, rohlik):
    item = polozka(prijemka, sklad, rohlik)

    response = client.post(
        reverse('inventory:goods_receipt_resolve_units', args=[prijemka.pk]),
        {f'factor_{item.pk}': 'dvanáct'}, follow=True,
    )

    assert 'jako číslo' in response.content.decode()
    item.refresh_from_db()
    assert item.quantity == Decimal('3')


def test_srovnani_bez_konfliktu_vrati_na_detail(client, uzivatel, prijemka, sklad, rohlik):
    polozka(prijemka, sklad, rohlik, source_unit='ks')

    response = client.get(
        reverse('inventory:goods_receipt_resolve_units', args=[prijemka.pk]), follow=True,
    )

    assert response.redirect_chain[-1][0] == reverse(
        'inventory:goods_receipt_detail', args=[prijemka.pk]
    )


def test_potvrzenou_prijemku_uz_srovnavat_nejde(client, uzivatel, prijemka, sklad, rohlik):
    polozka(prijemka, sklad, rohlik, source_unit='ks')
    prijemka.confirm()

    response = client.get(
        reverse('inventory:goods_receipt_resolve_units', args=[prijemka.pk]), follow=True,
    )

    assert 'už upravovat nelze' in response.content.decode()


def test_neplatny_prepocet_nezmeni_ani_drivejsi_polozky(client, uzivatel,
                                                        prijemka, sklad, rohlik):
    """
    `return` uvnitř `transaction.atomic()` transakci potvrdí, ne zruší.
    Když je druhý přepočet nesmysl, nesmí se uložit ani ten první.
    """
    mouka = Ingredient.objects.create(name='Mouka', unit='kg', base_unit='kg')
    prvni = polozka(prijemka, sklad, rohlik)
    druha = polozka(prijemka, sklad, mouka, source_name='Mouka pytel',
                    source_unit='pytel')

    response = client.post(
        reverse('inventory:goods_receipt_resolve_units', args=[prijemka.pk]),
        {f'factor_{prvni.pk}': '12', f'factor_{druha.pk}': 'dvanáct'},
        follow=True,
    )

    assert 'jako číslo' in response.content.decode()
    prvni.refresh_from_db()
    druha.refresh_from_db()
    assert prvni.quantity == Decimal('3')
    assert druha.quantity == Decimal('3')
    assert len(prijemka.unit_conflicts) == 2


def test_zaporny_prepocet_nezmeni_ani_drivejsi_polozky(client, uzivatel,
                                                       prijemka, sklad, rohlik):
    mouka = Ingredient.objects.create(name='Mouka', unit='kg', base_unit='kg')
    prvni = polozka(prijemka, sklad, rohlik)
    druha = polozka(prijemka, sklad, mouka, source_name='Mouka pytel',
                    source_unit='pytel')

    client.post(
        reverse('inventory:goods_receipt_resolve_units', args=[prijemka.pk]),
        {f'factor_{prvni.pk}': '12', f'factor_{druha.pk}': '-5'}, follow=True,
    )

    prvni.refresh_from_db()
    assert prvni.quantity == Decimal('3')


def test_nahled_dostane_cislo_s_teckou(client, uzivatel, prijemka, sklad, rohlik):
    """
    Projekt má české locale, takže by se množství vykreslilo jako „3,000".
    parseFloat by z „0,750" udělal nulu a náhled by lhal.
    """
    polozka(prijemka, sklad, rohlik, source_quantity=Decimal('0.75'))

    obsah = client.get(
        reverse('inventory:goods_receipt_resolve_units', args=[prijemka.pk])
    ).content.decode()

    assert 'data-quantity="0.750"' in obsah
    assert 'data-quantity="0,750"' not in obsah


def test_jmeno_pole_neprojde_lokalizaci(client, uzivatel, prijemka, sklad, rohlik):
    """
    Projekt má USE_THOUSAND_SEPARATOR, takže `{{ item.pk }}` by u čtyřmístného
    ID vykreslil „4 598" a jméno pole by přestalo sedět s tím, co hledá view.
    Uživatel by pak dostal „zadejte přepočet jako číslo" i po zadání jedničky.
    """
    item = polozka(prijemka, sklad, rohlik)
    GoodsReceiptItem.objects.filter(pk=item.pk).update(id=4598)
    item = GoodsReceiptItem.objects.get(pk=4598)

    obsah = client.get(
        reverse('inventory:goods_receipt_resolve_units', args=[prijemka.pk])
    ).content.decode()
    assert 'name="factor_4598"' in obsah

    client.post(reverse('inventory:goods_receipt_resolve_units', args=[prijemka.pk]),
                {f'factor_{item.pk}': '1,5'}, follow=True)

    item.refresh_from_db()
    assert item.quantity == Decimal('4.5')


def test_prepocet_jedna_odblokuje_potvrzeni(client, uzivatel, prijemka, sklad, rohlik):
    """
    „1 balení = 1 kus" je platná odpověď, ne chybějící rozhodnutí.
    Dokud se poznávalo podle `unit_factor != 1`, položka po zadání jedničky
    zůstala konfliktní: hláška slibovala úspěch a potvrdit stejně nešlo.
    """
    item = polozka(prijemka, sklad, rohlik)

    response = client.post(
        reverse('inventory:goods_receipt_resolve_units', args=[prijemka.pk]),
        {f'factor_{item.pk}': '1'}, follow=True,
    )

    item.refresh_from_db()
    assert item.unit_resolved is True
    assert item.has_unit_conflict is False
    assert not prijemka.unit_conflicts
    assert 'Příjemku teď jde potvrdit' in response.content.decode()

    prijemka.confirm()
    prijemka.refresh_from_db()
    assert prijemka.status == GoodsReceipt.Status.CONFIRMED


def test_naucena_jedna_plati_i_podruhe(client, uzivatel, prijemka, sklad,
                                       rohlik, pekarna):
    """Jednou zadané „1 bal = 1 ks" se nesmí příště ptát znovu."""
    item = polozka(prijemka, sklad, rohlik)
    client.post(reverse('inventory:goods_receipt_resolve_units', args=[prijemka.pk]),
                {f'factor_{item.pk}': '1'}, follow=True)

    alias = SupplierItemAlias.objects.get(raw_name='Rohlík karton')
    assert alias.unit_factor == Decimal('1')
    assert alias.unit_resolved is True

    from apps.inventory.matching import IngredientResolver
    shoda = IngredientResolver(supplier=pekarna, ingredients=[rohlik]).resolve(
        'Rohlík karton', unit='bal',
    )
    assert shoda.needs_unit_check is False
    assert shoda.unit_factor == Decimal('1')


def test_import_neoznaci_vychozi_jednicku_za_rozhodnuti(pekarna, rohlik):
    """
    Import posílá `unit_factor=1` i tam, kde uživatel nic nerozhodl. Kdyby se
    to uložilo jako vyřešené, u nesedících jednotek by se příště neptal nikdo
    a do skladu by se naskladnilo 1:1.
    """
    resolver = IngredientResolver(supplier=pekarna, ingredients=[rohlik])
    resolver.remember('Rohlík karton', ingredient=rohlik, unit='bal',
                      unit_factor=Decimal('1'))

    alias = SupplierItemAlias.objects.get(raw_name='Rohlík karton')
    assert alias.unit_resolved is False

    shoda = IngredientResolver(supplier=pekarna, ingredients=[rohlik]).resolve(
        'Rohlík karton', unit='bal',
    )
    assert shoda.needs_unit_check is True


def test_hlaska_nelze_kdyz_zbyva_konflikt(client, uzivatel, prijemka, sklad, rohlik,
                                          monkeypatch):
    """Úspěch se hlásí podle stavu po zápisu, ne podle počtu řádků ve smyčce."""
    from apps.inventory.models import GoodsReceiptItem

    item = polozka(prijemka, sklad, rohlik)
    # Zápis, který se „nepovede" – přepočet zůstane nevyřešený.
    monkeypatch.setattr(GoodsReceiptItem, 'apply_unit_factor', lambda self, factor: None)

    response = client.post(
        reverse('inventory:goods_receipt_resolve_units', args=[prijemka.pk]),
        {f'factor_{item.pk}': '12'}, follow=True,
    )

    obsah = response.content.decode()
    assert 'Potvrdit zatím nejde' in obsah
    assert 'Příjemku teď jde potvrdit' not in obsah


def test_import_neshodi_driv_potvrzeny_alias(client, uzivatel, prijemka, sklad,
                                             rohlik, pekarna):
    """
    Import volá `remember()` bez ohledu na jednotky. Kdyby zapsal výchozí
    `unit_resolved=False`, shodil by dřív potvrzený alias na nevyřešený
    a uživatel by ten samý přepočet zadával při každém dalším dokladu.
    """
    item = polozka(prijemka, sklad, rohlik)
    client.post(reverse('inventory:goods_receipt_resolve_units', args=[prijemka.pk]),
                {f'factor_{item.pk}': '1'}, follow=True)
    assert SupplierItemAlias.objects.get(raw_name='Rohlík karton').unit_resolved

    # Další doklad se stejnou položkou projde importem, který o jednotkách nic neví.
    IngredientResolver(supplier=pekarna, ingredients=[rohlik]).remember(
        'Rohlík karton', ingredient=rohlik, unit='bal', unit_factor=Decimal('1'),
    )

    alias = SupplierItemAlias.objects.get(raw_name='Rohlík karton')
    assert alias.unit_resolved is True

    shoda = IngredientResolver(supplier=pekarna, ingredients=[rohlik]).resolve(
        'Rohlík karton', unit='bal',
    )
    assert shoda.needs_unit_check is False
