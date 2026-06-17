"""
Parser pro CSV dodejky od dodavatele Makro.
"""
import csv
from decimal import Decimal, InvalidOperation
from datetime import datetime

# Import VAT choices ze sdílených forem
from apps.inventory.forms import VAT_RATE_CHOICES

# Mapování jednotek z CSV na standardní jednotky v systému
UNIT_MAPPING = {
    'BX': 'ks',  # Box
    'PC': 'ks',  # Piece
    'SW': 'ks',  # Single Wrap
    'CA': 'ks',  # Carton
}


def parse_supplier_csv(csv_file):
    """
    Parsuje CSV dodejku od dodavatele Makro.
    
    Args:
        csv_file: File object s CSV daty
    
    Returns:
        dict s klíči:
            - receipt_number: číslo dokladu (číslo faktury)
            - receipt_date: datum příjmu (datum faktury)
            - supplier: název dodavatele
            - items: list slovníků s položkami, každá obsahuje:
                - item_id: kód položky (EAN)
                - item_name: název položky
                - quantity: množství
                - unit: jednotka z CSV
                - unit_mapped: mapovaná jednotka pro systém
                - price_per_unit_net: cena bez DPH za jednotku
                - price_per_unit_gross: cena s DPH za jednotku
                - vat_rate: sazba DPH v %
                - vat_amount: částka DPH za jednotku
                - total_price: celková cena (pro kontrolu)
    """
    # Načtení CSV souboru - pokusíme se různé kódování
    decoded_file = None
    reader = None
    
    # Možná kódování pro české soubory
    encodings = ['utf-8', 'windows-1250', 'iso-8859-2', 'cp1250']
    
    for encoding in encodings:
        try:
            csv_file.seek(0)  # Reset file position
            decoded_file = (line.decode(encoding) for line in csv_file)
            reader = csv.reader(decoded_file, delimiter=';')
            rows = list(reader)
            break
        except UnicodeDecodeError:
            continue
    
    if reader is None:
        raise ValueError("Chyba při načítání CSV souboru: Nelze určit kódování souboru. Pokuste se použít UTF-8, Windows-1250 nebo ISO-8859-2.")
    
    # Základní informace o dodejce
    receipt_data = {
        'receipt_number': _get_header_value(rows, 'HDR', 13),  # Číslo faktury
        'receipt_date': _parse_date(_get_header_value(rows, 'HDR', 2)),  # Datum faktury
        'supplier': _get_header_value(rows, 'HDR', 3),  # Název dodavatele
        'items': []
    }
    
    # Zpracování položek
    for row in rows:
        if row[0] == 'LIN':  # Řádky s položkami začínají 'LIN'
            try:
                item_data = _parse_csv_item(row)
                receipt_data['items'].append(item_data)
            except Exception as e:
                # Pokračujeme i když některá položka selže
                print(f"Chyba při parsování položky: {e}")
                continue
    
    return receipt_data


def _get_header_value(rows, header_type, index):
    """
    Získá hodnotu z hlavičky CSV souboru.
    
    Args:
        rows: Seznam řádků z CSV
        header_type: Typ hlavičky (např. 'HDR')
        index: Index hodnoty v řádku
    
    Returns:
        str: Hodnota z hlavičky
    """
    for row in rows:
        if row[0] == header_type:
            return row[index] if len(row) > index else ''
    return ''


def _parse_date(date_str):
    """
    Parsuje datum z CSV.
    
    Args:
        date_str: Řetězec s datem ve formátu 'DD.MM.YYYY'
    
    Returns:
        date: Parsované datum
    """
    try:
        return datetime.strptime(date_str, '%d.%m.%Y').date()
    except ValueError:
        return datetime.now().date()


def _parse_decimal(value, default='0'):
    """
    Bezpečně parsuje decimal hodnotu z CSV.
    
    Args:
        value: Hodnota k parsování
        default: Výchozí hodnota, pokud se nepodaří parsovat
    
    Returns:
        Decimal: Parsovaná hodnota
    """
    try:
        # Nahrazení čárky tečkou pro správné parsování
        value = value.replace(',', '.')
        return Decimal(value)
    except (ValueError, InvalidOperation):
        return Decimal(default)


def _parse_csv_item(row):
    """
    Parsuje jednu položku z CSV (LIN řádek).
    
    Struktura LIN řádku:
    LIN;[pořadí];[EAN];[množství];[jednotka];[multiplier];[cena bez slevy bez DPH];
    [sleva];[cena po slevě bez DPH];[DPH z orig. ceny];[DPH po slevě];
    [cena celkem s DPH];[sazba DPH %];[název produktu];[artikl MAKRO];
    [cena za 1ks bez DPH];[kusů v balení];[alternativní EANy];[příznak];
    [ref. cena bez DPH];[ref. cena bez DPH 2];[cena za ks opakování]
    
    Args:
        row: Řádek z CSV souboru
    
    Returns:
        dict s daty položky
    """
    # Základní informace
    item_id = row[2]  # EAN kód (sloupec C)
    item_name = row[13]  # Název produktu (sloupec N - 14. sloupec)
    
    # Množství a jednotka
    quantity = _parse_decimal(row[3])  # Množství (sloupec D)
    unit = row[4]  # Jednotka (sloupec E: BX/PC/SW/CA)
    unit_mapped = UNIT_MAPPING.get(unit, 'ks')  # Mapovaná jednotka
    
    # Ceny a DPH
    # Cena za 1ks bez DPH (sloupec P - index 15)
    price_net = _parse_decimal(row[15])  # Cena za 1ks bez DPH
    vat_rate = _parse_decimal(row[12])  # Sazba DPH v % (sloupec L)
    total_price = _parse_decimal(row[11])  # Cena celkem s DPH (sloupec K)
    
    # Výpočet ceny za 1ks s DPH
    vat_multiplier = Decimal('1') + (vat_rate / Decimal('100'))
    price_gross_per_unit = (price_net * vat_multiplier).quantize(Decimal('0.01'))
    
    # Celková cena s DPH (pro referenci)
    total_price_gross = price_gross_per_unit * quantity
    
    # Částka DPH za jednotku
    vat_amount_per_unit = (price_gross_per_unit - price_net).quantize(Decimal('0.01'))
    
    return {
        'item_id': item_id,
        'item_name': item_name,
        'quantity': quantity,
        'unit': unit,
        'unit_mapped': unit_mapped,
        'price_per_unit_net': price_net,
        'price_per_unit_gross': price_gross_per_unit,
        'vat_rate': vat_rate,
        'vat_amount': vat_amount_per_unit,
        'total_price': total_price_gross,
        'total_price': total_price,
    }

