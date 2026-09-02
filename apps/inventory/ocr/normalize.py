"""
Převod anotace z Mistral OCR na kanonický `receipt_data`.

Výstup má stejný tvar jako `parse_supplier_csv` a `parse_bidfood_xml`, aby na něj
šly napojit existující kroky importu příjemky. Navíc nese `warnings` – seznam
věcí, které si má uživatel na dokladu zkontrolovat, protože OCR se plete.
"""
import logging
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from apps.inventory.forms import VAT_RATE_CHOICES

from .quirks import classify_line, map_unit

logger = logging.getLogger('apps.inventory')

MONEY = Decimal('0.01')
QUANTITY = Decimal('0.001')
DEFAULT_VAT_RATE = Decimal('12')
ALLOWED_VAT_RATES = [rate for rate, _label in VAT_RATE_CHOICES]

DATE_FORMATS = ('%Y-%m-%d', '%d.%m.%Y', '%d. %m. %Y', '%d/%m/%Y', '%Y/%m/%d')

DOC_TYPES = {'faktura', 'prodejka', 'dodaci_list', 'jine'}

# Nad tuhle odchylku mezi součtem položek a celkovou částkou z dokladu
# hlásíme rozpor. Koruna pokrývá zaokrouhlování, víc už je chyba čtení.
TOTAL_TOLERANCE = Decimal('1.00')


def to_receipt_data(annotation, source='ocr'):
    """
    Args:
        annotation: dict vrácený Mistralem podle `schema.DodaciDoklad`
        source: odkud data pocházejí, ukládá se do výsledku

    Returns:
        dict popsaný v plans/ocr_receipt_import_plan.md
    """
    warnings = []

    supplier = annotation.get('dodavatel') or {}
    doklad = annotation.get('doklad') or {}
    totals = _read_totals(annotation.get('celkem') or {})

    receipt_number = (doklad.get('cislo_dokladu') or '').strip()
    if not receipt_number:
        warnings.append('Na dokladu se nepodařilo přečíst číslo dokladu, doplňte ho ručně.')

    receipt_date = _parse_date(doklad.get('datum_dodani') or doklad.get('datum_vystaveni'))
    if receipt_date is None:
        receipt_date = date.today()
        warnings.append('Datum dokladu se nepodařilo přečíst, je předvyplněno dnešní datum.')

    supplier_ico = _clean_ico(supplier.get('ico'))
    if not supplier_ico:
        warnings.append('Na dokladu není čitelné IČO dodavatele, vyberte dodavatele ručně.')

    prices_include_vat = _resolve_price_basis(annotation, warnings)

    items = []
    for index, raw_item in enumerate(annotation.get('polozky') or [], start=1):
        item = _normalize_item(raw_item, index, prices_include_vat, warnings)
        if item is not None:
            items.append(item)

    if not items:
        warnings.append('Na dokladu nebyla rozpoznána žádná položka zboží.')

    _check_totals(items, totals, warnings)

    return {
        'source': source,
        'receipt_number': receipt_number,
        'receipt_date': receipt_date,
        'doc_type': _normalize_doc_type(doklad.get('typ_dokladu')),
        'supplier': (supplier.get('nazev') or '').strip(),
        'supplier_ico': supplier_ico,
        'supplier_id': None,
        'order_number': (doklad.get('cislo_objednavky') or '').strip(),
        'handwritten_note': (doklad.get('poznamka_rukou') or '').strip(),
        'prices_include_vat': prices_include_vat,
        'totals': totals,
        'items': items,
        'warnings': warnings,
    }


def _normalize_item(raw_item, index, prices_include_vat, warnings):
    """Zpracuje jeden řádek dokladu. Vrátí None u řádku, který nejde použít."""
    name = (raw_item.get('nazev') or '').strip()
    is_ignored, ignore_reason = classify_line(name)

    quantity = _to_decimal(raw_item.get('mnozstvi'))
    unit = (raw_item.get('jednotka') or '').strip()
    vat_rate = _resolve_vat_rate(raw_item.get('dph_procenta'), name, warnings)

    line_net = _to_decimal(raw_item.get('cena_bez_dph'))
    line_gross = _to_decimal(raw_item.get('cena_celkem'))
    unit_price = _to_decimal(raw_item.get('cena_za_mj'))

    if quantity is None or quantity == 0:
        # Bez množství nelze naskladnit. Řádek necháme v seznamu, aby uživatel
        # viděl, že na dokladu je, ale označíme ho k doplnění.
        if not is_ignored:
            warnings.append(f'Řádek {index} „{name}" nemá čitelné množství, doplňte ho.')
        quantity = Decimal('0')

    unit_net, unit_gross = _resolve_unit_prices(
        unit_price=unit_price,
        line_net=line_net,
        line_gross=line_gross,
        quantity=quantity,
        vat_rate=vat_rate,
        prices_include_vat=prices_include_vat,
    )

    if unit_net is None:
        if not is_ignored:
            warnings.append(f'Řádek {index} „{name}" nemá čitelnou cenu, doplňte ji.')
        unit_net = Decimal('0')
        unit_gross = Decimal('0')

    if line_gross is None:
        line_gross = (unit_gross * quantity).quantize(MONEY)
    if line_net is None:
        line_net = (unit_net * quantity).quantize(MONEY)

    return {
        'item_id': (raw_item.get('kod') or '').strip(),
        'item_name': name,
        'quantity': quantity.quantize(QUANTITY),
        'unit': unit,
        'unit_mapped': map_unit(unit),
        'price_per_unit_net': unit_net,
        'price_per_unit_gross': unit_gross,
        'vat_rate': vat_rate,
        'vat_amount': (unit_gross - unit_net).quantize(MONEY),
        'total_price': line_gross,
        'total_price_net': line_net,
        'is_ignored': is_ignored,
        'ignore_reason': ignore_reason,
    }


def _resolve_unit_prices(unit_price, line_net, line_gross, quantity, vat_rate,
                         prices_include_vat):
    """
    Dopočítá jednotkovou cenu bez DPH a s DPH.

    Doklady uvádějí různé kombinace sloupců, takže bereme, co je k dispozici:
    nejdřív jednotkovou cenu, pak řádkový součet bez DPH, nakonec s DPH.

    Returns:
        (net, gross) nebo (None, None), když se cena přečíst nedá.
    """
    multiplier = Decimal('1') + (vat_rate / Decimal('100'))

    if unit_price is not None:
        if prices_include_vat:
            gross = unit_price
            net = (gross / multiplier) if multiplier else gross
        else:
            net = unit_price
            gross = net * multiplier
        return net.quantize(MONEY), gross.quantize(MONEY)

    if quantity and line_net is not None:
        net = line_net / quantity
        return net.quantize(MONEY), (net * multiplier).quantize(MONEY)

    if quantity and line_gross is not None:
        gross = line_gross / quantity
        net = (gross / multiplier) if multiplier else gross
        return net.quantize(MONEY), gross.quantize(MONEY)

    return None, None


def _resolve_price_basis(annotation, warnings):
    """
    Zjistí, jestli je jednotková cena na dokladu s DPH, nebo bez.

    Model to hlásí v `ceny_jsou_s_dph`. Když si není jistý, ověříme to sami:
    vynásobíme jednotkovou cenu množstvím a podíváme se, jestli je blíž
    řádkovému součtu bez DPH, nebo s DPH.
    """
    declared = annotation.get('ceny_jsou_s_dph')
    if isinstance(declared, bool):
        return declared

    votes_net = 0
    votes_gross = 0
    for raw_item in annotation.get('polozky') or []:
        unit_price = _to_decimal(raw_item.get('cena_za_mj'))
        quantity = _to_decimal(raw_item.get('mnozstvi'))
        line_net = _to_decimal(raw_item.get('cena_bez_dph'))
        line_gross = _to_decimal(raw_item.get('cena_celkem'))
        if not unit_price or not quantity or line_net is None or line_gross is None:
            continue
        computed = unit_price * quantity
        if abs(computed - line_net) < abs(computed - line_gross):
            votes_net += 1
        else:
            votes_gross += 1

    if votes_net == 0 and votes_gross == 0:
        warnings.append(
            'Nepodařilo se určit, zda jsou ceny na dokladu s DPH, nebo bez. '
            'Počítáme s cenami bez DPH, zkontrolujte je.'
        )
        return False

    return votes_gross > votes_net


def _resolve_vat_rate(value, name, warnings):
    """Vrátí sazbu DPH omezenou na sazby, které systém zná."""
    rate = _to_decimal(value)
    if rate is None:
        warnings.append(
            f'U položky „{name}" nebyla přečtena sazba DPH, '
            f'je předvyplněno {DEFAULT_VAT_RATE} %.'
        )
        return DEFAULT_VAT_RATE

    if rate in ALLOWED_VAT_RATES:
        return rate

    # OCR občas přečte 12 jako 1,2 nebo 120. Přichytneme se nejbližší platné sazby.
    closest = min(ALLOWED_VAT_RATES, key=lambda allowed: abs(allowed - rate))
    warnings.append(
        f'U položky „{name}" byla přečtena sazba DPH {rate} %, '
        f'použita nejbližší platná sazba {closest} %.'
    )
    return closest


def _check_totals(items, totals, warnings):
    """
    Porovná součet položek s částkami vytištěnými na dokladu.

    Kontroluje se základ daně, ne částka s DPH. Doklady počítají DPH ze součtu
    základů, ne z jednotlivých řádků, takže součet řádkových cen s DPH se
    o pár korun rozchází i u naprosto správně přečteného dokladu. Základ daně
    naopak musí sednout na haléře, takže se v něm chyba čtení projeví.

    Do součtu jdou i nezbožní řádky – zaokrouhlení je součástí základu.
    """
    computed_net = sum(
        (item['total_price_net'] for item in items), Decimal('0')
    ).quantize(MONEY)

    doc_base = totals.get('base')
    if doc_base is not None:
        difference = (computed_net - doc_base).copy_abs()
        if difference > TOTAL_TOLERANCE:
            warnings.append(
                f'Součet položek bez DPH {computed_net} Kč nesedí se základem daně '
                f'na dokladu {doc_base} Kč (rozdíl {difference} Kč). '
                f'Zkontrolujte množství a ceny na řádcích.'
            )
        return

    # Doklad základ daně neuvádí – spadneme na hrubší kontrolu proti částce
    # k úhradě a připustíme zaokrouhlení na každém řádku.
    doc_total = totals.get('total')
    if doc_total is None:
        return

    computed_gross = sum(
        (item['total_price'] for item in items), Decimal('0')
    ).quantize(MONEY)
    tolerance = TOTAL_TOLERANCE + Decimal(len(items)) * MONEY
    difference = (computed_gross - doc_total).copy_abs()
    if difference > tolerance:
        warnings.append(
            f'Součet položek {computed_gross} Kč nesedí s částkou na dokladu '
            f'{doc_total} Kč (rozdíl {difference} Kč). Zkontrolujte řádky.'
        )


def _read_totals(celkem):
    return {
        'base': _to_decimal(celkem.get('zaklad')),
        'vat': _to_decimal(celkem.get('dph')),
        'total': _to_decimal(celkem.get('celkem_kc')),
    }


def _normalize_doc_type(value):
    key = (value or '').strip().lower().replace(' ', '_')
    return key if key in DOC_TYPES else 'jine'


def _clean_ico(value):
    """Nechá z IČO jen číslice – OCR do něj plete mezery a tečky."""
    if not value:
        return ''
    return ''.join(char for char in str(value) if char.isdigit())


def _parse_date(value):
    if not value:
        return None
    text = str(value).strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    logger.warning('OCR: nerozpoznaný formát data %r', value)
    return None


def _to_decimal(value):
    """Převede hodnotu z JSONu na Decimal. Vrací None, když to nejde."""
    if value is None or value == '':
        return None
    try:
        # Přes str, aby se nepřenesla nepřesnost floatu z JSONu.
        return Decimal(str(value).replace(',', '.').replace(' ', ''))
    except (InvalidOperation, ValueError, TypeError):
        return None
