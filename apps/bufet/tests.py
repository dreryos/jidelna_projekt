import io
from datetime import date
from decimal import Decimal

import openpyxl
from django.test import TestCase

from apps.bufet.fiskalpro_parser import (
    parse_bufet_file,
    parse_export_date,
    parse_fiskalpro_xlsx,
)


def _make_xlsx(rows):
    """Sestaví XLSX v paměti s hlavičkou exportu 'Položky dokladů'."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(['Typ', 'Artikl', 'Čárový kód', 'Název', 'Skupina', 'DPH',
               'Množství', 'MJ', 'Celkem', 'Daň', 'Celkem s DPH'])
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


class BufetXlsxParserTest(TestCase):
    def test_export_date_from_iso_filename(self):
        d = parse_export_date('Položky dokladů - kumulované 2026-07-05 11-44-41.xlsx')
        self.assertEqual(d, date(2026, 7, 5))

    def test_aggregates_by_name_not_article_code(self):
        # Stejný artiklový kód '1', dva různé produkty -> nesmí se sloučit
        xlsx = _make_xlsx([
            ['0 - prodej', '1', '', 'Pegas Almond', '1 - Nanuky', '12%', 10, 'ks', 100, 12, 112],
            ['0 - prodej', '1', '', 'Kinder Bueno', '1 - Nanuky', '21%', 5, 'ks', 50, 10, 60],
        ])
        items = {i['name']: i for i in parse_fiskalpro_xlsx(xlsx)}
        self.assertEqual(set(items), {'Pegas Almond', 'Kinder Bueno'})
        self.assertEqual(items['Pegas Almond']['quantity'], Decimal('10'))
        self.assertEqual(items['Kinder Bueno']['quantity'], Decimal('5'))

    def test_storno_subtracts(self):
        xlsx = _make_xlsx([
            ['0 - prodej', '5', '', 'Kofola', '', '12%', 20, 'ks', 200, 24, 224],
            ['1 - prodej návrat/storno', '5', '', 'Kofola', '', '12%', -3, 'ks', -30, -3.6, -33.6],
        ])
        items = parse_fiskalpro_xlsx(xlsx)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]['quantity'], Decimal('17'))

    def test_fully_returned_item_dropped(self):
        xlsx = _make_xlsx([
            ['0 - prodej', '5', '', 'Kofola', '', '12%', 3, 'ks', 30, 3.6, 33.6],
            ['1 - prodej návrat/storno', '5', '', 'Kofola', '', '12%', -3, 'ks', -30, -3.6, -33.6],
        ])
        self.assertEqual(parse_fiskalpro_xlsx(xlsx), [])

    def test_non_sale_rows_ignored(self):
        xlsx = _make_xlsx([
            ['0 - prodej', '5', '', 'Kofola', '', '12%', 4, 'ks', 40, 4.8, 44.8],
            ['107 - platba (karta/QR kód)', '', '', 'Platba', '', '0%', 1, '', 0, 0, 0],
        ])
        items = parse_fiskalpro_xlsx(xlsx)
        self.assertEqual([i['name'] for i in items], ['Kofola'])

    def test_empty_unit_defaults_to_ks(self):
        xlsx = _make_xlsx([
            ['0 - prodej', '5', '', 'Kofola', '', '12%', 4, None, 40, 4.8, 44.8],
        ])
        self.assertEqual(parse_fiskalpro_xlsx(xlsx)[0]['unit'], 'ks')

    def test_missing_columns_raise(self):
        wb = openpyxl.Workbook()
        wb.active.append(['Typ', 'Artikl', 'Název'])  # chybí Množství, Celkem s DPH
        buf = io.BytesIO(); wb.save(buf); buf.seek(0)
        with self.assertRaises(ValueError):
            parse_fiskalpro_xlsx(buf)

    def test_dispatch_by_extension(self):
        xlsx = _make_xlsx([
            ['0 - prodej', '5', '', 'Kofola', '', '12%', 4, 'ks', 40, 4.8, 44.8],
        ])
        items = parse_bufet_file(xlsx, 'export.xlsx')
        self.assertEqual(items[0]['name'], 'Kofola')

    def test_dispatch_unknown_extension(self):
        with self.assertRaises(ValueError):
            parse_bufet_file(io.BytesIO(b'x'), 'data.txt')
