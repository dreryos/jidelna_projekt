"""
Kontroly příjemky před zápisem na sklad.

OCR se plete a člověk taky. Tyhle kontroly nic neblokují – jen řeknou, co si
má uživatel na dokladu ověřit, než příjemku potvrdí. Blokovat by nešlo:
každá z nich má legitimní výjimku (dodavatel opravdu zdražil, doklad se
opravdu importuje znovu po smazání).
"""
import logging
from decimal import Decimal

from apps.inventory.models import GoodsReceipt, IngredientPriceHistory, StockItem

logger = logging.getLogger('apps.inventory')

# O kolik se smí nákupní cena lišit od poslední známé, než na to upozorníme.
# Sezónní zelenina skáče běžně o desítky procent, posunutá desetinná čárka
# ale udělá řádovou změnu.
PRICE_DEVIATION_THRESHOLD = Decimal('0.5')


def check_duplicate_receipt(receipt_number, supplier=None, supplier_name='',
                            exclude_pk=None):
    """
    Hledá příjemku se stejným číslem dokladu od stejného dodavatele.

    Naskladnit jeden dodák dvakrát je snadné – doklad koluje mezi lidmi
    a druhý ho pořídí, aniž by věděl o prvním.

    Returns:
        GoodsReceipt, nebo None.
    """
    number = (receipt_number or '').strip()
    if not number:
        return None

    duplicates = GoodsReceipt.objects.filter(receipt_number__iexact=number)
    if exclude_pk:
        duplicates = duplicates.exclude(pk=exclude_pk)

    if supplier is not None:
        duplicates = duplicates.filter(supplier_obj=supplier)
    elif supplier_name:
        duplicates = duplicates.filter(supplier__iexact=supplier_name.strip())

    return duplicates.select_related('warehouse').order_by('-created_at').first()


def last_known_price(ingredient, warehouse):
    """
    Poslední známá nákupní cena suroviny na skladě, včetně DPH.

    Bere se z historie cen; když surovina historii nemá, sáhne se na aktuální
    skladovou cenu. `None` znamená, že se surovina nakupuje poprvé a není
    s čím srovnávat.
    """
    if ingredient is None or warehouse is None:
        return None

    historie = IngredientPriceHistory.objects.filter(
        ingredient=ingredient, warehouse=warehouse,
    ).order_by('-valid_from').values_list('price', flat=True).first()
    if historie is not None:
        return historie

    return StockItem.objects.filter(
        ingredient=ingredient, warehouse=warehouse,
    ).values_list('price', flat=True).first()


def check_price_deviation(ingredient, warehouse, price, threshold=None):
    """
    Porovná nákupní cenu s poslední známou.

    Chytá hlavně chybu čtení – „54,90" přečtené jako „5490" projde všemi
    ostatními kontrolami, protože doklad si sedí sám se sebou.

    Returns:
        dict s klíči `previous`, `current`, `ratio` a `direction`,
        nebo None, když je cena v pořádku nebo není s čím srovnávat.
    """
    threshold = PRICE_DEVIATION_THRESHOLD if threshold is None else Decimal(str(threshold))
    previous = last_known_price(ingredient, warehouse)

    if previous is None or previous <= 0:
        return None

    current = Decimal(str(price))
    if current <= 0:
        return None

    ratio = (current - previous) / previous
    if abs(ratio) <= threshold:
        return None

    return {
        'previous': previous,
        'current': current,
        'ratio': ratio,
        'direction': 'zdražení' if ratio > 0 else 'zlevnění',
    }


def collect_receipt_warnings(items, warehouse_by_index=None):
    """
    Projde položky příjemky a vrátí texty upozornění.

    Args:
        items: seznam dvojic (surovina, cena včetně DPH) doplněný o název
               z dokladu – konkrétně trojic (název, surovina, cena)
        warehouse_by_index: sklad pro každou položku; když chybí, kontrola
                            cen se přeskočí

    Returns:
        list textů k zobrazení uživateli.
    """
    warnings = []
    for index, (name, ingredient, price) in enumerate(items):
        warehouse = (warehouse_by_index or {}).get(index)
        deviation = check_price_deviation(ingredient, warehouse, price)
        if deviation is None:
            continue
        warnings.append(
            f'„{name}": cena {deviation["current"]} Kč je proti poslední známé '
            f'({deviation["previous"]} Kč) {deviation["direction"]} o '
            f'{abs(deviation["ratio"]) * 100:.0f} %. Zkontrolujte ji na dokladu.'
        )
    return warnings


# Přesnost, se kterou se ceny ukládají – odpovídá decimal_places cenových polí.
STORED_PRICE_PRECISION = Decimal('0.000001')

# O kolik smí zaokrouhlení ceny uhnout, než na to upozorníme.
PRICE_PRECISION_TOLERANCE = Decimal('0.01')


def check_price_precision(unit_price, factor):
    """
    Ověří, že se jednotková cena vejde do přesnosti cenových polí.

    Ceny se ukládají na šest desetinných míst. Při běžných potravinách se
    kontrola neozve – smysl má u extrémního přepočtu, kde by cena za skladovou
    jednotku spadla pod desetitisícinu haléře a zaokrouhlení by z ní ukrojilo
    procenta.

    Returns:
        dict s klíči `exact`, `stored` a `error`, nebo None, když je cena
        v pořádku.
    """
    factor = Decimal(str(factor))
    if factor <= 0:
        return None

    exact = Decimal(str(unit_price)) / factor
    if exact == 0:
        return None

    stored = exact.quantize(STORED_PRICE_PRECISION)
    error = (stored - exact).copy_abs() / exact

    if error <= PRICE_PRECISION_TOLERANCE:
        return None

    return {'exact': exact, 'stored': stored, 'error': error}
