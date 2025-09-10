from django.test import TestCase
from decimal import Decimal

from apps.canteens.models import Canteen, Warehouse
from apps.core.models import Ingredient, Recipe, RecipeIngredient
from apps.inventory.models import StockItem
from apps.production.models import ProductionOrder, PickingList


class PickingListDecrementTest(TestCase):
    def setUp(self):
        self.canteen = Canteen.objects.create(name='Test Canteen')
        self.warehouse = Warehouse.objects.create(name='Main', canteen=self.canteen)
        self.ingredient = Ingredient.objects.create(name='Mouka', unit='kg')
        # stock 10 kg at price 1.0
        StockItem.objects.create(warehouse=self.warehouse, ingredient=self.ingredient, quantity=Decimal('10.000'), price=1.0)

        # recipe with 1 kg per adult portion
        self.recipe = Recipe.objects.create(name='Chleba')
        RecipeIngredient.objects.create(recipe=self.recipe, ingredient=self.ingredient, quantity_adult=Decimal('1.000'), quantity_child=Decimal('0.500'))

    def test_decrement_on_complete(self):
        order = ProductionOrder.objects.create(recipe=self.recipe, canteen=self.canteen, portions_adult=2, portions_child=0, date='2025-09-10')
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
