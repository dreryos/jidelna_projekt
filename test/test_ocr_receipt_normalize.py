"""
Testy normalizace OCR dokladů.

Běží nad reálnými anotacemi z backups/bolero, takže nesahají na síť ani na API.
Pokrývají:

- převod anotace na kanonický receipt_data
- odfiltrování nezbožních řádků (zaokrouhlení)
- odvození, zda jsou ceny na dokladu s DPH, nebo bez
- kontrolu součtu proti základu daně na dokladu
- chování u nečitelného dokladu (varování místo výjimky)
"""
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from django.conf import settings

from apps.inventory.ocr.client import OcrError, load_fixture
from apps.inventory.ocr.normalize import to_receipt_data
from apps.inventory.ocr.quirks import classify_line, map_unit

FIXTURE_ROOT = Path(settings.BASE_DIR) / 'backups' / 'bolero'

pytestmark = pytest.mark.skipif(
    not FIXTURE_ROOT.exists(),
    reason='Chybí ukázkové OCR anotace v backups/bolero.',
)


def load(name):
    return to_receipt_data(load_fixture(FIXTURE_ROOT / name)['annotation'])


def all_fixtures():
    return sorted(path.parent.name for path in FIXTURE_ROOT.glob('*/document-annotation.json'))


def test_prodejka_hlavicka():
    data = load('1hsItXfw.jpg')

    assert data['source'] == 'ocr'
    assert data['receipt_number'] == 'PR20260548'
    assert data['receipt_date'] == date(2026, 8, 24)
    assert data['doc_type'] == 'prodejka'
    assert data['supplier_ico'] == '68524358'
    assert data['totals']['total'] == Decimal('1219')


def test_polozky_a_ceny():
    data = load('1hsItXfw.jpg')
    rajce = data['items'][0]

    assert rajce['item_name'] == 'Rajče keř TUR'
    assert rajce['quantity'] == Decimal('6.700')
    assert rajce['unit_mapped'] == 'kg'
    assert rajce['vat_rate'] == Decimal('12')
    # Doklad uvádí jednotkovou cenu bez DPH, cenu s DPH dopočítáváme.
    assert rajce['price_per_unit_net'] == Decimal('54.90')
    assert rajce['price_per_unit_gross'] == Decimal('61.49')
    assert rajce['vat_amount'] == Decimal('6.59')
    assert rajce['is_ignored'] is False


def test_zaokrouhleni_je_oznaceno_jako_nezbozni_radek():
    data = load('1hsItXfw.jpg')
    posledni = data['items'][-1]

    assert posledni['item_name'] == 'Zaokrouhlení'
    assert posledni['is_ignored'] is True
    assert posledni['ignore_reason'] == 'zaokrouhlení'
    # Ostatní řádky zbožní jsou.
    assert all(not item['is_ignored'] for item in data['items'][:-1])


def test_zaporne_zaokrouhleni_se_precte_se_znamenkem():
    data = load('a7Bds-5f.jpg')
    posledni = data['items'][-1]

    assert posledni['is_ignored'] is True
    assert posledni['price_per_unit_net'] == Decimal('-0.32')


def test_jednotka_ks_zustane_ks():
    data = load('Whb-Bubd.jpg')
    salat = next(item for item in data['items'] if item['item_name'].startswith('Salát'))

    assert salat['unit_mapped'] == 'ks'
    assert salat['quantity'] == Decimal('6.000')


def test_ceny_bez_dph_jsou_rozpoznany_i_bez_priznaku():
    """Anotace z playgroundu příznak `ceny_jsou_s_dph` nemá, odvodíme si ho."""
    payload = load_fixture(FIXTURE_ROOT / '1hsItXfw.jpg')
    assert 'ceny_jsou_s_dph' not in payload['annotation']

    data = to_receipt_data(payload['annotation'])
    assert data['prices_include_vat'] is False


@pytest.mark.parametrize('fixture_name', all_fixtures())
def test_soucet_polozek_sedi_se_zakladem_dane(fixture_name):
    """Všechny reálné doklady musí projít součtovou kontrolou."""
    data = load(fixture_name)

    soucet_warnings = [w for w in data['warnings'] if 'Součet položek' in w]
    assert soucet_warnings == [], soucet_warnings


def test_neprecteny_doklad_vraci_varovani_misto_vyjimky():
    """Sken bez hlavičky (jen razítko) se musí dát dokončit ručně."""
    data = load('mQQw0vKd.jpg')

    assert data['receipt_number'] == ''
    assert data['supplier_ico'] == ''
    assert data['receipt_date'] == date.today()
    assert any('číslo dokladu' in w for w in data['warnings'])
    assert any('IČO' in w for w in data['warnings'])
    # Zboží se přesto přečetlo.
    assert any(not item['is_ignored'] for item in data['items'])


def test_chybejici_fixtura_hlasi_srozumitelnou_chybu():
    with pytest.raises(OcrError, match='document-annotation.json'):
        load_fixture(FIXTURE_ROOT / 'neexistuje')


@pytest.mark.parametrize('nazev,ocekavano', [
    ('Zaokrouhlení', True),
    ('Zaokrouhleni DPH', True),
    ('Doprava', True),
    ('Vratné obaly', True),
    ('Přepravka plastová', True),
    ('Jablko Gala IT', False),
    ('Zelí bílé nové PL', False),
])
def test_klasifikace_radku(nazev, ocekavano):
    is_ignored, _reason = classify_line(nazev)
    assert is_ignored is ocekavano


@pytest.mark.parametrize('vstup,ocekavano', [
    ('kg', 'kg'),
    ('KG', 'kg'),
    ('ks', 'ks'),
    ('PC', 'ks'),
    ('karton', 'bal'),
    ('BX', 'bal'),
    ('kg netto', 'kg'),
    ('', 'ks'),
    ('neznámá', 'ks'),
])
def test_mapovani_jednotek(vstup, ocekavano):
    assert map_unit(vstup) == ocekavano


@pytest.mark.parametrize('filename', ['IMG_4821.HEIC', 'sken.heif', 'foto.jpg', 'sken.PNG'])
def test_podporovane_formaty_konci_jako_jpeg(filename):
    """
    Příjemky fotí víc lidí z různých telefonů. iPhone posílá HEIC, Android JPEG.
    Mistral HEIC nebere, takže všechno překódujeme na JPEG ještě před odesláním.
    """
    import io

    import pillow_heif
    from PIL import Image

    from apps.inventory.ocr.client import prepare_image

    pillow_heif.register_heif_opener()
    image = Image.new('RGB', (3000, 2000), 'white')
    buffer = io.BytesIO()
    if filename.lower().endswith(('.heic', '.heif')):
        pillow_heif.from_pillow(image).save(buffer, quality=60)
    else:
        image.save(buffer, format=Image.registered_extensions()[Path(filename).suffix.lower()])

    data, mime = prepare_image(buffer.getvalue(), filename)

    assert mime == 'image/jpeg'
    # Delší strana se zmenší, aby upload nebyl zbytečně velký.
    assert max(Image.open(io.BytesIO(data)).size) == 2200


def test_neznamy_format_hlasi_srozumitelnou_chybu():
    from apps.inventory.ocr.client import prepare_image

    with pytest.raises(OcrError, match='HEIC'):
        prepare_image(b'x', 'sken.bmp')


@pytest.mark.parametrize('nazev,ocekavano', [
    # Obalový materiál mívá přívlastek vepředu, klíčové slovo je až za ním.
    ('Vratné přepravky', True),
    ('Vratné obaly - lahve', True),
    ('Zálohované palety EUR', True),
    ('Vratné palety EUR', True),
    ('Doprava a manipulace', True),
    ('Sleva množstevní', True),
    # Zboží se stejným kořenem se ignorovat nesmí.
    # Sporné slovo samo o sobě neignorujeme – tohle je zboží, ne obal.
    ('Paleta chleba konzumního', False),
    ('Rohlík tukový 43g', False),
    ('Chléb konzumní kmínový 1200g', False),
])
def test_klasifikace_obalu_a_sluzeb(nazev, ocekavano):
    is_ignored, _reason = classify_line(nazev)
    assert is_ignored is ocekavano
