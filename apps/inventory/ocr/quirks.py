"""
Zvláštnosti jednotlivých dokladů, které OCR schéma samo nevyřeší.

Dvě věci, které se liší dodavatel od dodavatele:

1. Řádky, které nejsou zboží (zaokrouhlení, doprava, vratné obaly). Do skladu
   nepatří, ale v součtu dokladu jsou, takže je nesmíme jen zahodit.
2. Zápis měrných jednotek. Každý doklad si píše jednotky po svém.
"""
import re

from apps.inventory.naming import strip_diacritics

# Řádky, které nejdou na sklad. Porovnává se bez diakritiky, protože dodavatelé
# je píšou různě („Zaokrouhlení", „Zaokrouhleni DPH").
#
# Klíčová slova hledáme kdekoli v názvu – obalový materiál se často píše
# s přívlastkem vepředu („Vratné přepravky", „Zálohované palety"). Předpony
# hledáme jen na začátku, protože jako součást názvu zboží by braly i platné
# položky.
#
# U sporných slov schválně neignorujeme. Neoznačený nezbožní řádek uživatel
# v kroku 2 odškrtne a hned ho vidí; nesprávně označený zbožní řádek naopak
# tiše zmizí ze skladu. Proto tu není samotné „paleta" – „Paleta chleba" je
# zboží. Obalové řádky chytnou přívlastky „vratný" a „zálohovaný“, zbytek
# se doučí přes alias dodavatele.
NON_STOCK_KEYWORDS = (
    ('zaokrouhlen', 'zaokrouhlení'),
    ('doprav', 'doprava'),
    ('prepravn', 'přepravné'),
    ('vratn', 'vratný obal'),
    ('zalohovan', 'zálohovaný obal'),
    ('zaloha na obal', 'záloha na obal'),
    ('balne', 'balné'),
    ('manipulacni poplatek', 'manipulační poplatek'),
)

NON_STOCK_PREFIXES = (
    ('prepravka', 'přepravka'),
    ('poplatek', 'poplatek'),
    ('sleva', 'sleva'),
    ('bonus', 'bonus'),
    ('obaly', 'obaly'),
)

# Zápisy jednotek, na které jsme narazili, na jednotky používané v systému.
UNIT_MAPPING = {
    'kg': 'kg', 'kilogram': 'kg', 'kgm': 'kg',
    'g': 'g', 'gram': 'g', 'grm': 'g',
    'l': 'l', 'ltr': 'l', 'litr': 'l',
    'ml': 'ml',
    'ks': 'ks', 'kus': 'ks', 'kusy': 'ks', 'pc': 'ks', 'pcs': 'ks', 'piece': 'ks',
    'bal': 'bal', 'balen': 'bal', 'bx': 'bal', 'box': 'bal', 'bag': 'bal',
    'kart': 'bal', 'karton': 'bal', 'ca': 'bal', 'ct': 'bal',
    'sw': 'ks',
}


def classify_line(name):
    """
    Rozhodne, jestli je řádek zboží.

    Returns:
        (is_ignored: bool, reason: str) – reason je prázdný u zboží.
    """
    if not name or not name.strip():
        return True, 'prázdný název'

    haystack = strip_diacritics(name).lower().strip()

    for keyword, label in NON_STOCK_KEYWORDS:
        # Hranice slova zleva, aby „doprav" nechytlo nic uvnitř jiného slova.
        if re.search(rf'\b{keyword}', haystack):
            return True, label

    for prefix, label in NON_STOCK_PREFIXES:
        if haystack.startswith(prefix):
            return True, label

    return False, ''


def map_unit(unit, fallback='ks'):
    """Převede jednotku z dokladu na jednotku používanou v systému."""
    if not unit:
        return fallback

    key = strip_diacritics(str(unit)).lower().strip().rstrip('.')
    if key in UNIT_MAPPING:
        return UNIT_MAPPING[key]

    # Doklady občas píšou jednotku spolu s množstvím („6,70 kg") nebo
    # s upřesněním („kg netto"). Zkusíme první slovo.
    first_word = re.split(r'[\s/]+', key)[0] if key else ''
    return UNIT_MAPPING.get(first_word, fallback)
