"""
Parser přehledů prodeje z pokladního systému FiskalPRO.

Formát XLSX "Položky dokladů – kumulované …": export bez provozovny,
s typem dokladu (prodej / storno) na řádek; agregace po názvu.
Z exportu se čte jen název, množství, MJ a artikl – ceny, DPH, skupiny
a čárové kódy se ignorují (ceny se berou z interní DB po spárování).
"""
import io
import re
from decimal import Decimal, InvalidOperation
from datetime import date


# "…kumulované 2026-07-05 11-44-41.xlsx" (YYYY-MM-DD HH-MM-SS)
FILENAME_DATE_RE = re.compile(r'(\d{4})-(\d{2})-(\d{2})[ _]\d{2}-\d{2}-\d{2}')

# Sloupce XLSX exportu "Položky dokladů – kumulované"
XLSX_REQUIRED_COLUMNS = {'Typ', 'Artikl', 'Název', 'Množství'}


def parse_export_date(filename: str) -> date | None:
    """Extrahuje datum exportu z názvu souboru."""
    m = FILENAME_DATE_RE.search(filename or '')
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def _to_decimal(value) -> Decimal:
    """Bezpečně převede číselnou/textovou hodnotu buňky na Decimal."""
    if value is None:
        return Decimal('0')
    if isinstance(value, Decimal):
        return value
    if isinstance(value, (int, float)):
        return Decimal(str(value))
    try:
        return Decimal(str(value).strip().replace(',', '.') or '0')
    except InvalidOperation:
        return Decimal('0')


def parse_fiskalpro_xlsx(xlsx_file) -> list[dict]:
    """
    Parsuje XLSX export "Položky dokladů – kumulované" z FiskalPRO.

    - Neobsahuje provozovnu (establishments zůstává prázdné).
    - Obsahuje typ dokladu (0 - prodej, 1 - prodej návrat/storno, platba …).
      Platební řádky se ignorují; storno má záporné množství a odečítá se.
    - Artiklové číslo NENÍ jednoznačné (jeden kód = více produktů), proto
      agregujeme podle názvu položky.
    - Ceny, DPH, skupiny a čárové kódy z exportu se nečtou – ceny se
      po spárování berou z interní DB (sklad).

    Returns:
        list slovníků s klíči: article_code, name, quantity, unit,
        establishments. Vrací jen položky s kladným čistým prodaným
        množstvím (po odečtení storna).

    Raises:
        ValueError: pokud sešit nelze načíst nebo chybí očekávané sloupce.
    """
    try:
        import openpyxl
    except ImportError as e:
        raise ValueError("Knihovna openpyxl není nainstalována.") from e

    if isinstance(xlsx_file, (bytes, bytearray)):
        xlsx_file = io.BytesIO(xlsx_file)

    try:
        wb = openpyxl.load_workbook(xlsx_file, read_only=True, data_only=True)
    except Exception as e:
        raise ValueError(f"Soubor XLSX nelze načíst: {e}") from e

    ws = wb.active
    rows = ws.iter_rows(values_only=True)

    try:
        header = next(rows)
    except StopIteration:
        wb.close()
        raise ValueError("XLSX je prázdný.") from None

    col = {str(name).strip(): idx for idx, name in enumerate(header) if name is not None}
    missing = XLSX_REQUIRED_COLUMNS - set(col)
    if missing:
        wb.close()
        raise ValueError(f"XLSX neobsahuje očekávané sloupce: {', '.join(sorted(missing))}") from None

    def cell(row, name, default=''):
        idx = col.get(name)
        if idx is None or idx >= len(row) or row[idx] is None:
            return default
        return row[idx]

    aggregated: dict[str, dict] = {}

    for row in rows:
        typ = str(cell(row, 'Typ', '')).strip()
        # Bereme jen řádky prodeje (a jeho storno); platby a jiné doklady ignorujeme
        if 'prodej' not in typ.lower():
            continue

        name = str(cell(row, 'Název', '')).strip()
        if not name:
            continue

        qty = _to_decimal(cell(row, 'Množství', 0))
        code = str(cell(row, 'Artikl', '')).strip()
        unit = str(cell(row, 'MJ', '')).strip() or 'ks'

        # Agregujeme podle názvu – artiklové číslo není jednoznačné
        entry = aggregated.get(name)
        if entry is None:
            entry = aggregated[name] = {
                'article_code': code,
                'name': name,
                'quantity': Decimal('0'),
                'unit': unit,
                'establishments': [],
            }

        entry['quantity'] += qty

    wb.close()

    # Jen položky s kladným čistým prodejem (storno mohlo prodej vynulovat)
    return [e for e in aggregated.values() if e['quantity'] > 0]


def parse_bufet_file(uploaded_file, filename: str) -> list[dict]:
    """Načte položky prodeje z nahraného souboru (podporován XLSX z FiskalPRO)."""
    if not (filename or '').lower().endswith('.xlsx'):
        raise ValueError("Nepodporovaný formát souboru. Nahrajte XLSX z FiskalPRO.")
    return parse_fiskalpro_xlsx(uploaded_file)
