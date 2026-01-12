"""
TODO: Unit testy pro XML parser

Testy které by měly být implementovány:
- test_parse_valid_xml: Parsování validního XML
- test_parse_invalid_xml: Chyba při nevalidním XML
- test_missing_recipes_section: Chyba když chybí <Recipes>
- test_missing_schedule_section: Chyba když chybí <MenuSchedule>
- test_meal_type_mapping: Správné mapování meal_type atributů
- test_ingredient_conversion: Převody jednotek (kg→g, l→ml)
- test_warnings_for_missing_type: Warnings pro meals bez type atributu
- test_portion_count_parsing: Parsování portionCount atributu
"""

from django.test import TestCase
from django.core.exceptions import ValidationError
from apps.production.xml_parser import parse_menu_template_xml


class XMLParserTestCase(TestCase):
    """Testy pro XML parser šablon jídelníčků"""
    
    def setUp(self):
        """Setup testovacích dat"""
        pass
    
    # TODO: Implementovat testy
