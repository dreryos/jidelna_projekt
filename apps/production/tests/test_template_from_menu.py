"""Uložení jídelníčku jako šablony.

Šablona (`MenuTemplate`) je XML s harmonogramem: posun dne, kód receptu, typ
jídla. Jídelníček se dá obrátit na šablonu a znovu importovat; hlavní riziko
je tichá ztráta nebo změna dat při převodu, proto kulatý test přes skutečný
průvodce importu.
"""
from datetime import date, timedelta

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from apps.canteens.models import Canteen
from apps.core.models import Category, Recipe, UserProfile
from apps.production.models import MenuPlan, MenuTemplate, ProductionOrder
from apps.production.xml_parser import parse_menu_template_xml

START = date(2026, 11, 2)


class MenuTemplateFromPlanTest(TestCase):
    def setUp(self):
        self.canteen = Canteen.objects.create(name='Jídelna')
        self.category = Category.objects.create(code='HJ', name='Hlavní jídla')
        self.plan = MenuPlan.objects.create(
            name='Podzimní tábor', canteen=self.canteen,
            date_from=START, date_to=START + timedelta(days=4),
        )
        self.recipe_a = self._recipe('Guláš')
        self.recipe_b = self._recipe('Řízek')
        self.recipe_c = self._recipe('Polévka dne')

    def _recipe(self, name):
        return Recipe.objects.create(name=name, category=self.category, base_portions=10)

    def _order(self, recipe, day, meal_type='LUNCH', replacement_of=None, plan=None):
        return ProductionOrder.objects.create(
            menu_plan=plan or self.plan, recipe=recipe, canteen=self.canteen,
            date=START + timedelta(days=day), meal_type=meal_type,
            replacement_of=replacement_of,
        )

    def _parsed(self, template):
        return parse_menu_template_xml(template.xml_content)

    def test_offsets_codes_and_meal_types(self):
        self._order(self.recipe_a, 0, 'LUNCH')
        self._order(self.recipe_b, 0, 'DINNER')
        self._order(self.recipe_c, 2, 'BREAKFAST')

        template, report = MenuTemplate.create_from_menu_plan(self.plan, 'Šablona 1')

        schedule = {d['date_offset']: d['meals'] for d in self._parsed(template)['schedule']}
        self.assertEqual(
            sorted((m['meal_type'], m['recipe_code']) for m in schedule[0]),
            sorted([('LUNCH', self.recipe_a.code), ('DINNER', self.recipe_b.code)]),
        )
        self.assertEqual(
            [(m['meal_type'], m['recipe_code']) for m in schedule[2]],
            [('BREAKFAST', self.recipe_c.code)],
        )
        self.assertEqual(report['meals'], 3)

    def test_empty_day_keeps_its_place(self):
        """Den bez jídla uprostřed se nesmí zhroutit - posun dnů se zachová."""
        self._order(self.recipe_a, 0)
        self._order(self.recipe_b, 3)
        template, _ = MenuTemplate.create_from_menu_plan(self.plan, 'S mezerou')
        offsets = {d['date_offset'] for d in self._parsed(template)['schedule'] if d['meals']}
        self.assertEqual(offsets, {0, 3})

    def test_replaced_original_is_dropped_in_favour_of_replacement(self):
        """Do šablony patří to, co se skutečně vařilo, ne zaměněný původní recept."""
        original = self._order(self.recipe_a, 1)
        self._order(self.recipe_b, 1, replacement_of=original)

        template, report = MenuTemplate.create_from_menu_plan(self.plan, 'Se záměnou')

        codes = [m['recipe_code'] for d in self._parsed(template)['schedule'] for m in d['meals']]
        self.assertEqual(codes, [self.recipe_b.code])
        self.assertEqual(report['replaced_skipped'], 1)

    def test_technical_cards_are_skipped_and_counted(self):
        """Polévka a druhá večeře jsou technické karty s pseudo-receptem, ne jídla.

        Formát šablony je nezná a převod zpět by je tiše změnil na oběd.
        """
        self._order(self.recipe_a, 0, 'LUNCH')
        self._order(self.recipe_b, 0, 'SOUP')
        self._order(self.recipe_c, 0, 'DINNER_SECOND')

        template, report = MenuTemplate.create_from_menu_plan(self.plan, 'Bez karet')

        types = [m['meal_type'] for d in self._parsed(template)['schedule'] for m in d['meals']]
        self.assertEqual(types, ['LUNCH'])
        self.assertEqual(report['technical_skipped'], 2)

    def test_plan_without_meals_is_rejected(self):
        with self.assertRaises(ValidationError):
            MenuTemplate.create_from_menu_plan(self.plan, 'Prázdná')
        self.assertEqual(MenuTemplate.objects.count(), 0)

    def test_plan_with_only_technical_cards_is_rejected(self):
        self._order(self.recipe_a, 0, 'SOUP')
        with self.assertRaises(ValidationError):
            MenuTemplate.create_from_menu_plan(self.plan, 'Jen karty')

    def test_duplicate_name_is_rejected_case_insensitively(self):
        self._order(self.recipe_a, 0)
        MenuTemplate.create_from_menu_plan(self.plan, 'Tábor')
        with self.assertRaises(ValidationError):
            MenuTemplate.create_from_menu_plan(self.plan, 'tábor')

    def test_blank_name_is_rejected(self):
        self._order(self.recipe_a, 0)
        with self.assertRaises(ValidationError):
            MenuTemplate.create_from_menu_plan(self.plan, '   ')

    def test_xml_passes_import_parser_without_warnings(self):
        self._order(self.recipe_a, 0)
        template, _ = MenuTemplate.create_from_menu_plan(self.plan, 'Čistá')
        self.assertEqual(self._parsed(template)['warnings'], [])

    def test_order_dates_before_plan_start_do_not_make_negative_offsets(self):
        """Nekonzistentní data: jídlo před začátkem jídelníčku."""
        self._order(self.recipe_a, -1)
        self._order(self.recipe_b, 0)
        template, _ = MenuTemplate.create_from_menu_plan(self.plan, 'Posun')
        offsets = [d['date_offset'] for d in self._parsed(template)['schedule']]
        self.assertTrue(all(o >= 0 for o in offsets), offsets)


class RoundTripThroughImportWizardTest(TestCase):
    """Jídelníček -> šablona -> import průvodcem -> stejná struktura."""

    def setUp(self):
        self.canteen = Canteen.objects.create(name='Jídelna')
        category = Category.objects.create(code='HJ', name='Hlavní jídla')
        self.recipes = [
            Recipe.objects.create(name=n, category=category, base_portions=10)
            for n in ('Guláš', 'Řízek', 'Palačinky')
        ]
        self.plan = MenuPlan.objects.create(
            name='Původní', canteen=self.canteen,
            date_from=START, date_to=START + timedelta(days=3),
        )
        for recipe, day, meal in [
            (self.recipes[0], 0, 'LUNCH'), (self.recipes[1], 0, 'DINNER'),
            (self.recipes[2], 2, 'LUNCH'), (self.recipes[0], 3, 'BREAKFAST'),
        ]:
            ProductionOrder.objects.create(
                menu_plan=self.plan, recipe=recipe, canteen=self.canteen,
                date=START + timedelta(days=day), meal_type=meal,
            )
        self.user = User.objects.create_superuser('admin', password='x')
        self.client.force_login(self.user)

    @staticmethod
    def _structure(plan):
        return sorted(
            ((o.date - plan.date_from).days, o.meal_type, o.recipe.code)
            for o in plan.production_orders.all()
        )

    def test_imported_plan_has_the_same_structure(self):
        template, _ = MenuTemplate.create_from_menu_plan(self.plan, 'Kulatá')
        new_start = date(2027, 1, 11)

        step1 = self.client.post(reverse('production:menu_import_step1'), {
            'import_source': 'template', 'template': template.pk,
            'canteen': self.canteen.pk, 'start_date': new_start.isoformat(),
            'menu_name': 'Z šablony',
        })
        self.assertEqual(step1.status_code, 302, getattr(step1, 'context', None) and step1.context['form'].errors)
        self.client.post(reverse('production:menu_import_step3'))

        imported = MenuPlan.objects.get(name='Z šablony')
        self.assertEqual(imported.date_from, new_start)
        self.assertEqual(self._structure(imported), self._structure(self.plan))


class SaveAsTemplateViewTest(TestCase):
    def setUp(self):
        self.canteen = Canteen.objects.create(name='Jídelna A')
        self.other = Canteen.objects.create(name='Jídelna B')
        category = Category.objects.create(code='HJ', name='Hlavní jídla')
        recipe = Recipe.objects.create(name='Guláš', category=category, base_portions=10)
        self.plan = MenuPlan.objects.create(
            name='Tábor', canteen=self.canteen, date_from=START, date_to=START,
        )
        ProductionOrder.objects.create(
            menu_plan=self.plan, recipe=recipe, canteen=self.canteen,
            date=START, meal_type='LUNCH',
        )
        self.url = reverse('production:menu_save_as_template', args=[self.plan.pk])

        self.owner = User.objects.create_user('majitel')
        UserProfile.objects.get_or_create(user=self.owner)[0].canteens.set([self.canteen])
        self.stranger = User.objects.create_user('cizi')
        UserProfile.objects.get_or_create(user=self.stranger)[0].canteens.set([self.other])

    def test_get_shows_summary_with_plan_name_prefilled(self):
        self.client.force_login(self.owner)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Tábor')

    def test_post_creates_template_and_redirects(self):
        self.client.force_login(self.owner)
        response = self.client.post(self.url, {'name': 'Uložená', 'description': 'z jídelníčku'})
        self.assertEqual(response.status_code, 302)
        template = MenuTemplate.objects.get(name='Uložená')
        self.assertEqual(template.description, 'z jídelníčku')

    def test_post_with_duplicate_name_shows_error_and_creates_nothing(self):
        self.client.force_login(self.owner)
        self.client.post(self.url, {'name': 'Uložená'})
        response = self.client.post(self.url, {'name': 'uložená'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(MenuTemplate.objects.count(), 1)

    def test_user_of_other_canteen_gets_404(self):
        self.client.force_login(self.stranger)
        self.assertEqual(self.client.get(self.url).status_code, 404)
        self.assertEqual(self.client.post(self.url, {'name': 'X'}).status_code, 404)
        self.assertEqual(MenuTemplate.objects.count(), 0)

    def test_anonymous_is_redirected_to_login(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertIn('/login', response['Location'])
