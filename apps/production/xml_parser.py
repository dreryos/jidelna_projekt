"""
XML parser pro šablony jídelníčků.

Parsuje XML soubory ve formátu MenuImportDescription a validuje jejich strukturu.
"""

import xml.etree.ElementTree as ET
from django.core.exceptions import ValidationError
from decimal import Decimal, InvalidOperation
from typing import Dict, List, Any


# Mapování XML type atributů na MealType choices
MEAL_TYPE_MAPPING = {
    'snidane': 'BREAKFAST',
    'svacina_dopoledni': 'SNACK_MORNING',
    'polevka': 'LUNCH',
    'obed': 'LUNCH',
    'svacina_odpoledni': 'SNACK_AFTERNOON',
    'vecere': 'DINNER',
}


def parse_menu_template_xml(xml_content: str) -> Dict[str, Any]:
    """
    Parsuje XML šablonu jídelníčku a vrací strukturovaná data.
    
    Args:
        xml_content: XML string s definicí šablony
        
    Returns:
        Dictionary s klíči:
        - recipes: List receptů k vytvoření
        - schedule: List dnů s jídly
        - warnings: List varování pro uživatele
        
    Raises:
        ValidationError: Pokud je XML nevalidní nebo chybí povinné sekce
    """
    warnings = []
    
    # Parsování XML
    try:
        root = ET.fromstring(xml_content)
    except ET.ParseError as e:
        raise ValidationError(
            f"Chyba při čtení XML souboru: {str(e)}. "
            "Zkontrolujte prosím, že soubor obsahuje validní XML."
        )
    
    # Validace root elementu
    if root.tag != 'MenuImportDescription':
        raise ValidationError(
            f"Neplatný kořenový element '{root.tag}'. "
            "Očekáván element 'MenuImportDescription'."
        )
    
    # Validace existence povinných sekcí
    recipes_section = root.find('Recipes')
    schedule_section = root.find('MenuSchedule')
    
    if recipes_section is None:
        raise ValidationError(
            "V XML chybí sekce '<Recipes>'. "
            "Šablona musí obsahovat definice receptů."
        )
    
    if schedule_section is None:
        raise ValidationError(
            "V XML chybí sekce '<MenuSchedule>'. "
            "Šablona musí obsahovat harmonogram jídel."
        )
    
    # Parsování receptů
    parsed_recipes = []
    for recipe_elem in recipes_section.findall('Recipe'):
        try:
            recipe_data = _parse_recipe(recipe_elem)
            parsed_recipes.append(recipe_data)
        except (ValueError, KeyError) as e:
            code = recipe_elem.get('code', 'NEZNÁMÝ')
            warnings.append(f"Chyba v receptu {code}: {str(e)}")
    
    # Parsování harmonogramu
    parsed_schedule = []
    for day_elem in schedule_section.findall('Day'):
        try:
            day_data = _parse_day(day_elem, warnings)
            parsed_schedule.append(day_data)
        except (ValueError, KeyError) as e:
            day_name = day_elem.get('name', 'NEZNÁMÝ')
            warnings.append(f"Chyba v dni {day_name}: {str(e)}")
    
    return {
        'recipes': parsed_recipes,
        'schedule': parsed_schedule,
        'warnings': warnings
    }


def _parse_recipe(recipe_elem: ET.Element) -> Dict[str, Any]:
    """Parsuje jeden <Recipe> element."""
    code = recipe_elem.get('code')
    name = recipe_elem.get('name')
    category = recipe_elem.get('category')
    base_portions = recipe_elem.get('basePortions', '10')
    
    if not code:
        raise ValueError("Recept nemá povinný atribut 'code'")
    if not name:
        raise ValueError("Recept nemá povinný atribut 'name'")
    if not category:
        raise ValueError("Recept nemá povinný atribut 'category'")
    
    try:
        base_portions = int(base_portions)
    except ValueError:
        raise ValueError(f"Neplatná hodnota basePortions: {base_portions}")
    
    # Parsování ingrediencí
    ingredients = []
    ingredients_elem = recipe_elem.find('Ingredients')
    if ingredients_elem is not None:
        for ing_elem in ingredients_elem.findall('Ingredient'):
            ingredient_data = _parse_ingredient(ing_elem, base_portions)
            ingredients.append(ingredient_data)
    
    return {
        'code': code,
        'name': name,
        'category': category,
        'base_portions': base_portions,
        'ingredients': ingredients
    }


def _parse_ingredient(ing_elem: ET.Element, base_portions: int) -> Dict[str, Any]:
    """Parsuje jeden <Ingredient> element."""
    name = ing_elem.get('name')
    quantity_str = ing_elem.get('quantity', '0')
    unit = ing_elem.get('unit', 'kg')
    
    if not name:
        raise ValueError("Ingredience nemá povinný atribut 'name'")
    
    try:
        quantity = Decimal(quantity_str)
    except (ValueError, InvalidOperation):
        raise ValueError(f"Neplatná hodnota quantity: {quantity_str}")
    
    # Převod na gramy (množství na 1 porci v gramech/mililitrech)
    # XML má množství pro basePortions v kg/l, potřebujeme gramy na 1 porci
    quantity_in_grams = _convert_to_grams(quantity, unit)
    quantity_per_portion = quantity_in_grams / base_portions
    
    return {
        'name': name,
        'quantity': quantity,
        'unit': unit,
        'quantity_per_portion': quantity_per_portion
    }


def _convert_to_grams(quantity: Decimal, unit: str) -> Decimal:
    """Převede množství na gramy/mililitry."""
    unit = unit.lower()
    
    if unit in ['kg']:
        return quantity * 1000
    elif unit in ['l']:
        return quantity * 1000  # 1l = 1000ml
    elif unit in ['g', 'ml']:
        return quantity
    elif unit in ['ks']:
        return quantity  # Kusové suroviny necháme jako jsou
    else:
        # Neznámá jednotka - použijeme jako gramy
        return quantity


def _parse_day(day_elem: ET.Element, warnings: List[str]) -> Dict[str, Any]:
    """Parsuje jeden <Day> element."""
    day_name = day_elem.get('name', '')
    date_offset_str = day_elem.get('dateOffset', '0')
    
    try:
        date_offset = int(date_offset_str)
    except ValueError:
        raise ValueError(f"Neplatná hodnota dateOffset: {date_offset_str}")
    
    # Parsování jídel
    meals = []
    for meal_elem in day_elem.findall('Meal'):
        meal_data = _parse_meal(meal_elem, day_name, warnings)
        meals.append(meal_data)
    
    return {
        'name': day_name,
        'date_offset': date_offset,
        'meals': meals
    }


def _parse_meal(meal_elem: ET.Element, day_name: str, warnings: List[str]) -> Dict[str, Any]:
    """Parsuje jeden <Meal> element."""
    recipe_code = meal_elem.get('recipeCode')
    meal_type_raw = meal_elem.get('type', '').lower()
    note = meal_elem.get('note', '')
    portion_count_str = meal_elem.get('portionCount')
    
    if not recipe_code:
        raise ValueError("Jídlo nemá povinný atribut 'recipeCode'")
    
    # Mapování meal type
    meal_type = MEAL_TYPE_MAPPING.get(meal_type_raw, 'LUNCH')
    
    # Varování pokud type atribut chybí nebo není rozpoznán
    if not meal_type_raw:
        warnings.append(
            f"Den {day_name}, recept {recipe_code}: "
            "Chybí atribut 'type', použit výchozí typ 'Oběd'"
        )
    elif meal_type_raw not in MEAL_TYPE_MAPPING:
        warnings.append(
            f"Den {day_name}, recept {recipe_code}: "
            f"Neznámý typ jídla '{meal_type_raw}', použit výchozí typ 'Oběd'"
        )
    
    # Parsování počtu porcí (pokud je uvedeno)
    portion_count = None
    if portion_count_str:
        try:
            portion_count = int(portion_count_str)
        except ValueError:
            warnings.append(
                f"Den {day_name}, recept {recipe_code}: "
                f"Neplatná hodnota portionCount: {portion_count_str}"
            )
    
    return {
        'recipe_code': recipe_code,
        'meal_type': meal_type,
        'note': note,
        'portion_count': portion_count
    }
