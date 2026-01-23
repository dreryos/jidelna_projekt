"""
Testy pro soft delete funkcionalitu surovin.
"""
from decimal import Decimal
from django.test import TestCase
from django.contrib.auth.models import User
from django.utils import timezone
from apps.core.models import Ingredient
from apps.canteens.models import Canteen, Warehouse
from apps.inventory.models import (
    StockItem, GoodsReceipt, GoodsReceiptItem,
    InventoryVerification, InventoryVerificationItem, StockTransfer, StockTransferItem
)
from apps.production.models import PickingList, MenuPlan


class IngredientSoftDeleteTestCase(TestCase):
    """Testy pro deaktivaci surovin pomocí soft delete."""
    
    def setUp(self):
        """Příprava testovacích dat."""
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass123'
        )
        
        self.ingredient = Ingredient.objects.create(
            name='Test surovina',
            unit='kg',
            base_unit='kg',
            recipe_unit='g',
            conversion_factor=Decimal('1000')
        )
        
        # Vytvoření jídelny a skladu
        self.canteen = Canteen.objects.create(
            name='Testovací jídelna',
            address='Test 123'
        )
        
        self.warehouse = Warehouse.objects.create(
            name='Testovací sklad',
            canteen=self.canteen
        )
    
    def test_ingredient_starts_active(self):
        """Test, že nově vytvořená surovina je aktivní."""
        self.assertTrue(self.ingredient.is_active)
        self.assertIsNone(self.ingredient.deactivated_at)
        self.assertIsNone(self.ingredient.deactivated_by)
    
    def test_can_deactivate_unused_ingredient(self):
        """Test, že nepoužitou surovinu lze deaktivovat."""
        can_deactivate, reason = self.ingredient.can_be_deactivated()
        self.assertTrue(can_deactivate)
        self.ingredient.deactivate(self.user)
        
        self.assertFalse(self.ingredient.is_active)
        self.assertIsNotNone(self.ingredient.deactivated_at)
        self.assertEqual(self.ingredient.deactivated_by, self.user)
    
    def test_cannot_deactivate_with_stock(self):
        """Test, že surovinu se skladovými zásobami nelze deaktivovat."""
        StockItem.objects.create(
            ingredient=self.ingredient,
            warehouse=self.warehouse,
            quantity=Decimal('10.5'),
            price=Decimal('100.0')
        )
        
        can_deactivate, reason = self.ingredient.can_be_deactivated()
        self.assertFalse(can_deactivate)
        self.assertIn('na skladě', reason)
    
    def test_cannot_deactivate_with_draft_receipt(self):
        """Test, že surovinu v rozpracovaném příjmu nelze deaktivovat."""
        receipt = GoodsReceipt.objects.create(
            warehouse=self.warehouse,
            receipt_number='TEST-001',
            receipt_date=timezone.now().date(),
            status='DRAFT',
            created_by=self.user
        )
        
        GoodsReceiptItem.objects.create(
            goods_receipt=receipt,
            ingredient=self.ingredient,
            warehouse=self.warehouse,
            quantity=Decimal('5.0'),
            price_without_vat=Decimal('100.0'),
            vat_rate=Decimal('12')
        )
        
        can_deactivate, reason = self.ingredient.can_be_deactivated()
        self.assertFalse(can_deactivate)
        self.assertIn('rozpracovaných příjmech', reason)
    
    def test_cannot_deactivate_with_in_progress_inventory(self):
        """Test, že surovinu v probíhající inventuře nelze deaktivovat."""
        inventory = InventoryVerification.objects.create(
            warehouse=self.warehouse,
            created_by=self.user,
            status=InventoryVerification.Status.IN_PROGRESS
        )
        
        InventoryVerificationItem.objects.create(
            verification=inventory,
            ingredient=self.ingredient,
            system_quantity=Decimal('10.0')
        )
        
        can_deactivate, reason = self.ingredient.can_be_deactivated()
        self.assertFalse(can_deactivate)
        self.assertIn('probíhajících inventur', reason)
    
    def test_cannot_deactivate_with_active_transfer(self):
        """Test, že surovinu v aktivní převodce nelze deaktivovat."""
        warehouse_to = Warehouse.objects.create(
            name='Druhý sklad',
            canteen=self.canteen
        )
        
        transfer = StockTransfer.objects.create(
            warehouse_from=self.warehouse,
            warehouse_to=warehouse_to,
            transfer_date=timezone.now().date(),
            created_by=self.user,
            status='PENDING'
        )
        
        StockTransferItem.objects.create(
            stock_transfer=transfer,
            ingredient=self.ingredient,
            quantity=Decimal('5.0'),
            unit_price_with_vat=Decimal('150.0')
        )
        
        can_deactivate, reason = self.ingredient.can_be_deactivated()
        self.assertFalse(can_deactivate)
        self.assertIn('převodek', reason)
    
    def test_can_activate_deactivated_ingredient(self):
        """Test, že deaktivovanou surovinu lze opět aktivovat."""
        self.ingredient.deactivate(self.user)
        self.assertFalse(self.ingredient.is_active)
        
        self.ingredient.activate()
        self.assertTrue(self.ingredient.is_active)
        self.assertIsNone(self.ingredient.deactivated_at)
        self.assertIsNone(self.ingredient.deactivated_by)
    
    def test_ingredient_str_shows_inactive_status(self):
        """Test, že __str__ zobrazuje [NEAKTIVNÍ] u deaktivovaných surovin."""
        original_str = str(self.ingredient)
        self.assertEqual(original_str, 'Test surovina (kg)')
        
        self.ingredient.deactivate(self.user)
        inactive_str = str(self.ingredient)
        self.assertEqual(inactive_str, 'Test surovina (kg) [NEAKTIVNÍ]')
    
    def test_deactivate_raises_error_if_not_allowed(self):
        """Test, že deactivate() vyvolá ValueError pokud nelze deaktivovat."""
        StockItem.objects.create(
            ingredient=self.ingredient,
            warehouse=self.warehouse,
            quantity=Decimal('10.5'),
            price=Decimal('100.0')
        )
        
        with self.assertRaises(ValueError) as context:
            self.ingredient.deactivate(self.user)
        
        self.assertIn('Surovinu nelze deaktivovat', str(context.exception))
