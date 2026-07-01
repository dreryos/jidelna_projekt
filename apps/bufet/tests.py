import io
from datetime import date
from decimal import Decimal

import openpyxl
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from apps.bufet.models import BufetImport
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
        wb.active.append(['Typ', 'Artikl', 'Název'])  # chybí Množství
        buf = io.BytesIO()
        wb.save(buf)
        buf.seek(0)
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


class BufetUploadFlowTest(TestCase):
    """Kroky nahrání importu: přístup k jídelně, špatná vstupní data, dvojité odeslání.

    Testy předtím pokrývaly jen parser, ani jeden pohled.
    """

    def setUp(self):
        from apps.canteens.models import Canteen, Warehouse
        from apps.core.models import Ingredient, UserProfile

        self.canteen_a = Canteen.objects.create(name='Jídelna A')
        self.canteen_b = Canteen.objects.create(name='Jídelna B')
        self.warehouse_b = Warehouse.objects.create(name='Sklad B', canteen=self.canteen_b)
        self.ingredient = Ingredient.objects.create(
            name='Limonáda', unit='ks', base_unit='ks', recipe_unit='ks',
            conversion_factor=Decimal('1'),
        )

        self.user_a = User.objects.create_user('uzivatel_a')
        profile, _ = UserProfile.objects.get_or_create(user=self.user_a)
        profile.canteens.set([self.canteen_a])
        self.user_b = User.objects.create_user('uzivatel_b')
        profile, _ = UserProfile.objects.get_or_create(user=self.user_b)
        profile.canteens.set([self.canteen_b])

    def _start(self, user, warehouse_id=None):
        """Přihlásí uživatele a nastaví session tak, jako by prošel krokem 1."""
        self.client.force_login(user)
        session = self.client.session
        session['bufet_items'] = [{
            'article_code': '1', 'name': 'Limonáda', 'quantity': '3', 'unit': 'ks',
            'establishments': '',
        }]
        session['bufet_warehouse_id'] = warehouse_id if warehouse_id is not None else self.warehouse_b.id
        session['bufet_filename'] = 'export.xlsx'
        session['bufet_export_date'] = '2026-10-01'
        session.save()

    def test_step2_denies_user_of_other_canteen(self):
        """Krok 2 dřív nekontroloval přístup k jídelně skladu, krok 1 a 3 ano."""
        self._start(self.user_a)
        response = self.client.get(reverse('bufet:upload_step2'))
        self.assertRedirects(response, reverse('bufet:upload_step1'), fetch_redirect_response=False)

    def test_step2_allows_user_of_own_canteen(self):
        self._start(self.user_b)
        self.assertEqual(self.client.get(reverse('bufet:upload_step2')).status_code, 200)

    def test_step2_non_numeric_warehouse_id_does_not_crash(self):
        """Nečíselné ID ve session dřív skončilo chybou 500."""
        self._start(self.user_b, warehouse_id='abc')
        response = self.client.get(reverse('bufet:upload_step2'))
        self.assertRedirects(response, reverse('bufet:upload_step1'), fetch_redirect_response=False)

    def test_step3_non_numeric_warehouse_id_does_not_crash(self):
        self._start(self.user_b, warehouse_id='abc')
        response = self.client.post(reverse('bufet:upload_step3'))
        self.assertRedirects(response, reverse('bufet:upload_step1'), fetch_redirect_response=False)
        self.assertEqual(BufetImport.objects.count(), 0)

    def test_step3_resubmit_after_completion_creates_no_second_import(self):
        """Odeslání po dokončení (znovunačtení stránky) nevytvoří druhý import.

        Testuje jen sekvenční případ. Skutečně souběžné dva požadavky tahle
        kontrola nechytí: session se ukládá až po skončení view, takže druhý
        požadavek ještě čte původní položky. Na to by byl potřeba zámek nebo
        unikátní omezení v databázi, ne session.
        """
        self._start(self.user_b)
        data = {'ingredient_0': str(self.ingredient.id)}
        self.client.post(reverse('bufet:upload_step3'), data)
        self.client.post(reverse('bufet:upload_step3'), data)
        self.assertEqual(BufetImport.objects.count(), 1)


class BufetWriteOffForeignKeyTest(TestCase):
    """BufetImport.write_off je cizí klíč, ne holé číslo."""

    def setUp(self):
        from apps.canteens.models import Canteen, Warehouse
        from apps.inventory.models import StockWriteOff

        creator = User.objects.create_user('tvurce')
        canteen = Canteen.objects.create(name='Jídelna')
        warehouse = Warehouse.objects.create(name='Sklad', canteen=canteen)
        self.write_off = StockWriteOff.objects.create(
            warehouse=warehouse, category='BUFET_SALE',
            write_off_date=date(2026, 10, 1), created_by=creator,
        )
        self.bufet_import = BufetImport.objects.create(
            warehouse=warehouse, filename='export.xlsx', export_date=date(2026, 10, 1),
            status=BufetImport.Status.CONFIRMED, created_by=creator,
            write_off=self.write_off,
        )

    def test_reachable_from_write_off(self):
        self.assertEqual(list(self.write_off.bufet_imports.all()), [self.bufet_import])

    def test_deleting_write_off_keeps_the_import(self):
        """SET_NULL: smazání odepsání nesmí smazat historii importu."""
        self.write_off.delete()
        self.bufet_import.refresh_from_db()
        self.assertIsNone(self.bufet_import.write_off)

    def test_total_cost_is_none_without_write_off(self):
        self.write_off.delete()
        self.bufet_import.refresh_from_db()
        self.assertIsNone(self.bufet_import.get_write_off_total_cost())
