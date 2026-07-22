from django.test import TestCase
from django.contrib.auth.models import User
from decimal import Decimal
from datetime import date

from apps.canteens.models import Canteen, Warehouse
from apps.core.models import Ingredient, Recipe, RecipeIngredient
from apps.inventory.models import StockItem
from apps.production.models import (
    ProductionOrder, PickingList, PickingListDocument,
    MenuPlan, ProductionOrderPortionVariant,
)


class MealReplacementTest(TestCase):
    """Záměna plánovaného jídla ve výdejce: originál dostane odběr 0
    a sbalí se, místo něj se vygenerují normy jiného receptu."""

    def setUp(self):
        self.user = User.objects.create_superuser('admin', 'a@a.cz', 'x')
        self.client.force_login(self.user)

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

        self.menu_plan = MenuPlan.objects.create(
            name='Plan', canteen=self.canteen,
            date_from=date(2025, 9, 10), date_to=date(2025, 9, 10),
        )
        self.original_recipe = Recipe.objects.create(name='Guláš', base_portions=10)
        RecipeIngredient.objects.create(
            recipe=self.original_recipe, ingredient=self.flour,
            quantity_per_portion=Decimal('1.000'),
        )
        self.new_recipe = Recipe.objects.create(name='Rizoto', base_portions=10)
        RecipeIngredient.objects.create(
            recipe=self.new_recipe, ingredient=self.rice,
            quantity_per_portion=Decimal('2.000'),
        )

        self.order = ProductionOrder.objects.create(
            recipe=self.original_recipe, canteen=self.canteen,
            menu_plan=self.menu_plan, date=date(2025, 9, 10),
            meal_type=ProductionOrder.MealType.LUNCH,
        )
        ProductionOrderPortionVariant.objects.create(
            production_order=self.order, portions=5, coefficient=Decimal('1.0'),
        )
        self.order.generate_picking_list()

        self.document = PickingListDocument.objects.create(
            name='Doc', canteen=self.canteen,
            date_from=date(2025, 9, 10), date_to=date(2025, 9, 10),
            created_by=self.user,
        )
        # Přiřazení přes save(), aby se zablokoval sklad jako v reálném toku
        for item in PickingList.objects.filter(production_order=self.order):
            item.document = self.document
            item.save()

    def _edit_url(self):
        return f'/production/vydejky/{self.document.id}/edit/'

    def _existing_qty_fields(self):
        # Nová UX: pole skutečného množství jsou defaultně prázdná. Prázdné =
        # beze změny (položka zůstane PENDING), takže záměnu jídla nezablokují.
        return {
            f'quantity_actual_item_{item.id}': ''
            for item in PickingList.objects.filter(document=self.document)
        }

    def _replace(self):
        return self.client.post(self._edit_url(), data={
            **self._existing_qty_fields(),
            f'replace_order_{self.order.id}': str(self.new_recipe.id),
        })

    def test_replace_creates_substitute_and_zeroes_original(self):
        response = self._replace()
        self.assertEqual(response.status_code, 302)

        # Originál: odběr 0, COMPLETED, blokace mouky uvolněna
        original_item = PickingList.objects.get(
            production_order=self.order, ingredient=self.flour)
        self.assertEqual(original_item.status, PickingList.Status.COMPLETED)
        self.assertEqual(original_item.quantity_actual, Decimal('0'))
        flour_stock = StockItem.objects.get(ingredient=self.flour)
        self.assertEqual(flour_stock.quantity, Decimal('100'))
        self.assertEqual(flour_stock.quantity_blocked, Decimal('0'))

        # Náhrada: stejné porce, normy nového receptu, PENDING, blokuje sklad
        replacement = ProductionOrder.objects.get(replacement_of=self.order)
        self.assertEqual(replacement.recipe, self.new_recipe)
        self.assertEqual(replacement.meal_type, self.order.meal_type)
        self.assertEqual(replacement.total_effective_portions, Decimal('5.0'))
        repl_item = PickingList.objects.get(
            production_order=replacement, ingredient=self.rice)
        self.assertEqual(repl_item.document_id, self.document.id)
        self.assertEqual(repl_item.quantity_planned, Decimal('10'))  # 5 × 2 kg
        self.assertEqual(repl_item.status, PickingList.Status.PENDING)
        rice_stock = StockItem.objects.get(ingredient=self.rice)
        self.assertEqual(rice_stock.quantity_blocked, Decimal('10'))

    def test_replace_forbidden_when_issued(self):
        item = PickingList.objects.get(production_order=self.order)
        item.quantity_actual = item.quantity_planned
        item.status = PickingList.Status.COMPLETED
        item.save()

        response = self.client.post(self._edit_url(), data={
            f'quantity_actual_item_{item.id}': str(item.quantity_planned),
            f'status_item_{item.id}': 'COMPLETED',
            f'replace_order_{self.order.id}': str(self.new_recipe.id),
        })
        self.assertEqual(response.status_code, 302)
        self.assertFalse(
            ProductionOrder.objects.filter(replacement_of=self.order).exists())

    def test_unreplace_restores_original(self):
        self._replace()
        replacement = ProductionOrder.objects.get(replacement_of=self.order)

        response = self.client.post(self._edit_url(), data={
            **self._existing_qty_fields(),
            f'unreplace_order_{self.order.id}': '1',
        })
        self.assertEqual(response.status_code, 302)

        self.assertFalse(
            ProductionOrder.objects.filter(id=replacement.id).exists())
        original_item = PickingList.objects.get(
            production_order=self.order, ingredient=self.flour)
        self.assertEqual(original_item.status, PickingList.Status.PENDING)
        self.assertIsNone(original_item.quantity_actual)
        # Blokace mouky obnovena, rýže uvolněna
        self.assertEqual(
            StockItem.objects.get(ingredient=self.flour).quantity_blocked,
            Decimal('5'))
        self.assertEqual(
            StockItem.objects.get(ingredient=self.rice).quantity_blocked,
            Decimal('0'))

    def test_document_delete_cleans_replacement_order(self):
        self._replace()
        replacement = ProductionOrder.objects.get(replacement_of=self.order)

        response = self.client.post(
            f'/production/vydejky/{self.document.id}/smazat/')
        self.assertEqual(response.status_code, 302)
        self.assertFalse(
            ProductionOrder.objects.filter(id=replacement.id).exists())
        # Původní plánované jídlo zůstává
        self.assertTrue(ProductionOrder.objects.filter(id=self.order.id).exists())

    def test_replacement_hidden_in_menu_plan(self):
        self._replace()
        response = self.client.get(f'/production/jidelnicky/{self.menu_plan.id}/')
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        # Náhrada se v plánu nezobrazuje jako jídlo; „Rizoto" smí být nejvýš
        # v selectech receptů, ne v kartě jídla
        self.assertNotIn('Rizoto</strong>', html)
        self.assertIn('Guláš', html)

    def test_render_strip_and_badge(self):
        self._replace()
        html = self.client.get(self._edit_url()).content.decode()
        self.assertIn('zaměněno za <strong>Rizoto</strong>', html)
        self.assertIn('záměna za: Guláš', html)
        self.assertIn(f'unreplace_order_{self.order.id}', html)
        # karta náhrady nesmí nabízet další záměnu
        self.assertNotIn(
            f'replace_order_{ProductionOrder.objects.get(replacement_of=self.order).id}',
            html)
