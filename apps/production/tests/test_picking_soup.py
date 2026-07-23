"""Testy prázdné polévky ve výdejce (větev výdejka-rework-soups).

Polévka funguje jako druhá večeře: v jídelníčku není, ve výdejce se zobrazuje
jako prázdná karta před obědem, kuchař ji vyplní až po uvaření. Na papírovou
PDF výdejku se netiskne.
"""
import sys
import types
from decimal import Decimal
from datetime import date
from unittest.mock import patch, MagicMock

from django.test import TestCase
from django.contrib.auth.models import User

from apps.canteens.models import Canteen, Warehouse
from apps.core.models import Ingredient, Recipe, RecipeIngredient
from apps.inventory.models import StockItem
from apps.production.models import (
    ProductionOrder, PickingList, MenuPlan,
    ProductionOrderPortionVariant, PickingListDocument,
)


class PickingSoupTest(TestCase):
    def setUp(self):
        self.canteen = Canteen.objects.create(name='Test Canteen')
        self.warehouse = Warehouse.objects.create(name='Main', canteen=self.canteen)
        self.flour = Ingredient.objects.create(
            name='Mouka', unit='kg', base_unit='kg', recipe_unit='kg',
            conversion_factor=Decimal('1.0'),
        )
        self.rice = Ingredient.objects.create(
            name='Rýže', unit='kg', base_unit='kg', recipe_unit='kg',
            conversion_factor=Decimal('1.0'),
        )
        for ing in (self.flour, self.rice):
            StockItem.objects.create(
                warehouse=self.warehouse, ingredient=ing,
                quantity=Decimal('100'), price=Decimal('10'),
            )

        self.day = date(2025, 9, 10)
        self.menu_plan = MenuPlan.objects.create(
            name='Plan', canteen=self.canteen,
            date_from=self.day, date_to=self.day,
        )
        self.recipe = Recipe.objects.create(name='Guláš', base_portions=10)
        RecipeIngredient.objects.create(
            recipe=self.recipe, ingredient=self.flour,
            quantity_per_portion=Decimal('1.000'),
        )
        self.order = ProductionOrder.objects.create(
            recipe=self.recipe, canteen=self.canteen, menu_plan=self.menu_plan,
            date=self.day, meal_type=ProductionOrder.MealType.LUNCH,
        )
        ProductionOrderPortionVariant.objects.create(
            production_order=self.order, portions=5, coefficient=Decimal('1.0'),
        )
        self.order.generate_picking_list()

        self.document = PickingListDocument.objects.create(
            name='Doc', canteen=self.canteen,
            date_from=self.day, date_to=self.day,
            created_by=User.objects.create_user(username='creator'),
        )
        for item in PickingList.objects.filter(production_order=self.order):
            item.document = self.document
            item.save()

        self.user = User.objects.create_superuser(username='admin', password='x')
        self.client.force_login(self.user)

    def _url(self):
        return f'/production/vydejky/{self.document.id}/edit/'

    def _soup_order(self):
        return ProductionOrder.objects.filter(
            canteen=self.canteen, date=self.day,
            meal_type=ProductionOrder.MealType.SOUP,
        ).first()

    def test_soup_placeholder_shown_on_edit(self):
        """Editace výdejky zobrazí prázdnou kartu polévky s panelem přidání."""
        html = self.client.get(self._url()).content.decode()
        self.assertIn('Polévka', html)
        self.assertIn(f'new_ingredient_soup_{self.day.isoformat()}_0', html)
        # dokud se nic nepřidá, žádný příkaz polévky neexistuje
        self.assertIsNone(self._soup_order())

    def test_add_soup_creates_order_and_issues(self):
        """Přidání suroviny založí příkaz Polévka a rovnou vydá (odečte sklad)."""
        response = self.client.post(self._url(), data={
            f'new_ingredient_soup_{self.day.isoformat()}_0': str(self.rice.id),
            f'new_quantity_soup_{self.day.isoformat()}_0': '2',
        })
        self.assertEqual(response.status_code, 302)

        soup = self._soup_order()
        self.assertIsNotNone(soup)
        item = PickingList.objects.get(production_order=soup, ingredient=self.rice)
        self.assertEqual(item.document_id, self.document.id)
        self.assertEqual(item.status, PickingList.Status.COMPLETED)
        self.assertEqual(item.quantity_actual, Decimal('2'))
        rice_stock = StockItem.objects.get(ingredient=self.rice)
        self.assertEqual(rice_stock.quantity, Decimal('98'))  # 100 - 2

    def test_soup_single_order_per_day(self):
        """Víc surovin polévky v jednom dni sdílí jediný příkaz."""
        self.client.post(self._url(), data={
            f'new_ingredient_soup_{self.day.isoformat()}_0': str(self.rice.id),
            f'new_quantity_soup_{self.day.isoformat()}_0': '2',
            f'new_ingredient_soup_{self.day.isoformat()}_1': str(self.flour.id),
            f'new_quantity_soup_{self.day.isoformat()}_1': '1',
        })
        self.assertEqual(
            ProductionOrder.objects.filter(
                canteen=self.canteen, date=self.day,
                meal_type=ProductionOrder.MealType.SOUP,
            ).count(),
            1,
        )
        soup = self._soup_order()
        self.assertEqual(
            PickingList.objects.filter(production_order=soup).count(), 2)

    def test_soup_excluded_from_pdf(self):
        """Polévka se nedostane do PDF výdejky (netiskne se na papír)."""
        self.client.post(self._url(), data={
            f'new_ingredient_soup_{self.day.isoformat()}_0': str(self.rice.id),
            f'new_quantity_soup_{self.day.isoformat()}_0': '2',
        })
        self.assertIsNotNone(self._soup_order())

        captured = {}

        def fake_render(template_name, context):
            captured['context'] = context
            return '<html></html>'

        # WeasyPrint na macOS bez GTK nejde ani importovat – podstrčíme fake
        # modul, HTML(...).write_pdf() jen nic nezapíše
        fake_weasy = types.ModuleType('weasyprint')
        fake_weasy.HTML = MagicMock()

        from apps.production import utils
        with patch.object(utils, 'render_to_string', side_effect=fake_render), \
                patch.dict(sys.modules, {'weasyprint': fake_weasy}):
            utils.generate_picking_list_pdf_file(
                self.document, base_url='/', save=False)

        meal_types = [
            m['meal_type']
            for _, meals in captured['context']['daily_picking_data']
            for m in meals
        ]
        self.assertNotIn('SOUP', meal_types)
        self.assertIn('LUNCH', meal_types)

    def test_soup_date_out_of_range_rejected(self):
        """Datum polévky mimo období výdejky → chyba, žádný příkaz nevznikne."""
        out = date(2025, 9, 11)  # dokument je jen na 2025-09-10
        response = self.client.post(self._url(), data={
            f'new_ingredient_soup_{out.isoformat()}_0': str(self.rice.id),
            f'new_quantity_soup_{out.isoformat()}_0': '2',
        }, follow=True)
        self.assertContains(response, 'Datum polévky je mimo období výdejky.')
        self.assertFalse(
            ProductionOrder.objects.filter(
                meal_type=ProductionOrder.MealType.SOUP).exists())

    def test_soup_creation_integrity_race_uses_existing(self):
        """Souběh: create narazí na unique constraint → helper vrátí příkaz,
        který mezitím založil druhý request (větev IntegrityError)."""
        from django.db import IntegrityError
        from apps.production import views

        existing = MagicMock(name='existing_soup_order')
        sibling = MagicMock(name='sibling')
        # filter().first() v pořadí: initial soup → None, sibling → sibling,
        # fallback po IntegrityError → existing
        firsts = [None, sibling, existing]

        def filter_side(*args, **kwargs):
            m = MagicMock()
            m.first.return_value = firsts.pop(0)
            return m

        with patch.object(views.ProductionOrder, 'objects') as objs, \
                patch.object(views.Recipe, 'objects') as recipe_objs:
            objs.filter.side_effect = filter_side
            objs.create.side_effect = IntegrityError('duplicate')
            recipe_objs.get_or_create.return_value = (MagicMock(), True)
            result = views._get_or_create_lazy_meal_order(
                self.document, self.day,
                ProductionOrder.MealType.SOUP, 'Polévka', 'POLEVKA',
            )

        self.assertIs(result, existing)

    def test_soup_removed_when_document_deleted(self):
        """Smazání výdejky uklidí i prázdný/naplněný příkaz polévky."""
        self.client.post(self._url(), data={
            f'new_ingredient_soup_{self.day.isoformat()}_0': str(self.rice.id),
            f'new_quantity_soup_{self.day.isoformat()}_0': '2',
        })
        soup_id = self._soup_order().id

        response = self.client.post(
            f'/production/vydejky/{self.document.id}/smazat/')
        self.assertEqual(response.status_code, 302)
        self.assertFalse(ProductionOrder.objects.filter(id=soup_id).exists())
