"""
Parser pro CSV přehledy prodeje z pokladního systému FiskalPRO.
"""
import csv
import io
import re
from decimal import Decimal, InvalidOperation
from datetime import date


FILENAME_DATE_RE = re.compile(r'(\d{8})-\d{6}')


def parse_export_date(filename: str) -> date | None:
    """Extrahuje datum exportu z názvu souboru (formát YYYYMMDD-HHMMSS)."""
    m = FILENAME_DATE_RE.search(filename)
    if not m:
        return None
    try:
        return date(int(m.group(1)[:4]), int(m.group(1)[4:6]), int(m.group(1)[6:8]))
    except ValueError:
        return None


def _parse_decimal(value) -> Decimal:
    """Převede číslo s desetinnou čárkou na Decimal. Bezpečně zpracuje None/chybějící hodnoty."""
    if not isinstance(value, str):
        return Decimal('0')
    try:
        return Decimal(value.strip().replace(',', '.') or '0')
    except InvalidOperation:
        return Decimal('0')


def _safe_str(value) -> str:
    """Bezpečně ořeže hodnotu buňky CSV; chybějící/None hodnoty (u zkrácených řádků) vrátí jako ''."""
    return value.strip() if isinstance(value, str) else ''


def parse_fiskalpro_csv(csv_file) -> list[dict]:
    """
    Parsuje CSV přehled prodeje z FiskalPRO a agreguje množství přes všechny provozovny.

    Args:
        csv_file: file-like objekt nebo bytes s CSV daty

    Returns:
        list slovníků s agregovanými položkami:
            - article_code: kód artiklíku
            - barcode: EAN kód (může být prázdný)
            - name: název položky
            - group: skupina/kategorie z pokladny
            - quantity: celkové prodané množství (přes všechny provozovny)
            - unit: měrná jednotka
            - total_price_with_vat: celková tržba vč. DPH
            - total_price_without_vat: celková tržba bez DPH
            - establishments: seznam provozoven, kde bylo prodáno

    Raises:
        ValueError: pokud soubor nelze načíst nebo neobsahuje očekávané sloupce
    """
    if isinstance(csv_file, (bytes, bytearray)):
        raw = csv_file
    else:
        raw = csv_file.read()

    # Detekce kódování: zkusíme nejdřív striktní UTF-8 varianty (chybný vstup spolehlivě
    # vyhodí UnicodeDecodeError), teprve pak cp1250 jako fallback. Opačné pořadí je nebezpečné –
    # cp1250 dekóduje téměř libovolnou bajtovou sekvenci bez chyby, takže by tiše "úspěšně"
    # ale špatně dekódoval i skutečné UTF-8 exporty s českou diakritikou.
    for encoding in ('utf-8-sig', 'utf-8', 'cp1250'):
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise ValueError("Nepodporované kódování souboru. Očekáváno Windows-1250 nebo UTF-8.")

    reader = csv.DictReader(io.StringIO(text), delimiter=';')

    required_columns = {'Artikl', 'Název', 'Množství', 'Cena celkem', 'Cena celkem s DPH'}
    if not required_columns.issubset(set(reader.fieldnames or [])):
        missing = required_columns - set(reader.fieldnames or [])
        raise ValueError(f"CSV neobsahuje očekávané sloupce: {', '.join(missing)}")

    # Agregace po artiklíku
    aggregated: dict[str, dict] = {}

    for row in reader:
        # csv.DictReader vrátí None pro chybějící pole u zkrácených/poškozených řádků,
        # proto nelze na hodnotu spolehnout se voláním .strip() přímo.
        code = _safe_str(row.get('Artikl'))
        if not code:
            continue

        qty = _parse_decimal(row.get('Množství', '0'))
        price_with_vat = _parse_decimal(row.get('Cena celkem s DPH', '0'))
        price_without_vat = _parse_decimal(row.get('Cena celkem', '0'))
        barcode = _safe_str(row.get('Čárový kód'))
        name = _safe_str(row.get('Název'))
        group = _safe_str(row.get('Skupina'))
        unit = _safe_str(row.get('MJ')) or 'ks'
        establishment = _safe_str(row.get('Název provozovny'))

        if code not in aggregated:
            aggregated[code] = {
                'article_code': code,
                'barcode': barcode,
                'name': name,
                'group': group,
                'quantity': Decimal('0'),
                'unit': unit,
                'total_price_with_vat': Decimal('0'),
                'total_price_without_vat': Decimal('0'),
                'establishments': [],
            }

        entry = aggregated[code]
        entry['quantity'] += qty
        entry['total_price_with_vat'] += price_with_vat
        entry['total_price_without_vat'] += price_without_vat

        # Upřednostňujeme záznam s EAN a skupinou
        if barcode and not entry['barcode']:
            entry['barcode'] = barcode
        if group and not entry['group']:
            entry['group'] = group

        if establishment and establishment not in entry['establishments']:
            entry['establishments'].append(establishment)

    return list(aggregated.values())
