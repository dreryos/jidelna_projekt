"""Testy nového workflow zadávání skutečně vydaných množství ve výdejce.

Nová UX (větev výdejky-rework):
- pole skutečného množství jsou defaultně prázdná,
- vyplněné množství = vydat (COMPLETED + odečet ze skladu),
- prázdné pole = beze změny (položka zůstane PENDING, blokace drží),
- koš odebere surovinu z výdejky a uvolní blokaci na skladu.
"""
from decimal import Decimal
from datetime import date

from django.test import TestCase
from django.contrib.auth.models import User

from apps.canteens.models import Canteen, Warehouse
from apps.core.models import Ingredient, Recipe, RecipeIngredient
from apps.inventory.models import StockItem
from apps.production.models import (
    ProductionOrder, PickingList, MenuPlan,
    ProductionOrderPortionVariant, PickingListDocument,
)


class PickingEditActualsTest(TestCase):
    def setUp(self):
        self.canteen = Canteen.objects.create(name='Test Canteen')
        self.warehouse = Warehouse.objects.create(name='Main', canteen=self.canteen)
        self.ingredient = Ingredient.objects.create(
            name='Mouka', unit='kg', base_unit='kg', recipe_unit='kg',
            conversion_factor=Decimal('1.0'),
        )
        self.stock = StockItem.objects.create(
            warehouse=self.warehouse, ingredient=self.ingredient,
            quantity=Decimal('100.000'), price=Decimal('1.00'),
        )
        self.recipe = Recipe.objects.create(name='Chleba', base_portions=10)
        RecipeIngredient.objects.create(
            recipe=self.recipe, ingredient=self.ingredient,
            quantity_per_portion=Decimal('1.000'),
        )
        self.menu_plan = MenuPlan.objects.create(
            name='Test Menu', canteen=self.canteen,
            date_from=date(2025, 9, 10), date_to=date(2025, 9, 10),
        )
        self.order = ProductionOrder.objects.create(
            recipe=self.recipe, canteen=self.canteen,
            menu_plan=self.menu_plan, date=date(2025, 9, 10),
        )
        ProductionOrderPortionVariant.objects.create(
            production_order=self.order, portions=3, coefficient=Decimal('1.0'),
        )
        self.order.generate_picking_list()

        self.document = PickingListDocument.objects.create(
            name='Doc', canteen=self.canteen,
            date_from=date(2025, 9, 10), date_to=date(2025, 9, 10),
            created_by=User.objects.create_user(username='creator'),
        )
        # Přiřazení přes save() zablokuje plánované množství (reálný tok)
        for item in PickingList.objects.filter(production_order=self.order):
            item.document = self.document
            item.save()

        self.item = PickingList.objects.get(production_order=self.order)
        # planned = 3 porce × 1 kg/porci
        self.assertEqual(self.item.quantity_planned, Decimal('3.000'))
        self.stock.refresh_from_db()
        self.assertEqual(self.stock.quantity_blocked, Decimal('3.000'))

        self.user = User.objects.create_superuser(username='admin', password='x')
        self.client.force_login(self.user)

    def _url(self):
        return f'/production/vydejky/{self.document.id}/edit/'

    def test_filled_quantity_issues_and_deducts(self):
        """Vyplněné množství → COMPLETED, odblokuje a odečte ze skladu."""
        response = self.client.post(self._url(), data={
            f'quantity_actual_item_{self.item.id}': '3',
        })
        self.assertEqual(response.status_code, 302)

        self.item.refresh_from_db()
        self.assertEqual(self.item.status, PickingList.Status.COMPLETED)
        self.assertEqual(self.item.quantity_actual, Decimal('3.000'))

        self.stock.refresh_from_db()
        self.assertEqual(self.stock.quantity, Decimal('97.000'))  # 100 - 3
        self.assertEqual(self.stock.quantity_blocked, Decimal('0.000'))

    def test_partial_fill_deducts_actual_and_releases_block(self):
        """Vydané menší než plánované → odečte skutečné, blokace se uvolní celá."""
        response = self.client.post(self._url(), data={
            f'quantity_actual_item_{self.item.id}': '2',
        })
        self.assertEqual(response.status_code, 302)

        self.item.refresh_from_db()
        self.assertEqual(self.item.quantity_actual, Decimal('2.000'))
        self.stock.refresh_from_db()
        self.assertEqual(self.stock.quantity, Decimal('98.000'))  # 100 - 2
        self.assertEqual(self.stock.quantity_blocked, Decimal('0.000'))

    def test_empty_quantity_leaves_item_unchanged(self):
        """Prázdné pole → beze změny: PENDING, blokace i sklad zůstanou."""
        response = self.client.post(self._url(), data={
            f'quantity_actual_item_{self.item.id}': '',
        })
        self.assertEqual(response.status_code, 302)

        self.item.refresh_from_db()
        self.assertEqual(self.item.status, PickingList.Status.PENDING)
        self.assertIsNone(self.item.quantity_actual)
        self.stock.refresh_from_db()
        self.assertEqual(self.stock.quantity, Decimal('100.000'))
        self.assertEqual(self.stock.quantity_blocked, Decimal('3.000'))

    def test_zero_quantity_is_rejected(self):
        """0 není platné vydané množství – položka zůstane PENDING."""
        response = self.client.post(self._url(), data={
            f'quantity_actual_item_{self.item.id}': '0',
        })
        self.assertEqual(response.status_code, 302)

        self.item.refresh_from_db()
        self.assertEqual(self.item.status, PickingList.Status.PENDING)
        self.assertIsNone(self.item.quantity_actual)
        self.stock.refresh_from_db()
        self.assertEqual(self.stock.quantity, Decimal('100.000'))
        self.assertEqual(self.stock.quantity_blocked, Decimal('3.000'))

    def test_missing_field_leaves_item_unchanged(self):
        """Pole vůbec neodeslané (jiná akce) → položka beze změny."""
        response = self.client.post(self._url(), data={'cook': ''})
        self.assertEqual(response.status_code, 302)

        self.item.refresh_from_db()
        self.assertEqual(self.item.status, PickingList.Status.PENDING)
        self.assertIsNone(self.item.quantity_actual)
        self.stock.refresh_from_db()
        self.assertEqual(self.stock.quantity_blocked, Decimal('3.000'))
    def test_delete_item_removes_and_unblocks(self):
        """Koš → smaže položku a uvolní blokaci na skladu."""
        item_id = self.item.id
        response = self.client.post(self._url(), data={
            f'delete_item_{item_id}': '1',
        })
        self.assertEqual(response.status_code, 302)

        self.assertFalse(PickingList.objects.filter(id=item_id).exists())
        self.stock.refresh_from_db()
        self.assertEqual(self.stock.quantity, Decimal('100.000'))
        self.assertEqual(self.stock.quantity_blocked, Decimal('0.000'))

    def test_completed_item_not_reissued_on_resave(self):
        """Vydaná položka se prázdným polem znovu neodečte (jednosměrný tok)."""
        # vydáme
        self.client.post(self._url(), data={
            f'quantity_actual_item_{self.item.id}': '3',
        })
        self.stock.refresh_from_db()
        self.assertEqual(self.stock.quantity, Decimal('97.000'))

        # opětovné uložení s prázdným polem nesmí sklad hnout
        self.client.post(self._url(), data={
            f'quantity_actual_item_{self.item.id}': '',
        })
        self.stock.refresh_from_db()
        self.assertEqual(self.stock.quantity, Decimal('97.000'))
        self.item.refresh_from_db()
        self.assertEqual(self.item.status, PickingList.Status.COMPLETED)
