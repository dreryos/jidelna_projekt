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


class AddIngredientTargetsCorrectOrderTest(TestCase):
    """Surovina přidaná ve výdejce k druhému jídlu dne se musí zapsat
    k tomuto jídlu, ne k prvnímu jídlu dne."""

    def setUp(self):
        self.user = User.objects.create_superuser('admin', 'a@a.cz', 'x')
        self.client.force_login(self.user)

        self.canteen = Canteen.objects.create(name='Test Canteen')
        self.warehouse = Warehouse.objects.create(name='Main', canteen=self.canteen)
        self.flour = Ingredient.objects.create(
            name='Mouka', unit='kg', base_unit='kg', recipe_unit='kg',
            conversion_factor=Decimal('1.0'),
        )
        self.salt = Ingredient.objects.create(
            name='Sůl', unit='kg', base_unit='kg', recipe_unit='kg',
            conversion_factor=Decimal('1.0'),
        )
        StockItem.objects.create(warehouse=self.warehouse, ingredient=self.flour,
                                 quantity=Decimal('100'), price=Decimal('1'))
        StockItem.objects.create(warehouse=self.warehouse, ingredient=self.salt,
                                 quantity=Decimal('100'), price=Decimal('1'))

        menu_plan = MenuPlan.objects.create(
            name='Plan', canteen=self.canteen,
            date_from=date(2025, 9, 10), date_to=date(2025, 9, 10),
        )
        self.orders = []
        for meal_type, recipe_name in [
            (ProductionOrder.MealType.LUNCH, 'Oběd jídlo'),
            (ProductionOrder.MealType.DINNER, 'Večeře jídlo'),
        ]:
            recipe = Recipe.objects.create(name=recipe_name, base_portions=10)
            RecipeIngredient.objects.create(
                recipe=recipe, ingredient=self.flour,
                quantity_per_portion=Decimal('1.000'),
            )
            order = ProductionOrder.objects.create(
                recipe=recipe, canteen=self.canteen, menu_plan=menu_plan,
                date=date(2025, 9, 10), meal_type=meal_type,
            )
            ProductionOrderPortionVariant.objects.create(
                production_order=order, portions=2, coefficient=Decimal('1.0'),
            )
            order.generate_picking_list()
            self.orders.append(order)

        self.document = PickingListDocument.objects.create(
            name='Doc', canteen=self.canteen,
            date_from=date(2025, 9, 10), date_to=date(2025, 9, 10),
            created_by=self.user,
        )
        PickingList.objects.filter(
            production_order__in=self.orders
        ).update(document=self.document)

    def test_added_ingredient_goes_to_selected_meal(self):
        dinner = self.orders[1]
        existing = {
            f'quantity_actual_item_{item.id}': str(item.quantity_planned)
            for item in PickingList.objects.filter(document=self.document)
        }
        response = self.client.post(
            f'/production/vydejky/{self.document.id}/edit/',
            data={
                **existing,
                f'new_ingredient_order_{dinner.id}_0': str(self.salt.id),
                f'new_quantity_order_{dinner.id}_0': '1.5',
            },
        )
        self.assertEqual(response.status_code, 302)
        added = PickingList.objects.get(document=self.document, ingredient=self.salt)
        self.assertEqual(added.production_order_id, dinner.id,
                         'Přidaná surovina se zapsala k jinému jídlu')

    def test_add_panel_names_match_meals(self):
        response = self.client.get(f'/production/vydejky/{self.document.id}/edit/')
        html = response.content.decode()
        for order in self.orders:
            assert f'new_ingredient_order_{order.id}_0' in html, order.id
            assert f'id="add-rows-{order.id}"' in html, order.id
        # panel druhého jídla musí být uvnitř karty s jeho receptem
        # (název hledáme jen v hlavičce karty – select záměny obsahuje
        # všechny recepty)
        import re
        cards = re.split(r'meal-card', html)
        for chunk in cards:
            header = chunk.split('add-ingredient-panel')[0]
            if 'Večeře jídlo' in header and 'new_ingredient_order_' in chunk:
                m = re.search(r'new_ingredient_order_(\d+)_0', chunk)
                assert m and int(m.group(1)) == self.orders[1].id, m and m.group(1)

    def test_add_targets_meal_when_alphabetical_differs_from_display(self):
        """Prod scénář: večeře je abecedně první (Chilli < Snídaně),
        zobrazení řadí podle typu jídla. Přidání ke snídani nesmí
        skončit u večeře."""
        breakfast, dinner = self.orders
        breakfast.meal_type = 'BREAKFAST'
        breakfast.save()
        breakfast.recipe.name = 'Snídaně II'
        breakfast.recipe.save()
        dinner.recipe.name = 'Chilli con carne, chléb'
        dinner.recipe.save()

        existing = {
            f'quantity_actual_item_{item.id}': str(item.quantity_planned)
            for item in PickingList.objects.filter(document=self.document)
        }
        response = self.client.post(
            f'/production/vydejky/{self.document.id}/edit/',
            data={
                **existing,
                f'new_ingredient_order_{breakfast.id}_0': str(self.salt.id),
                f'new_quantity_order_{breakfast.id}_0': '1.5',
            },
        )
        self.assertEqual(response.status_code, 302)
        added = PickingList.objects.get(document=self.document, ingredient=self.salt)
        self.assertEqual(added.production_order_id, breakfast.id)

        # A v HTML musí být panel snídaně uvnitř karty snídaně (název jen
        # z hlavičky – select záměny obsahuje všechny recepty)
        html = self.client.get(f'/production/vydejky/{self.document.id}/edit/').content.decode()
        import re
        for chunk in re.split(r'meal-card', html):
            header = chunk.split('add-ingredient-panel')[0]
            if 'Snídaně II' in header and 'new_ingredient_order_' in chunk:
                m = re.search(r'new_ingredient_order_(\d+)_0', chunk)
                self.assertEqual(int(m.group(1)), breakfast.id)

    def test_second_dinner_created_on_add(self):
        """Přidání suroviny do prázdné karty druhé večeře založí jídlo
        „Výdej" s meal_type=DINNER_SECOND pro daný den."""
        day = date(2025, 9, 10)
        # prázdná karta se renderuje
        html = self.client.get(f'/production/vydejky/{self.document.id}/edit/').content.decode()
        self.assertIn(f'new_ingredient_dinner2_{day.isoformat()}_0', html)
        self.assertIn('Druhá večeře', html)

        existing = {
            f'quantity_actual_item_{item.id}': str(item.quantity_planned)
            for item in PickingList.objects.filter(document=self.document)
        }
        response = self.client.post(
            f'/production/vydejky/{self.document.id}/edit/',
            data={
                **existing,
                f'new_ingredient_dinner2_{day.isoformat()}_0': str(self.salt.id),
                f'new_quantity_dinner2_{day.isoformat()}_0': '2,5',
            },
        )
        self.assertEqual(response.status_code, 302)

        order = ProductionOrder.objects.get(
            canteen=self.canteen, date=day, meal_type='DINNER_SECOND')
        self.assertEqual(order.recipe.name, 'Výdej')
        item = PickingList.objects.get(production_order=order, ingredient=self.salt)
        self.assertEqual(item.document_id, self.document.id)
        self.assertEqual(item.quantity_planned, Decimal('2.5'))
        self.assertEqual(item.warehouse, self.warehouse)

        # karta druhé večeře už není prázdný placeholder, ale jídlo s položkou
        html = self.client.get(f'/production/vydejky/{self.document.id}/edit/').content.decode()
        self.assertNotIn(f'new_ingredient_dinner2_{day.isoformat()}_0', html)
        self.assertIn(f'new_ingredient_order_{order.id}_0', html)

        # druhé přidání použije existující order
        response = self.client.post(
            f'/production/vydejky/{self.document.id}/edit/',
            data={
                **existing,
                f'quantity_actual_item_{item.id}': '2.5',
                f'new_ingredient_order_{order.id}_0': str(self.flour.id),
                f'new_quantity_order_{order.id}_0': '1',
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            ProductionOrder.objects.filter(meal_type='DINNER_SECOND').count(), 1)
        self.assertEqual(
            PickingList.objects.filter(production_order=order).count(), 2)

    def test_document_delete_removes_empty_second_dinner(self):
        """Smazání výdejky uklidí i prázdný příkaz druhé večeře, aby se
        nepletl do příště generovaných výdejek s nulovými množstvími."""
        day = date(2025, 9, 10)
        existing = {
            f'quantity_actual_item_{item.id}': str(item.quantity_planned)
            for item in PickingList.objects.filter(document=self.document)
        }
        self.client.post(
            f'/production/vydejky/{self.document.id}/edit/',
            data={
                **existing,
                f'new_ingredient_dinner2_{day.isoformat()}_0': str(self.salt.id),
                f'new_quantity_dinner2_{day.isoformat()}_0': '1',
            },
        )
        self.assertTrue(ProductionOrder.objects.filter(meal_type='DINNER_SECOND').exists())

        response = self.client.post(f'/production/vydejky/{self.document.id}/smazat/')
        self.assertEqual(response.status_code, 302)
        self.assertFalse(ProductionOrder.objects.filter(meal_type='DINNER_SECOND').exists())
        # běžná jídla z plánu zůstávají
        self.assertEqual(ProductionOrder.objects.count(), 2)

    def test_second_dinner_survives_regeneration(self):
        """Příkaz druhé večeře má variantu 1 porce, override ukládá množství
        na porci a přegenerování výdejky množství nevynuluje."""
        day = date(2025, 9, 10)
        existing = {
            f'quantity_actual_item_{item.id}': str(item.quantity_planned)
            for item in PickingList.objects.filter(document=self.document)
        }
        self.client.post(
            f'/production/vydejky/{self.document.id}/edit/',
            data={
                **existing,
                f'new_ingredient_dinner2_{day.isoformat()}_0': str(self.salt.id),
                f'new_quantity_dinner2_{day.isoformat()}_0': '2.5',
            },
        )
        order = ProductionOrder.objects.get(meal_type='DINNER_SECOND')
        self.assertEqual(order.total_effective_portions, Decimal('1.0'))

        override = order.ingredient_overrides.get(ingredient=self.salt)
        self.assertEqual(override.quantity_per_portion, Decimal('2.500'))

        order.generate_picking_list()
        item = PickingList.objects.get(production_order=order, ingredient=self.salt)
        self.assertEqual(item.quantity_planned, Decimal('2.500'))
