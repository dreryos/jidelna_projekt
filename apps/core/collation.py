"""Česká kolace pro SQLite.

SQLite standardně řadí binárně podle UTF-8, takže názvy začínající na
Č, Š, Ž končí až za Z. Tato kolace implementuje řazení podle české
abecedy včetně spřežky "ch" (řadí se mezi H a I).

Registruje se pod názvem "czech" na každé SQLite připojení přes signál
``connection_created`` (viz apps/core/apps.py) a používá se v Meta.ordering
modelu Ingredient a v explicitních order_by pro vyhledávání surovin.
"""

# Primární pořadí písmen české abecedy. Písmena s diakritikou, která
# nejsou samostatnými písmeny abecedy (á, é, ě, í, ó, ú, ů, ý, ď, ť, ň),
# sdílí primární váhu se základním písmenem - o jejich pořadí rozhoduje
# až sekundární porovnání celých řetězců.
_ALPHABET = (
    ('a', 'á', 'ä'),
    ('b',),
    ('c',),
    ('č',),
    ('d', 'ď'),
    ('e', 'é', 'ě'),
    ('f',),
    ('g',),
    ('h',),
    ('ch',),
    ('i', 'í'),
    ('j',),
    ('k',),
    ('l',),
    ('m',),
    ('n', 'ň'),
    ('o', 'ó', 'ö'),
    ('p',),
    ('q',),
    ('r',),
    ('ř',),
    ('s',),
    ('š',),
    ('t', 'ť'),
    ('u', 'ú', 'ů', 'ü'),
    ('v',),
    ('w',),
    ('x',),
    ('y', 'ý'),
    ('z',),
    ('ž',),
)

_WEIGHTS = {
    char: weight
    for weight, group in enumerate(_ALPHABET)
    for char in group
}


def czech_sort_key(text):
    """Vrátí primární řadicí klíč pro český text.

    Znaky mimo abecedu (číslice, interpunkce) se řadí před písmena
    podle svého kódu, stejně jako v ASCII.
    """
    lowered = text.lower()
    key = []
    i = 0
    while i < len(lowered):
        if lowered[i] == 'c' and i + 1 < len(lowered) and lowered[i + 1] == 'h':
            key.append((1, _WEIGHTS['ch']))
            i += 2
            continue
        weight = _WEIGHTS.get(lowered[i])
        if weight is not None:
            key.append((1, weight))
        else:
            key.append((0, ord(lowered[i])))
        i += 1
    return key


def czech_collation(a, b):
    """Porovnávací funkce pro sqlite3.create_collation."""
    key_a = czech_sort_key(a)
    key_b = czech_sort_key(b)
    if key_a < key_b:
        return -1
    if key_a > key_b:
        return 1
    # Sekundární porovnání: rozliší diakritiku a velikost písmen
    # u řetězců se shodným primárním klíčem.
    return (a > b) - (a < b)


def register_czech_collation(sender=None, connection=None, **kwargs):
    """Handler signálu connection_created - registruje kolaci na SQLite."""
    if connection is not None and connection.vendor == 'sqlite':
        connection.connection.create_collation('czech', czech_collation)
