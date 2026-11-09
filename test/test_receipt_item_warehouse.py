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
