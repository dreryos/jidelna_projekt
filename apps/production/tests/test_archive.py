from django.test import TestCase, Client
from django.contrib.auth.models import User
from decimal import Decimal
from datetime import date
import json

from apps.canteens.models import Canteen, Warehouse
from apps.core.models import Ingredient, Recipe, RecipeIngredient, UserProfile
from apps.inventory.models import StockItem
from apps.production.models import (
    ProductionOrder, PickingList, MenuPlan, 
    ProductionOrderPortionVariant, PickingListDocument
)


class PickingListArchiveTest(TestCase):
    def setUp(self):
        """Set up test data"""
        # Create user (profile is created automatically via signal)
        self.user = User.objects.create_user(
            username='testuser', 
            password='testpass123',
            email='test@test.com'
        )
        self.profile = self.user.profile
        
        # Create canteen and warehouse
        self.canteen = Canteen.objects.create(name='Test Canteen')
        self.profile.canteens.add(self.canteen)
        self.warehouse = Warehouse.objects.create(name='Main', canteen=self.canteen)
        
        # Create ingredient
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
            price=1.0
        )

        # Create recipe
        self.recipe = Recipe.objects.create(name='Chleba', base_portions=10)
        RecipeIngredient.objects.create(
            recipe=self.recipe, 
            ingredient=self.ingredient, 
            quantity_per_portion=Decimal('1.000')
        )
        
        # Create menu plan
        self.menu_plan = MenuPlan.objects.create(
            name='Test Menu',
            canteen=self.canteen,
            date_from=date(2025, 9, 10),
            date_to=date(2025, 9, 10)
        )
        
        # Create production order
        self.order = ProductionOrder.objects.create(
            recipe=self.recipe,
            canteen=self.canteen,
            menu_plan=self.menu_plan,
            date=date(2025, 9, 10)
        )
        
        # Add portion variant
        ProductionOrderPortionVariant.objects.create(
            production_order=self.order,
            portions=2,
            coefficient=Decimal('1.0')
        )
        
        # Generate picking list
        self.order.generate_picking_list()
        
        # Create picking list document
        self.document = PickingListDocument.objects.create(
            name='Test Document',
            canteen=self.canteen,
            date_from=date(2025, 9, 10),
            date_to=date(2025, 9, 10),
            created_by=self.user
        )
        
        # Associate picking list items with document
        for item in self.order.picking_list_items.all():
            item.document = self.document
            item.save()
        
        # Set up client (without CSRF enforcement for tests)
        self.client = Client(enforce_csrf_checks=False)
        self.client.login(username='testuser', password='testpass123')

    def test_can_be_archived_returns_false_when_not_all_completed(self):
        """Test that can_be_archived returns False when not all items are COMPLETED"""
        # Items are PENDING by default
        self.assertFalse(self.document.can_be_archived())
    
    def test_can_be_archived_returns_true_when_all_completed(self):
        """Test that can_be_archived returns True when all items are COMPLETED"""
        # Mark all items as COMPLETED
        for item in self.document.items.all():
            item.quantity_actual = item.quantity_planned
            item.status = PickingList.Status.COMPLETED
            item.save()
        
        self.assertTrue(self.document.can_be_archived())
    
    def test_archive_fails_when_not_all_completed(self):
        """Test that archiving fails when not all items are COMPLETED"""
        response = self.client.post(
            f'/production/vydejky/{self.document.id}/archive/',
            content_type='application/json',
            HTTP_X_REQUESTED_WITH='XMLHttpRequest'
        )
        
        # Debug: Print the response if not 400
        if response.status_code != 400:
            print(f"Response status: {response.status_code}")
            print(f"Response content: {response.content}")
        
        self.assertEqual(response.status_code, 400)
        data = json.loads(response.content)
        self.assertFalse(data['success'])
        self.assertIn('Všechny položky musí mít status', data['error'])
        
        # Document should not be archived
        self.document.refresh_from_db()
        self.assertFalse(self.document.archived)
    
    def test_archive_succeeds_when_all_completed(self):
        """Test that archiving succeeds when all items are COMPLETED"""
        # Mark all items as COMPLETED
        for item in self.document.items.all():
            item.quantity_actual = item.quantity_planned
            item.status = PickingList.Status.COMPLETED
            item.save()
        
        response = self.client.post(
            f'/production/vydejky/{self.document.id}/archive/',
            content_type='application/json',
            HTTP_X_REQUESTED_WITH='XMLHttpRequest'
        )
        
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        self.assertTrue(data['success'])
        
        # Document should be archived
        self.document.refresh_from_db()
        self.assertTrue(self.document.archived)
        self.assertIsNotNone(self.document.archived_at)
    
    def test_archive_requires_post_method(self):
        """Test that archive endpoint requires POST method"""
        response = self.client.get(
            f'/production/vydejky/{self.document.id}/archive/'
        )
        
        self.assertEqual(response.status_code, 405)
        data = json.loads(response.content)
        self.assertFalse(data['success'])
    
    def test_archive_requires_authentication(self):
        """Test that archive endpoint requires authentication"""
        # Logout
        self.client.logout()
        
        response = self.client.post(
            f'/production/vydejky/{self.document.id}/archive/',
            content_type='application/json'
        )
        
        # Should redirect to login (302) or return 403
        self.assertIn(response.status_code, [302, 403])
    
    def test_archive_checks_permissions(self):
        """Test that archive endpoint checks user permissions"""
        # Create another canteen
        other_canteen = Canteen.objects.create(name='Other Canteen')
        
        # Create document for other canteen
        other_document = PickingListDocument.objects.create(
            name='Other Document',
            canteen=other_canteen,
            date_from=date(2025, 9, 10),
            date_to=date(2025, 9, 10),
            created_by=self.user
        )
        
        # Try to archive document from canteen user doesn't have access to
        response = self.client.post(
            f'/production/vydejky/{other_document.id}/archive/',
            content_type='application/json',
            HTTP_X_REQUESTED_WITH='XMLHttpRequest'
        )
        
        self.assertEqual(response.status_code, 403)
        data = json.loads(response.content)
        self.assertFalse(data['success'])
