"""
Testy filtrování a vyhledávání v seznamu příjmů zboží.

Seznam byl dřív filtrovatelný jen podle skladu a stavu. Doplněno o
vyhledávání podle čísla dokladu, filtr podle dodavatele a podle data
příjmu.
"""
from datetime import date, timedelta

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from apps.canteens.models import Canteen, Warehouse
from apps.inventory.models import GoodsReceipt, Supplier

pytestmark = pytest.mark.django_db


@pytest.fixture
def uzivatel(client):
    user = get_user_model().objects.create_superuser('skladnik', password='tajne')
    client.force_login(user)
    return user


@pytest.fixture
def sklad():
    canteen = Canteen.objects.create(name='Jídelna Topinka')
    return Warehouse.objects.create(name='Hlavní sklad', canteen=canteen)


@pytest.fixture
def bolero():
    return Supplier.objects.create(name='BOLERO Fruit', slug='bolero-fruit')


@pytest.fixture
def makro():
    return Supplier.objects.create(name='Makro', slug='makro')


def vytvor_prijem(sklad, uzivatel, **kwargs):
    defaults = {
        'warehouse': sklad, 'receipt_number': 'D1', 'created_by': uzivatel,
    }
    defaults.update(kwargs)
    return GoodsReceipt.objects.create(**defaults)


def test_hledani_podle_cisla_dokladu(client, uzivatel, sklad):
    hledany = vytvor_prijem(sklad, uzivatel, receipt_number='DL2026/001')
    vytvor_prijem(sklad, uzivatel, receipt_number='DL2026/002')

    response = client.get(reverse('inventory:goods_receipt_list'), {'search': '2026/001'})

    prijmy = list(response.context['goods_receipts'])
    assert prijmy == [hledany]


def test_filtr_podle_dodavatele(client, uzivatel, sklad, bolero, makro):
    od_bolera = vytvor_prijem(sklad, uzivatel, receipt_number='D1', supplier_obj=bolero)
    vytvor_prijem(sklad, uzivatel, receipt_number='D2', supplier_obj=makro)

    response = client.get(reverse('inventory:goods_receipt_list'), {'supplier': bolero.id})

    prijmy = list(response.context['goods_receipts'])
    assert prijmy == [od_bolera]


def test_filtr_podle_data_prijmu(client, uzivatel, sklad):
    dnes = date.today()
    cerstvy = vytvor_prijem(sklad, uzivatel, receipt_number='D1', receipt_date=dnes)
    stary = vytvor_prijem(sklad, uzivatel, receipt_number='D2',
                          receipt_date=dnes - timedelta(days=60))

    response = client.get(reverse('inventory:goods_receipt_list'), {
        'date_from': (dnes - timedelta(days=7)).isoformat(),
    })

    prijmy = list(response.context['goods_receipts'])
    assert cerstvy in prijmy
    assert stary not in prijmy


def test_bez_filtru_se_zobrazi_vsechno(client, uzivatel, sklad, bolero):
    a = vytvor_prijem(sklad, uzivatel, receipt_number='D1', supplier_obj=bolero)
    b = vytvor_prijem(sklad, uzivatel, receipt_number='D2')

    response = client.get(reverse('inventory:goods_receipt_list'))

    prijmy = list(response.context['goods_receipts'])
    assert set(prijmy) == {a, b}


def test_neplatne_datum_ve_filtru_neshodi_stranku(client, uzivatel, sklad):
    """
    `receipt_date__gte='neco'` by Django předalo rovnou do SQL a spadlo
    by na ValueError – neplatné datum se má tiše ignorovat, ne shodit
    celou stránku do 500.
    """
    prijem = vytvor_prijem(sklad, uzivatel, receipt_number='D1')

    response = client.get(reverse('inventory:goods_receipt_list'), {
        'date_from': 'neplatne-datum', 'date_to': '2026-13-40',
    })

    assert response.status_code == 200
    assert list(response.context['goods_receipts']) == [prijem]


def test_deaktivovany_dodavatel_zustava_ve_filtru(client, uzivatel, sklad, bolero):
    """
    Historickou příjemku od dodavatele, kterého mezitím někdo deaktivoval,
    musí jít podle něj pořád dohledat – jinak by ho nešlo ve filtru vůbec
    vybrat, přestože příjemky s ním v seznamu zůstávají.
    """
    prijem = vytvor_prijem(sklad, uzivatel, receipt_number='D1', supplier_obj=bolero)
    bolero.is_active = False
    bolero.save()

    response = client.get(reverse('inventory:goods_receipt_list'))

    assert bolero in response.context['suppliers']

    response = client.get(reverse('inventory:goods_receipt_list'), {'supplier': bolero.id})
    assert list(response.context['goods_receipts']) == [prijem]
