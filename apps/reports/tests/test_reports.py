from django.test import TestCase
from decimal import Decimal
from django.contrib.auth import get_user_model

from apps.canteens.models import Canteen, Warehouse
from apps.core.models import Ingredient, Recipe, RecipeIngredient
from apps.inventory.models import StockItem
from apps.production.models import (
    ProductionOrder,
    MenuPlan,
    ProductionOrderPortionVariant,
    ProductionOrderIngredientOverride,
    PickingList,
    PickingListDocument,
)
from apps.reports.views import generate_order_report

User = get_user_model()

# Conversion factor: 1 kg = 1000 g
KG_TO_G_CONVERSION = Decimal('1000')


class ReportAggregationTest(TestCase):
    def setUp(self):
        self.canteen = Canteen.objects.create(name='Růžená')
        self.w1 = Warehouse.objects.create(name='Sklad1', canteen=self.canteen)
        
        # Suroviny s novými jednotkami
        self.ingredient = Ingredient.objects.create(
            name='Cukr',
            base_unit='kg',
            recipe_unit='g',
            conversion_factor=KG_TO_G_CONVERSION
        )
        StockItem.objects.create(
            warehouse=self.w1,
            ingredient=self.ingredient,
            quantity=Decimal('5.000'),
            price=Decimal('10.0')
        )

        self.recipe = Recipe.objects.create(name='Koláč')
        # Nová struktura: quantity_per_portion v receptových jednotkách (gramy)
        RecipeIngredient.objects.create(
            recipe=self.recipe,
            ingredient=self.ingredient,
            quantity_per_portion=KG_TO_G_CONVERSION  # 1000g = 1kg na porci
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

    def test_generate_order_report_count_fields(self):
        """Test that sufficient_stock_count and to_order_count are calculated correctly"""
        # Create second ingredient
        ingredient2 = Ingredient.objects.create(
            name='Mouka',
            base_unit='kg',
            recipe_unit='g',
            conversion_factor=KG_TO_G_CONVERSION
        )
        # Add stock for second ingredient - enough stock
        StockItem.objects.create(
            warehouse=self.w1,
            ingredient=ingredient2,
            quantity=Decimal('20.000'),
            price=Decimal('15.0')
        )
        
        # Add second ingredient to recipe
        RecipeIngredient.objects.create(
            recipe=self.recipe,
            ingredient=ingredient2,
            quantity_per_portion=Decimal('500')  # 500g = 0.5kg per portion
        )
        
        order = ProductionOrder.objects.create(
            recipe=self.recipe,
            menu_plan=self.menu_plan,
            canteen=self.canteen,
            date='2025-09-01'
        )
        # 10 portions: Cukr needs 10kg (stock 5kg), Mouka needs 5kg (stock 20kg)
        ProductionOrderPortionVariant.objects.create(
            production_order=order,
            coefficient=Decimal('1.0'),
            portions=10
        )
        
        report = generate_order_report(self.canteen, '2025-09-01', '2025-09-30')
        
        # Cukr: needed 10kg, stock 5kg -> to_order 5kg (insufficient)
        # Mouka: needed 5kg, stock 20kg -> to_order 0 (sufficient)
        self.assertEqual(len(report['items']), 2)
        self.assertEqual(report['sufficient_stock_count'], 1)  # Mouka has enough
        self.assertEqual(report['to_order_count'], 1)  # Cukr needs ordering


class ReportPickingListCoverageTest(TestCase):
    """Testy dvojího počítání: potřeba krytá výdejkou promítnutou do skladu se nesmí počítat znovu."""

    def setUp(self):
        self.user = User.objects.create_user(username='tester', password='x')
        self.canteen = Canteen.objects.create(name='Růžená')
        self.w1 = Warehouse.objects.create(name='Sklad1', canteen=self.canteen)

        self.ingredient = Ingredient.objects.create(
            name='Cukr',
            base_unit='kg',
            recipe_unit='g',
            conversion_factor=KG_TO_G_CONVERSION
        )
        self.stock = StockItem.objects.create(
            warehouse=self.w1,
            ingredient=self.ingredient,
            quantity=Decimal('5.000'),
            price=Decimal('10.0')
        )

        self.recipe = Recipe.objects.create(name='Koláč')
        RecipeIngredient.objects.create(
            recipe=self.recipe,
            ingredient=self.ingredient,
            quantity_per_portion=KG_TO_G_CONVERSION  # 1 kg na porci
        )

        self.menu_plan = MenuPlan.objects.create(
            name='Test Menu',
            canteen=self.canteen,
            date_from='2025-09-01',
            date_to='2025-09-30'
        )
        self.order = ProductionOrder.objects.create(
            recipe=self.recipe,
            menu_plan=self.menu_plan,
            canteen=self.canteen,
            date='2025-09-01'
        )
        ProductionOrderPortionVariant.objects.create(
            production_order=self.order,
            coefficient=Decimal('1.0'),
            portions=3
        )

    def _make_document(self):
        return PickingListDocument.objects.create(
            name='Výdejka test',
            canteen=self.canteen,
            date_from='2025-09-01',
            date_to='2025-09-30',
            created_by=self.user
        )

    def test_pending_picking_list_without_document_is_counted(self):
        """PENDING výdejka bez dokumentu nic neblokuje -> potřeba se počítá normálně."""
        PickingList.objects.create(
            production_order=self.order,
            warehouse=self.w1,
            ingredient=self.ingredient,
            quantity_planned=Decimal('3.000')
        )

        report = generate_order_report(self.canteen, '2025-09-01', '2025-09-30')
        self.assertEqual(len(report['items']), 1)
        it = report['items'][0]
        self.assertEqual(it['needed'], 3.0)
        self.assertEqual(it['stock'], 5.0)
        self.assertEqual(it['to_order'], 0)

    def test_blocked_picking_list_not_double_counted(self):
        """Výdejka přiřazená k dokumentu blokuje zásobu -> potřeba se už nepočítá."""
        PickingList.objects.create(
            production_order=self.order,
            document=self._make_document(),
            warehouse=self.w1,
            ingredient=self.ingredient,
            quantity_planned=Decimal('3.000')
        )
        self.stock.refresh_from_db()
        # Sanity: blokace proběhla, dostupné = 5 - 3 = 2 kg
        self.assertEqual(self.stock.quantity_available, Decimal('2.000'))

        report = generate_order_report(self.canteen, '2025-09-01', '2025-09-30')
        # Potřeba příkazu je krytá blokací -> surovina se v reportu neobjeví
        self.assertEqual(len(report['items']), 0)

    def test_completed_picking_list_not_double_counted(self):
        """COMPLETED výdejka: zásoba už odečtená -> potřeba se už nepočítá."""
        pl = PickingList.objects.create(
            production_order=self.order,
            document=self._make_document(),
            warehouse=self.w1,
            ingredient=self.ingredient,
            quantity_planned=Decimal('3.000')
        )
        pl.status = PickingList.Status.COMPLETED
        pl.quantity_actual = Decimal('3.000')
        pl.save()
        self.stock.refresh_from_db()
        # Sanity: odblokováno a odečteno, zbývá 2 kg
        self.assertEqual(self.stock.quantity_available, Decimal('2.000'))

        report = generate_order_report(self.canteen, '2025-09-01', '2025-09-30')
        self.assertEqual(len(report['items']), 0)

    def test_covered_order_does_not_hide_other_orders_need(self):
        """Krytý příkaz se přeskočí, ale potřeba jiného příkazu se počítá dál."""
        PickingList.objects.create(
            production_order=self.order,
            document=self._make_document(),
            warehouse=self.w1,
            ingredient=self.ingredient,
            quantity_planned=Decimal('3.000')
        )
        order2 = ProductionOrder.objects.create(
            recipe=self.recipe,
            menu_plan=self.menu_plan,
            canteen=self.canteen,
            date='2025-09-15'
        )
        ProductionOrderPortionVariant.objects.create(
            production_order=order2,
            coefficient=Decimal('1.0'),
            portions=4
        )

        report = generate_order_report(self.canteen, '2025-09-01', '2025-09-30')
        self.assertEqual(len(report['items']), 1)
        it = report['items'][0]
        # order2: 4 kg, dostupné 5 - 3 (blokace) = 2 kg -> objednat 2 kg
        self.assertEqual(it['needed'], 4.0)
        self.assertEqual(it['stock'], 2.0)
        self.assertEqual(it['to_order'], 2.0)

    def test_order_changed_after_picking_list_counts_residual_need(self):
        """
        Příkaz upravený PO vytvoření výdejky: blokace kryje jen původní
        plánované množství, zbytek potřeby se musí započítat do objednávky.
        """
        PickingList.objects.create(
            production_order=self.order,
            document=self._make_document(),
            warehouse=self.w1,
            ingredient=self.ingredient,
            quantity_planned=Decimal('3.000')
        )
        self.stock.refresh_from_db()
        self.assertEqual(self.stock.quantity_available, Decimal('2.000'))

        # Navýšíme porce 3 -> 6 (potřeba 6 kg, blokováno jen 3 kg)
        variant = self.order.portion_variants.first()
        variant.portions = 6
        variant.save()

        report = generate_order_report(self.canteen, '2025-09-01', '2025-09-30')
        self.assertEqual(len(report['items']), 1)
        it = report['items'][0]
        # Zbytek potřeby nad blokaci = 6 - 3 = 3 kg, dostupné 2 kg -> objednat 1 kg
        self.assertEqual(it['needed'], 3.0)
        self.assertEqual(it['stock'], 2.0)
        self.assertEqual(it['to_order'], 1.0)

    def test_order_reduced_after_picking_list_fully_covered(self):
        """
        Příkaz zmenšený PO vytvoření výdejky: blokace potřebu kryje celou,
        surovina se v reportu neobjeví.
        """
        PickingList.objects.create(
            production_order=self.order,
            document=self._make_document(),
            warehouse=self.w1,
            ingredient=self.ingredient,
            quantity_planned=Decimal('3.000')
        )

        # Snížíme porce 3 -> 2 (potřeba 2 kg < blokováno 3 kg)
        variant = self.order.portion_variants.first()
        variant.portions = 2
        variant.save()

        report = generate_order_report(self.canteen, '2025-09-01', '2025-09-30')
        self.assertEqual(len(report['items']), 0)


class ReportIngredientOverrideTest(TestCase):
    """Testy, že report respektuje úpravy jídelníčku (ingredient overrides)."""

    def setUp(self):
        self.canteen = Canteen.objects.create(name='Růžená')
        self.w1 = Warehouse.objects.create(name='Sklad1', canteen=self.canteen)

        self.ingredient = Ingredient.objects.create(
            name='Cukr',
            base_unit='kg',
            recipe_unit='g',
            conversion_factor=KG_TO_G_CONVERSION
        )
        StockItem.objects.create(
            warehouse=self.w1,
            ingredient=self.ingredient,
            quantity=Decimal('5.000'),
            price=Decimal('10.0')
        )

        self.recipe = Recipe.objects.create(name='Koláč')
        RecipeIngredient.objects.create(
            recipe=self.recipe,
            ingredient=self.ingredient,
            quantity_per_portion=KG_TO_G_CONVERSION  # 1 kg na porci
        )

        self.menu_plan = MenuPlan.objects.create(
            name='Test Menu',
            canteen=self.canteen,
            date_from='2025-09-01',
            date_to='2025-09-30'
        )
        self.order = ProductionOrder.objects.create(
            recipe=self.recipe,
            menu_plan=self.menu_plan,
            canteen=self.canteen,
            date='2025-09-01'
        )
        ProductionOrderPortionVariant.objects.create(
            production_order=self.order,
            coefficient=Decimal('1.0'),
            portions=3
        )

    def test_override_changed_quantity(self):
        """Změněné množství na porci se promítne do potřeby."""
        ProductionOrderIngredientOverride.objects.create(
            production_order=self.order,
            ingredient=self.ingredient,
            quantity_per_portion=Decimal('500'),  # 0.5 kg místo 1 kg
            original_quantity=KG_TO_G_CONVERSION
        )

        report = generate_order_report(self.canteen, '2025-09-01', '2025-09-30')
        self.assertEqual(len(report['items']), 1)
        # 3 porce × 0.5 kg = 1.5 kg
        self.assertEqual(report['items'][0]['needed'], 1.5)

    def test_override_removed_ingredient(self):
        """Odstraněná surovina se v reportu neobjeví."""
        ProductionOrderIngredientOverride.objects.create(
            production_order=self.order,
            ingredient=self.ingredient,
            quantity_per_portion=None,
            original_quantity=KG_TO_G_CONVERSION,
            is_removed=True
        )

        report = generate_order_report(self.canteen, '2025-09-01', '2025-09-30')
        self.assertEqual(len(report['items']), 0)

    def test_override_added_ingredient(self):
        """Přidaná surovina (mimo recept) se do reportu započítá."""
        added = Ingredient.objects.create(
            name='Vanilka',
            base_unit='kg',
            recipe_unit='g',
            conversion_factor=KG_TO_G_CONVERSION
        )
        ProductionOrderIngredientOverride.objects.create(
            production_order=self.order,
            ingredient=added,
            quantity_per_portion=Decimal('100'),  # 0.1 kg na porci
            original_quantity=Decimal('0'),
            is_added=True
        )

        report = generate_order_report(self.canteen, '2025-09-01', '2025-09-30')
        self.assertEqual(len(report['items']), 2)
        by_name = {it['ingredient'].name: it for it in report['items']}
        self.assertIn('Vanilka', by_name)
        # 3 porce × 0.1 kg = 0.3 kg, sklad 0 -> objednat 0.3
        self.assertEqual(by_name['Vanilka']['needed'], 0.3)
        self.assertEqual(by_name['Vanilka']['stock'], 0.0)
        self.assertEqual(by_name['Vanilka']['to_order'], 0.3)
