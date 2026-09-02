"""
Testy normalizace názvů položek z dodavatelských dokladů.

Vstupy jsou skutečné názvy z `backups/bolero` a ze syntetického dodacího listu
pekárny. `raw_key` má rozlišovat, `core_key` slučovat.
"""
import pytest

from apps.inventory.naming import core_name, normalize_name, strip_diacritics


@pytest.mark.parametrize('vstup,ocekavano', [
    ('Rajče keř TUR', 'rajce ker tur'),
    ('Cibule cal.70/90 25kg NL', 'cibule cal 70 90 25kg nl'),
    ('Banán ECU "akce"', 'banan ecu akce'),
    ('', ''),
])
def test_raw_key_zachova_vse_krome_diakritiky_a_interpunkce(vstup, ocekavano):
    assert normalize_name(vstup) == ocekavano


@pytest.mark.parametrize('vstup,ocekavano', [
    # Země původu odpadá.
    ('Jablko Gala IT', 'jablko gala'),
    ('Okurka PL', 'okurka'),
    ('Mandarinka Clementina JAR', 'mandarinka clementina'),
    # Gramáž, kalibrace a obal taky.
    ('Cibule cal.70/90 25kg NL', 'cibule'),
    ('Mrkev 5kg igelít NL', 'mrkev'),
    ('Chléb konzumní kmínový 1200g', 'chleb konzumni kminovy'),
    # Promo poznámka v uvozovkách.
    ('Banán ECU "akce"', 'banan'),
    # Odrůda a popis zboží zůstávají – jsou to různé položky.
    ('Okurka balená NL', 'okurka balena'),
    ('Rajče volné NL', 'rajce volne'),
    # Zkratky, které o zboží něco říkají, se za zemi nepovažují.
    ('Mléko polotučné BIO 1,5l', 'mleko polotucne bio'),
])
def test_core_key_odstrani_sum(vstup, ocekavano):
    assert core_name(vstup) == ocekavano


def test_ruzny_zapis_teze_polozky_da_stejny_core_key():
    """Tyhle tři řádky jsou z různých dokladů, ale je to jedna surovina."""
    varianty = [
        'Cibule cal.70/90 25kg NL',
        'Cibule cal 70/90 10kg AT/NL',
        'Cibule cal.70/90 25kg CZ',
    ]
    assert len({core_name(v) for v in varianty}) == 1


def test_ruzne_odrudy_se_neslijí():
    """Země původu je šum, odrůda ne."""
    assert core_name('Jablko Gala IT') != core_name('Jablko Golden IT')


def test_kod_v_nazvu_se_nezahodi():
    """Číslo v alfanumerickém kódu nese význam, samotná gramáž ne."""
    assert core_name('Mouka hladká T530 1kg') == 'mouka hladka t530'


def test_prazdny_core_key_spadne_zpet_na_raw_key():
    """Název složený jen ze šumu nesmí skončit prázdným klíčem."""
    assert core_name('25kg NL') == normalize_name('25kg NL')


def test_odstraneni_diakritiky():
    assert strip_diacritics('Žluťoučký kůň') == 'Zlutoucky kun'
