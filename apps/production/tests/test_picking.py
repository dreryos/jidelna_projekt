from django.test import TestCase
from decimal import Decimal
from datetime import date

from apps.canteens.models import Canteen, Warehouse
from apps.core.models import Ingredient, Recipe, RecipeIngredient
from apps.inventory.models import StockItem
from apps.production.models import ProductionOrder, PickingList, MenuPlan, ProductionOrderPortionVariant, PickingListDocument
from django.contrib.auth.models import User


class PickingListDecrementTest(TestCase):
    def setUp(self):
        self.canteen = Canteen.objects.create(name='Test Canteen')
        self.warehouse = Warehouse.objects.create(name='Main', canteen=self.canteen)
        self.ingredient = Ingredient.objects.create(
            name='Mouka', 
            unit='kg', 
            base_unit='kg', 
            recipe_unit='kg',
            conversion_factor=Decimal('1.0')  # kg->kg bez převodu
        )
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
    
    def test_multiple_portion_variants_picking_list(self):
        """
        Test že ProductionOrder s více variantami porcí správně vypočítá celkové množství
        surovin ve vychystávacím seznamu.
        
        Test ověřuje:
        - Správný výpočet množství ze všech variant
        - Aplikaci koeficientů na jednotlivé varianty
        - Celkové efektivní porce: 2*1.0 + 3*1.5 + 1*0.5 = 7.0
        - Celkové množství suroviny: 7.0 kg (7 porcí * 1 kg/porci)
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
        
        # Přidáme 3 různé varianty porcí
        ProductionOrderPortionVariant.objects.create(
            production_order=order,
            portions=2,
            coefficient=Decimal('1.0'),  # 2 normální porce
            order=0
        )
        ProductionOrderPortionVariant.objects.create(
            production_order=order,
            portions=3,
            coefficient=Decimal('1.5'),  # 3 velké porce (1.5x)
            order=1
        )
        ProductionOrderPortionVariant.objects.create(
            production_order=order,
            portions=1,
            coefficient=Decimal('0.5'),  # 1 malá porce (0.5x)
            order=2
        )
        
        # Vygenerujeme picking list
        order.generate_picking_list()
        
        # Ověříme, že byl vytvořen picking list item
        pl = order.picking_list_items.first()
        self.assertIsNotNone(pl, "Picking list item should be created")
        self.assertEqual(pl.ingredient, self.ingredient)
        
        # Ověříme výpočet celkových efektivních porcí
        # 2*1.0 + 3*1.5 + 1*0.5 = 2.0 + 4.5 + 0.5 = 7.0 efektivních porcí
        expected_effective_portions = Decimal('7.0')
        self.assertEqual(order.total_effective_portions, float(expected_effective_portions))
        
        # Ověříme celkový počet porcí (bez koeficientů)
        # 2 + 3 + 1 = 6 porcí
        expected_total_portions = 6
        self.assertEqual(order.total_portions, expected_total_portions)
        
        # Ověříme plánované množství suroviny v picking listu
        # 7.0 efektivních porcí * 1 kg/porci = 7.0 kg
        expected_quantity = Decimal('7.000')
        self.assertEqual(
            pl.quantity_planned, 
            expected_quantity,
            f"Expected {expected_quantity} kg, got {pl.quantity_planned} kg"
        )
        
        # Bonus: Ověříme že dekrementace skladu funguje i s více variantami
        pl.quantity_actual = expected_quantity
        pl.warehouse = self.warehouse
        pl.status = PickingList.Status.COMPLETED
        pl.save()
        
        # Sklad by měl být snížen z 10 kg na 3 kg (10 - 7 = 3)
        si = StockItem.objects.get(warehouse=self.warehouse, ingredient=self.ingredient)
        self.assertEqual(si.quantity, Decimal('3.000'))
    
    def test_production_order_without_canteen_uses_menu_plan_canteen(self):
        """
        Test že ProductionOrder automaticky přebírá jídelnu z menu_plan při uložení,
        pokud canteen není explicitně nastavena.
        
        Test ověřuje:
        - save() metoda automaticky nastaví canteen z menu_plan.canteen
        - get_canteen() vrací správnou jídelnu
        - Vychystávací seznam správně předvyplní sklad z jídelny
        - Systém funguje bez manuálního nastavování canteen
        """
        # Vytvoříme MenuPlan s jídelnou
        menu_plan = MenuPlan.objects.create(
            name='Test Menu',
            canteen=self.canteen,
            date_from=date(2025, 9, 10),
            date_to=date(2025, 9, 10)
        )
        
        # Vytvoříme ProductionOrder BEZ canteen (explicitně None)
        # save() by měla automaticky nastavit canteen z menu_plan
        order = ProductionOrder.objects.create(
            recipe=self.recipe,
            canteen=None,  # Explicitně bez jídelny
            menu_plan=menu_plan,
            date=date(2025, 9, 10)
        )
        
        # Ověříme že save() automaticky nastavila canteen z menu_plan
        order.refresh_from_db()
        self.assertEqual(order.canteen, self.canteen, 
                        "save() should auto-set canteen from menu_plan.canteen")
        self.assertEqual(order.get_canteen(), self.canteen, 
                        "get_canteen() should return the canteen")
        
        # Přidáme variantu porce
        ProductionOrderPortionVariant.objects.create(
            production_order=order,
            portions=5,
            coefficient=Decimal('1.0'),
            order=0
        )
        
        # Vygenerujeme picking list
        order.generate_picking_list()
        
        # Ověříme, že byl vytvořen picking list item
        pl = order.picking_list_items.first()
        self.assertIsNotNone(pl, "Picking list item should be created")
        self.assertEqual(pl.ingredient, self.ingredient)
        
        # Ověříme, že byl předvyplněn správný sklad (z jídelny menu_plan)
        self.assertEqual(pl.warehouse, self.warehouse,
                        "Warehouse should be prefilled from menu_plan's canteen")
        
        # Ověříme správné množství (5 porcí × 1 kg/porci = 5 kg)
        expected_quantity = Decimal('5.000')
        self.assertEqual(pl.quantity_planned, expected_quantity)
        
        # Ověříme že dekrementace skladu funguje i bez přímé vazby na jídelnu
        pl.quantity_actual = expected_quantity
        pl.status = PickingList.Status.COMPLETED
        pl.save()
        
        # Sklad by měl být snížen z 10 kg na 5 kg (10 - 5 = 5)
        si = StockItem.objects.get(warehouse=self.warehouse, ingredient=self.ingredient)
        self.assertEqual(si.quantity, Decimal('5.000'),
                        "Stock should be decremented even when order.canteen is None")
    
    def test_production_order_without_menu_plan_raises_error(self):
        """
        Test že vytvoření ProductionOrder bez menu_plan vyvolá chybu.
        
        Test ověřuje:
        - Databázové omezení NOT NULL na menu_plan_id je vynuceno
        - Migrace 0009 správně nastavila menu_plan jako povinné pole
        - Systém brání vytváření sirotčích ProductionOrder bez menu_plan
        
        Toto je kritické omezení architektury "menu-first" - každý ProductionOrder
        MUSÍ být součástí MenuPlan.
        """
        from django.db import IntegrityError, connection
        
        # Pokus o vložení záznamu přímo na úrovni databáze (obcházíme Django ORM a save metodu)
        with self.assertRaises(IntegrityError) as context:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO production_productionorder 
                    (recipe_id, canteen_id, menu_plan_id, date, created_at)
                    VALUES (%s, %s, NULL, %s, datetime('now'))
                    """,
                    [self.recipe.id, self.canteen.id, '2025-09-10']
                )
        
        # Ověříme, že chyba souvisí s NOT NULL constraint
        error_message = str(context.exception)
        # SQLite chybová zpráva obsahuje "NOT NULL constraint failed"
        self.assertTrue(
            'not null' in error_message.lower() or 'menu_plan_id' in error_message.lower(),
            f"Error should mention NOT NULL constraint or menu_plan_id. Got: {error_message}"
        )
    
    def test_picking_list_with_zero_stock(self):
        """
        Test že vychystávací seznam správně zpracovává nulový stav ve skladu.
        
        Test ověřuje:
        - Picking list se vytvoří i když sklad má nulový stav
        - prefilled_warehouse JE vyplněna i když sklad má nulový stav (změna chování)
        - Systém předvyplní sklad aby mohla probíhat blokace a odepsání do mínusu
        
        Toto je důležité pro plánování - i když není zásoba, musíme vědět odkud se má vzít
        a umožnit odepsání do mínusu.
        """
        # Nastavíme sklad na nulu
        stock_item = StockItem.objects.get(warehouse=self.warehouse, ingredient=self.ingredient)
        stock_item.quantity = Decimal('0.000')
        stock_item.save()
        
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
            portions=5,
            coefficient=Decimal('1.0'),
            order=0
        )
        
        # Vygenerujeme picking list
        order.generate_picking_list()
        
        # Měla by být vytvořena jedna položka vychystávacího seznamu
        pl = order.picking_list_items.first()
        self.assertIsNotNone(pl, "Picking list item should be created even with zero stock")
        self.assertEqual(pl.ingredient, self.ingredient)
        
        # Ověřte, že prefilled_warehouse JE vyplněna i když má nulový stav
        # Nové chování: předvyplníme sklad i s nulovou zásobou pro blokaci/odepsání
        self.assertEqual(pl.warehouse, self.warehouse, 
                         "Warehouse should be prefilled even when stock quantity is zero")
        
        # Ověříme správné plánované množství (5 porcí × 1 kg/porci = 5 kg)
        expected_quantity = Decimal('5.000')
        self.assertEqual(pl.quantity_planned, expected_quantity,
                        "Planned quantity should be calculated correctly regardless of stock")
    
    def test_create_stock_item_when_missing(self):
        """
        Test že při vytvoření výdejky se automaticky vytvoří skladová položka s nulovou zásobou,
        pokud surovina není ve skladu.
        
        Test ověřuje:
        - Při generování picking listu se vytvoří StockItem s quantity=0 pokud neexistuje
        - StockItem je vytvořena v prvním skladu patřícím k jídelně
        - Warehouse je předvyplněna v picking listu i když má nulovou zásobu
        - Systém umožňuje blokaci a odepsání do mínusu
        """
        # Vytvoříme novou surovinu, která NENÍ ve skladu
        new_ingredient = Ingredient.objects.create(
            name='Cukr',
            unit='kg',
            base_unit='kg',
            recipe_unit='kg',
            conversion_factor=Decimal('1.0')
        )
        
        # Vytvoříme recept s touto surovinou
        recipe_with_new_ingredient = Recipe.objects.create(
            name='Koláč',
            base_portions=10
        )
        RecipeIngredient.objects.create(
            recipe=recipe_with_new_ingredient,
            ingredient=new_ingredient,
            quantity_per_portion=Decimal('0.5')
        )
        
        # Ověříme, že surovina není ve skladu
        self.assertFalse(
            StockItem.objects.filter(
                ingredient=new_ingredient,
                warehouse__canteen=self.canteen
            ).exists(),
            "Ingredient should not be in stock initially"
        )
        
        # Vytvoříme MenuPlan
        menu_plan = MenuPlan.objects.create(
            name='Test Menu',
            canteen=self.canteen,
            date_from=date(2025, 9, 10),
            date_to=date(2025, 9, 10)
        )
        
        # Vytvoříme ProductionOrder s touto surovinou
        order = ProductionOrder.objects.create(
            recipe=recipe_with_new_ingredient,
            canteen=self.canteen,
            menu_plan=menu_plan,
            date=date(2025, 9, 10)
        )
        
        # Přidáme variantu porce
        ProductionOrderPortionVariant.objects.create(
            production_order=order,
            portions=10,
            coefficient=Decimal('1.0'),
            order=0
        )
        
        # Vygenerujeme picking list - mělo by vytvořit StockItem s 0
        order.generate_picking_list()
        
        # Ověříme, že byla vytvořena skladová položka s nulovou zásobou
        stock_item = StockItem.objects.filter(
            ingredient=new_ingredient,
            warehouse__canteen=self.canteen
        ).first()
        self.assertIsNotNone(stock_item, "StockItem should be created with zero quantity")
        self.assertEqual(stock_item.quantity, Decimal('0.000'),
                        "StockItem quantity should be 0")
        self.assertEqual(stock_item.price, Decimal('0.00'),
                        "StockItem price should be 0")
        self.assertEqual(stock_item.warehouse, self.warehouse,
                        "StockItem should be in the first warehouse of the canteen")
        
        # Ověříme, že picking list byl vytvořen
        pl = order.picking_list_items.first()
        self.assertIsNotNone(pl, "Picking list item should be created")
        self.assertEqual(pl.ingredient, new_ingredient)
        
        # Ověříme, že warehouse je předvyplněna i když má nulovou zásobu
        self.assertEqual(pl.warehouse, self.warehouse,
                        "Warehouse should be prefilled even with zero stock after creation")
        
        # Ověříme správné plánované množství (10 porcí × 0.5 kg/porci = 5 kg)
        expected_quantity = Decimal('5.000')
        self.assertEqual(pl.quantity_planned, expected_quantity)
        
        # Bonus: Ověříme, že můžeme odepsat do mínusu
        pl.quantity_actual = expected_quantity
        pl.status = PickingList.Status.COMPLETED
        pl.save()
        
        # Sklad by měl být v mínusu (0 - 5 = -5)
        stock_item.refresh_from_db()
        self.assertEqual(stock_item.quantity, Decimal('-5.000'),
                        "Stock should go negative when ingredient was not available")


class PickingListDocumentArchiveTest(TestCase):
    """Testy pro archivaci dokumentů výdejek"""
    
    def setUp(self):
        self.canteen = Canteen.objects.create(name='Test Canteen')
        self.warehouse = Warehouse.objects.create(name='Main', canteen=self.canteen)
        self.user = User.objects.create_user(username='testuser', password='testpass')
        
        self.ingredient = Ingredient.objects.create(
            name='Mouka',
            unit='kg',
            base_unit='kg',
            recipe_unit='kg',
            conversion_factor=Decimal('1.0')
        )
        StockItem.objects.create(
            warehouse=self.warehouse,
            ingredient=self.ingredient,
            quantity=Decimal('10.000'),
            price=Decimal('1.0')
        )
        
        self.recipe = Recipe.objects.create(name='Chleba', base_portions=10)
        RecipeIngredient.objects.create(
            recipe=self.recipe,
            ingredient=self.ingredient,
            quantity_per_portion=Decimal('1.000')
        )
        
        # Vytvoříme menu plan a production order
        self.menu_plan = MenuPlan.objects.create(
            name='Test Menu',
            canteen=self.canteen,
            date_from=date(2025, 11, 18),
            date_to=date(2025, 11, 18)
        )
        
        self.order = ProductionOrder.objects.create(
            recipe=self.recipe,
            canteen=self.canteen,
            menu_plan=self.menu_plan,
            date=date(2025, 11, 18)
        )
        
        ProductionOrderPortionVariant.objects.create(
            production_order=self.order,
            portions=5,
            coefficient=Decimal('1.0'),
            order=0
        )
        
        self.order.generate_picking_list()
        
        # Vytvoříme dokument výdejky
        self.document = PickingListDocument.objects.create(
            name='Test výdejka',
            canteen=self.canteen,
            date_from=date(2025, 11, 18),
            date_to=date(2025, 11, 18),
            created_by=self.user
        )
        
        # Propojíme picking list s dokumentem
        for item in self.order.picking_list_items.all():
            item.document = self.document
            item.save()
    
    def test_cannot_archive_with_pending_items(self):
        """Test že nelze archivovat dokument s nevydanými položkami"""
        # Dokument má položky ve stavu PENDING
        self.assertFalse(self.document.can_be_archived())
        
        status = self.document.get_completion_status()
        self.assertEqual(status['completed'], 0)
        self.assertEqual(status['pending'], 1)
        self.assertFalse(self.document.can_be_archived())
    
    def test_can_archive_with_all_completed(self):
        """Test že lze archivovat dokument když jsou všechny položky dokončené"""
        # Dokončíme všechny položky
        for item in self.document.items.all():
            item.quantity_actual = item.quantity_planned
            item.status = PickingList.Status.COMPLETED
            item.save()
        
        # Nyní by mělo být možné archivovat
        self.assertTrue(self.document.can_be_archived())
        
        status = self.document.get_completion_status()
        self.assertEqual(status['completed'], 1)
        self.assertEqual(status['pending'], 0)
        self.assertEqual(status['percentage'], 100)
    
    def test_archive_document(self):
        """Test archivace dokumentu"""
        # Dokončíme všechny položky
        for item in self.document.items.all():
            item.quantity_actual = item.quantity_planned
            item.status = PickingList.Status.COMPLETED
            item.save()
        
        # Archivujeme
        self.document.archived = True
        self.document.save()
        
        # Ověříme
        self.document.refresh_from_db()
        self.assertTrue(self.document.archived)
    
    def test_completion_status_with_multiple_items(self):
        """Test správného počítání stavu dokončení s více položkami"""
        # Přidáme další surovinu
        ingredient2 = Ingredient.objects.create(
            name='Sůl',
            unit='kg',
            base_unit='kg',
            recipe_unit='kg',
            conversion_factor=Decimal('1.0')
        )
        StockItem.objects.create(
            warehouse=self.warehouse,
            ingredient=ingredient2,
            quantity=Decimal('5.000'),
            price=Decimal('2.0')
        )
        
        RecipeIngredient.objects.create(
            recipe=self.recipe,
            ingredient=ingredient2,
            quantity_per_portion=Decimal('0.1')
        )
        
        # Vygenerujeme nový picking list
        self.order.generate_picking_list()
        
        # Propojíme nové položky s dokumentem
        for item in self.order.picking_list_items.filter(ingredient=ingredient2):
            item.document = self.document
            item.save()
        
        # Nyní máme 2 položky
        status = self.document.get_completion_status()
        self.assertEqual(status['total'], 2)
        self.assertEqual(status['completed'], 0)
        self.assertEqual(status['pending'], 2)
        
        # Dokončíme jednu položku
        first_item = self.document.items.first()
        first_item.quantity_actual = first_item.quantity_planned
        first_item.status = PickingList.Status.COMPLETED
        first_item.save()
        
        status = self.document.get_completion_status()
        self.assertEqual(status['completed'], 1)
        self.assertEqual(status['pending'], 1)
        self.assertEqual(status['percentage'], 50)
        self.assertFalse(self.document.can_be_archived())
        
        # Dokončíme druhou položku
        second_item = self.document.items.exclude(id=first_item.id).first()
        second_item.quantity_actual = second_item.quantity_planned
        second_item.status = PickingList.Status.COMPLETED
        second_item.save()
        
        status = self.document.get_completion_status()
        self.assertEqual(status['completed'], 2)
        self.assertEqual(status['pending'], 0)
        self.assertEqual(status['percentage'], 100)
        self.assertTrue(self.document.can_be_archived())
