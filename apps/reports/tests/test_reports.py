from django.test import TestCase
from decimal import Decimal
from django.contrib.auth import get_user_model

from apps.canteens.models import Canteen, Warehouse
from apps.core.models import Ingredient, Recipe, RecipeIngredient
from apps.inventory.models import StockItem
from apps.production.models import ProductionOrder, MenuPlan, ProductionOrderPortionVariant
from apps.reports.views import generate_order_report

User = get_user_model()


class ReportAggregationTest(TestCase):
    def setUp(self):
        self.canteen = Canteen.objects.create(name='Růžená')
        self.w1 = Warehouse.objects.create(name='Sklad1', canteen=self.canteen)
        
        # Suroviny s novými jednotkami
        self.ingredient = Ingredient.objects.create(
            name='Cukr',
            base_unit='kg',
            recipe_unit='g',
            conversion_factor=Decimal('1000')  # 1 kg = 1000 g
        )
        StockItem.objects.create(
            warehouse=self.w1,
            ingredient=self.ingredient,
            quantity=Decimal('5.000'),
            price=10.0
        )

        self.recipe = Recipe.objects.create(name='Koláč')
        # Nová struktura: quantity_per_portion v receptových jednotkách (gramy)
        RecipeIngredient.objects.create(
            recipe=self.recipe,
            ingredient=self.ingredient,
            quantity_per_portion=Decimal('1000.000')  # 1000g = 1kg na porci
        )
        
        # Vytvoříme menu plan
        self.menu_plan = MenuPlan.objects.create(
            name='Test Menu',
            canteen=self.canteen,
            date_from='2025-09-01',
            date_to='2025-09-30'
        )

    def test_generate_order_report_basic(self):
        # Vytvoříme výrobní příkaz s variantami porcí
        order = ProductionOrder.objects.create(
            recipe=self.recipe,
            menu_plan=self.menu_plan,
            canteen=self.canteen,
            date='2025-09-01'
        )
        # Přidáme variantu: 3 porce s koeficientem 1.0 (normální porce)
        ProductionOrderPortionVariant.objects.create(
            production_order=order,
            coefficient=Decimal('1.0'),
            portions=3
        )
        
        report = generate_order_report(self.canteen, '2025-09-01', '2025-09-30')
        items = report['items']
        self.assertEqual(len(items), 1)
        it = items[0]
        # needed = 3 kg (3 porce × 1kg/porce), stock = 5 kg => to_order 0
        self.assertEqual(it['needed'], 3.0)
        self.assertEqual(it['stock'], 5.0)
        self.assertEqual(it['to_order'], 0)
    
    def test_generate_order_report_with_multiple_variants(self):
        """Test s více variantami porcí (různé koeficienty)"""
        order = ProductionOrder.objects.create(
            recipe=self.recipe,
            menu_plan=self.menu_plan,
            canteen=self.canteen,
            date='2025-09-01'
        )
        # 10 normálních porcí (koef. 1.0) + 5 polovičních porcí (koef. 0.5)
        ProductionOrderPortionVariant.objects.create(
            production_order=order,
            coefficient=Decimal('1.0'),
            portions=10
        )
        ProductionOrderPortionVariant.objects.create(
            production_order=order,
            coefficient=Decimal('0.5'),
            portions=5
        )
        
        report = generate_order_report(self.canteen, '2025-09-01', '2025-09-30')
        items = report['items']
        self.assertEqual(len(items), 1)
        it = items[0]
        # needed = (10 × 1.0 + 5 × 0.5) × 1kg = 12.5 kg, stock = 5 kg => to_order 7.5
        self.assertEqual(it['needed'], 12.5)
        self.assertEqual(it['stock'], 5.0)
        self.assertEqual(it['to_order'], 7.5)
    
    def test_generate_order_report_insufficient_stock(self):
        """Test když není dostatek zásob"""
        order = ProductionOrder.objects.create(
            recipe=self.recipe,
            menu_plan=self.menu_plan,
            canteen=self.canteen,
            date='2025-09-01'
        )
        ProductionOrderPortionVariant.objects.create(
            production_order=order,
            coefficient=Decimal('1.0'),
            portions=10  # Potřebujeme 10 kg, ale máme jen 5 kg
        )
        
        report = generate_order_report(self.canteen, '2025-09-01', '2025-09-30')
        items = report['items']
        self.assertEqual(len(items), 1)
        it = items[0]
        self.assertEqual(it['needed'], 10.0)
        self.assertEqual(it['stock'], 5.0)
        self.assertEqual(it['to_order'], 5.0)
    
    def test_generate_order_report_multiple_orders(self):
        """Test s více výrobními příkazy ve stejném období"""
        # První příkaz
        order1 = ProductionOrder.objects.create(
            recipe=self.recipe,
            menu_plan=self.menu_plan,
            canteen=self.canteen,
            date='2025-09-01'
        )
        ProductionOrderPortionVariant.objects.create(
            production_order=order1,
            coefficient=Decimal('1.0'),
            portions=2
        )
        
        # Druhý příkaz
        order2 = ProductionOrder.objects.create(
            recipe=self.recipe,
            menu_plan=self.menu_plan,
            canteen=self.canteen,
            date='2025-09-15'
        )
        ProductionOrderPortionVariant.objects.create(
            production_order=order2,
            coefficient=Decimal('1.0'),
            portions=3
        )
        
        report = generate_order_report(self.canteen, '2025-09-01', '2025-09-30')
        items = report['items']
        self.assertEqual(len(items), 1)
        it = items[0]
        # needed = (2 + 3) kg = 5 kg, stock = 5 kg => to_order 0
        self.assertEqual(it['needed'], 5.0)
        self.assertEqual(it['stock'], 5.0)
        self.assertEqual(it['to_order'], 0)
    
    def test_generate_order_report_outside_date_range(self):
        """Test že příkazy mimo období nejsou zahrnuty"""
        order = ProductionOrder.objects.create(
            recipe=self.recipe,
            menu_plan=self.menu_plan,
            canteen=self.canteen,
            date='2025-10-01'  # Mimo období 09/01-09/30
        )
        ProductionOrderPortionVariant.objects.create(
            production_order=order,
            coefficient=Decimal('1.0'),
            portions=10
        )
        
        report = generate_order_report(self.canteen, '2025-09-01', '2025-09-30')
        items = report['items']
        # Žádný příkaz v období -> žádné položky
        self.assertEqual(len(items), 0)
