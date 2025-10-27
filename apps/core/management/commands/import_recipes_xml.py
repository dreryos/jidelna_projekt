"""
Management command pro import receptů z recipebook.xml

Použití:
    python manage.py import_recipes_xml <cesta_k_xml_souboru>
    
Příklad:
    python manage.py import_recipes_xml docs/recipebook.xml

Command:
- Vytvoří kategorie receptů z XML
- Importuje recepty s kódy a kategoriemi
- Automaticky vytvoří neexistující suroviny s výchozími hodnotami
- Převede množství z XML (gramy na 10 porcí) na množství na 1 porci
"""

import xml.etree.ElementTree as ET
from decimal import Decimal
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.core.models import Category, Recipe, Ingredient, RecipeIngredient


class Command(BaseCommand):
    help = 'Importuje recepty z recipebook.xml souboru'

    def add_arguments(self, parser):
        parser.add_argument(
            'xml_file',
            type=str,
            help='Cesta k XML souboru s recepty'
        )
        parser.add_argument(
            '--clear',
            action='store_true',
            help='Smazat všechny existující recepty před importem'
        )
        parser.add_argument(
            '--update',
            action='store_true',
            help='Aktualizovat existující recepty místo přeskočení'
        )

    def handle(self, *args, **options):
        xml_file = options['xml_file']
        clear = options['clear']
        update = options['update']

        self.stdout.write(self.style.SUCCESS(f'Načítám XML soubor: {xml_file}'))

        try:
            tree = ET.parse(xml_file)
            root = tree.getroot()
        except FileNotFoundError:
            raise CommandError(f'Soubor {xml_file} nebyl nalezen')
        except ET.ParseError as e:
            raise CommandError(f'Chyba při parsování XML: {e}')

        # Smazání dat pokud je požadováno
        if clear:
            self.stdout.write(self.style.WARNING('Mažu existující recepty...'))
            Recipe.objects.all().delete()
            Category.objects.all().delete()

        # Import kategorií
        categories_created = self.import_categories(root)
        self.stdout.write(self.style.SUCCESS(f'Vytvořeno kategorií: {categories_created}'))

        # Import receptů
        with transaction.atomic():
            recipes_created, recipes_updated, recipes_skipped = self.import_recipes(root, update)

        self.stdout.write(self.style.SUCCESS(
            f'\nImport dokončen:\n'
            f'  - Nové recepty: {recipes_created}\n'
            f'  - Aktualizované: {recipes_updated}\n'
            f'  - Přeskočené: {recipes_skipped}'
        ))

    def import_categories(self, root):
        """Importuje kategorie z XML"""
        categories_elem = root.find('Categories')
        if categories_elem is None:
            self.stdout.write(self.style.WARNING('Sekce Categories nebyla nalezena'))
            return 0

        count = 0
        for cat_elem in categories_elem.findall('Category'):
            code = cat_elem.get('id')
            name = cat_elem.get('name')

            if code and name:
                category, created = Category.objects.get_or_create(
                    code=code,
                    defaults={'name': name}
                )
                if created:
                    count += 1
                    self.stdout.write(f'  Kategorie: {code} - {name}')

        return count

    def import_recipes(self, root, update=False):
        """Importuje recepty z XML"""
        recipes_elem = root.find('Recipes')
        if recipes_elem is None:
            raise CommandError('Sekce Recipes nebyla nalezena v XML')

        created = 0
        updated = 0
        skipped = 0

        for recipe_elem in recipes_elem.findall('Recipe'):
            code = recipe_elem.get('code')
            category_id = recipe_elem.get('categoryId')
            base_portions = int(recipe_elem.get('basePortions', 10))

            name_elem = recipe_elem.find('Name')
            if name_elem is None or not name_elem.text:
                self.stdout.write(self.style.WARNING(f'Recept {code} nemá název, přeskakuji'))
                skipped += 1
                continue

            name = name_elem.text.strip()

            # Najdeme kategorii
            category = None
            if category_id:
                try:
                    category = Category.objects.get(code=category_id)
                except Category.DoesNotExist:
                    self.stdout.write(self.style.WARNING(
                        f'Kategorie {category_id} neexistuje, recept {name} bude bez kategorie'
                    ))

            # Vytvoříme nebo najdeme recept
            recipe_exists = Recipe.objects.filter(category=category, code=code).exists()

            if recipe_exists and not update:
                self.stdout.write(f'  Přeskakuji {code} - {name} (již existuje)')
                skipped += 1
                continue

            if recipe_exists and update:
                recipe = Recipe.objects.get(category=category, code=code)
                recipe.name = name
                recipe.base_portions = base_portions
                recipe.save()
                # Smažeme staré ingredience
                recipe.recipeingredient_set.all().delete()
                self.stdout.write(f'  Aktualizuji {code} - {name}')
                updated += 1
            else:
                recipe = Recipe.objects.create(
                    code=code,
                    name=name,
                    category=category,
                    base_portions=base_portions
                )
                self.stdout.write(f'  Vytvářím {code} - {name}')
                created += 1

            # Import ingrediencí
            ingredients_elem = recipe_elem.find('Ingredients')
            if ingredients_elem is not None:
                self.import_recipe_ingredients(recipe, ingredients_elem, base_portions)

        return created, updated, skipped

    def import_recipe_ingredients(self, recipe, ingredients_elem, base_portions):
        """Importuje ingredience pro daný recept"""
        for ing_elem in ingredients_elem.findall('Ingredient'):
            ing_name = ing_elem.get('name')
            net_quantity_g = ing_elem.get('netQuantityG')
            notes = ing_elem.get('notes', '')

            if not ing_name or net_quantity_g is None:
                continue

            # Převedeme na Decimal
            try:
                total_quantity_g = Decimal(net_quantity_g)
            except (ValueError, TypeError):
                self.stdout.write(self.style.WARNING(
                    f'    Neplatné množství pro {ing_name}: {net_quantity_g}'
                ))
                continue

            # Vypočítáme množství na 1 porci
            quantity_per_portion = total_quantity_g / Decimal(str(base_portions))

            # Vytvoříme nebo najdeme surovinu
            ingredient = self.get_or_create_ingredient(ing_name)

            # Zkontrolujeme, zda ingredience již není v receptu (duplicita v XML)
            existing = RecipeIngredient.objects.filter(
                recipe=recipe,
                ingredient=ingredient
            ).first()

            if existing:
                # Aktualizujeme množství (sčítáme)
                existing.quantity_per_portion += quantity_per_portion
                if notes and not existing.notes:
                    existing.notes = notes
                existing.save()
                self.stdout.write(
                    f'    * {ing_name}: +{quantity_per_portion:.3f}{ingredient.recipe_unit}/porci (celkem {existing.quantity_per_portion:.3f})'
                )
            else:
                # Vytvoříme normu receptu
                RecipeIngredient.objects.create(
                    recipe=recipe,
                    ingredient=ingredient,
                    quantity_per_portion=quantity_per_portion,
                    notes=notes
                )

                self.stdout.write(
                    f'    + {ing_name}: {quantity_per_portion:.3f}{ingredient.recipe_unit}/porci'
                )

    def get_or_create_ingredient(self, name):
        """
        Vrátí surovinu podle názvu. Pokud neexistuje, vytvoří ji s výchozími hodnotami.
        
        Výchozí hodnoty:
        - unit: 'kg' (pro zpětnou kompatibilitu)
        - base_unit: 'kg'
        - recipe_unit: 'g'
        - conversion_factor: 1000
        """
        try:
            return Ingredient.objects.get(name=name)
        except Ingredient.DoesNotExist:
            # Detekce jednotky podle názvu
            base_unit = 'kg'
            recipe_unit = 'g'
            conversion_factor = Decimal('1000')

            # Speciální případy
            name_lower = name.lower()
            if any(word in name_lower for word in ['vejce', 'ks', 'kus']):
                base_unit = 'ks'
                recipe_unit = 'ks'
                conversion_factor = Decimal('1')
            elif any(word in name_lower for word in ['voda', 'mléko', 'šťáva', 'olej', 'ocet']):
                base_unit = 'l'
                recipe_unit = 'ml'
                conversion_factor = Decimal('1000')

            ingredient = Ingredient.objects.create(
                name=name,
                unit=base_unit,  # Pro zpětnou kompatibilitu
                base_unit=base_unit,
                recipe_unit=recipe_unit,
                conversion_factor=conversion_factor
            )

            self.stdout.write(self.style.SUCCESS(
                f'    Vytvořena nová surovina: {name} ({base_unit}/{recipe_unit})'
            ))

            return ingredient
