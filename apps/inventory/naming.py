"""
Normalizace názvů položek z dodavatelských dokladů.

Dodavatelé píšou stejné zboží pokaždé jinak. Ze `backups/bolero`:

    Jablko Gala IT
    Jablko Golden IT
    Jabíko Pinova DE            (překlep z OCR)
    Cibule cal.70/90 25kg NL
    Cibule cal 70/90 10kg AT/NL
    Mrkev 5kg igelít NL
    Banán ECU "akce"

Z každého názvu děláme dva klíče:

- `normalize_name` → `raw_key`: název bez diakritiky a interpunkce. Slouží
  k přesné shodě „tenhle řetězec už jsem od tohohle dodavatele viděl".
- `core_name` → `core_key`: raw_key zbavený země původu, gramáže, obalu
  a promo poznámek. Slouží k tomu, aby `Jablko Gala IT` a `Jablko Gala PL`
  spadly do stejné přihrádky.

Modul schválně nesahá na Django ani na modely – importuje ho `models.py`,
takže jakýkoli import zpět by udělal kruh.
"""
import re
import unicodedata

# Dvou- až třípísmenné zkratky velkými písmeny na konci názvu bývají země
# původu. Nedržíme jejich seznam – pravidlo se pozná podle velikosti písmen
# v původním názvu, takže funguje i pro zemi, kterou jsme ještě neviděli.
# Výjimky jsou zkratky, které o zboží něco říkají.
KEEP_UPPERCASE = {'bio', 'xxl', 'xl', 'uht', 'led', 'psc'}

# Slova popisující obal, ne zboží. Držíme krátký seznam – „balená" u okurky
# nebo „volné" u rajčat naopak rozlišuje dvě různé položky, ta tu nejsou.
PACKAGING_WORDS = {
    'igelit', 'sacek', 'sitka', 'karton', 'kartonu', 'kbelik', 'folie', 'doza',
}

# Čárový kód dodavatel připisuje do názvu (`GTIN: 8594001345724`); samotné
# číslo odstraní NUMERIC_TOKEN_RE, ale slovo `gtin` a oddělovač `_` by zůstaly.
BARCODE_WORDS = {'gtin', 'gtn', '_'}

# Promo poznámky.
PROMO_WORDS = {'akce', 'akcni', 'sleva', 'vyprodej', 'novinka'}

# Gramáž, počty kusů a kalibrace. „cal.70/90" je kalibr cibule, ne název.
NUMERIC_TOKEN_RE = re.compile(
    r'^\d+(?:[.,]\d+)?(?:kg|dkg|g|l|ml|ks|x|%)?$'
)
# Jednotka oddělená mezerou od čísla (`2,25 KG`, `1 l`) – číslo odpadne samo,
# ale jednotka by v klíči zůstala.
UNIT_TOKEN_RE = re.compile(r'^(?:kg|dkg|g|l|ml|ks)$')
CALIBER_TOKEN_RE = re.compile(r'^cal\.?\d*$')

# Zkratky a jiné zápisy téhož slova → jedno kanonické slovo. Klíče jsou tvar
# po `normalize_name` (bez diakritiky, malými). Aplikuje se po odstranění šumu
# na každý token, tedy i na názvy surovin v systému: obě strany porovnání se
# tak dostanou do stejného tvaru. Dopisovat jen to, co se v dokladech opravdu
# objevilo (měří `manage.py replay_matching`); nespekulovat do zásoby.
SYNONYMS = {
    'vepr': 'veprova',
    'cheddar': 'cedar',
    'dzem': 'marmelada',
    'puding': 'pudink',
    'bezlepko': 'bezlepkovy',
    'melloun': 'meloun',
    'mysli': 'mussli',
    'musli': 'mussli',
}

# Text v uvozovkách a závorkách je skoro vždy poznámka, ne název.
BRACKETED_RE = re.compile(r'["„“\'(\[][^"„“\')\]]*["„“\')\]]')

SEPARATOR_RE = re.compile(r'[\s/\\,;:+]+')
# Pro core_key dělíme i na tečce, jinak zůstane „cal.70" v jednom kuse
# a kalibrace se nepozná. V raw_key na tom nezáleží, tečku tam stejně
# smaže odstranění interpunkce.
# Hvězdička je zápis balení (`4*500G`, `1*5KG`): bez dělení by se token
# `4 500g` normalizoval až uvnitř a pravidlo na čísla by ho nepoznalo.
CORE_SPLIT_RE = re.compile(r'[\s/\\,;:+.*]+')
PUNCTUATION_RE = re.compile(r'[^\w\s]')
WHITESPACE_RE = re.compile(r'\s+')


def strip_diacritics(text):
    """Odstraní diakritiku, aby šlo porovnávat bez ohledu na háčky a čárky."""
    normalized = unicodedata.normalize('NFKD', text)
    return ''.join(char for char in normalized if not unicodedata.combining(char))


def normalize_name(name):
    """
    Klíč pro přesnou shodu: malá písmena, bez diakritiky a interpunkce.

    >>> normalize_name('Cibule cal.70/90 25kg NL')
    'cibule cal 70 90 25kg nl'
    """
    if not name:
        return ''

    text = strip_diacritics(str(name)).lower()
    text = SEPARATOR_RE.sub(' ', text)
    text = PUNCTUATION_RE.sub(' ', text)
    return WHITESPACE_RE.sub(' ', text).strip()


def core_name(name):
    """
    Klíč pro přihrádku: raw_key bez země, gramáže, obalu a promo poznámek.

    >>> core_name('Cibule cal.70/90 25kg NL')
    'cibule'
    >>> core_name('Jablko Gala IT')
    'jablko gala'
    >>> core_name('Banán ECU "akce"')
    'banan'

    Zbude-li po odstranění šumu prázdno, vracíme raw_key – prázdný klíč by
    slil dohromady položky, které spolu nesouvisí.
    """
    if not name:
        return ''

    # Poznámky v uvozovkách pryč ještě před normalizací, dokud jsou vidět.
    without_notes = BRACKETED_RE.sub(' ', str(name))

    # Země původu se pozná podle velkých písmen, takže původní tvar tokenu
    # potřebujeme vedle normalizovaného.
    original_tokens = CORE_SPLIT_RE.split(without_notes.strip())

    # Zkratku země pravidlo zahazuje kdekoli v názvu, i když stojí uprostřed
    # (`ZEL.POD SVÍČ.`). Varianta „jen na konci" se měřila přes `replay_matching`
    # a dopadla hůř (fuzzy přesnost 89 → 86 %, nepoznaných 49 → 52), protože
    # značky velkými písmeny (`ARO`, `BK`) jsou častější než zkratky slov.
    kept = []
    for original in original_tokens:
        token = normalize_name(original)
        if not token or _is_noise(token) or _is_country_code(token, original):
            continue
        kept.append(SYNONYMS.get(token, token))

    core = WHITESPACE_RE.sub(' ', ' '.join(kept)).strip()
    return core or normalize_name(name)


def _is_noise(token):
    """Rozhodne, jestli token popisuje obal, gramáž nebo promo, ne zboží."""
    if token in PACKAGING_WORDS or token in PROMO_WORDS or token in BARCODE_WORDS:
        return True

    return bool(
        NUMERIC_TOKEN_RE.match(token) or CALIBER_TOKEN_RE.match(token)
        or UNIT_TOKEN_RE.match(token)
    )


def _is_country_code(token, original):
    """Zkratka země: 2–3 písmena, v originále velkými, bez číslic."""
    stripped = PUNCTUATION_RE.sub('', original)
    return (
        2 <= len(stripped) <= 3
        and stripped.isalpha()
        and stripped.isupper()
        and token not in KEEP_UPPERCASE
    )
