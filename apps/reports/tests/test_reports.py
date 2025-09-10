from django.test import TestCase
from decimal import Decimal

from apps.canteens.models import Canteen, Warehouse
from apps.core.models import Ingredient, Recipe, RecipeIngredient
from apps.inventory.models import StockItem
from apps.production.models import ProductionOrder
from apps.reports.views import generate_order_report


class ReportAggregationTest(TestCase):
    def setUp(self):
        self.canteen = Canteen.objects.create(name='Růžená')
        self.w1 = Warehouse.objects.create(name='Sklad1', canteen=self.canteen)
        self.ingredient = Ingredient.objects.create(name='Cukr', unit='kg')
        StockItem.objects.create(warehouse=self.w1, ingredient=self.ingredient, quantity=Decimal('5.000'), price=10.0)

        self.recipe = Recipe.objects.create(name='Koláč')
        RecipeIngredient.objects.create(recipe=self.recipe, ingredient=self.ingredient, quantity_adult=Decimal('1.000'), quantity_child=Decimal('0.500'))

    def test_generate_order_report_basic(self):
        # create production orders in date range
        ProductionOrder.objects.create(recipe=self.recipe, canteen=self.canteen, portions_adult=3, portions_child=0, date='2025-09-01')
        report = generate_order_report(self.canteen, '2025-09-01', '2025-09-30')
        items = report['items']
        self.assertEqual(len(items), 1)
        it = items[0]
        # needed = 3 kg, stock = 5 kg => to_order 0
        self.assertEqual(it['needed'], 3.0)
        self.assertEqual(it['stock'], 5.0)
        self.assertEqual(it['to_order'], 0)
