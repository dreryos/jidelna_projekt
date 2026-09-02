"""
Testy importu příjemky z fotky dokladu.

OCR se v testech nevolá – `run_ocr` je nahrazeno anotací z
`test/fixtures/ocr`, takže testy neplatí za stránky a nezávisí na síti.
Fixtury jsou verzované; složka `backups/` je v .gitignore a test postavený
na ní by na čistém klonu spadl. Ověřuje se celá cesta
od nahrání fotky po vytvoření příjemky, včetně toho, co si systém zapamatuje
a kdy se maže fotka.
"""
import json
from decimal import Decimal
from pathlib import Path

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.files.storage import default_storage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import reverse

from apps.canteens.models import Canteen, Warehouse
from apps.core.models import Ingredient
from apps.inventory.models import (
    GoodsReceipt, GoodsReceiptItem, GoodsReceiptScan, StockItem, Supplier,
    SupplierItemAlias,
)

pytestmark = pytest.mark.django_db

FIXTURE = Path(settings.BASE_DIR) / 'test' / 'fixtures' / 'ocr' / 'prodejka_zelenina'


@pytest.fixture
def media_root(tmp_path):
    with override_settings(MEDIA_ROOT=tmp_path, MISTRAL_API_KEY='testovaci-klic'):
        yield tmp_path


@pytest.fixture
def sklad():
    canteen = Canteen.objects.create(name='Jídelna Topinka')
    return Warehouse.objects.create(name='Hlavní sklad', canteen=canteen)


@pytest.fixture
def uzivatel(client):
    user = get_user_model().objects.create_superuser('skladnik', password='tajne')
    client.force_login(user)
    return user


@pytest.fixture
def bolero():
    return Supplier.objects.create(
        name='BOLERO Fruit', slug='bolero-fruit', ico='11122233',
    )


@pytest.fixture
def suroviny():
    return {
        'rajce': Ingredient.objects.create(name='Rajče', unit='kg', base_unit='kg'),
        'paprika': Ingredient.objects.create(name='Paprika', unit='kg', base_unit='kg'),
        'zeli': Ingredient.objects.create(name='Zelí', unit='kg', base_unit='kg'),
    }


@pytest.fixture
def ocr_bez_site(monkeypatch):
    """Nahradí volání Mistralu uloženou anotací a fotku nechá projít."""
    from apps.inventory.ocr import client

    annotation = json.loads(
        (FIXTURE / 'document-annotation.json').read_text(encoding='utf-8')
    )

    def fake_run_ocr(raw_bytes, filename, **kwargs):
        return {'annotation': annotation, 'markdown': '# doklad', 'raw': {}}

    def fake_prepare_image(raw_bytes, filename):
        return b'zmensena-fotka', 'image/jpeg'

    monkeypatch.setattr(client, 'run_ocr', fake_run_ocr)
    monkeypatch.setattr(client, 'prepare_image', fake_prepare_image)
    return annotation


def nahrat_doklad(client, sklad, nazev='doklad.jpg'):
    return client.post(reverse('inventory:photo_import_step1'), {
        'scan_file': SimpleUploadedFile(nazev, b'data', content_type='image/jpeg'),
        'warehouse': sklad.id,
    }, follow=True)


# --- Krok 1 ---

def test_bez_klice_se_formular_neodesle(client, uzivatel, sklad):
    with override_settings(MISTRAL_API_KEY=''):
        response = client.get(reverse('inventory:photo_import_step1'))

    assert response.status_code == 200
    assert 'MISTRAL_API_KEY' in response.content.decode()


def test_nahrani_dokladu_ulozi_sken_i_data(client, uzivatel, sklad, bolero,
                                           media_root, ocr_bez_site):
    response = nahrat_doklad(client, sklad)

    assert response.status_code == 200
    scan = GoodsReceiptScan.objects.get()
    assert scan.uploaded_by == uzivatel
    assert scan.goods_receipt is None
    assert scan.annotation['doklad']['cislo_dokladu'] == 'PR20260001'
    assert default_storage.exists(scan.file_path)

    data = client.session['photo_receipt_data']
    assert data['receipt_number'] == 'PR20260001'
    assert data['supplier_id'] == bolero.id


def test_prilis_velky_soubor_se_odmitne(client, uzivatel, sklad, media_root):
    from apps.inventory.views import MAX_SCAN_UPLOAD_BYTES

    velky = SimpleUploadedFile(
        'velky.jpg', b'x' * (MAX_SCAN_UPLOAD_BYTES + 1), content_type='image/jpeg',
    )
    response = client.post(reverse('inventory:photo_import_step1'), {
        'scan_file': velky, 'warehouse': sklad.id,
    }, follow=True)

    assert 'příliš velký' in response.content.decode()
    assert GoodsReceiptScan.objects.count() == 0


def test_chyba_ocr_nenechá_viset_sken(client, uzivatel, sklad, media_root, monkeypatch):
    from apps.inventory.ocr import client as ocr_client

    def selhat(*args, **kwargs):
        raise ocr_client.OcrError('Rozpoznání dokladu selhalo: timeout')

    monkeypatch.setattr(ocr_client, 'run_ocr', selhat)
    monkeypatch.setattr(ocr_client, 'prepare_image', lambda b, n: (b'x', 'image/jpeg'))

    response = nahrat_doklad(client, sklad)

    assert 'selhalo' in response.content.decode()
    assert GoodsReceiptScan.objects.count() == 0


# --- Krok 2 ---

def test_nahled_nabidne_suroviny_a_oznaci_nezbozni_radky(client, uzivatel, sklad,
                                                         bolero, suroviny,
                                                         media_root, ocr_bez_site):
    nahrat_doklad(client, sklad)

    response = client.get(reverse('inventory:photo_import_step2'))

    assert response.status_code == 200
    polozky = client.session['photo_receipt_data']['items']
    rajce, *_zbytek, zaokrouhleni = polozky
    assert rajce['ingredient_name'] == 'Rajče'
    assert zaokrouhleni['is_ignored'] is True


def test_bez_session_vrati_na_zacatek(client, uzivatel):
    response = client.get(reverse('inventory:photo_import_step2'))

    assert response.status_code == 302
    assert response.url == reverse('inventory:photo_import_step1')


# --- Krok 3 ---

def odeslat_prijemku(client, sklad, suroviny, vynechat=()):
    """Potvrdí položky dokladu tak, jak by je odklikl uživatel."""
    data = client.session['photo_receipt_data']
    payload = {
        'receipt_number': data['receipt_number'],
        'receipt_date': data['receipt_date'],
        'supplier_obj': data['supplier_id'] or '',
    }
    mapovani = {
        'Rajče keř TUR': suroviny['rajce'],
        'Paprika červená NL': suroviny['paprika'],
        'Paprika žlutá NL': suroviny['paprika'],
        'Zelí bílé nové PL': suroviny['zeli'],
    }
    for index, item in enumerate(data['items']):
        surovina = mapovani.get(item['item_name'])
        if surovina is None or index in vynechat:
            continue
        payload[f'include_{index}'] = 'on'
        payload[f'ingredient_{index}'] = surovina.id
        payload[f'quantity_{index}'] = item['quantity']
        payload[f'warehouse_{index}'] = sklad.id
    return client.post(reverse('inventory:photo_import_step3'), payload, follow=True)


def test_vytvoreni_prijemky(client, uzivatel, sklad, bolero, suroviny,
                            media_root, ocr_bez_site):
    nahrat_doklad(client, sklad)

    odeslat_prijemku(client, sklad, suroviny)

    prijemka = GoodsReceipt.objects.get()
    assert prijemka.receipt_number == 'PR20260001'
    assert prijemka.supplier_obj == bolero
    assert prijemka.status == GoodsReceipt.Status.DRAFT
    # Zaokrouhlení se na sklad nedostalo.
    assert prijemka.items.count() == 4
    assert not prijemka.items.filter(ingredient__name='Zaokrouhlení').exists()


def test_sken_se_navaze_na_prijemku(client, uzivatel, sklad, bolero, suroviny,
                                    media_root, ocr_bez_site):
    nahrat_doklad(client, sklad)

    odeslat_prijemku(client, sklad, suroviny)

    scan = GoodsReceiptScan.objects.get()
    assert scan.goods_receipt == GoodsReceipt.objects.get()
    # Fotka žije do potvrzení příjemky.
    assert scan.has_file is True


def test_import_se_nauci_mapovani_i_odmitnute_radky(client, uzivatel, sklad, bolero,
                                                    suroviny, media_root, ocr_bez_site):
    nahrat_doklad(client, sklad)

    odeslat_prijemku(client, sklad, suroviny)

    rajce = SupplierItemAlias.objects.get(raw_name='Rajče keř TUR')
    assert rajce.supplier == bolero
    assert rajce.ingredient == suroviny['rajce']

    # Odškrtnutý řádek se zapamatuje jako nezbožní.
    zaokrouhleni = SupplierItemAlias.objects.get(raw_name='Zaokrouhlení')
    assert zaokrouhleni.is_ignored is True
    assert zaokrouhleni.ingredient is None


def test_druhy_doklad_uz_je_predvyplneny(client, uzivatel, sklad, bolero, suroviny,
                                         media_root, ocr_bez_site):
    """Smysl celého mechanismu: podruhé už uživatel jen odklikne."""
    nahrat_doklad(client, sklad)
    odeslat_prijemku(client, sklad, suroviny)

    nahrat_doklad(client, sklad, nazev='druhy.jpg')
    client.get(reverse('inventory:photo_import_step2'))

    polozky = client.session['photo_receipt_data']['items']
    zbozi = [item for item in polozky if not item['is_ignored']]
    assert zbozi, 'doklad musí obsahovat zboží'
    assert all(item['is_automatic'] for item in zbozi)


def test_neurcena_surovina_vrati_na_kontrolu(client, uzivatel, sklad, bolero,
                                             suroviny, media_root, ocr_bez_site):
    nahrat_doklad(client, sklad)
    data = client.session['photo_receipt_data']

    response = client.post(reverse('inventory:photo_import_step3'), {
        'receipt_number': data['receipt_number'],
        'receipt_date': data['receipt_date'],
        'include_0': 'on',  # zaškrtnuto, ale bez vybrané suroviny
    }, follow=True)

    assert 'vyberte surovinu' in response.content.decode()
    assert GoodsReceipt.objects.count() == 0


# --- Sken a jeho životnost ---

def test_potvrzeni_prijemky_smaze_fotku(client, uzivatel, sklad, bolero, suroviny,
                                        media_root, ocr_bez_site):
    nahrat_doklad(client, sklad)
    odeslat_prijemku(client, sklad, suroviny)
    prijemka = GoodsReceipt.objects.get()
    cesta = GoodsReceiptScan.objects.get().file_path

    client.post(reverse('inventory:goods_receipt_confirm', args=[prijemka.pk]))

    scan = GoodsReceiptScan.objects.get()
    assert scan.has_file is False
    assert not default_storage.exists(cesta)
    # Anotace zůstává kvůli dohledatelnosti.
    assert scan.annotation['doklad']['cislo_dokladu'] == 'PR20260001'


def test_sken_vidi_jen_opravneny_uzivatel(client, uzivatel, sklad, bolero,
                                          media_root, ocr_bez_site):
    nahrat_doklad(client, sklad)
    scan = GoodsReceiptScan.objects.get()

    assert client.get(reverse('inventory:photo_import_scan', args=[scan.pk])).status_code == 200

    get_user_model().objects.create_user('cizi', password='tajne')
    client.logout()
    client.login(username='cizi', password='tajne')

    assert client.get(reverse('inventory:photo_import_scan', args=[scan.pk])).status_code == 404


def test_smazana_fotka_vraci_404(client, uzivatel, sklad, bolero, media_root, ocr_bez_site):
    nahrat_doklad(client, sklad)
    scan = GoodsReceiptScan.objects.get()
    scan.delete_file()

    response = client.get(reverse('inventory:photo_import_scan', args=[scan.pk]))

    assert response.status_code == 404


def test_neuplny_csv_import_nenechá_rozdelanou_prijemku(client, uzivatel, sklad):
    """
    Stejná past jako u importu z fotky: `transaction.atomic` roluje zpět
    výjimku, ne `return redirect()`.
    """
    session = client.session
    session['supplier_csv_receipt_data'] = {
        'receipt_number': 'F1', 'receipt_date': '2026-09-02', 'supplier': 'Makro',
        'items': [{
            'item_id': '1', 'item_name': 'Mouka', 'quantity': '1', 'unit': 'ks',
            'unit_mapped': 'ks', 'price_per_unit_net': '10',
            'price_per_unit_gross': '11.2', 'vat_rate': '12',
            'vat_amount': '1.2', 'total_price': '11.2',
        }],
    }
    session['supplier_csv_default_warehouse'] = str(sklad.id)
    session.save()

    response = client.post(reverse('inventory:supplier_csv_import_step3'), {}, follow=True)

    assert 'Musíte vybrat surovinu' in response.content.decode()
    assert GoodsReceipt.objects.count() == 0


# --- Jednotky ---

@pytest.fixture
def ocr_pekarna(monkeypatch):
    """Doklad pekárny: rohlíky po kartonech, mouka po kilech."""
    from apps.inventory.ocr import client

    annotation = {
        'dodavatel': {'nazev': 'Pekárna Podlesí s.r.o.', 'ico': '77788899'},
        'doklad': {'cislo_dokladu': 'DL2026/0001', 'typ_dokladu': 'dodaci_list',
                   'datum_vystaveni': '2026-09-02'},
        'ceny_jsou_s_dph': False,
        'polozky': [
            {'nazev': 'Rohlík tukový karton', 'mnozstvi': 3, 'jednotka': 'bal',
             'cena_za_mj': 120, 'dph_procenta': 12, 'cena_bez_dph': 360},
            {'nazev': 'Mouka hladká', 'mnozstvi': 2, 'jednotka': 'kg',
             'cena_za_mj': 30, 'dph_procenta': 12, 'cena_bez_dph': 60},
        ],
        'celkem': {'zaklad': 420, 'dph': 50.4, 'celkem_kc': 470.4},
    }
    monkeypatch.setattr(client, 'run_ocr',
                        lambda *a, **kw: {'annotation': annotation, 'markdown': '', 'raw': {}})
    monkeypatch.setattr(client, 'prepare_image', lambda b, n: (b'x', 'image/jpeg'))
    return annotation


@pytest.fixture
def pekarna():
    return Supplier.objects.create(
        name='Pekárna Podlesí', slug='pekarna-p', ico='77788899',
    )


def test_jednoznacny_prevod_naskladni_spravne_mnozstvi(client, uzivatel, sklad,
                                                       pekarna, media_root, ocr_pekarna):
    """Doklad uvádí 2 kg, sklad vede mouku v gramech."""
    mouka = Ingredient.objects.create(name='Mouka hladká', unit='g', base_unit='g')
    nahrat_doklad(client, sklad)
    client.get(reverse('inventory:photo_import_step2'))

    data = client.session['photo_receipt_data']
    radek = next(i for i, item in enumerate(data['items'])
                 if item['item_name'] == 'Mouka hladká')
    assert data['items'][radek]['unit_factor'] == '1000'

    client.post(reverse('inventory:photo_import_step3'), {
        'receipt_number': data['receipt_number'],
        'receipt_date': data['receipt_date'],
        'supplier_obj': pekarna.id,
        f'include_{radek}': 'on',
        f'ingredient_{radek}': mouka.id,
        f'quantity_{radek}': data['items'][radek]['quantity'],
        f'unit_factor_{radek}': data['items'][radek]['unit_factor'],
        f'warehouse_{radek}': sklad.id,
    }, follow=True)

    polozka = GoodsReceiptItem.objects.get()
    assert polozka.quantity == Decimal('2000')
    # Celková cena řádku se převodem změnit nesmí.
    assert polozka.quantity * polozka.price_without_vat == Decimal('60')


def test_nejednoznacne_jednotky_zastavi_import(client, uzivatel, sklad, pekarna,
                                               media_root, ocr_pekarna):
    """Kolik rohlíků je v kartonu, systém neví – hádat nesmí."""
    rohlik = Ingredient.objects.create(name='Rohlík', unit='ks', base_unit='ks')
    nahrat_doklad(client, sklad)
    response = client.get(reverse('inventory:photo_import_step2'))

    assert 'Doplňte, kolik' in response.content.decode()

    data = client.session['photo_receipt_data']
    radek = next(i for i, item in enumerate(data['items'])
                 if 'Rohlík' in item['item_name'])
    assert data['items'][radek]['needs_unit_check'] is True

    response = client.post(reverse('inventory:photo_import_step3'), {
        'receipt_number': data['receipt_number'],
        'receipt_date': data['receipt_date'],
        'supplier_obj': pekarna.id,
        f'include_{radek}': 'on',
        f'ingredient_{radek}': rohlik.id,
        f'quantity_{radek}': '3',
        f'unit_factor_{radek}': '1',
        f'warehouse_{radek}': sklad.id,
    }, follow=True)

    assert 'Doplňte přepočet' in response.content.decode()
    assert GoodsReceipt.objects.count() == 0


def test_zadany_prepocet_se_pouzije_i_zapamatuje(client, uzivatel, sklad, pekarna,
                                                 media_root, ocr_pekarna):
    rohlik = Ingredient.objects.create(name='Rohlík', unit='ks', base_unit='ks')
    nahrat_doklad(client, sklad)
    client.get(reverse('inventory:photo_import_step2'))
    data = client.session['photo_receipt_data']
    radek = next(i for i, item in enumerate(data['items'])
                 if 'Rohlík' in item['item_name'])

    client.post(reverse('inventory:photo_import_step3'), {
        'receipt_number': data['receipt_number'],
        'receipt_date': data['receipt_date'],
        'supplier_obj': pekarna.id,
        f'include_{radek}': 'on',
        f'ingredient_{radek}': rohlik.id,
        f'quantity_{radek}': '3',
        f'unit_factor_{radek}': '12',
        f'warehouse_{radek}': sklad.id,
    }, follow=True)

    polozka = GoodsReceiptItem.objects.get()
    assert polozka.quantity == Decimal('36')
    assert polozka.price_without_vat == Decimal('10')

    # Příště už se ptát nemusí.
    alias = SupplierItemAlias.objects.get(raw_name='Rohlík tukový karton')
    assert alias.unit_factor == Decimal('12')


def test_zaporny_prepocet_se_odmitne(client, uzivatel, sklad, pekarna,
                                     media_root, ocr_pekarna):
    rohlik = Ingredient.objects.create(name='Rohlík', unit='ks', base_unit='ks')
    nahrat_doklad(client, sklad)
    data = client.session['photo_receipt_data']

    response = client.post(reverse('inventory:photo_import_step3'), {
        'receipt_number': data['receipt_number'],
        'receipt_date': data['receipt_date'],
        'supplier_obj': pekarna.id,
        'include_0': 'on',
        'ingredient_0': rohlik.id,
        'quantity_0': '3',
        'unit_factor_0': '-5',
        'warehouse_0': sklad.id,
    }, follow=True)

    assert 'kladné číslo' in response.content.decode()
    assert GoodsReceipt.objects.count() == 0


# --- Pojistky v kroku 2 ---

def test_duplicitni_doklad_se_ohlasi(client, uzivatel, sklad, bolero, suroviny,
                                     media_root, ocr_bez_site):
    nahrat_doklad(client, sklad)
    odeslat_prijemku(client, sklad, suroviny)

    nahrat_doklad(client, sklad, nazev='znovu.jpg')
    response = client.get(reverse('inventory:photo_import_step2'))

    assert 'už v systému je' in response.content.decode()


def test_skok_v_cene_se_ohlasi(client, uzivatel, sklad, bolero, suroviny,
                               media_root, ocr_bez_site):
    """Rajče se dosud kupovalo za 6,15 Kč/kg, doklad říká 61,49 Kč/kg."""
    from apps.inventory.models import IngredientPriceHistory
    from django.utils import timezone

    IngredientPriceHistory.objects.create(
        ingredient=suroviny['rajce'], warehouse=sklad,
        price=Decimal('6.15'), valid_from=timezone.now(),
    )
    nahrat_doklad(client, sklad)

    response = client.get(reverse('inventory:photo_import_step2'))

    assert 'proti poslední známé' in response.content.decode()


def test_csv_import_prepocte_jednoznacne_jednotky(client, uzivatel, sklad):
    """
    Import z CSV nemá v rozhraní kde poměr zadat, ale kilogramy na gramy
    převést umí – poměr je daný.
    """
    mouka = Ingredient.objects.create(name='Mouka', unit='g', base_unit='g')
    session = client.session
    session['supplier_csv_receipt_data'] = {
        'receipt_number': 'F2', 'receipt_date': '2026-09-02', 'supplier': 'Makro',
        'items': [{
            'item_id': '1', 'item_name': 'Mouka hladká', 'quantity': '2',
            'unit': 'kg', 'unit_mapped': 'kg', 'price_per_unit_net': '30',
            'price_per_unit_gross': '33.6', 'vat_rate': '12',
            'vat_amount': '3.6', 'total_price': '67.2',
        }],
    }
    session['supplier_csv_default_warehouse'] = str(sklad.id)
    session.save()

    client.post(reverse('inventory:supplier_csv_import_step3'), {
        'ingredient_0': mouka.id, 'warehouse_0': sklad.id,
    }, follow=True)

    polozka = GoodsReceiptItem.objects.get()
    assert polozka.quantity == Decimal('2000')
    assert polozka.quantity * polozka.price_without_vat == Decimal('60')


def test_csv_import_oznaci_nejednoznacne_jednotky_a_neda_potvrdit(client, uzivatel, sklad):
    """
    Kusy na kilogramy se tiše přepočítat nedají. Import projde, ale položka
    se označí a příjemka se nepotvrdí – kontrola sedí tam, kde se mění sklad,
    ne v importu, který jde obejít.
    """
    rajce = Ingredient.objects.create(name='Rajče', unit='kg', base_unit='kg')
    session = client.session
    session['supplier_csv_receipt_data'] = {
        'receipt_number': 'F3', 'receipt_date': '2026-09-02', 'supplier': 'Makro',
        'items': [{
            'item_id': '1', 'item_name': 'Rajče volné', 'quantity': '6',
            'unit': 'ks', 'unit_mapped': 'ks', 'price_per_unit_net': '10',
            'price_per_unit_gross': '11.2', 'vat_rate': '12',
            'vat_amount': '1.2', 'total_price': '67.2',
        }],
    }
    session['supplier_csv_default_warehouse'] = str(sklad.id)
    session.save()

    client.post(reverse('inventory:supplier_csv_import_step3'), {
        'ingredient_0': rajce.id, 'warehouse_0': sklad.id,
    }, follow=True)

    polozka = GoodsReceiptItem.objects.get()
    # Množství se nehádá – zůstává tak, jak přišlo z dokladu.
    assert polozka.quantity == Decimal('6')
    assert polozka.source_unit == 'ks'
    assert polozka.has_unit_conflict is True

    prijemka = GoodsReceipt.objects.get()
    response = client.post(
        reverse('inventory:goods_receipt_confirm', args=[prijemka.pk]), follow=True,
    )

    prijemka.refresh_from_db()
    assert prijemka.status == GoodsReceipt.Status.DRAFT
    # Uživatel skončí tam, kde se přepočet dá doplnit, ne na hlášce bez cesty ven.
    assert response.redirect_chain[-1][0] == reverse(
        'inventory:goods_receipt_resolve_units', args=[prijemka.pk]
    )
    # Do skladu se nic nedostalo.
    assert not StockItem.objects.filter(ingredient=rajce).exists()


def test_pdf_sken_se_posle_jako_pdf(client, uzivatel, sklad, media_root):
    """Doklad nahraný jako PDF nesmí odejít s hlavičkou obrázku."""
    from apps.inventory.ocr.storage import save_scan

    scan = GoodsReceiptScan.objects.create(
        file_path=save_scan(b'%PDF-1.4', 'application/pdf'),
        original_filename='doklad.pdf', uploaded_by=uzivatel,
    )

    response = client.get(reverse('inventory:photo_import_scan', args=[scan.pk]))

    assert response.status_code == 200
    assert response['Content-Type'] == 'application/pdf'


def test_obrazkovy_sken_se_posle_jako_obrazek(client, uzivatel, sklad, media_root):
    from apps.inventory.ocr.storage import save_scan

    scan = GoodsReceiptScan.objects.create(
        file_path=save_scan(b'fotka', 'image/jpeg'),
        original_filename='doklad.jpg', uploaded_by=uzivatel,
    )

    response = client.get(reverse('inventory:photo_import_scan', args=[scan.pk]))

    assert response['Content-Type'] == 'image/jpeg'
