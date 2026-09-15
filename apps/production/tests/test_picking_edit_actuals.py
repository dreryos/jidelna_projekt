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

    def test_unissue_reverts_to_pending_and_restores_stock(self):
        """Zrušit výdej → COMPLETED zpět na PENDING, sklad i blokace obnoveny."""
        # nejdřív vydáme
        self.client.post(self._url(), data={
            f'quantity_actual_item_{self.item.id}': '3',
        })
        self.stock.refresh_from_db()
        self.assertEqual(self.stock.quantity, Decimal('97.000'))
        self.assertEqual(self.stock.quantity_blocked, Decimal('0.000'))

        # zrušíme výdej
        response = self.client.post(self._url(), data={
            f'unissue_item_{self.item.id}': '1',
        })
        self.assertEqual(response.status_code, 302)

        self.item.refresh_from_db()
        self.assertEqual(self.item.status, PickingList.Status.PENDING)
        self.assertIsNone(self.item.quantity_actual)
        self.stock.refresh_from_db()
        self.assertEqual(self.stock.quantity, Decimal('100.000'))
        self.assertEqual(self.stock.quantity_blocked, Decimal('3.000'))

    def test_correction_flow_unissue_then_reissue(self):
        """Oprava: vydat 3 → zrušit výdej → vydat 2. Sklad 98, blokace 0."""
        self.client.post(self._url(), data={
            f'quantity_actual_item_{self.item.id}': '3',
        })
        self.client.post(self._url(), data={
            f'unissue_item_{self.item.id}': '1',
        })
        self.client.post(self._url(), data={
            f'quantity_actual_item_{self.item.id}': '2',
        })

        self.item.refresh_from_db()
        self.assertEqual(self.item.status, PickingList.Status.COMPLETED)
        self.assertEqual(self.item.quantity_actual, Decimal('2.000'))
        self.stock.refresh_from_db()
        self.assertEqual(self.stock.quantity, Decimal('98.000'))
        self.assertEqual(self.stock.quantity_blocked, Decimal('0.000'))

    def test_unissue_pending_item_is_noop(self):
        """Zrušit výdej na nevydané (PENDING) položce nic nezmění."""
        response = self.client.post(self._url(), data={
            f'unissue_item_{self.item.id}': '1',
        })
        self.assertEqual(response.status_code, 302)

        self.item.refresh_from_db()
        self.assertEqual(self.item.status, PickingList.Status.PENDING)
        self.assertIsNone(self.item.quantity_actual)
        self.stock.refresh_from_db()
        self.assertEqual(self.stock.quantity, Decimal('100.000'))
        self.assertEqual(self.stock.quantity_blocked, Decimal('3.000'))

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


class PickingBulkDeleteTest(TestCase):
    """Hromadné odebrání více surovin naráz (checkboxy + tlačítko Smazat vybrané)."""

    def setUp(self):
        self.canteen = Canteen.objects.create(name='Test Canteen')
        self.warehouse = Warehouse.objects.create(name='Main', canteen=self.canteen)

        self.ingredients = {}
        self.stocks = {}
        for name in ('Mouka', 'Cukr', 'Sůl'):
            ing = Ingredient.objects.create(
                name=name, unit='kg', base_unit='kg', recipe_unit='kg',
                conversion_factor=Decimal('1.0'),
            )
            self.ingredients[name] = ing
            self.stocks[name] = StockItem.objects.create(
                warehouse=self.warehouse, ingredient=ing,
                quantity=Decimal('100.000'), price=Decimal('1.00'),
            )

        self.recipe = Recipe.objects.create(name='Koláč', base_portions=10)
        for name in ('Mouka', 'Cukr', 'Sůl'):
            RecipeIngredient.objects.create(
                recipe=self.recipe, ingredient=self.ingredients[name],
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
        for item in PickingList.objects.filter(production_order=self.order):
            item.document = self.document
            item.save()

        self.items = {
            item.ingredient.name: item
            for item in PickingList.objects.filter(document=self.document)
        }

        self.user = User.objects.create_superuser(username='admin', password='x')
        self.client.force_login(self.user)

    def _url(self, document=None):
        document = document or self.document
        return f'/production/vydejky/{document.id}/edit/'

    def test_bulk_delete_removes_multiple_and_unblocks(self):
        id1 = self.items['Mouka'].id
        id2 = self.items['Cukr'].id
        response = self.client.post(self._url(), data={
            'bulk_delete_items': '1',
            'delete_items': [id1, id2],
        })
        self.assertEqual(response.status_code, 302)

        self.assertFalse(PickingList.objects.filter(id=id1).exists())
        self.assertFalse(PickingList.objects.filter(id=id2).exists())
        self.assertTrue(PickingList.objects.filter(id=self.items['Sůl'].id).exists())

        self.stocks['Mouka'].refresh_from_db()
        self.stocks['Cukr'].refresh_from_db()
        self.stocks['Sůl'].refresh_from_db()
        self.assertEqual(self.stocks['Mouka'].quantity_blocked, Decimal('0.000'))
        self.assertEqual(self.stocks['Cukr'].quantity_blocked, Decimal('0.000'))
        self.assertEqual(self.stocks['Sůl'].quantity_blocked, Decimal('3.000'))
        # mazání neodečítá ze skladu, jen odblokuje
        self.assertEqual(self.stocks['Mouka'].quantity, Decimal('100.000'))

    def test_bulk_delete_ignores_completed_items(self):
        sul_item = self.items['Sůl']
        self.client.post(self._url(), data={
            f'quantity_actual_item_{sul_item.id}': '3',
        })
        sul_item.refresh_from_db()
        self.assertEqual(sul_item.status, PickingList.Status.COMPLETED)

        id1 = self.items['Mouka'].id
        id2 = self.items['Cukr'].id
        response = self.client.post(self._url(), data={
            'bulk_delete_items': '1',
            'delete_items': [id1, id2, sul_item.id],
        })
        self.assertEqual(response.status_code, 302)

        self.assertFalse(PickingList.objects.filter(id=id1).exists())
        self.assertFalse(PickingList.objects.filter(id=id2).exists())
        sul_item.refresh_from_db()
        self.assertEqual(sul_item.status, PickingList.Status.COMPLETED)
        self.stocks['Sůl'].refresh_from_db()
        self.assertEqual(self.stocks['Sůl'].quantity, Decimal('97.000'))
        self.assertEqual(self.stocks['Sůl'].quantity_blocked, Decimal('0.000'))

    def test_bulk_delete_requires_button_marker(self):
        id1 = self.items['Mouka'].id
        response = self.client.post(self._url(), data={
            'delete_items': [id1],
        })
        self.assertEqual(response.status_code, 302)
        self.assertTrue(PickingList.objects.filter(id=id1).exists())
        self.stocks['Mouka'].refresh_from_db()
        self.assertEqual(self.stocks['Mouka'].quantity_blocked, Decimal('3.000'))

    def test_bulk_delete_ignores_foreign_document_items(self):
        other_document = PickingListDocument.objects.create(
            name='Other Doc', canteen=self.canteen,
            date_from=date(2025, 9, 10), date_to=date(2025, 9, 10),
            created_by=User.objects.create_user(username='creator2'),
        )
        foreign_id = self.items['Mouka'].id
        response = self.client.post(self._url(document=other_document), data={
            'bulk_delete_items': '1',
            'delete_items': [foreign_id],
        })
        self.assertEqual(response.status_code, 302)
        self.assertTrue(PickingList.objects.filter(id=foreign_id).exists())

    def test_bulk_delete_empty_selection_is_noop(self):
        response = self.client.post(self._url(), data={
            'bulk_delete_items': '1',
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            PickingList.objects.filter(document=self.document).count(), 3
        )

    def test_bulk_delete_invalid_ids_ignored(self):
        response = self.client.post(self._url(), data={
            'bulk_delete_items': '1',
            'delete_items': ['abc', '999999'],
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            PickingList.objects.filter(document=self.document).count(), 3
        )

    def test_bulk_delete_on_archived_document_forbidden(self):
        """Archivovaný dokument: view chytá PermissionDenied a redirectuje
        s chybovou hláškou (stejný kontrakt jako u ostatních POST akcí)."""
        self.document.archived = True
        self.document.save()
        id1 = self.items['Mouka'].id
        response = self.client.post(self._url(), data={
            'bulk_delete_items': '1',
            'delete_items': [id1],
        })
        self.assertEqual(response.status_code, 302)
        self.assertTrue(PickingList.objects.filter(id=id1).exists())

    def test_single_delete_still_works_with_bulk_field_present(self):
        id1 = self.items['Mouka'].id
        response = self.client.post(self._url(), data={
            f'delete_item_{id1}': '1',
        })
        self.assertEqual(response.status_code, 302)
        self.assertFalse(PickingList.objects.filter(id=id1).exists())
        self.stocks['Mouka'].refresh_from_db()
        self.assertEqual(self.stocks['Mouka'].quantity_blocked, Decimal('0.000'))

    def test_bulk_delete_removes_outside_meal_item_and_unblocks(self):
        outside_ingredient = Ingredient.objects.create(
            name='Pepř', unit='kg', base_unit='kg', recipe_unit='kg',
            conversion_factor=Decimal('1.0'),
        )
        outside_stock = StockItem.objects.create(
            warehouse=self.warehouse,
            ingredient=outside_ingredient,
            quantity=Decimal('50.000'),
            price=Decimal('1.00'),
        )
        outside_item = PickingList.objects.create(
            production_order=None,
            document=self.document,
            warehouse=self.warehouse,
            ingredient=outside_ingredient,
            quantity_planned=Decimal('1.500'),
            status=PickingList.Status.PENDING,
        )
        outside_stock.refresh_from_db()
        self.assertEqual(outside_stock.quantity_blocked, Decimal('1.500'))

        response = self.client.post(self._url(), data={
            'bulk_delete_items': '1',
            'delete_items': [outside_item.id],
        })
        self.assertEqual(response.status_code, 302)
        self.assertFalse(PickingList.objects.filter(id=outside_item.id).exists())
        outside_stock.refresh_from_db()
        self.assertEqual(outside_stock.quantity, Decimal('50.000'))
        self.assertEqual(outside_stock.quantity_blocked, Decimal('0.000'))

    def test_edit_page_renders_bulk_delete_checkboxes(self):
        """GET stránky obsahuje bulk checkboxy a tlačítko Smazat vybrané."""
        response = self.client.get(self._url())
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'item-delete-checkbox')
        self.assertContains(response, 'select-all-items')
        self.assertContains(response, 'name="bulk_delete_items"')
        self.assertContains(response, 'id="bulk-delete-bar"')
