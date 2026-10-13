"""Osiřelé položky výdejek a jídla ve více jídelnících.

Obojí vzniká na výměnné sobotě: starý turnus končí sobotou, nový jí začíná
a stejné jídlo je v obou jídelníčcích. Doklad dostane jen jedna kopie, druhá
zůstane viset bez dokladu - a staré upozornění (`stale_picking_summary`) ji
nevidí, protože hledá jen položky v dokladech.
"""
from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from apps.canteens.models import Canteen, Warehouse
from apps.core.models import Ingredient, Recipe, UserProfile
from apps.production.models import (
    MenuPlan, PickingList, PickingListDocument, ProductionOrder,
)
from apps.production.utils import duplicate_meals, orphan_picking_summary

TODAY = date(2026, 10, 13)
SATURDAY = TODAY - timedelta(days=10)
DINNER = ProductionOrder.MealType.DINNER
LUNCH = ProductionOrder.MealType.LUNCH


class Base(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser('admin', password='x')
        self.canteen = Canteen.objects.create(name='Růžená')
        self.other_canteen = Canteen.objects.create(name='Varvažov')
        self.warehouses = {
            self.canteen.pk: Warehouse.objects.create(name='Sklad R', canteen=self.canteen),
            self.other_canteen.pk: Warehouse.objects.create(name='Sklad V', canteen=self.other_canteen),
        }
        self.ingredient = Ingredient.objects.create(
            name='Fazole', unit='kg', base_unit='kg', recipe_unit='kg',
            conversion_factor=Decimal('1'),
        )
        self.recipe = Recipe.objects.create(name='Chilli', base_portions=10)
        self._n = 0

    def menu(self, name, d_from, d_to, canteen=None):
        return MenuPlan.objects.create(
            name=name, canteen=canteen or self.canteen, date_from=d_from, date_to=d_to,
        )

    def order(self, menu, day, meal=DINNER, documented=False, status=PickingList.Status.PENDING):
        order = ProductionOrder.objects.create(
            menu_plan=menu, recipe=self.recipe, canteen=menu.canteen,
            date=day, meal_type=meal,
        )
        document = None
        if documented:
            self._n += 1
            document = PickingListDocument.objects.create(
                name=f'Doc {self._n}', canteen=menu.canteen,
                date_from=day, date_to=day, created_by=self.admin,
            )
        extra = {'quantity_actual': Decimal('1')} if status == PickingList.Status.COMPLETED else {}
        PickingList.objects.create(
            production_order=order, document=document,
            warehouse=self.warehouses[menu.canteen_id],
            ingredient=self.ingredient, quantity_planned=Decimal('1'),
            status=status, **extra,
        )
        return order


class OrphanPickingTest(Base):
    def test_past_order_without_document_is_reported(self):
        menu = self.menu('M', SATURDAY, SATURDAY)
        self.order(menu, SATURDAY)

        rows = orphan_picking_summary(self.admin, today=TODAY)

        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]['orders'], rows[0]['items']), (1, 1))
        self.assertEqual(rows[0]['missing'], 1)
        self.assertEqual(rows[0]['duplicates'], 0)

    def test_same_meal_with_document_elsewhere_is_duplicate(self):
        old = self.menu('Starý turnus', SATURDAY - timedelta(days=14), SATURDAY)
        new = self.menu('Nový turnus', SATURDAY, SATURDAY + timedelta(days=14))
        self.order(old, SATURDAY, documented=True)
        self.order(new, SATURDAY)

        row = orphan_picking_summary(self.admin, today=TODAY)[0]

        self.assertEqual((row['duplicates'], row['missing']), (1, 0))

    def test_different_meal_type_is_not_duplicate(self):
        old = self.menu('Starý', SATURDAY, SATURDAY)
        new = self.menu('Nový', SATURDAY, SATURDAY)
        self.order(old, SATURDAY, meal=LUNCH, documented=True)
        self.order(new, SATURDAY, meal=DINNER)

        row = orphan_picking_summary(self.admin, today=TODAY)[0]

        self.assertEqual((row['duplicates'], row['missing']), (0, 1))

    def test_future_and_today_are_not_reported(self):
        menu = self.menu('M', TODAY, TODAY + timedelta(days=3))
        self.order(menu, TODAY)
        self.order(menu, TODAY + timedelta(days=1))

        self.assertEqual(orphan_picking_summary(self.admin, today=TODAY), [])

    def test_documented_and_completed_items_are_not_reported(self):
        menu = self.menu('M', SATURDAY, SATURDAY)
        self.order(menu, SATURDAY, documented=True)
        self.order(menu, SATURDAY, meal=LUNCH, status=PickingList.Status.COMPLETED)

        self.assertEqual(orphan_picking_summary(self.admin, today=TODAY), [])

    def test_replacement_orders_are_ignored(self):
        """Náhrada ze záměny se nevydává, generátor ji taky přeskakuje."""
        menu = self.menu('M', SATURDAY, SATURDAY)
        original = self.order(menu, SATURDAY, documented=True)
        replacement = self.order(menu, SATURDAY, meal=LUNCH)
        ProductionOrder.objects.filter(pk=replacement.pk).update(replacement_of=original)

        self.assertEqual(orphan_picking_summary(self.admin, today=TODAY), [])

    def test_user_sees_only_own_canteens(self):
        menu = self.menu('M', SATURDAY, SATURDAY)
        other = self.menu('M2', SATURDAY, SATURDAY, canteen=self.other_canteen)
        self.order(menu, SATURDAY)
        self.order(other, SATURDAY)
        user = User.objects.create_user('kuchar')
        UserProfile.objects.get_or_create(user=user)[0].canteens.set([self.canteen])

        rows = orphan_picking_summary(user, today=TODAY)

        self.assertEqual([r['canteen_name'] for r in rows], ['Růžená'])

    def test_home_page_shows_warning(self):
        menu = self.menu('M', SATURDAY, SATURDAY)
        self.order(menu, SATURDAY)
        self.client.force_login(self.admin)

        response = self.client.get(reverse('home'))

        self.assertContains(response, 'Dny bez výdejky')


class DuplicateMealsTest(Base):
    def test_overlapping_saturday_is_reported_in_both_menus(self):
        old = self.menu('Starý', SATURDAY - timedelta(days=14), SATURDAY)
        new = self.menu('Nový', SATURDAY, SATURDAY + timedelta(days=14))
        self.order(old, SATURDAY)
        self.order(new, SATURDAY)

        for menu, other in ((old, new), (new, old)):
            found = duplicate_meals(menu)
            self.assertEqual(len(found), 1)
            self.assertEqual(found[0]['date'], SATURDAY)
            self.assertEqual(found[0]['others'], [other])

    def test_split_by_meal_has_no_duplicate(self):
        """Správné rozdělení výměnné soboty: oběd starému, večeře novému."""
        old = self.menu('Starý', SATURDAY - timedelta(days=14), SATURDAY)
        new = self.menu('Nový', SATURDAY, SATURDAY + timedelta(days=14))
        self.order(old, SATURDAY, meal=LUNCH)
        self.order(new, SATURDAY, meal=DINNER)

        self.assertEqual(duplicate_meals(old), [])
        self.assertEqual(duplicate_meals(new), [])

    def test_other_canteen_is_not_a_duplicate(self):
        mine = self.menu('Moje', SATURDAY, SATURDAY)
        theirs = self.menu('Cizí', SATURDAY, SATURDAY, canteen=self.other_canteen)
        self.order(mine, SATURDAY)
        self.order(theirs, SATURDAY)

        self.assertEqual(duplicate_meals(mine), [])

    def test_menu_without_orders_has_no_duplicates(self):
        self.assertEqual(duplicate_meals(self.menu('Prázdný', SATURDAY, SATURDAY)), [])

    def test_menu_detail_shows_banner(self):
        old = self.menu('Starý', SATURDAY - timedelta(days=14), SATURDAY)
        new = self.menu('Nový', SATURDAY, SATURDAY + timedelta(days=14))
        self.order(old, SATURDAY)
        self.order(new, SATURDAY)
        self.client.force_login(self.admin)

        response = self.client.get(reverse('production:menu_detail', args=[new.pk]))

        self.assertContains(response, 'Stejná jídla jsou i v jiném jídelníčku')
