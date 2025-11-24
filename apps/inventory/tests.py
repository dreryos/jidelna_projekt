from django.test import TestCase
from django.utils import timezone
from decimal import Decimal
from datetime import datetime, timedelta

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
        import time
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
        import time
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
        import time
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
