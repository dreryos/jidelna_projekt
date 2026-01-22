import xml.etree.ElementTree as ET
from decimal import Decimal
from typing import Dict, Any, Tuple

from django.db import transaction

from apps.core.models import Ingredient, Category, Recipe, RecipeIngredient


def _update_if_missing(obj, field: str, value: Any) -> bool:
    """Set field only if current value is empty/None and new value is provided."""
    if value in (None, ""):
        return False
    current = getattr(obj, field, None)
    if current in (None, ""):
        setattr(obj, field, value)
        return True
    return False


def _decimal_or_none(value: str):
    try:
        return Decimal(str(value))
    except Exception:
        return None


def export_backup_xml() -> bytes:
    root = ET.Element("Backup", version="1.0")

    ingredients_el = ET.SubElement(root, "Ingredients")
    for ing in Ingredient.objects.all().order_by("name"):
        el = ET.SubElement(ingredients_el, "Ingredient")
        el.set("name", ing.name)
        if ing.base_unit:
            el.set("baseUnit", ing.base_unit)
        if ing.recipe_unit:
            el.set("recipeUnit", ing.recipe_unit)
        if ing.conversion_factor is not None:
            el.set("conversionFactor", str(ing.conversion_factor))
        if ing.unit:
            el.set("unit", ing.unit)

    categories_el = ET.SubElement(root, "Categories")
    for cat in Category.objects.all().order_by("code"):
        el = ET.SubElement(categories_el, "Category")
        el.set("code", cat.code or "")
        el.set("name", cat.name or "")

    recipes_el = ET.SubElement(root, "Recipes")
    recipes_qs = Recipe.objects.all().select_related("category").prefetch_related(
        "recipeingredient_set__ingredient"
    ).order_by("code")

    for recipe in recipes_qs:
        rec_el = ET.SubElement(recipes_el, "Recipe")
        rec_el.set("code", recipe.code or "")
        rec_el.set("name", recipe.name or "")
        rec_el.set("description", recipe.description or "")
        rec_el.set("categoryCode", recipe.category.code if recipe.category else "")
        rec_el.set("basePortions", str(recipe.base_portions or ""))
        rec_el.set("sellingVatRate", str(recipe.selling_vat_rate or ""))

        r_ing_el = ET.SubElement(rec_el, "Ingredients")
        for ri in recipe.recipeingredient_set.all().order_by("id"):
            ri_el = ET.SubElement(r_ing_el, "Ingredient")
            ri_el.set("name", ri.ingredient.name)
            ri_el.set("quantityPerPortion", str(ri.quantity_per_portion))
            if ri.notes:
                ri_el.set("notes", ri.notes)

    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def import_backup_xml(xml_content: bytes, dry_run: bool = False) -> Dict[str, Any]:
    report = {
        "categories_created": 0,
        "categories_updated": 0,
        "ingredients_created": 0,
        "ingredients_updated": 0,
        "recipes_created": 0,
        "recipes_updated": 0,
        "recipe_ingredients_created": 0,
        "recipe_ingredients_updated": 0,
        "missing_references": [],
    }

    root = ET.fromstring(xml_content)

    with transaction.atomic():
        # Categories
        for cat_el in root.find("Categories") or []:
            code = cat_el.get("code", "").strip()
            name = cat_el.get("name", "").strip()
            if not code:
                continue
            cat, created = Category.objects.get_or_create(code=code)
            if created:
                report["categories_created"] += 1
            updated = _update_if_missing(cat, "name", name)
            if updated and not created:
                report["categories_updated"] += 1
            if created or updated:
                cat.save()

        # Ingredients
        for ing_el in root.find("Ingredients") or []:
            name = ing_el.get("name", "").strip()
            if not name:
                continue
            ing, created = Ingredient.objects.get_or_create(name=name)
            if created:
                report["ingredients_created"] += 1
            changed = False
            changed |= _update_if_missing(ing, "base_unit", ing_el.get("baseUnit"))
            changed |= _update_if_missing(ing, "recipe_unit", ing_el.get("recipeUnit"))
            changed |= _update_if_missing(ing, "unit", ing_el.get("unit"))
            conv = _decimal_or_none(ing_el.get("conversionFactor"))
            if conv is not None and (ing.conversion_factor is None):
                ing.conversion_factor = conv
                changed = True
            if changed or created:
                ing.save()
                if changed and not created:
                    report["ingredients_updated"] += 1

        # Build category map
        cat_map: Dict[str, Category] = {c.code: c for c in Category.objects.all()}

        # Recipes
        recipes_el = root.find("Recipes") or []
        for rec_el in recipes_el:
            code = rec_el.get("code", "").strip()
            if not code:
                continue
            name = rec_el.get("name", "").strip()
            description = rec_el.get("description", "")
            category_code = rec_el.get("categoryCode", "").strip()
            base_portions = rec_el.get("basePortions", "").strip()
            selling_vat_rate = rec_el.get("sellingVatRate", "").strip()

            recipe, created = Recipe.objects.get_or_create(code=code)
            if created:
                report["recipes_created"] += 1

            changed = False
            changed |= _update_if_missing(recipe, "name", name)
            changed |= _update_if_missing(recipe, "description", description)

            if category_code and recipe.category is None:
                cat_obj = cat_map.get(category_code)
                if cat_obj:
                    recipe.category = cat_obj
                    changed = True
                else:
                    report["missing_references"].append(
                        f"Kategorie {category_code} pro recept {code} nenalezena"
                    )

            if base_portions:
                try:
                    incoming_bp = int(base_portions)
                    if created or recipe.base_portions in (None, 0):
                        recipe.base_portions = incoming_bp
                        changed = True
                except ValueError:
                    pass

            if selling_vat_rate:
                try:
                    incoming_vat = Decimal(selling_vat_rate)
                    if created or recipe.selling_vat_rate is None:
                        recipe.selling_vat_rate = incoming_vat
                        changed = True
                except Exception:
                    pass

            if changed or created:
                recipe.save()
                if changed and not created:
                    report["recipes_updated"] += 1

            # Recipe ingredients
            ri_parent = rec_el.find("Ingredients") or []
            for ri_el in ri_parent:
                ing_name = ri_el.get("name", "").strip()
                qty = _decimal_or_none(ri_el.get("quantityPerPortion"))
                notes = ri_el.get("notes", "")
                if not ing_name:
                    continue
                try:
                    ingredient = Ingredient.objects.get(name=ing_name)
                except Ingredient.DoesNotExist:
                    report["missing_references"].append(
                        f"Surovina {ing_name} pro recept {code} nenalezena"
                    )
                    continue

                ri_obj, ri_created = RecipeIngredient.objects.update_or_create(
                    recipe=recipe,
                    ingredient=ingredient,
                    defaults={
                        "quantity_per_portion": qty or Decimal("0"),
                        "notes": notes,
                    },
                )
                if ri_created:
                    report["recipe_ingredients_created"] += 1
                else:
                    report["recipe_ingredients_updated"] += 1

        if dry_run:
            transaction.set_rollback(True)

    return report
