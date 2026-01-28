from django.test import TestCase
from django.utils import timezone
from decimal import Decimal
from datetime import datetime, timedelta
import time

from apps.canteens.models import Canteen, Warehouse
from apps.core.models import Ingredient, Recipe, RecipeIngredient, Category
from apps.inventory.models import StockItem, IngredientPriceHistory


class IngredientPriceHistoryTest(TestCase):
    """Tests for price history tracking functionality"""
    
    def setUp(self):
        """Set up test data"""
        self.canteen = Canteen.objects.create(name='Test Canteen')
        self.warehouse = Warehouse.objects.create(name='Main Warehouse', canteen=self.canteen)
        
        self.ingredient = Ingredient.objects.create(
            name='Test Ingredient',
            unit='kg',
            base_unit='kg',
            recipe_unit='g',
            conversion_factor=Decimal('1000')
        )
        
        self.category = Category.objects.create(code='HJ', name='Hlavní jídla')
        self.recipe = Recipe.objects.create(
            name='Test Recipe',
            category=self.category,
            base_portions=10
        )
        RecipeIngredient.objects.create(
            recipe=self.recipe,
            ingredient=self.ingredient,
            quantity_per_portion=Decimal('100')  # 100g per portion
        )
    
    def test_price_history_created_on_stock_item_creation(self):
        """Test that price history is automatically created when StockItem is created"""
        stock_item = StockItem.objects.create(
            ingredient=self.ingredient,
            warehouse=self.warehouse,
            quantity=Decimal('10.000'),
            price=Decimal('50.00')
        )
        
        # Check that a price history record was created
        history = IngredientPriceHistory.objects.filter(
            ingredient=self.ingredient,
            warehouse=self.warehouse
        )
        
        self.assertEqual(history.count(), 1)
        self.assertEqual(history.first().price, Decimal('50.00'))
    
    def test_price_history_created_on_price_change(self):
        """Test that new price history record is created when price changes"""
        stock_item = StockItem.objects.create(
            ingredient=self.ingredient,
            warehouse=self.warehouse,
            quantity=Decimal('10.000'),
            price=Decimal('50.00')
        )
        
        # Initial history count should be 1
        self.assertEqual(
            IngredientPriceHistory.objects.filter(
                ingredient=self.ingredient,
                warehouse=self.warehouse
            ).count(),
            1
        )
        
        # Change the price
        stock_item.price = Decimal('60.00')
        stock_item.save()
        
        # History count should now be 2
        history = IngredientPriceHistory.objects.filter(
            ingredient=self.ingredient,
            warehouse=self.warehouse
        ).order_by('-valid_from')
        
        self.assertEqual(history.count(), 2)
        self.assertEqual(history[0].price, Decimal('60.00'))  # Latest price
        self.assertEqual(history[1].price, Decimal('50.00'))  # Original price
    
    def test_price_history_not_created_on_quantity_change(self):
        """Test that price history is NOT created when only quantity changes"""
        stock_item = StockItem.objects.create(
            ingredient=self.ingredient,
            warehouse=self.warehouse,
            quantity=Decimal('10.000'),
            price=Decimal('50.00')
        )
        
        # Initial count
        initial_count = IngredientPriceHistory.objects.filter(
            ingredient=self.ingredient,
            warehouse=self.warehouse
        ).count()
        
        # Change quantity only
        stock_item.quantity = Decimal('15.000')
        stock_item.save()
        
        # Count should not change
        new_count = IngredientPriceHistory.objects.filter(
            ingredient=self.ingredient,
            warehouse=self.warehouse
        ).count()
        
        self.assertEqual(initial_count, new_count)
    
    def test_get_price_at_date_current(self):
        """Test retrieving current price"""
        stock_item = StockItem.objects.create(
            ingredient=self.ingredient,
            warehouse=self.warehouse,
            quantity=Decimal('10.000'),
            price=Decimal('50.00')
        )
        
        # Get current price
        current_price = IngredientPriceHistory.get_price_at_date(
            self.ingredient,
            self.warehouse,
            timezone.now()
        )
        
        self.assertEqual(current_price, Decimal('50.00'))
    
    def test_get_price_at_date_historical(self):
        """Test retrieving historical price"""
        # Create initial stock item with price 50
        stock_item = StockItem.objects.create(
            ingredient=self.ingredient,
            warehouse=self.warehouse,
            quantity=Decimal('10.000'),
            price=Decimal('50.00')
        )
        
        # Get the timestamp of the first price
        first_history = IngredientPriceHistory.objects.filter(
            ingredient=self.ingredient,
            warehouse=self.warehouse
        ).first()
        first_timestamp = first_history.valid_from
        
        # Wait a moment and change price to 60
        time.sleep(0.01)
        stock_item.price = Decimal('60.00')
        stock_item.save()
        
        # Wait and change price to 70
        time.sleep(0.01)
        stock_item.price = Decimal('70.00')
        stock_item.save()
        
        # Get current price
        current_price = IngredientPriceHistory.get_price_at_date(
            self.ingredient,
            self.warehouse,
            timezone.now()
        )
        self.assertEqual(current_price, Decimal('70.00'))
        
        # Get historical price (at the time of first change)
        second_history = IngredientPriceHistory.objects.filter(
            ingredient=self.ingredient,
            warehouse=self.warehouse
        ).order_by('-valid_from')[1]
        
        historical_price = IngredientPriceHistory.get_price_at_date(
            self.ingredient,
            self.warehouse,
            second_history.valid_from
        )
        self.assertEqual(historical_price, Decimal('60.00'))
        
        # Get oldest price
        oldest_price = IngredientPriceHistory.get_price_at_date(
            self.ingredient,
            self.warehouse,
            first_timestamp
        )
        self.assertEqual(oldest_price, Decimal('50.00'))
    
    def test_get_price_at_date_before_any_history(self):
        """Test getting price for date before any history exists"""
        stock_item = StockItem.objects.create(
            ingredient=self.ingredient,
            warehouse=self.warehouse,
            quantity=Decimal('10.000'),
            price=Decimal('50.00')
        )
        
        # Try to get price from long ago (before any history)
        old_date = timezone.now() - timedelta(days=365)
        price = IngredientPriceHistory.get_price_at_date(
            self.ingredient,
            self.warehouse,
            old_date
        )
        
        # Should return current price from StockItem as fallback
        self.assertEqual(price, Decimal('50.00'))
    
    def test_get_price_at_date_no_stock_item(self):
        """Test getting price when no StockItem exists"""
        # Don't create a stock item
        price = IngredientPriceHistory.get_price_at_date(
            self.ingredient,
            self.warehouse,
            timezone.now()
        )
        
        # Should return 0
        self.assertEqual(price, Decimal('0'))
    
    def test_recipe_calculate_portion_price_with_historical_date(self):
        """Test that recipe price calculation uses historical prices when date is provided"""
        # Create stock item with initial price
        stock_item = StockItem.objects.create(
            ingredient=self.ingredient,
            warehouse=self.warehouse,
            quantity=Decimal('10.000'),
            price=Decimal('50.00')  # 50 Kč/kg
        )
        
        # Get timestamp for historical reference
        first_history = IngredientPriceHistory.objects.filter(
            ingredient=self.ingredient,
            warehouse=self.warehouse
        ).first()
        historical_date = first_history.valid_from
        
        # Change price
        time.sleep(0.01)
        stock_item.price = Decimal('80.00')  # 80 Kč/kg
        stock_item.save()
        
        # Calculate current price (should use 80 Kč/kg)
        current_price_info = self.recipe.calculate_portion_price(
            self.canteen,
            portions=1
        )
        # 100g = 0.1 kg, so cost should be 0.1 * 80 = 8 Kč
        self.assertEqual(current_price_info['per_portion'], Decimal('8.00'))
        
        # Calculate historical price (should use 50 Kč/kg)
        historical_price_info = self.recipe.calculate_portion_price(
            self.canteen,
            portions=1,
            price_date=historical_date
        )
        # 100g = 0.1 kg, so cost should be 0.1 * 50 = 5 Kč
        self.assertEqual(historical_price_info['per_portion'], Decimal('5.00'))
    
    def test_recipe_calculate_portion_price_without_date(self):
        """Test that recipe price calculation uses current prices when no date is provided"""
        stock_item = StockItem.objects.create(
            ingredient=self.ingredient,
            warehouse=self.warehouse,
            quantity=Decimal('10.000'),
            price=Decimal('50.00')  # 50 Kč/kg
        )
        
        # Calculate price without date (should use current price)
        price_info = self.recipe.calculate_portion_price(
            self.canteen,
            portions=1
        )
        # 100g = 0.1 kg, so cost should be 0.1 * 50 = 5 Kč
        self.assertEqual(price_info['per_portion'], Decimal('5.00'))
        
        # Change price
        stock_item.price = Decimal('60.00')
        stock_item.save()
        
        # Calculate again (should use new current price)
        new_price_info = self.recipe.calculate_portion_price(
            self.canteen,
            portions=1
        )
        # 100g = 0.1 kg, so cost should be 0.1 * 60 = 6 Kč
        self.assertEqual(new_price_info['per_portion'], Decimal('6.00'))
    
    def test_multiple_warehouses_average_price(self):
        """Test that price calculation averages across multiple warehouses"""
        # Create second warehouse
        warehouse2 = Warehouse.objects.create(name='Second Warehouse', canteen=self.canteen)
        
        # Create stock items with different prices
        StockItem.objects.create(
            ingredient=self.ingredient,
            warehouse=self.warehouse,
            quantity=Decimal('10.000'),
            price=Decimal('50.00')
        )
        
        StockItem.objects.create(
            ingredient=self.ingredient,
            warehouse=warehouse2,
            quantity=Decimal('10.000'),
            price=Decimal('70.00')
        )
        
        # Calculate price (should average: (50 + 70) / 2 = 60)
        price_info = self.recipe.calculate_portion_price(
            self.canteen,
            portions=1
        )
        # 100g = 0.1 kg, so cost should be 0.1 * 60 = 6 Kč
        self.assertEqual(price_info['per_portion'], Decimal('6.00'))
    
    def test_price_history_ordering(self):
        """Test that price history is ordered by valid_from descending"""
        stock_item = StockItem.objects.create(
            ingredient=self.ingredient,
            warehouse=self.warehouse,
            quantity=Decimal('10.000'),
            price=Decimal('50.00')
        )
        
        # Make several price changes
        for price in [Decimal('60.00'), Decimal('70.00'), Decimal('80.00')]:
            time.sleep(0.01)
            stock_item.price = price
            stock_item.save()
        
        # Get all history records
        history = IngredientPriceHistory.objects.filter(
            ingredient=self.ingredient,
            warehouse=self.warehouse
        )
        
        # Should be ordered with newest first
        prices = [h.price for h in history]
        self.assertEqual(prices[0], Decimal('80.00'))  # Newest
        self.assertEqual(prices[-1], Decimal('50.00'))  # Oldest


class GoodsReceiptTest(TestCase):
    """Tests for goods receipt functionality"""
    
    def setUp(self):
        """Set up test data"""
        from django.contrib.auth.models import User
        from apps.inventory.models import GoodsReceipt, GoodsReceiptItem
        
        self.canteen = Canteen.objects.create(name='Test Canteen')
        self.warehouse = Warehouse.objects.create(name='Main Warehouse', canteen=self.canteen)
        
        self.ingredient1 = Ingredient.objects.create(
            name='Flour',
            unit='kg',
            base_unit='kg',
            recipe_unit='g',
            conversion_factor=Decimal('1000')
        )
        
        self.ingredient2 = Ingredient.objects.create(
            name='Sugar',
            unit='kg',
            base_unit='kg',
            recipe_unit='g',
            conversion_factor=Decimal('1000')
        )
        
        self.user = User.objects.create_user(username='testuser', password='testpass')
    
    def test_create_goods_receipt(self):
        """Test creating a goods receipt"""
        from apps.inventory.models import GoodsReceipt, GoodsReceiptItem
        
        goods_receipt = GoodsReceipt.objects.create(
            warehouse=self.warehouse,
            receipt_number='GR-001',
            receipt_date=timezone.now().date(),
            supplier='Test Supplier',
            created_by=self.user
        )
        
        self.assertEqual(goods_receipt.status, GoodsReceipt.Status.DRAFT)
        self.assertEqual(goods_receipt.receipt_number, 'GR-001')
        self.assertEqual(goods_receipt.warehouse, self.warehouse)
    
    def test_add_items_to_goods_receipt(self):
        """Test adding items to goods receipt"""
        from apps.inventory.models import GoodsReceipt, GoodsReceiptItem
        
        goods_receipt = GoodsReceipt.objects.create(
            warehouse=self.warehouse,
            receipt_number='GR-001',
            receipt_date=timezone.now().date(),
            created_by=self.user
        )
        
        item1 = GoodsReceiptItem.objects.create(
            goods_receipt=goods_receipt,
            ingredient=self.ingredient1,
            quantity=Decimal('10.000'),
            price=Decimal('25.00')
        )
        
        item2 = GoodsReceiptItem.objects.create(
            goods_receipt=goods_receipt,
            ingredient=self.ingredient2,
            quantity=Decimal('5.000'),
            price=Decimal('30.00')
        )
        
        self.assertEqual(goods_receipt.items.count(), 2)
        self.assertEqual(item1.total_price, Decimal('250.00'))  # 10 * 25
        self.assertEqual(item2.total_price, Decimal('150.00'))  # 5 * 30
    
    def test_goods_receipt_total_value(self):
        """Test calculating total value of goods receipt"""
        from apps.inventory.models import GoodsReceipt, GoodsReceiptItem
        
        goods_receipt = GoodsReceipt.objects.create(
            warehouse=self.warehouse,
            receipt_number='GR-001',
            receipt_date=timezone.now().date(),
            created_by=self.user
        )
        
        GoodsReceiptItem.objects.create(
            goods_receipt=goods_receipt,
            ingredient=self.ingredient1,
            quantity=Decimal('10.000'),
            price=Decimal('25.00')
        )
        
        GoodsReceiptItem.objects.create(
            goods_receipt=goods_receipt,
            ingredient=self.ingredient2,
            quantity=Decimal('5.000'),
            price=Decimal('30.00')
        )
        
        # Total should be 250 + 150 = 400
        self.assertEqual(goods_receipt.get_total_value(), Decimal('400.00'))
    
    def test_confirm_goods_receipt_updates_stock(self):
        """Test that confirming goods receipt updates stock quantities"""
        from apps.inventory.models import GoodsReceipt, GoodsReceiptItem
        
        # Create initial stock
        stock1 = StockItem.objects.create(
            ingredient=self.ingredient1,
            warehouse=self.warehouse,
            quantity=Decimal('5.000'),
            price=Decimal('20.00')
        )
        
        # Create goods receipt
        goods_receipt = GoodsReceipt.objects.create(
            warehouse=self.warehouse,
            receipt_number='GR-001',
            receipt_date=timezone.now().date(),
            created_by=self.user
        )
        
        GoodsReceiptItem.objects.create(
            goods_receipt=goods_receipt,
            ingredient=self.ingredient1,
            quantity=Decimal('10.000'),
            price=Decimal('25.00')
        )
        
        GoodsReceiptItem.objects.create(
            goods_receipt=goods_receipt,
            ingredient=self.ingredient2,
            quantity=Decimal('5.000'),
            price=Decimal('30.00')
        )
        
        # Confirm the receipt
        goods_receipt.confirm()
        
        # Check stock was updated
        stock1.refresh_from_db()
        self.assertEqual(stock1.quantity, Decimal('15.000'))  # 5 + 10
        self.assertEqual(stock1.price, Decimal('25.00'))  # Updated price
        
        # Check new stock item was created for ingredient2
        stock2 = StockItem.objects.get(ingredient=self.ingredient2, warehouse=self.warehouse)
        self.assertEqual(stock2.quantity, Decimal('5.000'))
        self.assertEqual(stock2.price, Decimal('30.00'))
        
        # Check status changed
        self.assertEqual(goods_receipt.status, GoodsReceipt.Status.CONFIRMED)
        self.assertIsNotNone(goods_receipt.confirmed_at)
    
    def test_confirm_goods_receipt_creates_price_history(self):
        """Test that confirming goods receipt creates price history records"""
        from apps.inventory.models import GoodsReceipt, GoodsReceiptItem
        
        goods_receipt = GoodsReceipt.objects.create(
            warehouse=self.warehouse,
            receipt_number='GR-001',
            receipt_date=timezone.now().date(),
            created_by=self.user
        )
        
        GoodsReceiptItem.objects.create(
            goods_receipt=goods_receipt,
            ingredient=self.ingredient1,
            quantity=Decimal('10.000'),
            price=Decimal('25.00')
        )
        
        # Confirm the receipt
        goods_receipt.confirm()
        
        # Check price history was created
        history = IngredientPriceHistory.objects.filter(
            ingredient=self.ingredient1,
            warehouse=self.warehouse
        )
        
        self.assertEqual(history.count(), 1)
        self.assertEqual(history.first().price, Decimal('25.00'))
    
    def test_cannot_confirm_already_confirmed_receipt(self):
        """Test that already confirmed receipt cannot be confirmed again"""
        from apps.inventory.models import GoodsReceipt, GoodsReceiptItem
        
        goods_receipt = GoodsReceipt.objects.create(
            warehouse=self.warehouse,
            receipt_number='GR-001',
            receipt_date=timezone.now().date(),
            created_by=self.user
        )
        
        GoodsReceiptItem.objects.create(
            goods_receipt=goods_receipt,
            ingredient=self.ingredient1,
            quantity=Decimal('10.000'),
            price=Decimal('25.00')
        )
        
        # Confirm once
        goods_receipt.confirm()
        
        # Try to confirm again
        with self.assertRaises(ValueError):
            goods_receipt.confirm()

    def test_goods_receipt_item_vat_rate_form_preserves_and_saves(self):
        """Test that editing a GoodsReceiptItem via its form preserves and saves vat_rate"""
        from apps.inventory.models import GoodsReceipt, GoodsReceiptItem
        from apps.inventory.forms import GoodsReceiptItemForm

        goods_receipt = GoodsReceipt.objects.create(
            warehouse=self.warehouse,
            receipt_number='GR-002',
            receipt_date=timezone.now().date(),
            created_by=self.user
        )

        item = GoodsReceiptItem.objects.create(
            goods_receipt=goods_receipt,
            ingredient=self.ingredient1,
            warehouse=self.warehouse,
            quantity=Decimal('2.000'),
            price=Decimal('20.00'),
            vat_rate=Decimal('21')
        )

        # Initialize form for existing instance
        form = GoodsReceiptItemForm(instance=item)
        # The form initial should reflect instance value (as string in select)
        self.assertTrue(str(Decimal('21')) in str(form.initial.get('vat_rate') or form['vat_rate']))

        # Now submit an edit changing the vat_rate to 12
        data = {
            'ingredient': str(item.ingredient.id),
            'warehouse': str(self.warehouse.id),
            'quantity': '2.000',
            'price': '20.00',
            'vat_rate': '12',
            'notes': ''
        }
        form = GoodsReceiptItemForm(data, instance=item)
        self.assertTrue(form.is_valid(), msg=form.errors)
        saved = form.save()
        saved.refresh_from_db()
        self.assertEqual(saved.vat_rate, Decimal('12'))

    def test_goods_receipt_item_vat_rate_saved_in_formset(self):
        """Test that changing vat_rate via formset persists the change"""
        from apps.inventory.models import GoodsReceipt, GoodsReceiptItem
        from apps.inventory.forms import GoodsReceiptItemFormSet

        goods_receipt = GoodsReceipt.objects.create(
            warehouse=self.warehouse,
            receipt_number='GR-003',
            receipt_date=timezone.now().date(),
            created_by=self.user
        )

        item = GoodsReceiptItem.objects.create(
            goods_receipt=goods_receipt,
            ingredient=self.ingredient1,
            warehouse=self.warehouse,
            quantity=Decimal('1.000'),
            price=Decimal('10.00'),
            vat_rate=Decimal('21')
        )

        # Build formset POST-like data to change vat_rate to 0
        data = {
            'items-TOTAL_FORMS': '1',
            'items-INITIAL_FORMS': '1',
            'items-MIN_NUM_FORMS': '1',
            'items-MAX_NUM_FORMS': '100',
            'items-0-id': str(item.id),
            'items-0-ingredient': str(item.ingredient.id),
            'items-0-warehouse': str(self.warehouse.id),
            'items-0-quantity': '1.000',
            'items-0-price_without_vat': '',
            'items-0-price': '10.00',
            'items-0-vat_rate': '0',
            'items-0-notes': ''
        }

        formset = GoodsReceiptItemFormSet(data, instance=goods_receipt)
        self.assertTrue(formset.is_valid(), msg=formset.errors)
        instances = formset.save()
        item.refresh_from_db()
        self.assertEqual(item.vat_rate, Decimal('0'))

    def test_admin_stockitem_change_persists_vat_rate(self):
        """Simulate admin change of StockItem and ensure vat_rate persists"""
        from django.contrib.auth.models import User
        from django.test import Client
        from apps.inventory.models import StockItem

        # create superuser
        admin_user = User.objects.create_superuser('admin', 'admin@example.com', 'password')
        client = Client()
        client.login(username='admin', password='password')

        # Create stock item
        stock_item = StockItem.objects.create(
            ingredient=self.ingredient1,
            warehouse=self.warehouse,
            quantity=Decimal('5.000'),
            price=Decimal('50.00'),
            vat_rate=Decimal('12')
        )

        # GET the admin change form
        change_url = f"/admin/inventory/stockitem/{stock_item.pk}/change/"
        resp = client.get(change_url)
        self.assertEqual(resp.status_code, 200)

        # Prepare POST data: change vat_rate to 0 and clear price_without_vat
        post_data = {
            'ingredient': str(stock_item.ingredient.id),
            'warehouse': str(stock_item.warehouse.id),
            'quantity': '5.000',
            'price': '50.00',
            'vat_rate': '0',
            'price_without_vat': '',
        }

        # Include admin save param
        post_data['_save'] = 'Save'
        resp = client.post(change_url, post_data, follow=True)
        self.assertEqual(resp.status_code, 200)

        stock_item.refresh_from_db()
        self.assertEqual(stock_item.vat_rate, Decimal('0'))
    
    def test_price_change_tracking_through_goods_receipt(self):
        """Test that price changes are tracked through goods receipts"""
        from apps.inventory.models import GoodsReceipt, GoodsReceiptItem
        
        # First receipt with price 20
        receipt1 = GoodsReceipt.objects.create(
            warehouse=self.warehouse,
            receipt_number='GR-001',
            receipt_date=timezone.now().date(),
            created_by=self.user
        )
        
        GoodsReceiptItem.objects.create(
            goods_receipt=receipt1,
            ingredient=self.ingredient1,
            quantity=Decimal('10.000'),
            price=Decimal('20.00')
        )
        
        receipt1.confirm()
        
        # Second receipt with price 25
        time.sleep(0.01)
        receipt2 = GoodsReceipt.objects.create(
            warehouse=self.warehouse,
            receipt_number='GR-002',
            receipt_date=timezone.now().date(),
            created_by=self.user
        )
        
        GoodsReceiptItem.objects.create(
            goods_receipt=receipt2,
            ingredient=self.ingredient1,
            quantity=Decimal('5.000'),
            price=Decimal('25.00')
        )
        
        receipt2.confirm()
        
        # Check price history
        history = IngredientPriceHistory.objects.filter(
            ingredient=self.ingredient1,
            warehouse=self.warehouse
        ).order_by('-valid_from')
        
        self.assertEqual(history.count(), 2)
        self.assertEqual(history[0].price, Decimal('25.00'))  # Latest
        self.assertEqual(history[1].price, Decimal('20.00'))  # Oldest
        
        # Check stock quantity is cumulative
        stock = StockItem.objects.get(ingredient=self.ingredient1, warehouse=self.warehouse)
        self.assertEqual(stock.quantity, Decimal('15.000'))  # 10 + 5
        self.assertEqual(stock.price, Decimal('25.00'))  # Latest price
