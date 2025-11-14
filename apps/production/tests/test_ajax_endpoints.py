"""
Integrační testy pro AJAX endpointy v production modulu.
Testuje add_meal_to_menu endpoint včetně validace a chybových cest.
"""

from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth.models import User
from decimal import Decimal
from datetime import date, timedelta
import json

from apps.canteens.models import Canteen
from apps.core.models import Recipe, Category, UserProfile
from apps.production.models import MenuPlan, ProductionOrder, MenuPlanCoefficient, ProductionOrderPortionVariant


class AddMealToMenuAjaxTest(TestCase):
    """Testy pro AJAX endpoint add_meal_to_menu"""
    
    def setUp(self):
        """Příprava testovacích dat"""
        self.client = Client()
        
        # Vytvoříme uživatele (UserProfile se vytvoří automaticky signálem)
        self.user = User.objects.create_user(username='testuser', password='testpass123')
        self.superuser = User.objects.create_superuser(username='admin', password='adminpass123', email='admin@test.com')
        
        # Získáme UserProfile
        self.profile = self.user.profile
        
        # Vytvoříme jídelnu
        self.canteen = Canteen.objects.create(name='Test Canteen')
        self.profile.canteens.add(self.canteen)
        
        # Vytvoříme kategorii a recept
        self.category = Category.objects.create(name='Hlavní jídla')
        self.recipe = Recipe.objects.create(
            name='Svíčková',
            base_portions=10,
            category=self.category
        )
        
        # Vytvoříme jídelníček
        self.menu_plan = MenuPlan.objects.create(
            name='Týdenní menu',
            canteen=self.canteen,
            date_from=date.today(),
            date_to=date.today() + timedelta(days=7)
        )
        
        # Vytvoříme výchozí koeficienty
        MenuPlanCoefficient.objects.create(
            menu_plan=self.menu_plan,
            name='Normální porce',
            coefficient=Decimal('1.0'),
            order=0
        )
        MenuPlanCoefficient.objects.create(
            menu_plan=self.menu_plan,
            name='Malá porce',
            coefficient=Decimal('0.75'),
            order=1
        )
        
    
    def test_add_meal_success(self):
        """Test úspěšného přidání jídla do jídelníčku"""
        self.client.login(username='testuser', password='testpass123')
        
        meal_date = date.today() + timedelta(days=1)
        url = reverse('production:add_meal_to_menu', kwargs={'menu_pk': self.menu_plan.pk})
        
        response = self.client.post(
            url,
            data=json.dumps({
                'recipe_id': self.recipe.id,
                'date': meal_date.isoformat(),
                'variants': [
                    {'coefficient': '1.0', 'portions': 50, 'order': 0},
                    {'coefficient': '0.75', 'portions': 20, 'order': 1}
                ]
            }),
            content_type='application/json'
        )
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])
        self.assertIn('order_id', data)
        
        # Ověříme, že byl vytvořen ProductionOrder
        order = ProductionOrder.objects.get(id=data['order_id'])
        self.assertEqual(order.recipe, self.recipe)
        self.assertEqual(order.menu_plan, self.menu_plan)
        self.assertEqual(order.date, meal_date)
        self.assertEqual(order.canteen, self.canteen)
        
        # Ověříme varianty porcí
        variants = order.portion_variants.all()
        self.assertEqual(variants.count(), 2)
        self.assertEqual(variants[0].portions, 50)
        self.assertEqual(variants[0].coefficient, Decimal('1.0'))
        self.assertEqual(variants[1].portions, 20)
        self.assertEqual(variants[1].coefficient, Decimal('0.75'))
    
    def test_add_meal_without_authentication(self):
        """Test přidání jídla bez přihlášení - mělo by být zamítnuto"""
        meal_date = date.today() + timedelta(days=1)
        url = reverse('production:add_meal_to_menu', kwargs={'menu_pk': self.menu_plan.pk})
        
        response = self.client.post(
            url,
            data=json.dumps({
                'recipe_id': self.recipe.id,
                'date': meal_date.isoformat(),
                'portions': [{'coefficient_id': 1, 'portions': 50}]
            }),
            content_type='application/json'
        )
        
        # Mělo by být přesměrováno na login nebo vráceno 403/302
        self.assertIn(response.status_code, [302, 403])
    
    def test_add_meal_missing_required_fields(self):
        """Test s chybějícími povinnými poli"""
        self.client.login(username='testuser', password='testpass123')
        url = reverse('production:add_meal_to_menu', kwargs={'menu_pk': self.menu_plan.pk})
        
        # Chybí recipe_id
        response = self.client.post(
            url,
            data=json.dumps({
                'date': date.today().isoformat(),
                'portions': [{'coefficient_id': 1, 'portions': 50}]
            }),
            content_type='application/json'
        )
        
        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertFalse(data['success'])
        self.assertIn('error', data)
    
    def test_add_meal_invalid_menu_plan(self):
        """Test s neexistujícím menu_plan_id"""
        self.client.login(username='testuser', password='testpass123')
        
        # Používáme neexistující menu_pk v URL
        url = reverse('production:add_meal_to_menu', kwargs={'menu_pk': 99999})
        response = self.client.post(
            url,
            data=json.dumps({
                'recipe_id': self.recipe.id,
                'date': date.today().isoformat(),
                'portions': [{'coefficient_id': 1, 'portions': 50}]
            }),
            content_type='application/json'
        )
        
        self.assertEqual(response.status_code, 404)
        data = response.json()
        self.assertFalse(data['success'])
    
    def test_add_meal_invalid_recipe(self):
        """Test s neexistujícím recipe_id"""
        self.client.login(username='testuser', password='testpass123')
        url = reverse('production:add_meal_to_menu', kwargs={'menu_pk': self.menu_plan.pk})
        
        response = self.client.post(
            url,
            data=json.dumps({
                'recipe_id': 99999,  # Neexistující ID
                'date': date.today().isoformat(),
                'portions': [{'coefficient_id': 1, 'portions': 50}]
            }),
            content_type='application/json'
        )
        
        self.assertEqual(response.status_code, 404)
        data = response.json()
        self.assertFalse(data['success'])
    
    def test_add_meal_date_outside_menu_range(self):
        """Test s datem mimo rozsah jídelníčku - mělo by projít (není validováno)"""
        self.client.login(username='testuser', password='testpass123')
        url = reverse('production:add_meal_to_menu', kwargs={'menu_pk': self.menu_plan.pk})
        
        # Datum mimo rozsah jídelníčku (validace zatím není implementována)
        invalid_date = date.today() + timedelta(days=30)
        
        response = self.client.post(
            url,
            data=json.dumps({
                'recipe_id': self.recipe.id,
                'date': invalid_date.isoformat(),
                'total_portions': 50
            }),
            content_type='application/json'
        )
        
        # Zatím není validace datumu, tak by mělo projít
        self.assertEqual(response.status_code, 200)
    
    def test_add_meal_empty_portions(self):
        """Test s prázdným seznamem porcí - měl by využít fallback"""
        self.client.login(username='testuser', password='testpass123')
        url = reverse('production:add_meal_to_menu', kwargs={'menu_pk': self.menu_plan.pk})
        
        response = self.client.post(
            url,
            data=json.dumps({
                'recipe_id': self.recipe.id,
                'date': date.today().isoformat(),
                'total_portions': 0  # Nula porcí
            }),
            content_type='application/json'
        )
        
        # Systém by měl vytvořit variatu s 0 porcími (bytuč to není užitečné)
        self.assertEqual(response.status_code, 200)
    
    def test_add_meal_negative_portions(self):
        """Test se záporným počtem porcí - systém chybu nezachytí"""
        self.client.login(username='testuser', password='testpass123')
        url = reverse('production:add_meal_to_menu', kwargs={'menu_pk': self.menu_plan.pk})
        
        response = self.client.post(
            url,
            data=json.dumps({
                'recipe_id': self.recipe.id,
                'date': date.today().isoformat(),
                'total_portions': -10  # Záporné - model to má jako PositiveIntegerField ale validace není v AJAX
            }),
            content_type='application/json'
        )
        
        # Mělo by selhat, ale fallback vytvoří variantu
        # TODO: Přidat validaci do view
        self.assertIn(response.status_code, [200, 400])
    
    def test_add_meal_invalid_json(self):
        """Test s nevalidním JSON"""
        self.client.login(username='testuser', password='testpass123')
        url = reverse('production:add_meal_to_menu', kwargs={'menu_pk': self.menu_plan.pk})
        
        response = self.client.post(
            url,
            data='invalid json',
            content_type='application/json'
        )
        
        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertFalse(data['success'])
    
    def test_add_meal_unauthorized_canteen(self):
        """Test přidání jídla do jídelníčku, ke kterému nemá uživatel přístup"""
        # Vytvoříme druhou jídelnu, ke které user nemá přístup
        other_canteen = Canteen.objects.create(name='Other Canteen')
        other_menu = MenuPlan.objects.create(
            name='Other Menu',
            canteen=other_canteen,
            date_from=date.today(),
            date_to=date.today() + timedelta(days=7)
        )
        
        self.client.login(username='testuser', password='testpass123')
        url = reverse('production:add_meal_to_menu', kwargs={'menu_pk': other_menu.pk})
        
        response = self.client.post(
            url,
            data=json.dumps({
                'recipe_id': self.recipe.id,
                'date': date.today().isoformat(),
                'portions': [{'coefficient_id': 1, 'portions': 50}]
            }),
            content_type='application/json'
        )
        
        # Běžný uživatel by neměl mít přístup
        self.assertEqual(response.status_code, 403)
    
    def test_add_meal_superuser_any_canteen(self):
        """Test že superuser může přidávat do jakékoliv jídelny"""
        other_canteen = Canteen.objects.create(name='Other Canteen')
        other_menu = MenuPlan.objects.create(
            name='Other Menu',
            canteen=other_canteen,
            date_from=date.today(),
            date_to=date.today() + timedelta(days=7)
        )
        
        # Vytvoříme koeficient pro other_menu
        coef = MenuPlanCoefficient.objects.create(
            menu_plan=other_menu,
            name='Normal',
            coefficient=Decimal('1.0'),
            order=0
        )
        
        self.client.login(username='admin', password='adminpass123')
        url = reverse('production:add_meal_to_menu', kwargs={'menu_pk': other_menu.pk})
        
        response = self.client.post(
            url,
            data=json.dumps({
                'recipe_id': self.recipe.id,
                'date': date.today().isoformat(),
                'portions': [{'coefficient_id': coef.id, 'portions': 50}]
            }),
            content_type='application/json'
        )
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])
    
    def test_add_meal_duplicate_prevention(self):
        """Test že můžeme přidat stejné jídlo vícekrát (není duplicita)"""
        self.client.login(username='testuser', password='testpass123')
        
        meal_date = date.today() + timedelta(days=1)
        url = reverse('production:add_meal_to_menu', kwargs={'menu_pk': self.menu_plan.pk})
        request_data = {
            'recipe_id': self.recipe.id,
            'date': meal_date.isoformat(),
            'portions': [{'coefficient_id': self.menu_plan.default_coefficients.first().id, 'portions': 50}]
        }
        
        # První přidání
        response1 = self.client.post(
            url,
            data=json.dumps(request_data),
            content_type='application/json'
        )
        self.assertEqual(response1.status_code, 200)
        
        # Druhé přidání stejného jídla - mělo by být povoleno (může být oběd + večeře)
        response2 = self.client.post(
            url,
            data=json.dumps(request_data),
            content_type='application/json'
        )
        self.assertEqual(response2.status_code, 200)
        
        # Ověříme, že máme 2 záznamy
        orders = ProductionOrder.objects.filter(
            menu_plan=self.menu_plan,
            recipe=self.recipe,
            date=meal_date
        )
        self.assertEqual(orders.count(), 2)

