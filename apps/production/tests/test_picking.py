from django.test import TestCase
from decimal import Decimal
from datetime import date

from apps.canteens.models import Canteen, Warehouse
from apps.core.models import Ingredient, Recipe, RecipeIngredient
from apps.inventory.models import StockItem
from apps.production.models import ProductionOrder, PickingList, MenuPlan, ProductionOrderPortionVariant


class PickingListDecrementTest(TestCase):
    def setUp(self):
        self.canteen = Canteen.objects.create(name='Test Canteen')
        self.warehouse = Warehouse.objects.create(name='Main', canteen=self.canteen)
        self.ingredient = Ingredient.objects.create(name='Mouka', unit='kg', base_unit='kg', recipe_unit='kg')
        # stock 10 kg at price 1.0
        StockItem.objects.create(warehouse=self.warehouse, ingredient=self.ingredient, quantity=Decimal('10.000'), price=1.0)

        # recipe with 1 kg per portion
        self.recipe = Recipe.objects.create(name='Chleba', base_portions=10)
        RecipeIngredient.objects.create(recipe=self.recipe, ingredient=self.ingredient, quantity_per_portion=Decimal('1.000'))

    def test_decrement_on_complete(self):
        # Nejprve vytvoříme MenuPlan (nyní povinný)
        menu_plan = MenuPlan.objects.create(
            name='Test Menu',
            canteen=self.canteen,
            date_from=date(2025, 9, 10),
            date_to=date(2025, 9, 10)
        )
        
        # Vytvoříme ProductionOrder s menu_plan
        order = ProductionOrder.objects.create(
            recipe=self.recipe,
            canteen=self.canteen,
            menu_plan=menu_plan,
            date=date(2025, 9, 10)
        )
        
        # Přidáme variantu porce (nový systém)
        ProductionOrderPortionVariant.objects.create(
            production_order=order,
            portions=2,
            coefficient=Decimal('1.0')
        )
        
        # Znovu vygenerujeme picking list s variantou
        order.generate_picking_list()
        
        # There should be one picking item created
        pl = order.picking_list_items.first()
        self.assertIsNotNone(pl)

        # set actual and complete
        pl.quantity_actual = Decimal('2.000')
        pl.warehouse = self.warehouse
        pl.status = PickingList.Status.COMPLETED
        pl.save()

        # stock should be decremented from 10 -> 8
        si = StockItem.objects.get(warehouse=self.warehouse, ingredient=self.ingredient)
        self.assertEqual(si.quantity, Decimal('8.000'))
