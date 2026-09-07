"""
Testy normalizace OCR dokladů.

Běží nad anotacemi ve `test/fixtures/ocr`, takže nesahají na síť ani na API.
Fixtury jsou verzované – složka `backups/` je v .gitignore, takže testy nad ní
by na čistém klonu tiše přeskočily a nikdo by si toho nevšiml.

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

FIXTURE_ROOT = Path(settings.BASE_DIR) / 'test' / 'fixtures' / 'ocr'

# Reálné skeny od dodavatelů, pokud je má vývojář po ruce. Nejsou v gitu,
# takže se na nich nesmí zakládat základní pokrytí – jen rozšiřují záběr.
REAL_SCANS = Path(settings.BASE_DIR) / 'backups' / 'bolero'


def load(name):
    return to_receipt_data(load_fixture(FIXTURE_ROOT / name)['annotation'])


def all_fixtures():
    return sorted(path.parent.name for path in FIXTURE_ROOT.glob('*/document-annotation.json'))


def test_prodejka_hlavicka():
    data = load('prodejka_zelenina')

    assert data['source'] == 'ocr'
    assert data['receipt_number'] == 'PR20260001'
    assert data['receipt_date'] == date(2026, 8, 24)
    assert data['doc_type'] == 'prodejka'
    assert data['supplier_ico'] == '11122233'
    assert data['totals']['total'] == Decimal('1219')


def test_polozky_a_ceny():
    data = load('prodejka_zelenina')
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
    data = load('prodejka_zelenina')
    posledni = data['items'][-1]

    assert posledni['item_name'] == 'Zaokrouhlení'
    assert posledni['is_ignored'] is True
    assert posledni['ignore_reason'] == 'zaokrouhlení'
    # Ostatní řádky zbožní jsou.
    assert all(not item['is_ignored'] for item in data['items'][:-1])


def test_zaporne_zaokrouhleni_se_precte_se_znamenkem():
    data = load('bez_hlavicky')
    posledni = data['items'][-1]

    assert posledni['is_ignored'] is True
    assert posledni['price_per_unit_net'] == Decimal('-0.32')


def test_jednotka_baleni_se_mapuje():
    """Dodavatel fakturuje kartony, systém je vede jako balení."""
    data = load('dodaci_list_pekarna')
    rohlik = next(i for i in data['items'] if i['item_name'].startswith('Rohlík'))

    assert rohlik['unit'] == 'bal'
    assert rohlik['unit_mapped'] == 'bal'
    assert rohlik['quantity'] == Decimal('3.000')


def _minimalni_anotace(polozka):
    """
    Kostra anotace jen s tím, co `to_receipt_data` potřebuje – pro testy,
    které se nezajímají o hlavičku dokladu, jen o zpracování jednoho řádku.
    """
    return {
        'dodavatel': {'nazev': 'MAKRO Cash & Carry ČR s.r.o.', 'ico': '26450691'},
        'doklad': {'cislo_dokladu': 'D1', 'datum_vystaveni': '2026-09-07'},
        'ceny_jsou_s_dph': False,
        'polozky': [polozka],
    }


def test_pocet_v_baleni_se_prenasobi_do_mnozstvi():
    """
    MAKRO (webshop dodací list) udává zvlášť počet balení a kolik je
    v jednom balení – skladové množství je jejich součin, jednotková cena
    zůstává za jeden kus.
    """
    data = to_receipt_data(_minimalni_anotace({
        'nazev': 'Srdíčko jogurt ovocný 125g', 'mnozstvi': 10,
        'jednotka': 'ks', 'pocet_v_baleni': 20, 'cena_za_mj': 7.48,
        'dph_procenta': 12, 'cena_bez_dph': 1496.40,
    }))
    polozka = data['items'][0]

    assert polozka['quantity'] == Decimal('200.000')
    assert polozka['price_per_unit_net'] == Decimal('7.48')
    assert polozka['total_price_net'] == Decimal('1496.40')


def test_pocet_v_baleni_bez_jednotkove_ceny_se_dopocte_spravne():
    """
    Chybí-li cena_za_mj, jednotková cena se dopočte z řádkového součtu –
    ten je ale za VŠECHNY kusy, ne za balení, takže se musí dělit už
    přenásobeným množstvím. Jinak by cena za kus vyšla pocet_v_baleni-krát
    předražená (skladová hodnota by pak byla stejně-krát nadhodnocená).
    """
    data = to_receipt_data(_minimalni_anotace({
        'nazev': 'Srdíčko jogurt ovocný 125g', 'mnozstvi': 10,
        'jednotka': 'ks', 'pocet_v_baleni': 20,
        'dph_procenta': 12, 'cena_bez_dph': 1496.40,
    }))
    polozka = data['items'][0]

    assert polozka['quantity'] == Decimal('200.000')
    assert polozka['price_per_unit_net'] == Decimal('7.48')
    assert polozka['total_price_net'] == Decimal('1496.40')


def test_bez_pocet_v_baleni_zustava_mnozstvi_beze_zmeny():
    """Doklady bez rozlišení balení (drtivá většina) se chovají jako dřív."""
    data = to_receipt_data(_minimalni_anotace({
        'nazev': 'Rajče keř TUR', 'mnozstvi': 6.7, 'jednotka': 'kg',
        'cena_za_mj': 54.90, 'dph_procenta': 12,
    }))
    polozka = data['items'][0]

    assert polozka['quantity'] == Decimal('6.700')


def test_makro_kod_sazby_23_se_prelozi_na_12_procent():
    """
    Účtenky MAKRO z pokladny tisknou u položek místo procent interní kód
    sazbové skupiny – 23 vždycky znamená 12 %. Žádná legitimní sazba 23 %
    v ČR není, takže je bezpečné to opravit i jako pojistku v kódu, ne se
    spoléhat jen na to, že to model podle promptu přeloží sám.
    """
    data = to_receipt_data(_minimalni_anotace({
        'nazev': 'FL mléko TRV.1,5% 1L', 'mnozstvi': 5, 'jednotka': 'ks',
        'cena_za_mj': 9.90, 'dph_procenta': 23, 'cena_bez_dph': 49.50,
    }))
    polozka = data['items'][0]

    assert polozka['vat_rate'] == Decimal('12')
    assert not any('nejbližší platná sazba' in w for w in data['warnings'])


def _anotace_s_typem_dokladu(ico, typ_dokladu, polozka):
    return {
        'dodavatel': {'nazev': 'Test s.r.o.', 'ico': ico},
        'doklad': {'cislo_dokladu': 'D1', 'datum_vystaveni': '2026-09-07',
                   'typ_dokladu': typ_dokladu},
        'ceny_jsou_s_dph': False,
        'polozky': [polozka],
    }


def test_makro_pokladna_kod_sazby_0_se_prelozi_na_21_procent():
    """
    Kód 0 znamená 21 % jen na pokladní účtence MAKRO – IČO MAKRO a typ
    dokladu "faktura" (podle čárového kódu "FAKTURA – DAŇOVÝ DOKLAD").
    """
    data = to_receipt_data(_anotace_s_typem_dokladu('26450691', 'faktura', {
        'nazev': 'LANZA PWD COLOR 1X5,85kg', 'mnozstvi': 1, 'jednotka': 'ks',
        'cena_za_mj': 329.00, 'dph_procenta': 0, 'cena_bez_dph': 329.00,
    }))

    assert data['items'][0]['vat_rate'] == Decimal('21')


def test_makro_webshop_nulova_sazba_zustava_nulova():
    """Stejné IČO MAKRO, ale webshopový dodací list – kód 0 se nepřekládá."""
    data = to_receipt_data(_anotace_s_typem_dokladu('26450691', 'dodaci_list', {
        'nazev': 'Kniha o vaření', 'mnozstvi': 1, 'jednotka': 'ks',
        'cena_za_mj': 100, 'dph_procenta': 0, 'cena_bez_dph': 100,
    }))

    assert data['items'][0]['vat_rate'] == Decimal('0')


def test_jiny_dodavatel_nulova_sazba_zustava_nulova():
    """Jiné IČO než MAKRO, i s typem dokladu "faktura" – nepřekládá se."""
    data = to_receipt_data(_anotace_s_typem_dokladu('12345678', 'faktura', {
        'nazev': 'Kniha o vaření', 'mnozstvi': 1, 'jednotka': 'ks',
        'cena_za_mj': 100, 'dph_procenta': 0, 'cena_bez_dph': 100,
    }))

    assert data['items'][0]['vat_rate'] == Decimal('0')


def test_ceny_bez_dph_jsou_rozpoznany_i_bez_priznaku():
    """Anotace z playgroundu příznak `ceny_jsou_s_dph` nemá, odvodíme si ho."""
    payload = load_fixture(FIXTURE_ROOT / 'prodejka_zelenina')
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
    data = load('bez_hlavicky')

    assert data['receipt_number'] == ''
    assert data['supplier_ico'] == ''
    assert data['receipt_date'] == date.today()
    assert any('číslo dokladu' in w for w in data['warnings'])
    assert any('IČO' in w for w in data['warnings'])
    # Zboží se přesto přečetlo.
    assert any(not item['is_ignored'] for item in data['items'])


@pytest.mark.skipif(not REAL_SCANS.exists(), reason='Reálné skeny nejsou v gitu.')
@pytest.mark.parametrize('fixture_dir', sorted(
    (p.parent for p in REAL_SCANS.glob('*/document-annotation.json'))
    if REAL_SCANS.exists() else []
))
def test_realne_skeny_projdou_souctovou_kontrolou(fixture_dir):
    """
    Rozšiřující pokrytí nad skutečnými doklady. Složka `backups/` není v gitu,
    takže tenhle test na čistém klonu neběží – základní pokrytí stojí na
    fixturách v `test/fixtures/ocr`.
    """
    data = to_receipt_data(load_fixture(fixture_dir)['annotation'])

    assert [w for w in data['warnings'] if 'Součet položek' in w] == []


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
    # Jednotka nemusí stát první – doklady ji píšou i za množstvím.
    ('6,70 kg', 'kg'),
    ('12 ks', 'ks'),
    ('1,5 l', 'l'),
    ('', 'ks'),
    ('neznámá', 'ks'),
    ('2,5 neznámá', 'ks'),
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
    # Reálné MAKRO fráze – "sleva" a "kup víc = plať méň" nebývají na
    # začátku řádku, takže by je samotná předpona nechytla.
    ('Množstevní sleva při koupi 5 bal. a více', True),
    ('Kup více = plať méně - ARO rajčat. pyré', True),
    # Zboží se stejným kořenem se ignorovat nesmí.
    # Sporné slovo samo o sobě neignorujeme – tohle je zboží, ne obal.
    ('Paleta chleba konzumního', False),
    ('Rohlík tukový 43g', False),
    ('Chléb konzumní kmínový 1200g', False),
])
def test_klasifikace_obalu_a_sluzeb(nazev, ocekavano):
    is_ignored, _reason = classify_line(nazev)
    assert is_ignored is ocekavano


def test_pripravena_fotka_se_neprekoduje_znovu(monkeypatch):
    """
    Pohled si obrázek zmenší sám kvůli uložení skenu. Kdyby ho `run_ocr`
    překódoval znovu, ubere se kvalita a čas nadarmo.
    """
    from apps.inventory.ocr import client

    volani = []
    monkeypatch.setattr(client, 'prepare_image',
                        lambda b, n: volani.append(n) or (b, 'image/jpeg'))
    monkeypatch.setattr(client.settings, 'MISTRAL_API_KEY', 'testovaci-klic',
                        raising=False)

    try:
        client.run_ocr(b'uz-zmensene', 'doklad.jpg', mime_type='image/jpeg')
    except Exception:
        # Na síť se stejně nedostaneme, zajímá nás jen příprava obrázku.
        pass

    assert volani == []
