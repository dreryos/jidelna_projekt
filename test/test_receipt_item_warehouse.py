"""
Testy naskladnění položky příjemky do jejího vlastního skladu.

Formulář příjemky i importy (fotka, Bidfood, CSV) nechají u každé položky
zvolit sklad. `GoodsReceipt.confirm()` ho dřív ignoroval a všechno naskladnil
do skladu z hlavičky – zboží bufetu tak skončilo v kuchyni a ve skladu bufetu
chybělo.
"""
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.urls import reverse

from apps.canteens.models import Canteen, Warehouse
from apps.core.models import Ingredient, UserProfile
from apps.inventory.models import GoodsReceipt, GoodsReceiptItem, StockItem

pytestmark = pytest.mark.django_db


@pytest.fixture
def jidelna():
    return Canteen.objects.create(name='Růžená')


@pytest.fixture
def kuchyne(jidelna):
    return Warehouse.objects.create(name='Kuchyně', canteen=jidelna)


@pytest.fixture
def bufet(jidelna):
    return Warehouse.objects.create(name='Bufet', canteen=jidelna)


@pytest.fixture
def uzivatel():
    return get_user_model().objects.create_superuser('skladnik-wh', password='tajne')


@pytest.fixture
def cola():
    return Ingredient.objects.create(name='Cola', unit='ks', base_unit='ks')


def prijemka_s_polozkou(hlavicka, sklad_polozky, ingredient, user):
    prijemka = GoodsReceipt.objects.create(
        warehouse=hlavicka, receipt_number='DL-WH', created_by=user,
    )
    GoodsReceiptItem.objects.create(
        goods_receipt=prijemka, ingredient=ingredient, warehouse=sklad_polozky,
        quantity=Decimal('24'), price_without_vat=Decimal('20'),
        vat_rate=Decimal('12'), price=Decimal('22.40'),
    )
    return prijemka


def test_polozka_se_naskladni_do_sveho_skladu(kuchyne, bufet, cola, uzivatel):
    prijemka_s_polozkou(kuchyne, bufet, cola, uzivatel).confirm()

    assert StockItem.objects.get(ingredient=cola, warehouse=bufet).quantity == Decimal('24')
    assert not StockItem.objects.filter(ingredient=cola, warehouse=kuchyne).exists()


def test_zamceny_sklad_polozky_blokuje_potvrzeni(kuchyne, bufet, cola, uzivatel):
    bufet.is_locked = True
    bufet.save(update_fields=['is_locked'])
    prijemka = prijemka_s_polozkou(kuchyne, bufet, cola, uzivatel)

    with pytest.raises(ValidationError, match='Bufet'):
        prijemka.confirm()

    prijemka.refresh_from_db()
    assert prijemka.status == GoodsReceipt.Status.DRAFT
    assert not StockItem.objects.exists()


def test_sklad_polozky_v_cizi_jidelne_nejde_potvrdit(client, kuchyne, cola, uzivatel):
    cizi = Warehouse.objects.create(
        name='Cizí sklad', canteen=Canteen.objects.create(name='Ostrovec'),
    )
    vedouci = get_user_model().objects.create_user('vedouci-wh', password='tajne')
    profil, _ = UserProfile.objects.get_or_create(user=vedouci)
    profil.canteens.add(kuchyne.canteen)
    client.force_login(vedouci)
    prijemka = prijemka_s_polozkou(kuchyne, cizi, cola, uzivatel)

    client.post(reverse('inventory:goods_receipt_confirm', args=[prijemka.pk]))

    prijemka.refresh_from_db()
    assert prijemka.status == GoodsReceipt.Status.DRAFT
    assert not StockItem.objects.exists()


def test_confirm_s_uzivatelem_odmitne_cizi_sklad_polozky(kuchyne, cola, uzivatel):
    # Kontrola oprávnění sedí v `confirm()` nad zamčenými položkami – view
    # ji dělá mimo transakci a položka se mezitím může přepnout jinam.
    cizi = Warehouse.objects.create(
        name='Cizí sklad', canteen=Canteen.objects.create(name='Ostrovec'),
    )
    vedouci = get_user_model().objects.create_user('vedouci-cf', password='tajne')
    profil, _ = UserProfile.objects.get_or_create(user=vedouci)
    profil.canteens.add(kuchyne.canteen)
    prijemka = prijemka_s_polozkou(kuchyne, cizi, cola, uzivatel)

    with pytest.raises(ValidationError) as exc:
        prijemka.confirm(user=vedouci)

    assert 'Cizí sklad' not in str(exc.value)
    assert not StockItem.objects.exists()


def test_uprava_potvrzene_prijemky_neprojde_zamkem(kuchyne, bufet, cola, uzivatel):
    # Úprava drží starou instanci (prošla kontrolou konceptu), mezitím se
    # příjemka potvrdila. Zámek s novým přečtením stavu ji musí zastavit.
    prijemka = prijemka_s_polozkou(kuchyne, bufet, cola, uzivatel)
    zastarala = GoodsReceipt.objects.get(pk=prijemka.pk)
    prijemka.confirm()

    with pytest.raises(ValidationError):
        zastarala.lock_draft()


# --- Viditelnost příjemek podle jídelen ---

@pytest.fixture
def ostrovec_sklad():
    return Warehouse.objects.create(
        name='Ostrovec sklad', canteen=Canteen.objects.create(name='Ostrovec'),
    )


@pytest.fixture
def vedouci_ruzene(client, jidelna):
    vedouci = get_user_model().objects.create_user('vedouci-rz', password='tajne')
    profil, _ = UserProfile.objects.get_or_create(user=vedouci)
    profil.canteens.add(jidelna)
    client.force_login(vedouci)
    return vedouci


def test_detail_neukaze_prijemku_s_polozkou_v_cizi_jidelne(
        client, vedouci_ruzene, kuchyne, ostrovec_sklad, cola, uzivatel):
    prijemka = prijemka_s_polozkou(kuchyne, ostrovec_sklad, cola, uzivatel)

    response = client.get(reverse('inventory:goods_receipt_detail', args=[prijemka.pk]))

    assert response.status_code == 404


def test_potvrzovaci_stranka_neprozradi_cizi_sklad(
        client, vedouci_ruzene, kuchyne, ostrovec_sklad, cola, uzivatel):
    prijemka = prijemka_s_polozkou(kuchyne, ostrovec_sklad, cola, uzivatel)

    response = client.get(
        reverse('inventory:goods_receipt_confirm', args=[prijemka.pk]), follow=True,
    )

    assert 'Ostrovec sklad' not in response.content.decode()


def test_seznam_filtruje_i_podle_skladu_polozky(
        client, vedouci_ruzene, kuchyne, bufet, cola, uzivatel):
    prijemka = prijemka_s_polozkou(kuchyne, bufet, cola, uzivatel)
    jina = GoodsReceipt.objects.create(
        warehouse=kuchyne, receipt_number='DL-JEN-KUCHYNE', created_by=uzivatel,
    )

    response = client.get(reverse('inventory:goods_receipt_list'), {'warehouse': bufet.pk})

    nalezene = list(response.context['goods_receipts'])
    assert nalezene == [prijemka]
    assert jina not in nalezene


def test_seznam_skryje_prijemku_s_polozkou_v_cizi_jidelne(
        client, vedouci_ruzene, kuchyne, ostrovec_sklad, cola, uzivatel):
    prijemka_s_polozkou(kuchyne, ostrovec_sklad, cola, uzivatel)

    response = client.get(reverse('inventory:goods_receipt_list'))

    assert list(response.context['goods_receipts']) == []


# --- Záloha ---

def test_zaloha_obnovi_sklad_polozky_v_jine_jidelne(kuchyne, cola, uzivatel):
    # Stejný název skladu ve dvou jídelnách: bez jídelny u položky by ji
    # import hledal pod jídelnou hlavičky a dal ji do špatného skladu.
    import xml.etree.ElementTree as ET
    from collections import defaultdict

    from apps.core.backup import _export_goods_receipts, _import_goods_receipts

    druhy = Warehouse.objects.create(
        name='Kuchyně', canteen=Canteen.objects.create(name='Ostrovec'),
    )
    prijemka_s_polozkou(kuchyne, druhy, cola, uzivatel)
    root = ET.Element('Backup')
    _export_goods_receipts(root)
    GoodsReceipt.objects.all().delete()

    report = defaultdict(int, missing_references=[])
    warehouse_map = {
        f'{w.canteen.name}:{w.name}': w for w in Warehouse.objects.select_related('canteen')
    }
    _import_goods_receipts(root, warehouse_map, {}, {'Cola': cola}, uzivatel, report)

    assert GoodsReceiptItem.objects.get().warehouse == druhy


# --- Import ---

def test_user_warehouses_omezi_sklady_na_jidelny():
    # Bidfood, CSV i fotka berou sklad položky přes `user_warehouses()`;
    # celou cestu importu testuje `test_photo_import_views.py`.
    from apps.inventory.views import user_warehouses

    canteen = Canteen.objects.create(name='Moje')
    moje = Warehouse.objects.create(name='Můj sklad', canteen=canteen)
    cizi = Warehouse.objects.create(name='Cizí', canteen=Canteen.objects.create(name='Jiná'))
    user = get_user_model().objects.create_user('import-wh', password='tajne')
    profil, _ = UserProfile.objects.get_or_create(user=user)
    profil.canteens.add(canteen)

    assert list(user_warehouses(user)) == [moje]
    assert cizi not in user_warehouses(user)
