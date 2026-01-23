"""
Test pro ověření správného chování při mazání surovin.
"""
from django.test import TestCase, Client
from django.db.models import ProtectedError
from django.urls import reverse
from apps.core.models import Ingredient, Recipe, RecipeIngredient, Category
from apps.inventory.models import GoodsReceipt, GoodsReceiptItem, StockItem
from apps.canteens.models import Canteen, Warehouse
from apps.production.models import ProductionOrder, PickingList, MenuPlan
from decimal import Decimal
from datetime import date
from django.contrib.auth import get_user_model

User = get_user_model()


class IngredientDeletionTest(TestCase):
    """Testuje správné chování při mazání surovin"""
    
    def setUp(self):
        """Příprava testovacích dat"""
        # Vytvoříme testovacího uživatele
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass'
        )
        self.client = Client()
        self.client.login(username='testuser', password='testpass')
        
        # Vytvoříme testovací jídelnu a sklad
        self.canteen = Canteen.objects.create(name='Testovací jídelna')
        self.warehouse = Warehouse.objects.create(
            name='Hlavní sklad',
            canteen=self.canteen
        )
        
        # Vytvoříme testovací surovinu
        self.ingredient = Ingredient.objects.create(
            name='Testovací surovina',
            unit='kg',
            base_unit='kg',
            recipe_unit='g',
            conversion_factor=Decimal('1000')
        )
        
        # Vytvoříme kategorii a recept
        self.category = Category.objects.create(
            code='TEST',
            name='Testovací kategorie'
        )
        
    def test_can_delete_unused_ingredient(self):
        """Test, že se dá smazat nepoužitá surovina"""
        ingredient = Ingredient.objects.create(
            name='Nepoužitá surovina',
            unit='kg',
            base_unit='kg',
            recipe_unit='g',
            conversion_factor=Decimal('1000')
        )
        ingredient_id = ingredient.id
        
        # Smazání by mělo být úspěšné
        ingredient.delete()
        
        # Ověříme, že surovina byla skutečně smazána
        self.assertFalse(Ingredient.objects.filter(id=ingredient_id).exists())
    
    def test_can_delete_ingredient_with_cascade_relations(self):
        """Test, že se dá smazat surovina se vztahy CASCADE"""
        # Vytvoříme StockItem (CASCADE)
        StockItem.objects.create(
            ingredient=self.ingredient,
            warehouse=self.warehouse,
            quantity=Decimal('10'),
            price=Decimal('50')
        )
        
        # Smazání by mělo být úspěšné a smazat i StockItem
        self.ingredient.delete()
        
        # Ověříme, že StockItem byl smazán
        self.assertEqual(StockItem.objects.count(), 0)
    
    def test_cannot_delete_ingredient_with_goods_receipt_item(self):
        """Test, že se nedá smazat surovina s položkou příjmu zboží (PROTECT)"""
        # Vytvoříme příjem zboží
        goods_receipt = GoodsReceipt.objects.create(
            receipt_number='PR001',
            warehouse=self.warehouse,
            receipt_date=date.today(),
            supplier='Test dodavatel',
            created_by=self.user,
            status='DRAFT'
        )
        
        # Vytvoříme položku příjmu
        GoodsReceiptItem.objects.create(
            goods_receipt=goods_receipt,
            ingredient=self.ingredient,
            warehouse=self.warehouse,
            quantity=Decimal('10'),
            price_without_vat=Decimal('40'),
            vat_rate=Decimal('12')
        )
        
        # Smazání by mělo selhat s ProtectedError
        with self.assertRaises(ProtectedError):
            self.ingredient.delete()
    
    def test_cannot_delete_ingredient_with_picking_list(self):
        """Test, že se nedá smazat surovina s výdejkou (PROTECT)"""
        # Vytvoříme recept
        recipe = Recipe.objects.create(
            name='Testovací recept',
            category=self.category,
            base_portions=10
        )
        
        # Přidáme ingredienci do receptu
        RecipeIngredient.objects.create(
            recipe=recipe,
            ingredient=self.ingredient,
            quantity_per_portion=Decimal('100')
        )
        
        # Vytvoříme jídelníček
        menu_plan = MenuPlan.objects.create(
            name='Testovací jídelníček',
            canteen=self.canteen,
            date_from=date.today(),
            date_to=date.today()
        )
        
        # Vytvoříme výrobní příkaz
        production_order = ProductionOrder.objects.create(
            menu_plan=menu_plan,
            recipe=recipe,
            canteen=self.canteen,
            date=date.today()
        )
        
        # Vytvoříme položku výdejky
        PickingList.objects.create(
            production_order=production_order,
            ingredient=self.ingredient,
            quantity_planned=Decimal('1'),
            warehouse=self.warehouse
        )
        
        # Smazání by mělo selhat s ProtectedError
        with self.assertRaises(ProtectedError):
            self.ingredient.delete()
    
    def test_view_handles_protected_error(self):
        """Test, že custom view správně ošetřuje ProtectedError"""
        # Vytvoříme recept s ingrediencí
        recipe = Recipe.objects.create(
            name='Testovací recept',
            category=self.category,
            base_portions=10
        )
        RecipeIngredient.objects.create(
            recipe=recipe,
            ingredient=self.ingredient,
            quantity_per_portion=Decimal('100')
        )
        
        # Vytvoříme jídelníček a výrobní příkaz
        menu_plan = MenuPlan.objects.create(
            name='Testovací jídelníček',
            canteen=self.canteen,
            date_from=date.today(),
            date_to=date.today()
        )
        production_order = ProductionOrder.objects.create(
            menu_plan=menu_plan,
            recipe=recipe,
            canteen=self.canteen,
            date=date.today()
        )
        
        # Vytvoříme položku výdejky
        PickingList.objects.create(
            production_order=production_order,
            ingredient=self.ingredient,
            quantity_planned=Decimal('1'),
            warehouse=self.warehouse
        )
        
        # Pokusíme se smazat surovinu přes view
        url = reverse('core:ingredient_delete', kwargs={'pk': self.ingredient.pk})
        response = self.client.post(url, follow=True)
        
        # Měli bychom být přesměrováni na seznam surovin
        self.assertEqual(response.status_code, 200)
        
        # Surovina by měla stále existovat
        self.assertTrue(Ingredient.objects.filter(pk=self.ingredient.pk).exists())
        
        # Měla by být zobrazena chybová hláška
        messages = list(response.context['messages'])
        self.assertEqual(len(messages), 1)
        self.assertIn('Nelze smazat surovinu', str(messages[0]))
        self.assertIn('výdejky', str(messages[0]))
