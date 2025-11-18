from django.test import TestCase
from decimal import Decimal
from datetime import date

from apps.canteens.models import Canteen, Warehouse
from apps.core.models import Ingredient, Recipe, RecipeIngredient
from apps.inventory.models import StockItem
from apps.production.models import ProductionOrder, PickingList, MenuPlan, ProductionOrderPortionVariant, PickingListDocument
from django.contrib.auth.models import User


class StockBlockingTest(TestCase):
    def setUp(self):
        self.canteen = Canteen.objects.create(name='Test Canteen')
        self.warehouse = Warehouse.objects.create(name='Main', canteen=self.canteen)
        self.ingredient = Ingredient.objects.create(
            name='Mouka', 
            unit='kg', 
            base_unit='kg', 
            recipe_unit='kg',
            conversion_factor=Decimal('1.0')
        )
        # stock 10 kg at price 1.0
        self.stock = StockItem.objects.create(
            warehouse=self.warehouse, 
            ingredient=self.ingredient, 
            quantity=Decimal('10.000'), 
            price=Decimal('1.00')
        )

        # recipe with 1 kg per portion
        self.recipe = Recipe.objects.create(name='Chleba', base_portions=10)
        RecipeIngredient.objects.create(
            recipe=self.recipe, 
            ingredient=self.ingredient, 
            quantity_per_portion=Decimal('1.000')
        )
        
        self.user = User.objects.create_user(username='testuser', password='testpass')

    def test_blocking_when_document_assigned(self):
        """
        Test že když je picking list položka přiřazena k dokumentu,
        blokuje se plánované množství ze skladu.
        """
        # Vytvoříme MenuPlan
        menu_plan = MenuPlan.objects.create(
            name='Test Menu',
            canteen=self.canteen,
            date_from=date(2025, 9, 10),
            date_to=date(2025, 9, 10)
        )
        
        # Vytvoříme ProductionOrder
        order = ProductionOrder.objects.create(
            recipe=self.recipe,
            canteen=self.canteen,
            menu_plan=menu_plan,
            date=date(2025, 9, 10)
        )
        
        # Přidáme variantu porce
        ProductionOrderPortionVariant.objects.create(
            production_order=order,
            portions=3,
            coefficient=Decimal('1.0')
        )
        
        # Vygenerujeme picking list
        order.generate_picking_list()
        
        pl = order.picking_list_items.first()
        self.assertIsNotNone(pl)
        self.assertEqual(pl.quantity_planned, Decimal('3.000'))
        
        # Před přiřazením k dokumentu by nemělo být nic blokováno
        self.stock.refresh_from_db()
        self.assertEqual(self.stock.quantity_blocked, Decimal('0.000'))
        self.assertEqual(self.stock.quantity, Decimal('10.000'))
        
        # Vytvoříme dokument výdejky a přiřadíme položku
        document = PickingListDocument.objects.create(
            name='Test Document',
            canteen=self.canteen,
            date_from=date(2025, 9, 10),
            date_to=date(2025, 9, 10),
            created_by=self.user
        )
        
        pl.document = document
        pl.save()
        
        # Po přiřazení k dokumentu by mělo být zablokováno 3 kg
        self.stock.refresh_from_db()
        self.assertEqual(self.stock.quantity_blocked, Decimal('3.000'))
        self.assertEqual(self.stock.quantity, Decimal('10.000'))  # Celkové množství se nemění
        self.assertEqual(self.stock.quantity_available, Decimal('7.000'))  # Dostupné = 10 - 3

    def test_unblocking_and_deduction_on_complete(self):
        """
        Test že když je picking list položka dokončena,
        uvolní se blokované množství a odečte se skutečné množství ze skladu.
        """
        # Nastavíme scénář s již zablokovanou položkou
        menu_plan = MenuPlan.objects.create(
            name='Test Menu',
            canteen=self.canteen,
            date_from=date(2025, 9, 10),
            date_to=date(2025, 9, 10)
        )
        
        order = ProductionOrder.objects.create(
            recipe=self.recipe,
            canteen=self.canteen,
            menu_plan=menu_plan,
            date=date(2025, 9, 10)
        )
        
        ProductionOrderPortionVariant.objects.create(
            production_order=order,
            portions=3,
            coefficient=Decimal('1.0')
        )
        
        order.generate_picking_list()
        pl = order.picking_list_items.first()
        
        document = PickingListDocument.objects.create(
            name='Test Document',
            canteen=self.canteen,
            date_from=date(2025, 9, 10),
            date_to=date(2025, 9, 10),
            created_by=self.user
        )
        
        pl.document = document
        pl.save()
        
        # Ověříme že je zablokováno 3 kg
        self.stock.refresh_from_db()
        self.assertEqual(self.stock.quantity_blocked, Decimal('3.000'))
        self.assertEqual(self.stock.quantity, Decimal('10.000'))
        
        # Dokončíme výdej se skutečným množstvím 3.5 kg
        pl.quantity_actual = Decimal('3.500')
        pl.status = PickingList.Status.COMPLETED
        pl.save()
        
        # Po dokončení:
        # - blokace by měla být uvolněna (0)
        # - množství by mělo být odečteno (10 - 3.5 = 6.5)
        self.stock.refresh_from_db()
        self.assertEqual(self.stock.quantity_blocked, Decimal('0.000'))
        self.assertEqual(self.stock.quantity, Decimal('6.500'))
        self.assertEqual(self.stock.quantity_available, Decimal('6.500'))

    def test_multiple_picking_lists_blocking(self):
        """
        Test že více výdejek může blokovat množství ze stejného skladu
        a dostupné množství se správně snižuje.
        """
        menu_plan = MenuPlan.objects.create(
            name='Test Menu',
            canteen=self.canteen,
            date_from=date(2025, 9, 10),
            date_to=date(2025, 9, 11)
        )
        
        # První výrobní příkaz - 3 kg
        order1 = ProductionOrder.objects.create(
            recipe=self.recipe,
            canteen=self.canteen,
            menu_plan=menu_plan,
            date=date(2025, 9, 10)
        )
        ProductionOrderPortionVariant.objects.create(
            production_order=order1,
            portions=3,
            coefficient=Decimal('1.0')
        )
        order1.generate_picking_list()
        
        # Druhý výrobní příkaz - 4 kg
        order2 = ProductionOrder.objects.create(
            recipe=self.recipe,
            canteen=self.canteen,
            menu_plan=menu_plan,
            date=date(2025, 9, 11)
        )
        ProductionOrderPortionVariant.objects.create(
            production_order=order2,
            portions=4,
            coefficient=Decimal('1.0')
        )
        order2.generate_picking_list()
        
        # Vytvoříme dokument a přiřadíme obě položky
        document = PickingListDocument.objects.create(
            name='Test Document',
            canteen=self.canteen,
            date_from=date(2025, 9, 10),
            date_to=date(2025, 9, 11),
            created_by=self.user
        )
        
        pl1 = order1.picking_list_items.first()
        pl1.document = document
        pl1.save()
        
        # Po první blokaci: 10 - 3 = 7 kg dostupných
        self.stock.refresh_from_db()
        self.assertEqual(self.stock.quantity_blocked, Decimal('3.000'))
        self.assertEqual(self.stock.quantity_available, Decimal('7.000'))
        
        pl2 = order2.picking_list_items.first()
        pl2.document = document
        pl2.save()
        
        # Po druhé blokaci: 10 - (3 + 4) = 3 kg dostupných
        self.stock.refresh_from_db()
        self.assertEqual(self.stock.quantity_blocked, Decimal('7.000'))
        self.assertEqual(self.stock.quantity, Decimal('10.000'))
        self.assertEqual(self.stock.quantity_available, Decimal('3.000'))

    def test_blocking_prevents_double_allocation(self):
        """
        Test že blokované množství není dostupné pro další výdejku.
        Toto je hlavní účel blokování - prevence dvojité alokace.
        """
        menu_plan = MenuPlan.objects.create(
            name='Test Menu',
            canteen=self.canteen,
            date_from=date(2025, 9, 10),
            date_to=date(2025, 9, 10)
        )
        
        # První výrobní příkaz - zablokuje 8 kg
        order1 = ProductionOrder.objects.create(
            recipe=self.recipe,
            canteen=self.canteen,
            menu_plan=menu_plan,
            date=date(2025, 9, 10)
        )
        ProductionOrderPortionVariant.objects.create(
            production_order=order1,
            portions=8,
            coefficient=Decimal('1.0')
        )
        order1.generate_picking_list()
        
        document = PickingListDocument.objects.create(
            name='Test Document',
            canteen=self.canteen,
            date_from=date(2025, 9, 10),
            date_to=date(2025, 9, 10),
            created_by=self.user
        )
        
        pl1 = order1.picking_list_items.first()
        pl1.document = document
        pl1.save()
        
        # Po blokaci 8 kg z 10 kg zůstává pouze 2 kg dostupných
        self.stock.refresh_from_db()
        self.assertEqual(self.stock.quantity_blocked, Decimal('8.000'))
        self.assertEqual(self.stock.quantity_available, Decimal('2.000'))
        
        # Ověříme že dostupné množství je skutečně 2 kg
        # (v reálné aplikaci by views měly toto kontrolovat)
        available = self.stock.quantity - self.stock.quantity_blocked
        self.assertEqual(available, Decimal('2.000'))
        
        # Simulace: pokud bychom chtěli vytvořit další výdejku na 5 kg,
        # dostupné množství (2 kg) je nedostatečné
        self.assertLess(available, Decimal('5.000'))

    def test_blocking_with_zero_stock(self):
        """
        Test že blokování funguje i když je stav skladu nulový.
        Položka se vytvoří s nulovou zásobou a zablokovaným množstvím.
        """
        # Nastavíme sklad na nulu
        self.stock.quantity = Decimal('0.000')
        self.stock.save()
        
        menu_plan = MenuPlan.objects.create(
            name='Test Menu',
            canteen=self.canteen,
            date_from=date(2025, 9, 10),
            date_to=date(2025, 9, 10)
        )
        
        order = ProductionOrder.objects.create(
            recipe=self.recipe,
            canteen=self.canteen,
            menu_plan=menu_plan,
            date=date(2025, 9, 10)
        )
        
        ProductionOrderPortionVariant.objects.create(
            production_order=order,
            portions=5,
            coefficient=Decimal('1.0')
        )
        
        order.generate_picking_list()
        pl = order.picking_list_items.first()
        
        document = PickingListDocument.objects.create(
            name='Test Document',
            canteen=self.canteen,
            date_from=date(2025, 9, 10),
            date_to=date(2025, 9, 10),
            created_by=self.user
        )
        
        pl.document = document
        pl.save()
        
        # I když je sklad na nule, blokace by měla fungovat
        self.stock.refresh_from_db()
        self.assertEqual(self.stock.quantity, Decimal('0.000'))
        self.assertEqual(self.stock.quantity_blocked, Decimal('5.000'))
        self.assertEqual(self.stock.quantity_available, Decimal('-5.000'))  # Záporné = nedostatek

    def test_blocking_with_missing_ingredient(self):
        """
        Test že když surovina není ve skladu, vytvoří se položka
        s nulovou zásobou a zablokovaným množstvím.
        """
        # Vytvoříme novou surovinu, která NENÍ ve skladu
        new_ingredient = Ingredient.objects.create(
            name='Cukr',
            unit='kg',
            base_unit='kg',
            recipe_unit='kg',
            conversion_factor=Decimal('1.0')
        )
        
        recipe_with_new = Recipe.objects.create(name='Koláč', base_portions=10)
        RecipeIngredient.objects.create(
            recipe=recipe_with_new,
            ingredient=new_ingredient,
            quantity_per_portion=Decimal('0.5')
        )
        
        menu_plan = MenuPlan.objects.create(
            name='Test Menu',
            canteen=self.canteen,
            date_from=date(2025, 9, 10),
            date_to=date(2025, 9, 10)
        )
        
        order = ProductionOrder.objects.create(
            recipe=recipe_with_new,
            canteen=self.canteen,
            menu_plan=menu_plan,
            date=date(2025, 9, 10)
        )
        
        ProductionOrderPortionVariant.objects.create(
            production_order=order,
            portions=10,
            coefficient=Decimal('1.0')
        )
        
        order.generate_picking_list()
        pl = order.picking_list_items.first()
        
        # Ověříme že skladová položka byla vytvořena s nulovou zásobou
        stock_item = StockItem.objects.get(
            ingredient=new_ingredient,
            warehouse=self.warehouse
        )
        self.assertEqual(stock_item.quantity, Decimal('0.000'))
        self.assertEqual(stock_item.quantity_blocked, Decimal('0.000'))
        
        # Přiřadíme k dokumentu
        document = PickingListDocument.objects.create(
            name='Test Document',
            canteen=self.canteen,
            date_from=date(2025, 9, 10),
            date_to=date(2025, 9, 10),
            created_by=self.user
        )
        
        pl.document = document
        pl.save()
        
        # Po přiřazení k dokumentu by mělo být zablokováno 5 kg
        stock_item.refresh_from_db()
        self.assertEqual(stock_item.quantity, Decimal('0.000'))
        self.assertEqual(stock_item.quantity_blocked, Decimal('5.000'))
        self.assertEqual(stock_item.quantity_available, Decimal('-5.000'))

    def test_quantity_available_property(self):
        """
        Test že property quantity_available vrací správnou hodnotu.
        """
        self.stock.quantity = Decimal('10.000')
        self.stock.quantity_blocked = Decimal('3.000')
        self.stock.save()
        
        self.assertEqual(self.stock.quantity_available, Decimal('7.000'))
        
        self.stock.quantity_blocked = Decimal('0.000')
        self.stock.save()
        self.assertEqual(self.stock.quantity_available, Decimal('10.000'))
        
        self.stock.quantity_blocked = Decimal('12.000')
        self.stock.save()
        self.assertEqual(self.stock.quantity_available, Decimal('-2.000'))

    def test_block_and_unblock_methods(self):
        """
        Test že metody block_quantity a unblock_quantity fungují správně.
        """
        self.assertEqual(self.stock.quantity_blocked, Decimal('0.000'))
        
        # Zablokujeme 3 kg
        self.stock.block_quantity(Decimal('3.000'))
        self.stock.refresh_from_db()
        self.assertEqual(self.stock.quantity_blocked, Decimal('3.000'))
        
        # Zablokujeme dalších 2 kg
        self.stock.block_quantity(Decimal('2.000'))
        self.stock.refresh_from_db()
        self.assertEqual(self.stock.quantity_blocked, Decimal('5.000'))
        
        # Uvolníme 2 kg
        self.stock.unblock_quantity(Decimal('2.000'))
        self.stock.refresh_from_db()
        self.assertEqual(self.stock.quantity_blocked, Decimal('3.000'))
        
        # Uvolníme zbytek
        self.stock.unblock_quantity(Decimal('3.000'))
        self.stock.refresh_from_db()
        self.assertEqual(self.stock.quantity_blocked, Decimal('0.000'))
        
    def test_unblock_more_than_blocked(self):
        """
        Test že pokus o uvolnění většího množství než je zablokováno
        nastaví quantity_blocked na 0.
        """
        self.stock.block_quantity(Decimal('3.000'))
        self.stock.refresh_from_db()
        self.assertEqual(self.stock.quantity_blocked, Decimal('3.000'))
        
        # Pokusíme se uvolnit více než je zablokováno
        self.stock.unblock_quantity(Decimal('5.000'))
        self.stock.refresh_from_db()
        self.assertEqual(self.stock.quantity_blocked, Decimal('0.000'))
