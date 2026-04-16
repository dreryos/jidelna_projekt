from django.test import TestCase, Client
from django.contrib.auth.models import User
from decimal import Decimal
from datetime import date

from apps.canteens.models import Canteen, Warehouse
from apps.core.models import Ingredient, Recipe, RecipeIngredient, UserProfile
from apps.inventory.models import StockItem
from apps.production.models import (
    ProductionOrder, PickingList, MenuPlan,
    ProductionOrderPortionVariant, PickingListDocument,
)


class PickingListGeneratorTest(TestCase):
    """
    Testy pro view picking_list_generator — ověřují, že se výdejka
    vygeneruje správně i když PickingList položky neexistují nebo mají
    nulové množství (stale prefetch cache bug).
    """

    def setUp(self):
        self.canteen = Canteen.objects.create(name='Test Canteen')
        self.warehouse = Warehouse.objects.create(name='Main', canteen=self.canteen)
        self.ingredient = Ingredient.objects.create(
            name='Mouka',
            unit='kg',
            base_unit='kg',
            recipe_unit='kg',
            conversion_factor=Decimal('1.0'),
        )
        self.ingredient2 = Ingredient.objects.create(
            name='Cukr',
            unit='kg',
            base_unit='kg',
            recipe_unit='kg',
            conversion_factor=Decimal('1.0'),
        )
        StockItem.objects.create(
            warehouse=self.warehouse,
            ingredient=self.ingredient,
            quantity=Decimal('50.000'),
            price=Decimal('1.00'),
        )
        StockItem.objects.create(
            warehouse=self.warehouse,
            ingredient=self.ingredient2,
            quantity=Decimal('30.000'),
            price=Decimal('2.00'),
        )

        self.recipe = Recipe.objects.create(name='Chleba', base_portions=10)
        RecipeIngredient.objects.create(
            recipe=self.recipe,
            ingredient=self.ingredient,
            quantity_per_portion=Decimal('1.000'),
        )
        RecipeIngredient.objects.create(
            recipe=self.recipe,
            ingredient=self.ingredient2,
            quantity_per_portion=Decimal('0.500'),
        )

        self.user = User.objects.create_superuser(
            username='admin', password='testpass123'
        )
        self.client = Client()
        self.client.login(username='admin', password='testpass123')

        self.menu_plan = MenuPlan.objects.create(
            name='Test Menu',
            canteen=self.canteen,
            date_from=date(2026, 4, 20),
            date_to=date(2026, 4, 22),
        )

    def _create_order_with_variants(self, order_date, portions=10, coefficient='1.0'):
        """Vytvoří ProductionOrder s variantou porcí."""
        order = ProductionOrder.objects.create(
            menu_plan=self.menu_plan,
            recipe=self.recipe,
            canteen=self.canteen,
            date=order_date,
        )
        ProductionOrderPortionVariant.objects.create(
            production_order=order,
            portions=portions,
            coefficient=Decimal(coefficient),
            order=0,
        )
        return order

    def test_generator_creates_document_when_no_picking_items_exist(self):
        """
        Ověřuje, že picking_list_generator správně vygeneruje dokument
        i když ProductionOrder nemá žádné PickingList položky předem.
        Toto testuje opravu stale prefetch cache bugu.
        """
        order = self._create_order_with_variants(date(2026, 4, 20), portions=5)
        # Neexistují žádné PickingList položky
        self.assertEqual(order.picking_list_items.count(), 0)

        response = self.client.post('/production/vydejky/', {
            'canteen': self.canteen.id,
            'date_from': '2026-04-20',
            'date_to': '2026-04-20',
        })

        # Měl by přesměrovat (302) po úspěšném vygenerování
        self.assertEqual(response.status_code, 302)

        # Ověříme, že se vytvořil dokument
        doc = PickingListDocument.objects.first()
        self.assertIsNotNone(doc)
        self.assertEqual(doc.canteen, self.canteen)

        # Ověříme, že picking list položky existují a jsou propojeny s dokumentem
        items = PickingList.objects.filter(document=doc)
        self.assertGreater(items.count(), 0)

        # Ověříme správné množství (5 porcí × 1.0 kg = 5.0 kg pro Mouku)
        mouka_item = items.filter(ingredient=self.ingredient).first()
        self.assertIsNotNone(mouka_item)
        self.assertEqual(mouka_item.quantity_planned, Decimal('5.000'))

        # Ověříme správné množství (5 porcí × 0.5 kg = 2.5 kg pro Cukr)
        cukr_item = items.filter(ingredient=self.ingredient2).first()
        self.assertIsNotNone(cukr_item)
        self.assertEqual(cukr_item.quantity_planned, Decimal('2.500'))

    def test_generator_regenerates_zero_quantity_items(self):
        """
        Ověřuje, že výdejka s položkami s nulovým množstvím se správně
        regeneruje a propojí s dokumentem.
        """
        order = self._create_order_with_variants(date(2026, 4, 21), portions=8)

        # Vytvořím PickingList položky s quantity_planned=0 (simulace starého bugu)
        PickingList.objects.create(
            production_order=order,
            ingredient=self.ingredient,
            quantity_planned=Decimal('0'),
            warehouse=self.warehouse,
        )
        PickingList.objects.create(
            production_order=order,
            ingredient=self.ingredient2,
            quantity_planned=Decimal('0'),
            warehouse=self.warehouse,
        )

        response = self.client.post('/production/vydejky/', {
            'canteen': self.canteen.id,
            'date_from': '2026-04-21',
            'date_to': '2026-04-21',
        })

        self.assertEqual(response.status_code, 302)

        doc = PickingListDocument.objects.first()
        self.assertIsNotNone(doc)

        items = PickingList.objects.filter(document=doc)
        self.assertGreater(items.count(), 0)

        # Ověříme, že množství jsou nenulová (8 porcí × 1.0 kg = 8.0 kg)
        mouka_item = items.filter(ingredient=self.ingredient).first()
        self.assertIsNotNone(mouka_item)
        self.assertEqual(mouka_item.quantity_planned, Decimal('8.000'))

    def test_generator_handles_multiple_orders_mixed(self):
        """
        Ověřuje, že výdejka se vygeneruje správně pro více objednávek,
        kde některé mají existující picking list a některé ne.
        """
        # Order 1: S existujícím picking list (normální stav)
        order1 = self._create_order_with_variants(date(2026, 4, 20), portions=5)
        order1.generate_picking_list()
        self.assertEqual(order1.picking_list_items.count(), 2)

        # Order 2: Bez picking list (trigger regenerace)
        order2 = self._create_order_with_variants(date(2026, 4, 21), portions=10)
        self.assertEqual(order2.picking_list_items.count(), 0)

        response = self.client.post('/production/vydejky/', {
            'canteen': self.canteen.id,
            'date_from': '2026-04-20',
            'date_to': '2026-04-21',
        })

        self.assertEqual(response.status_code, 302)

        doc = PickingListDocument.objects.first()
        self.assertIsNotNone(doc)

        # Ověříme, že všechny položky jsou propojeny s dokumentem
        items = PickingList.objects.filter(document=doc)
        # 2 ingredience × 2 objednávky = 4 položky
        self.assertEqual(items.count(), 4)

        # Ověříme celkové množství Mouky: 5 + 10 = 15 kg
        mouka_total = sum(
            i.quantity_planned
            for i in items.filter(ingredient=self.ingredient)
        )
        self.assertEqual(mouka_total, Decimal('15.000'))
