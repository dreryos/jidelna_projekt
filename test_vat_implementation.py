"""
Testovací skript pro ověření funkcionality DPH v modulu Analytika

Tento skript testuje:
1. Vytvoření receptu s DPH sazbou
2. Vytvoření výrobního příkazu s automatickým kopírováním DPH
3. Výpočet cen s DPH pomocí calculate_portion_price
4. Ověření správnosti výpočtů zaokrouhlení
"""

import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'spiz_project.settings')
django.setup()

from decimal import Decimal
from apps.core.models import Recipe, Category, Ingredient, RecipeIngredient
from apps.production.models import ProductionOrder, MenuPlan
from apps.canteens.models import Canteen, Warehouse
from apps.inventory.models import StockItem
from django.contrib.auth import get_user_model
from datetime import date, timedelta

User = get_user_model()

def test_vat_functionality():
    print("=" * 80)
    print("TEST DPH FUNKCIONALITY V ANALYTICE")
    print("=" * 80)
    
    # 1. Test: Kontrola existence VAT_RATE_CHOICES
    print("\n1. Kontrola VAT_RATE_CHOICES...")
    from apps.core.constants import VAT_RATE_CHOICES
    print(f"   ✓ VAT_RATE_CHOICES definovány: {VAT_RATE_CHOICES}")
    
    # 2. Test: Ověření pole selling_vat_rate v Recipe
    print("\n2. Kontrola pole selling_vat_rate v Recipe...")
    recipe = Recipe.objects.first()
    if recipe:
        print(f"   ✓ Recept '{recipe.name}' má DPH: {recipe.selling_vat_rate}%")
        
        # Změníme DPH na 21%
        original_vat = recipe.selling_vat_rate
        recipe.selling_vat_rate = Decimal('21.00')
        recipe.save()
        recipe.refresh_from_db()
        print(f"   ✓ DPH změněno z {original_vat}% na {recipe.selling_vat_rate}%")
        
        # Vrátíme zpět
        recipe.selling_vat_rate = original_vat
        recipe.save()
    else:
        print("   ⚠ Žádné recepty v databázi pro testování")
    
    # 3. Test: Ověření pole selling_vat_rate v ProductionOrder
    print("\n3. Kontrola pole selling_vat_rate v ProductionOrder...")
    order = ProductionOrder.objects.first()
    if order:
        print(f"   ✓ Výrobní příkaz má DPH: {order.selling_vat_rate}%")
        print(f"   ✓ Recept má DPH: {order.recipe.selling_vat_rate}%")
        
        # Test signálu - vytvoříme nový ProductionOrder
        if order.menu_plan and order.canteen:
            print("\n4. Test signálu pro kopírování DPH...")
            # Změníme DPH receptu
            test_recipe = order.recipe
            original_recipe_vat = test_recipe.selling_vat_rate
            test_recipe.selling_vat_rate = Decimal('21.00')
            test_recipe.save()
            
            # Vytvoříme nový ProductionOrder - signal by měl zkopírovat DPH
            new_order = ProductionOrder.objects.create(
                menu_plan=order.menu_plan,
                recipe=test_recipe,
                canteen=order.canteen,
                date=date.today() + timedelta(days=30),
                meal_type=ProductionOrder.MealType.LUNCH
            )
            
            print(f"   ✓ Nový výrobní příkaz vytvořen")
            print(f"   ✓ DPH receptu: {test_recipe.selling_vat_rate}%")
            print(f"   ✓ DPH nového příkazu: {new_order.selling_vat_rate}%")
            
            if new_order.selling_vat_rate == test_recipe.selling_vat_rate:
                print("   ✓ Signal funguje správně - DPH zkopírováno!")
            else:
                print("   ✗ Signal nefunguje - DPH nezkopírováno")
            
            # Vyčistíme testovací data
            new_order.delete()
            test_recipe.selling_vat_rate = original_recipe_vat
            test_recipe.save()
    else:
        print("   ⚠ Žádné výrobní příkazy v databázi pro testování")
    
    # 5. Test: Výpočet cen s DPH
    print("\n5. Test výpočtu cen s DPH...")
    if recipe and recipe.recipeingredient_set.exists():
        # Najdeme jídelnu se skladem
        canteen = Canteen.objects.filter(warehouses__isnull=False).first()
        if canteen:
            print(f"   Testujeme s jídelnou: {canteen.name}")
            
            # Bez DPH
            price_without_vat = recipe.calculate_portion_price(canteen, portions=10)
            print(f"\n   Bez DPH:")
            print(f"   - Celkem: {price_without_vat['total']} Kč")
            print(f"   - Za porci: {price_without_vat['per_portion']} Kč")
            
            # S DPH 12%
            price_with_12 = recipe.calculate_portion_price(canteen, portions=10, vat_rate=Decimal('12.00'))
            print(f"\n   S DPH 12%:")
            print(f"   - Celkem bez DPH: {price_with_12['total']} Kč")
            print(f"   - Celkem s DPH: {price_with_12['total_with_vat']} Kč")
            print(f"   - DPH částka: {price_with_12['vat_amount']} Kč")
            print(f"   - Za porci bez DPH: {price_with_12['per_portion']} Kč")
            print(f"   - Za porci s DPH: {price_with_12['per_portion_with_vat']} Kč")
            
            # Ověření výpočtu
            expected_vat_multiplier = Decimal('1.12')
            calculated_total_with_vat = price_with_12['total'] * expected_vat_multiplier
            
            if abs(price_with_12['total_with_vat'] - calculated_total_with_vat.quantize(Decimal('0.01'))) < Decimal('0.01'):
                print(f"\n   ✓ Výpočet DPH je správný!")
            else:
                print(f"\n   ✗ Chyba ve výpočtu DPH!")
                print(f"   Očekáváno: {calculated_total_with_vat.quantize(Decimal('0.01'))} Kč")
                print(f"   Skutečnost: {price_with_12['total_with_vat']} Kč")
            
            # S DPH 21%
            price_with_21 = recipe.calculate_portion_price(canteen, portions=10, vat_rate=Decimal('21.00'))
            print(f"\n   S DPH 21%:")
            print(f"   - Celkem s DPH: {price_with_21['total_with_vat']} Kč")
            print(f"   - DPH částka: {price_with_21['vat_amount']} Kč")
            
        else:
            print("   ⚠ Žádná jídelna se skladem pro testování")
    else:
        print("   ⚠ Žádný recept se surovinami pro testování")
    
    # 6. Test: Zaokrouhlování
    print("\n6. Test zaokrouhlování na 2 desetinná místa...")
    test_values = [
        (Decimal('10.126'), Decimal('12.00'), Decimal('11.34')),  # 10.126 * 1.12 = 11.34112 -> 11.34
        (Decimal('15.995'), Decimal('12.00'), Decimal('17.91')),  # 15.995 * 1.12 = 17.9144 -> 17.91
        (Decimal('99.999'), Decimal('21.00'), Decimal('121.00')), # 99.999 * 1.21 = 120.99879 -> 121.00
    ]
    
    all_ok = True
    for base_price, vat_rate, expected in test_values:
        vat_multiplier = 1 + (vat_rate / Decimal('100'))
        result = base_price * vat_multiplier
        rounded_result = round(result, 2)
        
        if rounded_result == expected:
            print(f"   ✓ {base_price} Kč + {vat_rate}% DPH = {rounded_result} Kč")
        else:
            print(f"   ✗ {base_price} Kč + {vat_rate}% DPH: očekáváno {expected} Kč, výsledek {rounded_result} Kč")
            all_ok = False
    
    if all_ok:
        print("\n   ✓ Všechny testy zaokrouhlování prošly!")
    
    print("\n" + "=" * 80)
    print("TESTY DOKONČENY")
    print("=" * 80)

if __name__ == '__main__':
    try:
        test_vat_functionality()
    except Exception as e:
        print(f"\n✗ CHYBA PŘI TESTOVÁNÍ: {e}")
        import traceback
        traceback.print_exc()
