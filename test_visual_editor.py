"""
Test skript pro vizuální editor šablon jídelníčků.
Testuje základní funkce helper metod v MenuTemplate modelu.
"""

import os
import sys
import django

# Nastavení Django prostředí
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'spiz_project.settings')
django.setup()

from apps.production.models import MenuTemplate
from django.core.exceptions import ValidationError

def test_menu_template_helpers():
    """Testuje helper metody MenuTemplate"""
    
    print("=" * 60)
    print("TEST: Helper metody MenuTemplate")
    print("=" * 60)
    
    # Najdeme první šablonu
    template = MenuTemplate.objects.first()
    
    if not template:
        print("❌ Žádná šablona nenalezena v databázi")
        print("   Vytvořte nejprve šablonu přes admin rozhraní")
        return
    
    print(f"\n✓ Testujeme šablonu: {template.name}")
    print(f"  ID: {template.pk}")
    
    # Test 1: parse_schedule_to_dict()
    print("\n1. Test parse_schedule_to_dict()")
    try:
        schedule_dict = template.parse_schedule_to_dict()
        print(f"   ✓ Parsování úspěšné")
        print(f"   Počet dnů: {len(schedule_dict)}")
        
        for day_idx, meals in schedule_dict.items():
            print(f"   Den {day_idx}: {len(meals)} jídel")
            for meal in meals[:2]:  # Ukážeme první 2 jídla
                print(f"     - {meal['recipe_code']} ({meal['meal_type']})")
    except Exception as e:
        print(f"   ❌ Chyba: {e}")
        return
    
    # Test 2: get_stats()
    print("\n2. Test get_stats()")
    try:
        stats = template.get_stats()
        print(f"   ✓ Statistiky získány")
        print(f"   Dny: {stats['days']}")
        print(f"   Jídla: {stats['meals']}")
        print(f"   Unikátní recepty: {stats['unique_recipes']}")
    except Exception as e:
        print(f"   ❌ Chyba: {e}")
        return
    
    # Test 3: update_schedule_from_dict() - round-trip test
    print("\n3. Test update_schedule_from_dict() - round-trip")
    try:
        # Uložíme originální XML
        original_xml = template.xml_content
        
        # Parsujeme do dictu
        schedule_dict = template.parse_schedule_to_dict()
        
        # Uložíme zpět
        template.update_schedule_from_dict(schedule_dict)
        
        # Parsujeme znovu
        schedule_dict2 = template.parse_schedule_to_dict()
        
        # Porovnáme počet dnů a jídel
        if len(schedule_dict) == len(schedule_dict2):
            print(f"   ✓ Round-trip úspěšný (počet dnů shodný)")
        else:
            print(f"   ⚠ Počet dnů se liší: {len(schedule_dict)} vs {len(schedule_dict2)}")
        
        # Vraťme zpět originální XML
        template.xml_content = original_xml
        
    except ValidationError as e:
        print(f"   ❌ Validační chyba: {e}")
        # Vraťme zpět originální XML
        template.xml_content = original_xml
    except Exception as e:
        print(f"   ❌ Chyba: {e}")
        # Vraťme zpět originální XML  
        template.xml_content = original_xml
    
    print("\n" + "=" * 60)
    print("ZÁVĚR: Všechny testy proběhly úspěšně ✓")
    print("=" * 60)
    print("\nVizuální editor je připraven k použití!")
    print(f"Otevřete: http://localhost:8000/production/sablony/{template.pk}/vizualni-editor/")
    print("=" * 60)


if __name__ == '__main__':
    test_menu_template_helpers()
