"""
Testy pojistek proti dvojímu naskladnění a proti překlepu v ceně.

Obojí je chyba, kterou ostatní kontroly nezachytí – doklad si v obou
případech sedí sám se sebou.
"""
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from apps.canteens.models import Canteen, Warehouse
from apps.core.models import Ingredient
from apps.inventory.models import (
    GoodsReceipt, IngredientPriceHistory, StockItem, Supplier,
)
from apps.inventory.receipt_checks import (
    check_duplicate_receipt, check_price_deviation, last_known_price,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def sklad():
    canteen = Canteen.objects.create(name='Jídelna')
    return Warehouse.objects.create(name='Sklad', canteen=canteen)


@pytest.fixture
def rajce():
    return Ingredient.objects.create(name='Rajče', unit='kg', base_unit='kg')


@pytest.fixture
def bolero():
    return Supplier.objects.create(name='BOLERO', slug='bolero-check', ico='11122233')


@pytest.fixture
def prijemka(sklad, bolero):
    return GoodsReceipt.objects.create(
        warehouse=sklad, receipt_number='PR20260548', supplier='BOLERO Fruit',
        supplier_obj=bolero,
        created_by=get_user_model().objects.create_user('skladnik-d'),
    )


# --- Duplicitní doklad ---

def test_stejne_cislo_od_stejneho_dodavatele(prijemka, bolero):
    assert check_duplicate_receipt('PR20260548', supplier=bolero) == prijemka


def test_porovnani_ignoruje_velikost_pismen(prijemka, bolero):
    assert check_duplicate_receipt('pr20260548', supplier=bolero) == prijemka


def test_stejne_cislo_od_jineho_dodavatele_neni_duplicita(prijemka):
    jiny = Supplier.objects.create(name='Makro', slug='makro-check')

    assert check_duplicate_receipt('PR20260548', supplier=jiny) is None


def test_dohledani_podle_nazvu_kdyz_dodavatel_neni_prirazen(sklad):
    """Starší příjemky mají dodavatele jen jako text."""
    GoodsReceipt.objects.create(
        warehouse=sklad, receipt_number='DL77', supplier='Pekárna Podlesí',
        created_by=get_user_model().objects.create_user('skladnik-e'),
    )

    assert check_duplicate_receipt('DL77', supplier_name='pekárna podlesí') is not None


def test_prazdne_cislo_dokladu_neni_duplicita(prijemka, bolero):
    assert check_duplicate_receipt('', supplier=bolero) is None
    assert check_duplicate_receipt('   ', supplier=bolero) is None


def test_vlastni_prijemka_se_vylouci(prijemka, bolero):
    """Při editaci se příjemka nesmí označit za duplicitu sama sebe."""
    assert check_duplicate_receipt(
        'PR20260548', supplier=bolero, exclude_pk=prijemka.pk,
    ) is None


# --- Odchylka ceny ---

def test_bez_historie_neni_s_cim_srovnavat(rajce, sklad):
    assert last_known_price(rajce, sklad) is None
    assert check_price_deviation(rajce, sklad, Decimal('54.90')) is None


def test_posunuta_desetinna_carka_se_pozna(rajce, sklad):
    """„54,90" přečtené jako „5490" projde všemi ostatními kontrolami."""
    IngredientPriceHistory.objects.create(
        ingredient=rajce, warehouse=sklad, price=Decimal('54.90'),
        valid_from=timezone.now(),
    )

    odchylka = check_price_deviation(rajce, sklad, Decimal('5490'))

    assert odchylka is not None
    assert odchylka['direction'] == 'zdražení'
    assert odchylka['previous'] == Decimal('54.90')


def test_bezne_kolisani_ceny_neupozornuje(rajce, sklad):
    """Sezónní zelenina skáče, na to se upozorňovat nemá."""
    IngredientPriceHistory.objects.create(
        ingredient=rajce, warehouse=sklad, price=Decimal('50'),
        valid_from=timezone.now(),
    )

    assert check_price_deviation(rajce, sklad, Decimal('60')) is None


def test_vyrazne_zlevneni_se_taky_hlasi(rajce, sklad):
    IngredientPriceHistory.objects.create(
        ingredient=rajce, warehouse=sklad, price=Decimal('100'),
        valid_from=timezone.now(),
    )

    odchylka = check_price_deviation(rajce, sklad, Decimal('10'))

    assert odchylka['direction'] == 'zlevnění'


def test_bez_historie_se_vezme_skladova_cena(rajce, sklad):
    StockItem.objects.create(
        ingredient=rajce, warehouse=sklad, quantity=Decimal('5'),
        price=Decimal('54.90'), vat_rate=Decimal('12'),
        price_without_vat=Decimal('49'),
    )

    assert last_known_price(rajce, sklad) == Decimal('54.90')


def test_novejsi_cena_ma_prednost(rajce, sklad):
    ted = timezone.now()
    IngredientPriceHistory.objects.create(
        ingredient=rajce, warehouse=sklad, price=Decimal('40'),
        valid_from=ted - timezone.timedelta(days=30),
    )
    IngredientPriceHistory.objects.create(
        ingredient=rajce, warehouse=sklad, price=Decimal('55'),
        valid_from=ted,
    )

    assert last_known_price(rajce, sklad) == Decimal('55')


# --- Přesnost ceny po přepočtu ---

def test_prepocet_bez_ztraty_presnosti():
    from apps.inventory.receipt_checks import check_price_precision

    # 120 Kč za karton dvanácti kusů = 10 Kč za kus, přesně.
    assert check_price_precision(Decimal('120'), Decimal('12')) is None


def test_bezny_prevod_na_gramy_uz_presnost_neztraci():
    """
    Dřív se ceny ukládaly na dvě desetinná místa a 54,90 Kč/kg z toho vyšlo
    jako 0,05 Kč/g. Při šesti místech je 0,0549 Kč/g přesně.
    """
    from apps.inventory.receipt_checks import check_price_precision

    assert check_price_precision(Decimal('54.90'), Decimal('1000')) is None


def test_extremni_prepocet_presnost_stale_hlida():
    """Pojistka pro případ, kdy cena spadne pod přesnost cenových polí."""
    from apps.inventory.receipt_checks import check_price_precision

    ztrata = check_price_precision(Decimal('0.01'), Decimal('1000000'))

    assert ztrata is not None
    assert ztrata['error'] > Decimal('0.01')


def test_nulova_cena_se_neresi():
    from apps.inventory.receipt_checks import check_price_precision

    assert check_price_precision(Decimal('0'), Decimal('1000')) is None
    assert check_price_precision(Decimal('10'), Decimal('0')) is None


# --- Cena řádově mimo medián (potvrzení příjemky) ---

from django.urls import reverse

from apps.inventory.models import GoodsReceiptItem
from apps.inventory.receipt_checks import check_price_outliers


def _autor():
    return get_user_model().objects.get_or_create(username='nakupci')[0]


def nakup(sklad, surovina, cena, status=GoodsReceipt.Status.CONFIRMED, cislo=None):
    prijemka = GoodsReceipt.objects.create(
        warehouse=sklad, receipt_number=cislo or f'N{GoodsReceipt.objects.count()}',
        status=status, created_by=_autor(),
    )
    return GoodsReceiptItem.objects.create(
        goods_receipt=prijemka, ingredient=surovina, warehouse=sklad,
        quantity=Decimal('250'), price=Decimal(cena),
    )


@pytest.fixture
def historie_cen(sklad, rajce):
    for cena in ('9.20', '8.40', '12.00'):
        nakup(sklad, rajce, cena)


def test_desetinasobek_mediánu_se_ohlasi(sklad, rajce, historie_cen):
    # Případ z příjemky 20260454: celková cena řádku zadaná jako jednotková.
    polozka = nakup(sklad, rajce, '2480', status=GoodsReceipt.Status.DRAFT)

    [nalez] = check_price_outliers([polozka])

    assert nalez['median'] == Decimal('9.20')
    assert nalez['direction'] == 'vyšší'
    assert round(nalez['times']) == 270


def test_desetina_mediánu_se_ohlasi_taky(sklad, rajce, historie_cen):
    polozka = nakup(sklad, rajce, '0.50', status=GoodsReceipt.Status.DRAFT)

    [nalez] = check_price_outliers([polozka])

    assert nalez['direction'] == 'nižší'


def test_bezne_zdrazeni_projde(sklad, rajce, historie_cen):
    polozka = nakup(sklad, rajce, '45', status=GoodsReceipt.Status.DRAFT)

    assert check_price_outliers([polozka]) == []


def test_bez_dostatku_historie_se_nesrovnava(sklad, rajce):
    nakup(sklad, rajce, '9')
    nakup(sklad, rajce, '10')
    polozka = nakup(sklad, rajce, '2480', status=GoodsReceipt.Status.DRAFT)

    assert check_price_outliers([polozka]) == []


def test_koncepty_se_do_mediánu_nepocitaji(sklad, rajce, historie_cen):
    for _ in range(5):
        nakup(sklad, rajce, '2480', status=GoodsReceipt.Status.DRAFT)
    polozka = nakup(sklad, rajce, '2480', status=GoodsReceipt.Status.DRAFT)

    assert len(check_price_outliers([polozka])) == 1


@pytest.fixture
def prihlaseny(client):
    user = get_user_model().objects.create_superuser('skladnik-m', password='x')
    client.force_login(user)
    return user


def test_potvrzeni_bez_zaskrtnuti_cenu_nepusti(client, prihlaseny, sklad, rajce, historie_cen):
    polozka = nakup(sklad, rajce, '2480', status=GoodsReceipt.Status.DRAFT)
    url = reverse('inventory:goods_receipt_confirm', args=[polozka.goods_receipt.pk])

    assert 'Zkontrolujte ceny na dokladu' in client.get(url).content.decode()
    client.post(url)

    polozka.goods_receipt.refresh_from_db()
    assert polozka.goods_receipt.status == GoodsReceipt.Status.DRAFT
    assert not StockItem.objects.filter(ingredient=rajce, warehouse=sklad).exists()


def test_potvrzeni_se_zaskrtnutim_projde(client, prihlaseny, sklad, rajce, historie_cen):
    polozka = nakup(sklad, rajce, '2480', status=GoodsReceipt.Status.DRAFT)
    url = reverse('inventory:goods_receipt_confirm', args=[polozka.goods_receipt.pk])

    client.post(url, {'prices_checked': '1'})

    polozka.goods_receipt.refresh_from_db()
    assert polozka.goods_receipt.status == GoodsReceipt.Status.CONFIRMED


def test_bezna_prijemka_zaskrtnuti_nepotrebuje(client, prihlaseny, sklad, rajce, historie_cen):
    polozka = nakup(sklad, rajce, '10', status=GoodsReceipt.Status.DRAFT)
    url = reverse('inventory:goods_receipt_confirm', args=[polozka.goods_receipt.pk])

    assert 'prices_checked' not in client.get(url).content.decode()
    client.post(url)

    polozka.goods_receipt.refresh_from_db()
    assert polozka.goods_receipt.status == GoodsReceipt.Status.CONFIRMED
