"""
Převody měrných jednotek mezi dodacím listem a skladem.

Sklad vede každou surovinu v jedné jednotce (`Ingredient.base_unit`) a
`GoodsReceiptItem.quantity` se do něj přičítá přímo. Dodavatel ale fakturuje
v tom, co se mu hodí – mouku po kilech i po pytlích, rohlíky po kusech
i po kartonech. Když se množství z dokladu zapíše bez převodu, naskladní se
nesmysl a nikdo si toho nevšimne, protože chybí až na inventuře.

Modul rozlišuje dva případy:

- **jednoznačný převod** (kg ↔ g, l ↔ ml) – dá se udělat sám, poměr je dán,
- **nejednoznačný převod** (ks → kg, bal → ks) – kolik váží jeden kus nebo
  kolik kusů je v balení ví jenom člověk. Tady se musí zeptat a odpověď
  si zapamatovat do aliasu dodavatele.

Modul nesahá na Django ani na modely, aby šel použít odkudkoli.
"""
from decimal import Decimal

# Jednotky, mezi kterými je poměr daný fyzikou, ne dohodou s dodavatelem.
# Klíčem je jednotka, hodnotou její velikost ve společné referenční jednotce.
UNIT_SCALES = {
    'kg': Decimal('1000'),
    'dkg': Decimal('10'),
    'g': Decimal('1'),
    'l': Decimal('1000'),
    'dl': Decimal('100'),
    'ml': Decimal('1'),
}

# Do jaké skupiny jednotka patří. Převádět se dá jen uvnitř skupiny –
# litry na kilogramy bez znalosti hustoty nepřevede nikdo.
UNIT_FAMILIES = {
    'kg': 'hmotnost', 'dkg': 'hmotnost', 'g': 'hmotnost',
    'l': 'objem', 'dl': 'objem', 'ml': 'objem',
    'ks': 'kus', 'bal': 'kus',
}


def normalize_unit(unit):
    return (unit or '').strip().lower().rstrip('.')


def conversion_factor(from_unit, to_unit):
    """
    Kolika jednotkami `to_unit` je jedna jednotka `from_unit`.

    >>> conversion_factor('kg', 'g')
    Decimal('1000')
    >>> conversion_factor('g', 'kg')
    Decimal('0.001')

    Returns:
        Decimal pro jednoznačný převod, jinak None. `None` neznamená chybu –
        znamená „tohle musí říct člověk".
    """
    source = normalize_unit(from_unit)
    target = normalize_unit(to_unit)

    if not source or not target:
        return None
    if source == target:
        return Decimal('1')

    if source not in UNIT_SCALES or target not in UNIT_SCALES:
        return None
    if UNIT_FAMILIES.get(source) != UNIT_FAMILIES.get(target):
        return None

    return UNIT_SCALES[source] / UNIT_SCALES[target]


def units_are_compatible(from_unit, to_unit):
    """Jde převod udělat bez ptaní?"""
    return conversion_factor(from_unit, to_unit) is not None


def convert_line(quantity, unit_price, factor):
    """
    Přepočte řádek dokladu na skladovou jednotku.

    Množství se násobí, jednotková cena dělí – celková cena řádku musí zůstat
    stejná, jinak by příjemka přestala sedět s dokladem.

    >>> convert_line(Decimal('2'), Decimal('30'), Decimal('1000'))
    (Decimal('2000'), Decimal('0.030000'))

    Returns:
        (množství ve skladové jednotce, cena za skladovou jednotku)
    """
    factor = Decimal(str(factor))
    if factor <= 0:
        raise ValueError('Přepočet jednotek musí být kladné číslo.')

    converted_quantity = Decimal(str(quantity)) * factor
    # Šest desetinných míst odpovídá tomu, co unesou cenová pole ve skladu.
    # Míň by u surovin vedených v gramech ukrojilo procenta hodnoty.
    converted_price = (Decimal(str(unit_price)) / factor).quantize(Decimal('0.000001'))
    return converted_quantity, converted_price
