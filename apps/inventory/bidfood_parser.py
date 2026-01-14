"""
Parser pro XML dodejky z Bidfood Czech Republic.
"""
import xml.etree.ElementTree as ET
from decimal import Decimal, InvalidOperation
from datetime import datetime

# Import VAT choices ze sdílených forem
from apps.inventory.forms import VAT_RATE_CHOICES

# Mapování jednotek z XML na standardní jednotky v systému
UNIT_MAPPING = {
    'kg': 'kg',
    'ks': 'ks',
    'l': 'l',
    'Kč': 'ks',  # Pro dopravné a podobné položky
}


def parse_bidfood_xml(xml_file):
    """
    Parsuje XML dodejku z Bidfood.
    
    Args:
        xml_file: File object s XML daty
    
    Returns:
        dict s klíči:
            - receipt_number: číslo dokladu (salesId)
            - receipt_date: datum příjmu (documentDate)
            - supplier: název dodavatele
            - items: list slovníků s položkami, každá obsahuje:
                - item_id: kód položky
                - item_name: název položky
                - quantity: množství
                - unit: jednotka z XML
                - unit_mapped: mapovaná jednotka pro systém
                - price_per_unit_net: cena bez DPH za jednotku
                - price_per_unit_gross: cena s DPH za jednotku
                - vat_rate: sazba DPH v %
                - vat_amount: částka DPH za jednotku
                - total_price: celková cena (pro kontrolu)
    """
    try:
        tree = ET.parse(xml_file)
        root = tree.getroot()
    except ET.ParseError as e:
        raise ValueError(f"Chyba při parsování XML: {e}")
    
    # Základní informace o dodejce
    receipt_data = {
        'receipt_number': _get_text(root, 'salesId', 'N/A'),
        'receipt_date': _parse_date(root, 'documentDate'),
        'supplier': _get_text(root, 'supplier/name', 'Neznámý dodavatel'),
        'items': []
    }
    
    # Zpracování položek
    items_element = root.find('items')
    if items_element is None:
        return receipt_data
    
    for item in items_element.findall('item'):
        try:
            item_data = _parse_item(item)
            receipt_data['items'].append(item_data)
        except Exception as e:
            # Pokračujeme i když některá položka selže
            print(f"Chyba při parsování položky: {e}")
            continue
    
    return receipt_data


def _get_text(element, path, default=''):
    """Bezpečně získá text z XML elementu."""
    found = element.find(path)
    return found.text if found is not None and found.text else default


def _parse_date(element, path):
    """Parsuje datum z XML."""
    date_str = _get_text(element, path)
    try:
        return datetime.strptime(date_str, '%Y-%m-%d').date()
    except ValueError:
        return datetime.now().date()


def _parse_decimal(element, path, default='0'):
    """Bezpečně parsuje decimal hodnotu z XML."""
    text = _get_text(element, path, default)
    try:
        return Decimal(text)
    except (ValueError, InvalidOperation):
        return Decimal(default)


def _parse_item(item):
    """
    Parsuje jednu položku z XML.
    
    Args:
        item: XML Element reprezentující jednu položku
    
    Returns:
        dict s daty položky
    """
    # Základní informace
    item_id = _get_text(item, 'itemId', '')
    item_name = _get_text(item, 'itemName', 'Neznámá položka')
    
    # Množství a jednotka
    quantity = _parse_decimal(item, 'itemQty/quantity', '0')
    unit = _get_text(item, 'itemQty/unit', 'ks')
    unit_mapped = UNIT_MAPPING.get(unit, unit)
    
    # Ceny a DPH
    price_net = _parse_decimal(item, 'costPerUnitNet', '0')
    vat_rate = _parse_decimal(item, 'vatRate', '21')
    total_price = _parse_decimal(item, 'price/amount', '0')
    
    # Výpočet ceny s DPH za jednotku
    vat_multiplier = 1 + (vat_rate / Decimal('100'))
    price_gross = (price_net * vat_multiplier).quantize(Decimal('0.01'))
    
    # Částka DPH za jednotku
    vat_amount = (price_gross - price_net).quantize(Decimal('0.01'))
    
    return {
        'item_id': item_id,
        'item_name': item_name,
        'quantity': quantity,
        'unit': unit,
        'unit_mapped': unit_mapped,
        'price_per_unit_net': price_net,
        'price_per_unit_gross': price_gross,
        'vat_rate': vat_rate,
        'vat_amount': vat_amount,
        'total_price': total_price,
    }
