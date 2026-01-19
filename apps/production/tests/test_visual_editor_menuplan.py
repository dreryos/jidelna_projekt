from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth import get_user_model
from apps.production.models import MenuPlan, ProductionOrder
from apps.core.models import Recipe
from apps.canteens.models import Canteen
import json
from datetime import date


class MenuPlanVisualEditorTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user('tester', 'tester@example.com', 'password')
        self.canteen = Canteen.objects.create(name='Test Canteen')
        
        # Create UserProfile and assign canteen (required by CanteenOwnerMixin)
        self.profile = self.user.profile
        self.profile.canteens.add(self.canteen)
        
        self.recipe = Recipe.objects.create(code='R100', name='Test Recipe')
        self.menu = MenuPlan.objects.create(
            name='Test Menu',
            canteen=self.canteen,
            date_from=date(2026, 1, 1),
            date_to=date(2026, 1, 7)
        )
        self.client = Client()
        self.client.login(username='tester', password='password')

    def test_menu_visual_view_renders(self):
        url = reverse('production:menu_visual_edit', kwargs={'pk': self.menu.pk})
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode('utf-8')
        self.assertIn('id="template-data"', content)
        self.assertIn('scheduleDict', content)

    def test_add_and_remove_meal_ajax(self):
        add_url = reverse('production:menu_visual_add_meal_ajax', kwargs={'menu_pk': self.menu.pk})
        data = {
            'day_index': 0,
            'recipe_code': self.recipe.code,
            'meal_type': 'LUNCH'
        }
        resp = self.client.post(add_url, json.dumps(data), content_type='application/json')
        self.assertEqual(resp.status_code, 200)
        j = resp.json()
        self.assertTrue(j.get('success'))
        meal = j.get('meal')
        self.assertIsNotNone(meal)
        self.assertIn('unique_id', meal)
        # Check DB
        orders = ProductionOrder.objects.filter(menu_plan=self.menu, recipe=self.recipe)
        self.assertEqual(orders.count(), 1)
        order = orders.first()

        # Now remove via unique_id
        remove_url = reverse('production:menu_visual_remove_meal_ajax', kwargs={'menu_pk': self.menu.pk})
        payload = {'unique_id': meal['unique_id']}
        resp2 = self.client.post(remove_url, json.dumps(payload), content_type='application/json')
        self.assertEqual(resp2.status_code, 200)
        j2 = resp2.json()
        self.assertTrue(j2.get('success'))
        self.assertFalse(ProductionOrder.objects.filter(pk=order.pk).exists())

    def test_clear_day_ajax(self):
        # create two orders on day 1
        add_url = reverse('production:menu_visual_add_meal_ajax', kwargs={'menu_pk': self.menu.pk})
        data = {'day_index': 1, 'recipe_code': self.recipe.code, 'meal_type': 'LUNCH'}
        self.client.post(add_url, json.dumps(data), content_type='application/json')
        self.client.post(add_url, json.dumps(data), content_type='application/json')
        orders_before = ProductionOrder.objects.filter(menu_plan=self.menu, date=self.menu.date_from)
        # clear day 0
        clear_url = reverse('production:menu_visual_clear_day_ajax', kwargs={'menu_pk': self.menu.pk})
        resp = self.client.post(clear_url, json.dumps({'day_index': 0}), content_type='application/json')
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json().get('success'))
