import xml.etree.ElementTree as ET
from decimal import Decimal
from typing import Dict, Any, List, Optional, Set
from datetime import datetime

from django.db import transaction
from django.utils import timezone

from apps.core.models import Ingredient, Category, Recipe, RecipeIngredient
from apps.canteens.models import Canteen, Warehouse
from apps.inventory.models import (
    StockItem, GoodsReceipt, GoodsReceiptItem,
    StockTransfer, StockTransferItem,
    InventoryVerification, InventoryVerificationItem,
    StockWriteOff, StockWriteOffItem,
    Supplier, SupplierIngredientTemplate
)
from apps.production.models import (
    MenuPlan, MenuTemplate, ProductionOrder,
    ProductionOrderPortionVariant, ProductionOrderIngredientOverride,
    MenuPlanCoefficient
)


# Konstanty pro názvy entit
ENTITY_INGREDIENTS = 'ingredients'
ENTITY_CATEGORIES = 'categories'
ENTITY_RECIPES = 'recipes'
ENTITY_CANTEENS = 'canteens'
ENTITY_WAREHOUSES = 'warehouses'
ENTITY_STOCK_ITEMS = 'stock_items'
ENTITY_SUPPLIERS = 'suppliers'
ENTITY_MENU_TEMPLATES = 'menu_templates'
ENTITY_MENU_PLANS = 'menu_plans'
ENTITY_PRODUCTION_ORDERS = 'production_orders'
ENTITY_GOODS_RECEIPTS = 'goods_receipts'
ENTITY_STOCK_TRANSFERS = 'stock_transfers'
ENTITY_INVENTORY_VERIFICATIONS = 'inventory_verifications'
ENTITY_STOCK_WRITE_OFFS = 'stock_write_offs'

# Všechny dostupné entity
ALL_ENTITIES = [
    ENTITY_INGREDIENTS,
    ENTITY_CATEGORIES,
    ENTITY_RECIPES,
    ENTITY_CANTEENS,
    ENTITY_WAREHOUSES,
    ENTITY_SUPPLIERS,
    ENTITY_STOCK_ITEMS,
    ENTITY_MENU_TEMPLATES,
    ENTITY_MENU_PLANS,
    ENTITY_PRODUCTION_ORDERS,
    ENTITY_GOODS_RECEIPTS,
    ENTITY_STOCK_TRANSFERS,
    ENTITY_INVENTORY_VERIFICATIONS,
    ENTITY_STOCK_WRITE_OFFS,
]

# Základní entity (zpětná kompatibilita)
DEFAULT_ENTITIES = [
    ENTITY_INGREDIENTS,
    ENTITY_CATEGORIES,
    ENTITY_RECIPES,
]

# Mapa závislostí: entita -> seznam entit, které musí být exportovány
ENTITY_DEPENDENCIES = {
    ENTITY_RECIPES: [ENTITY_INGREDIENTS, ENTITY_CATEGORIES],
    ENTITY_STOCK_ITEMS: [ENTITY_INGREDIENTS, ENTITY_WAREHOUSES],
    ENTITY_WAREHOUSES: [ENTITY_CANTEENS],
    ENTITY_MENU_PLANS: [ENTITY_CANTEENS],
    ENTITY_PRODUCTION_ORDERS: [ENTITY_RECIPES, ENTITY_MENU_PLANS, ENTITY_CANTEENS],
    ENTITY_GOODS_RECEIPTS: [ENTITY_WAREHOUSES, ENTITY_SUPPLIERS],
    ENTITY_STOCK_TRANSFERS: [ENTITY_WAREHOUSES],
    ENTITY_INVENTORY_VERIFICATIONS: [ENTITY_WAREHOUSES],
    ENTITY_STOCK_WRITE_OFFS: [ENTITY_WAREHOUSES],
    ENTITY_MENU_TEMPLATES: [],  # XML obsah, žádné DB závislosti
    ENTITY_SUPPLIERS: [],
}

# Lidsky čitelné názvy entit
ENTITY_LABELS = {
    ENTITY_INGREDIENTS: 'Seznam surovin',
    ENTITY_CATEGORIES: 'Kategorie jídel',
    ENTITY_RECIPES: 'Recepty',
    ENTITY_CANTEENS: 'Jídelny',
    ENTITY_WAREHOUSES: 'Sklady',
    ENTITY_SUPPLIERS: 'Dodavatelé',
    ENTITY_STOCK_ITEMS: 'Stav skladů',
    ENTITY_MENU_TEMPLATES: 'Šablony jídelníčků',
    ENTITY_MENU_PLANS: 'Jídelníčky',
    ENTITY_PRODUCTION_ORDERS: 'Výrobní příkazy',
    ENTITY_GOODS_RECEIPTS: 'Příjmy zboží',
    ENTITY_STOCK_TRANSFERS: 'Převodky',
    ENTITY_INVENTORY_VERIFICATIONS: 'Inventury',
    ENTITY_STOCK_WRITE_OFFS: 'Odpisy',
}


def get_required_entities(selected: List[str]) -> Set[str]:
    """
    Vrátí množinu všech entit, které je nutné exportovat včetně závislostí.
    """
    result = set(selected)
    changed = True
    
    while changed:
        changed = False
        for entity in list(result):
            for dep in ENTITY_DEPENDENCIES.get(entity, []):
                if dep not in result:
                    result.add(dep)
                    changed = True
    
    return result


def _update_if_missing(obj, field: str, value: Any) -> bool:
    """Set field only if current value is empty/None and new value is provided."""
    if value in (None, ""):
        return False
    current = getattr(obj, field, None)
    if current in (None, ""):
        setattr(obj, field, value)
        return True
    return False


def _decimal_or_none(value):
    if value is None or value == '':
        return None
    try:
        return Decimal(str(value))
    except Exception:
        return None


def _datetime_or_none(value):
    """Parsuje ISO formát datetime nebo vrátí None."""
    if not value:
        return None
    try:
        # Zkusíme ISO formát
        return datetime.fromisoformat(value.replace('Z', '+00:00'))
    except Exception:
        try:
            # Zkusíme běžný formát
            return datetime.strptime(value, '%Y-%m-%d %H:%M:%S')
        except Exception:
            return None


def _date_or_none(value):
    """Parsuje datum nebo vrátí None."""
    if not value:
        return None
    try:
        return datetime.strptime(value, '%Y-%m-%d').date()
    except Exception:
        return None


def _bool_or_none(value):
    """Parsuje boolean nebo vrátí None."""
    if value is None or value == '':
        return None
    return value.lower() in ('true', '1', 'yes', 'on')


# ============================================================================
# EXPORT FUNKCE
# ============================================================================

def _export_ingredients(root: ET.Element, include: bool = True) -> None:
    """Exportuje suroviny."""
    if not include:
        return
    
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
        if not ing.is_active:
            el.set("isActive", "false")


def _export_categories(root: ET.Element, include: bool = True) -> None:
    """Exportuje kategorie."""
    if not include:
        return
    
    categories_el = ET.SubElement(root, "Categories")
    for cat in Category.objects.all().order_by("code"):
        el = ET.SubElement(categories_el, "Category")
        el.set("code", cat.code or "")
        el.set("name", cat.name or "")


def _export_recipes(root: ET.Element, include: bool = True) -> None:
    """Exportuje recepty včetně ingrediencí."""
    if not include:
        return
    
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


def _export_canteens(root: ET.Element, include: bool = True) -> None:
    """Exportuje jídelny."""
    if not include:
        return
    
    canteens_el = ET.SubElement(root, "Canteens")
    for canteen in Canteen.objects.all().order_by("name"):
        el = ET.SubElement(canteens_el, "Canteen")
        el.set("name", canteen.name)
        if canteen.address:
            el.set("address", canteen.address)


def _export_warehouses(root: ET.Element, include: bool = True) -> None:
    """Exportuje sklady."""
    if not include:
        return
    
    warehouses_el = ET.SubElement(root, "Warehouses")
    for wh in Warehouse.objects.all().select_related("canteen").order_by("canteen__name", "name"):
        el = ET.SubElement(warehouses_el, "Warehouse")
        el.set("name", wh.name)
        el.set("canteenName", wh.canteen.name if wh.canteen else "")
        el.set("isTransit", "true" if wh.is_transit_warehouse else "false")


def _export_suppliers(root: ET.Element, include: bool = True) -> None:
    """Exportuje dodavatele a jejich šablony."""
    if not include:
        return
    
    suppliers_el = ET.SubElement(root, "Suppliers")
    for supplier in Supplier.objects.all().order_by("name"):
        sup_el = ET.SubElement(suppliers_el, "Supplier")
        sup_el.set("name", supplier.name)
        sup_el.set("slug", supplier.slug)
        sup_el.set("isActive", "true" if supplier.is_active else "false")
        
        # Šablony surovin
        templates_el = ET.SubElement(sup_el, "Templates")
        for template in supplier.template_ingredients.all().select_related("ingredient"):
            t_el = ET.SubElement(templates_el, "Template")
            t_el.set("ingredientName", template.ingredient.name)
            if template.default_price_without_vat:
                t_el.set("defaultPriceWithoutVat", str(template.default_price_without_vat))
            t_el.set("defaultVatRate", str(template.default_vat_rate))
            t_el.set("sortOrder", str(template.sort_order))


def _export_stock_items(root: ET.Element, include: bool = True) -> None:
    """Exportuje skladové položky (stav skladů)."""
    if not include:
        return
    
    stock_el = ET.SubElement(root, "StockItems")
    for item in StockItem.objects.all().select_related("ingredient", "warehouse", "warehouse__canteen").order_by(
        "warehouse__canteen__name", "warehouse__name", "ingredient__name"
    ):
        el = ET.SubElement(stock_el, "StockItem")
        el.set("ingredientName", item.ingredient.name)
        el.set("warehouseName", item.warehouse.name)
        el.set("canteenName", item.warehouse.canteen.name if item.warehouse.canteen else "")
        el.set("quantity", str(item.quantity))
        el.set("quantityBlocked", str(item.quantity_blocked))
        el.set("price", str(item.price))
        el.set("vatRate", str(item.vat_rate))
        if item.price_without_vat:
            el.set("priceWithoutVat", str(item.price_without_vat))


def _export_menu_templates(root: ET.Element, include: bool = True) -> None:
    """Exportuje šablony jídelníčků."""
    if not include:
        return
    
    templates_el = ET.SubElement(root, "MenuTemplates")
    for template in MenuTemplate.objects.all().order_by("name"):
        el = ET.SubElement(templates_el, "MenuTemplate")
        el.set("name", template.name)
        if template.description:
            el.set("description", template.description)
        # XML obsah uložíme jako CDATA nebo escapovaný text
        xml_content_el = ET.SubElement(el, "XmlContent")
        xml_content_el.text = template.xml_content or ""


def _export_menu_plans(root: ET.Element, include: bool = True) -> None:
    """Exportuje jídelníčky včetně koeficientů."""
    if not include:
        return
    
    menus_el = ET.SubElement(root, "MenuPlans")
    for menu in MenuPlan.objects.all().select_related("canteen").order_by("-date_from"):
        menu_el = ET.SubElement(menus_el, "MenuPlan")
        menu_el.set("name", menu.name)
        menu_el.set("canteenName", menu.canteen.name if menu.canteen else "")
        menu_el.set("dateFrom", menu.date_from.isoformat())
        menu_el.set("dateTo", menu.date_to.isoformat())
        menu_el.set("defaultPortionsAdult", str(menu.default_portions_adult))
        menu_el.set("defaultPortionsChild", str(menu.default_portions_child))
        
        # Koeficienty
        coeffs_el = ET.SubElement(menu_el, "Coefficients")
        for coeff in menu.default_coefficients.all().order_by("order"):
            c_el = ET.SubElement(coeffs_el, "Coefficient")
            c_el.set("name", coeff.name)
            c_el.set("coefficient", str(coeff.coefficient))
            c_el.set("order", str(coeff.order))


def _export_production_orders(root: ET.Element, include: bool = True) -> None:
    """Exportuje výrobní příkazy včetně variant a override."""
    if not include:
        return
    
    orders_el = ET.SubElement(root, "ProductionOrders")
    for order in ProductionOrder.objects.all().select_related(
        "recipe", "menu_plan", "canteen"
    ).prefetch_related(
        "portion_variants", "ingredient_overrides"
    ).order_by("-date"):
        order_el = ET.SubElement(orders_el, "ProductionOrder")
        order_el.set("recipeCode", order.recipe.code if order.recipe else "")
        order_el.set("menuPlanName", order.menu_plan.name if order.menu_plan else "")
        order_el.set("canteenName", order.canteen.name if order.canteen else "")
        order_el.set("date", order.date.isoformat())
        order_el.set("mealType", order.meal_type)
        order_el.set("sellingVatRate", str(order.selling_vat_rate))
        
        # Varianty porcí
        variants_el = ET.SubElement(order_el, "PortionVariants")
        for variant in order.portion_variants.all().order_by("order"):
            v_el = ET.SubElement(variants_el, "Variant")
            v_el.set("name", variant.name or "")
            v_el.set("coefficient", str(variant.coefficient))
            v_el.set("portions", str(variant.portions))
            v_el.set("order", str(variant.order))
        
        # Override ingrediencí
        overrides_el = ET.SubElement(order_el, "IngredientOverrides")
        for override in order.ingredient_overrides.all().select_related("ingredient"):
            o_el = ET.SubElement(overrides_el, "Override")
            o_el.set("ingredientName", override.ingredient.name)
            if override.quantity_per_portion is not None:
                o_el.set("quantityPerPortion", str(override.quantity_per_portion))
            o_el.set("originalQuantity", str(override.original_quantity))
            o_el.set("isAdded", "true" if override.is_added else "false")
            o_el.set("isRemoved", "true" if override.is_removed else "false")


def _export_goods_receipts(root: ET.Element, include: bool = True) -> None:
    """Exportuje příjmy zboží včetně položek."""
    if not include:
        return
    
    receipts_el = ET.SubElement(root, "GoodsReceipts")
    for receipt in GoodsReceipt.objects.all().select_related(
        "warehouse", "warehouse__canteen", "supplier_obj", "created_by"
    ).order_by("-created_at"):
        rec_el = ET.SubElement(receipts_el, "GoodsReceipt")
        rec_el.set("receiptNumber", receipt.receipt_number)
        rec_el.set("warehouseName", receipt.warehouse.name if receipt.warehouse else "")
        rec_el.set("canteenName", receipt.warehouse.canteen.name if receipt.warehouse and receipt.warehouse.canteen else "")
        rec_el.set("receiptDate", receipt.receipt_date.isoformat())
        rec_el.set("status", receipt.status)
        if receipt.supplier:
            rec_el.set("supplier", receipt.supplier)
        if receipt.supplier_obj:
            rec_el.set("supplierSlug", receipt.supplier_obj.slug)
        if receipt.notes:
            rec_el.set("notes", receipt.notes)
        rec_el.set("createdBy", receipt.created_by.username if receipt.created_by else "")
        if receipt.confirmed_at:
            rec_el.set("confirmedAt", receipt.confirmed_at.isoformat())
        
        # Položky příjmu
        items_el = ET.SubElement(rec_el, "Items")
        for item in receipt.items.all().select_related("ingredient", "warehouse"):
            item_el = ET.SubElement(items_el, "Item")
            item_el.set("ingredientName", item.ingredient.name)
            item_el.set("warehouseName", item.warehouse.name if item.warehouse else "")
            item_el.set("quantity", str(item.quantity))
            item_el.set("price", str(item.price))
            if item.price_without_vat:
                item_el.set("priceWithoutVat", str(item.price_without_vat))
            item_el.set("vatRate", str(item.vat_rate))
            if item.notes:
                item_el.set("notes", item.notes)


def _export_stock_transfers(root: ET.Element, include: bool = True) -> None:
    """Exportuje převodky včetně položek."""
    if not include:
        return
    
    transfers_el = ET.SubElement(root, "StockTransfers")
    for transfer in StockTransfer.objects.all().select_related(
        "warehouse_from", "warehouse_to", "warehouse_from__canteen", "warehouse_to__canteen"
    ).order_by("-created_at"):
        trans_el = ET.SubElement(transfers_el, "StockTransfer")
        trans_el.set("transferNumber", transfer.transfer_number)
        trans_el.set("warehouseFromName", transfer.warehouse_from.name if transfer.warehouse_from else "")
        trans_el.set("warehouseToName", transfer.warehouse_to.name if transfer.warehouse_to else "")
        trans_el.set("transferDate", transfer.transfer_date.isoformat())
        trans_el.set("status", transfer.status)
        if transfer.notes:
            trans_el.set("notes", transfer.notes)
        if transfer.started_at:
            trans_el.set("startedAt", transfer.started_at.isoformat())
        if transfer.completed_at:
            trans_el.set("completedAt", transfer.completed_at.isoformat())
        
        # Položky převodky
        items_el = ET.SubElement(trans_el, "Items")
        for item in transfer.items.all().select_related("ingredient"):
            item_el = ET.SubElement(items_el, "Item")
            item_el.set("ingredientName", item.ingredient.name)
            item_el.set("quantity", str(item.quantity))
            item_el.set("unitPriceWithVat", str(item.unit_price_with_vat))


def _export_inventory_verifications(root: ET.Element, include: bool = True) -> None:
    """Exportuje inventury včetně položek."""
    if not include:
        return
    
    inventories_el = ET.SubElement(root, "InventoryVerifications")
    for inv in InventoryVerification.objects.all().select_related(
        "warehouse", "warehouse__canteen", "created_by", "started_by", "completed_by"
    ).order_by("-created_at"):
        inv_el = ET.SubElement(inventories_el, "InventoryVerification")
        inv_el.set("warehouseName", inv.warehouse.name if inv.warehouse else "")
        inv_el.set("canteenName", inv.warehouse.canteen.name if inv.warehouse and inv.warehouse.canteen else "")
        inv_el.set("status", inv.status)
        if inv.notes:
            inv_el.set("notes", inv.notes)
        inv_el.set("createdBy", inv.created_by.username if inv.created_by else "")
        if inv.started_at:
            inv_el.set("startedAt", inv.started_at.isoformat())
        if inv.completed_at:
            inv_el.set("completedAt", inv.completed_at.isoformat())
        if inv.cancelled_at:
            inv_el.set("cancelledAt", inv.cancelled_at.isoformat())
        
        # Položky inventury
        items_el = ET.SubElement(inv_el, "Items")
        for item in inv.items.all().select_related("ingredient"):
            item_el = ET.SubElement(items_el, "Item")
            item_el.set("ingredientName", item.ingredient.name)
            item_el.set("systemQuantity", str(item.system_quantity))
            if item.counted_quantity is not None:
                item_el.set("countedQuantity", str(item.counted_quantity))
            if item.difference != 0:
                item_el.set("difference", str(item.difference))
            item_el.set("isNewlyFound", "true" if item.is_newly_found else "false")
            if item.notes:
                item_el.set("notes", item.notes)


def _export_stock_write_offs(root: ET.Element, include: bool = True) -> None:
    """Exportuje odpisy včetně položek."""
    if not include:
        return
    
    writeoffs_el = ET.SubElement(root, "StockWriteOffs")
    for wo in StockWriteOff.objects.all().select_related(
        "warehouse", "warehouse__canteen", "created_by"
    ).order_by("-write_off_date"):
        wo_el = ET.SubElement(writeoffs_el, "StockWriteOff")
        wo_el.set("warehouseName", wo.warehouse.name if wo.warehouse else "")
        wo_el.set("canteenName", wo.warehouse.canteen.name if wo.warehouse and wo.warehouse.canteen else "")
        wo_el.set("category", wo.category)
        wo_el.set("writeOffDate", wo.write_off_date.isoformat())
        if wo.notes:
            wo_el.set("notes", wo.notes)
        wo_el.set("createdBy", wo.created_by.username if wo.created_by else "")
        if wo.cash_register_import_id:
            wo_el.set("cashRegisterImportId", wo.cash_register_import_id)
        
        # Položky odpisu
        items_el = ET.SubElement(wo_el, "Items")
        for item in wo.items.all().select_related("ingredient"):
            item_el = ET.SubElement(items_el, "Item")
            item_el.set("ingredientName", item.ingredient.name)
            item_el.set("quantity", str(item.quantity))
            item_el.set("unitCost", str(item.unit_cost))
            if item.notes:
                item_el.set("notes", item.notes)


# ============================================================================
# HLAVNÍ EXPORT FUNKCE
# ============================================================================

def export_backup_xml(selected_entities: Optional[List[str]] = None) -> bytes:
    """
    Exportuje vybrané entity do XML zálohy.
    
    Args:
        selected_entities: Seznam klíčů entit k exportu. 
                          Pokud None, exportují se výchozí entity (zpětná kompatibilita).
    
    Returns:
        XML obsah jako bytes.
    """
    if selected_entities is None:
        selected_entities = DEFAULT_ENTITIES
    
    # Získáme všechny potřebné entity včetně závislostí
    entities_to_export = get_required_entities(selected_entities)
    
    # Vytvoříme root element s verzí 2.0
    root = ET.Element("Backup", version="2.0", exportDate=timezone.now().isoformat())
    
    # Exportujeme jednotlivé entity
    _export_ingredients(root, ENTITY_INGREDIENTS in entities_to_export)
    _export_categories(root, ENTITY_CATEGORIES in entities_to_export)
    _export_recipes(root, ENTITY_RECIPES in entities_to_export)
    _export_canteens(root, ENTITY_CANTEENS in entities_to_export)
    _export_warehouses(root, ENTITY_WAREHOUSES in entities_to_export)
    _export_suppliers(root, ENTITY_SUPPLIERS in entities_to_export)
    _export_stock_items(root, ENTITY_STOCK_ITEMS in entities_to_export)
    _export_menu_templates(root, ENTITY_MENU_TEMPLATES in entities_to_export)
    _export_menu_plans(root, ENTITY_MENU_PLANS in entities_to_export)
    _export_production_orders(root, ENTITY_PRODUCTION_ORDERS in entities_to_export)
    _export_goods_receipts(root, ENTITY_GOODS_RECEIPTS in entities_to_export)
    _export_stock_transfers(root, ENTITY_STOCK_TRANSFERS in entities_to_export)
    _export_inventory_verifications(root, ENTITY_INVENTORY_VERIFICATIONS in entities_to_export)
    _export_stock_write_offs(root, ENTITY_STOCK_WRITE_OFFS in entities_to_export)
    
    # Pretty print XML
    ET.indent(root, space='  ')
    
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


# ============================================================================
# IMPORT FUNKCE
# ============================================================================

def _import_canteens(root: ET.Element, report: Dict[str, Any]) -> Dict[str, Canteen]:
    """Importuje jídelny a vrátí mapu název -> objekt."""
    canteen_map = {}
    report['canteens_created'] = 0
    report['canteens_updated'] = 0
    
    canteens_el = root.find("Canteens")
    if canteens_el is None:
        return canteen_map
    
    for cant_el in canteens_el:
        name = cant_el.get("name", "").strip()
        if not name:
            continue
        
        address = cant_el.get("address", "").strip()
        
        canteen, created = Canteen.objects.get_or_create(name=name)
        if created:
            report['canteens_created'] += 1
        
        changed = _update_if_missing(canteen, "address", address)
        if changed or created:
            canteen.save()
            if changed and not created:
                report['canteens_updated'] += 1
        
        canteen_map[name] = canteen
    
    return canteen_map


def _import_warehouses(root: ET.Element, canteen_map: Dict[str, Canteen], report: Dict[str, Any]) -> Dict[str, Warehouse]:
    """Importuje sklady a vrátí mapu název -> objekt."""
    warehouse_map = {}
    report['warehouses_created'] = 0
    report['warehouses_updated'] = 0
    
    warehouses_el = root.find("Warehouses")
    if warehouses_el is None:
        return warehouse_map
    
    for wh_el in warehouses_el:
        name = wh_el.get("name", "").strip()
        canteen_name = wh_el.get("canteenName", "").strip()
        is_transit = wh_el.get("isTransit", "false").lower() == "true"
        
        if not name or canteen_name not in canteen_map:
            continue
        
        canteen = canteen_map[canteen_name]
        
        # Pro transit warehouse použijeme get_or_create_transit_warehouse
        if is_transit:
            warehouse = canteen.get_or_create_transit_warehouse()
            created = False  # Transit warehouse může existovat
        else:
            warehouse, created = Warehouse.objects.get_or_create(
                name=name, canteen=canteen
            )
        
        if created:
            report['warehouses_created'] += 1
        else:
            report['warehouses_updated'] += 0  # U skladů nic neměníme
        
        warehouse_map[f"{canteen_name}:{name}"] = warehouse
    
    return warehouse_map


def _import_suppliers(root: ET.Element, report: Dict[str, Any]) -> Dict[str, Supplier]:
    """Importuje dodavatele a jejich šablony."""
    supplier_map = {}
    report['suppliers_created'] = 0
    report['suppliers_updated'] = 0
    report['supplier_templates_created'] = 0
    
    suppliers_el = root.find("Suppliers")
    if suppliers_el is None:
        return supplier_map
    
    # Musíme mít mapu surovin
    ingredient_map = {i.name: i for i in Ingredient.objects.all()}
    
    for sup_el in suppliers_el:
        name = sup_el.get("name", "").strip()
        slug = sup_el.get("slug", "").strip()
        
        if not name or not slug:
            continue
        
        is_active = sup_el.get("isActive", "true").lower() == "true"
        
        supplier, created = Supplier.objects.get_or_create(
            slug=slug,
            defaults={'name': name, 'is_active': is_active}
        )
        
        if created:
            report['suppliers_created'] += 1
        else:
            changed = _update_if_missing(supplier, "name", name)
            if changed:
                supplier.save()
                report['suppliers_updated'] += 1
        
        # Import šablon
        templates_el = sup_el.find("Templates")
        if templates_el is not None:
            for t_el in templates_el:
                ing_name = t_el.get("ingredientName", "").strip()
                if ing_name not in ingredient_map:
                    continue
                
                ingredient = ingredient_map[ing_name]
                price = _decimal_or_none(t_el.get("defaultPriceWithoutVat"))
                vat_rate = _decimal_or_none(t_el.get("defaultVatRate")) or Decimal('12')
                sort_order = int(t_el.get("sortOrder", "0") or 0)
                
                template, t_created = SupplierIngredientTemplate.objects.get_or_create(
                    supplier=supplier,
                    ingredient=ingredient,
                    defaults={
                        'default_price_without_vat': price,
                        'default_vat_rate': vat_rate,
                        'sort_order': sort_order
                    }
                )
                
                if t_created:
                    report['supplier_templates_created'] += 1
        
        supplier_map[slug] = supplier
    
    return supplier_map


def _import_stock_items(root: ET.Element, ingredient_map: Dict[str, Ingredient], 
                        warehouse_map: Dict[str, Warehouse], report: Dict[str, Any]) -> None:
    """Importuje skladové položky."""
    report['stock_items_created'] = 0
    report['stock_items_updated'] = 0
    
    stock_el = root.find("StockItems")
    if stock_el is None:
        return
    
    for item_el in stock_el:
        ing_name = item_el.get("ingredientName", "").strip()
        wh_name = item_el.get("warehouseName", "").strip()
        canteen_name = item_el.get("canteenName", "").strip()
        
        wh_key = f"{canteen_name}:{wh_name}"
        
        if ing_name not in ingredient_map or wh_key not in warehouse_map:
            continue
        
        ingredient = ingredient_map[ing_name]
        warehouse = warehouse_map[wh_key]
        
        quantity = _decimal_or_none(item_el.get("quantity")) or Decimal('0')
        quantity_blocked = _decimal_or_none(item_el.get("quantityBlocked")) or Decimal('0')
        price = _decimal_or_none(item_el.get("price")) or Decimal('0')
        vat_rate = _decimal_or_none(item_el.get("vatRate")) or Decimal('12')
        price_without_vat = _decimal_or_none(item_el.get("priceWithoutVat"))
        
        stock_item, created = StockItem.objects.get_or_create(
            ingredient=ingredient,
            warehouse=warehouse,
            defaults={
                'quantity': quantity,
                'quantity_blocked': quantity_blocked,
                'price': price,
                'vat_rate': vat_rate,
                'price_without_vat': price_without_vat
            }
        )
        
        if created:
            report['stock_items_created'] += 1
        else:
            # Aktualizujeme hodnoty
            stock_item.quantity = quantity
            stock_item.quantity_blocked = quantity_blocked
            stock_item.price = price
            stock_item.vat_rate = vat_rate
            if price_without_vat is not None:
                stock_item.price_without_vat = price_without_vat
            stock_item.save()
            report['stock_items_updated'] += 1


def _import_menu_templates(root: ET.Element, report: Dict[str, Any]) -> None:
    """Importuje šablony jídelníčků."""
    report['menu_templates_created'] = 0
    report['menu_templates_updated'] = 0
    
    templates_el = root.find("MenuTemplates")
    if templates_el is None:
        return
    
    for temp_el in templates_el:
        name = temp_el.get("name", "").strip()
        if not name:
            continue
        
        description = temp_el.get("description", "").strip()
        xml_content_el = temp_el.find("XmlContent")
        xml_content = xml_content_el.text if xml_content_el is not None else ""
        
        template, created = MenuTemplate.objects.get_or_create(
            name=name,
            defaults={'description': description, 'xml_content': xml_content or ''}
        )
        
        if created:
            report['menu_templates_created'] += 1
        else:
            template.description = description
            template.xml_content = xml_content or ''
            template.save()
            report['menu_templates_updated'] += 1


def _import_menu_plans(root: ET.Element, canteen_map: Dict[str, Canteen], 
                       report: Dict[str, Any]) -> Dict[str, MenuPlan]:
    """Importuje jídelníčky a vrátí mapu název -> objekt."""
    menu_map = {}
    report['menu_plans_created'] = 0
    report['menu_plans_updated'] = 0
    report['menu_plan_coefficients_created'] = 0
    
    menus_el = root.find("MenuPlans")
    if menus_el is None:
        return menu_map
    
    for menu_el in menus_el:
        name = menu_el.get("name", "").strip()
        canteen_name = menu_el.get("canteenName", "").strip()
        
        if not name or canteen_name not in canteen_map:
            continue
        
        canteen = canteen_map[canteen_name]
        date_from = _date_or_none(menu_el.get("dateFrom"))
        date_to = _date_or_none(menu_el.get("dateTo"))
        
        if not date_from or not date_to:
            continue
        
        default_portions_adult = int(menu_el.get("defaultPortionsAdult", "50") or 50)
        default_portions_child = int(menu_el.get("defaultPortionsChild", "30") or 30)
        
        menu, created = MenuPlan.objects.get_or_create(
            name=name,
            canteen=canteen,
            defaults={
                'date_from': date_from,
                'date_to': date_to,
                'default_portions_adult': default_portions_adult,
                'default_portions_child': default_portions_child
            }
        )
        
        if created:
            report['menu_plans_created'] += 1
        else:
            menu.date_from = date_from
            menu.date_to = date_to
            menu.default_portions_adult = default_portions_adult
            menu.default_portions_child = default_portions_child
            menu.save()
            report['menu_plans_updated'] += 1
        
        # Import koeficientů
        coeffs_el = menu_el.find("Coefficients")
        if coeffs_el is not None:
            # Smažeme staré koeficienty a vytvoříme nové
            menu.default_coefficients.all().delete()
            
            for c_el in coeffs_el:
                coeff_name = c_el.get("name", "").strip()
                coefficient = _decimal_or_none(c_el.get("coefficient")) or Decimal('1.0')
                order = int(c_el.get("order", "0") or 0)
                
                MenuPlanCoefficient.objects.create(
                    menu_plan=menu,
                    name=coeff_name,
                    coefficient=coefficient,
                    order=order
                )
                report['menu_plan_coefficients_created'] += 1
        
        menu_map[name] = menu
    
    return menu_map


def _import_production_orders(root: ET.Element, recipe_map: Dict[str, Recipe],
                               menu_map: Dict[str, MenuPlan], canteen_map: Dict[str, Canteen],
                               ingredient_map: Dict[str, Ingredient], report: Dict[str, Any]) -> None:
    """Importuje výrobní příkazy."""
    report['production_orders_created'] = 0
    report['production_orders_updated'] = 0
    report['portion_variants_created'] = 0
    report['ingredient_overrides_created'] = 0
    
    orders_el = root.find("ProductionOrders")
    if orders_el is None:
        return
    
    for order_el in orders_el:
        recipe_code = order_el.get("recipeCode", "").strip()
        menu_name = order_el.get("menuPlanName", "").strip()
        canteen_name = order_el.get("canteenName", "").strip()
        
        if recipe_code not in recipe_map:
            continue
        
        recipe = recipe_map[recipe_code]
        menu_plan = menu_map.get(menu_name)
        canteen = canteen_map.get(canteen_name)
        
        date = _date_or_none(order_el.get("date"))
        if not date:
            continue
        
        meal_type = order_el.get("mealType", "LUNCH")
        selling_vat_rate = _decimal_or_none(order_el.get("sellingVatRate")) or Decimal('12')
        
        # Najdeme nebo vytvoříme výrobní příkaz
        order, created = ProductionOrder.objects.get_or_create(
            recipe=recipe,
            menu_plan=menu_plan,
            date=date,
            defaults={
                'canteen': canteen,
                'meal_type': meal_type,
                'selling_vat_rate': selling_vat_rate
            }
        )
        
        if created:
            report['production_orders_created'] += 1
        else:
            order.canteen = canteen
            order.meal_type = meal_type
            order.selling_vat_rate = selling_vat_rate
            order.save()
            report['production_orders_updated'] += 1
        
        # Smažeme staré varianty a override a vytvoříme nové
        order.portion_variants.all().delete()
        order.ingredient_overrides.all().delete()
        
        # Import variant porcí
        variants_el = order_el.find("PortionVariants")
        if variants_el is not None:
            for v_el in variants_el:
                name = v_el.get("name", "")
                coefficient = _decimal_or_none(v_el.get("coefficient")) or Decimal('1.0')
                portions = int(v_el.get("portions", "0") or 0)
                order_num = int(v_el.get("order", "0") or 0)
                
                ProductionOrderPortionVariant.objects.create(
                    production_order=order,
                    name=name,
                    coefficient=coefficient,
                    portions=portions,
                    order=order_num
                )
                report['portion_variants_created'] += 1
        
        # Import override ingrediencí
        overrides_el = order_el.find("IngredientOverrides")
        if overrides_el is not None:
            for o_el in overrides_el:
                ing_name = o_el.get("ingredientName", "").strip()
                if ing_name not in ingredient_map:
                    continue
                
                ingredient = ingredient_map[ing_name]
                quantity_per_portion = _decimal_or_none(o_el.get("quantityPerPortion"))
                original_quantity = _decimal_or_none(o_el.get("originalQuantity")) or Decimal('0')
                is_added = o_el.get("isAdded", "false").lower() == "true"
                is_removed = o_el.get("isRemoved", "false").lower() == "true"
                
                ProductionOrderIngredientOverride.objects.create(
                    production_order=order,
                    ingredient=ingredient,
                    quantity_per_portion=quantity_per_portion,
                    original_quantity=original_quantity,
                    is_added=is_added,
                    is_removed=is_removed
                )
                report['ingredient_overrides_created'] += 1


# ============================================================================
# HLAVNÍ IMPORT FUNKCE
# ============================================================================

def import_backup_xml(xml_content: bytes, dry_run: bool = False) -> Dict[str, Any]:
    """
    Importuje zálohu z XML. Importuje pouze entity přítomné v XML.
    
    Args:
        xml_content: XML obsah jako bytes.
        dry_run: Pokud True, změny nejsou uloženy do databáze.
    
    Returns:
        Report o importu jako slovník.
    """
    report = {
        # Existující klíče pro zpětnou kompatibilitu
        "categories_created": 0,
        "categories_updated": 0,
        "ingredients_created": 0,
        "ingredients_updated": 0,
        "recipes_created": 0,
        "recipes_updated": 0,
        "recipe_ingredients_created": 0,
        "recipe_ingredients_updated": 0,
        "missing_references": [],
        # Nové klíče
        "canteens_created": 0,
        "canteens_updated": 0,
        "warehouses_created": 0,
        "warehouses_updated": 0,
        "suppliers_created": 0,
        "suppliers_updated": 0,
        "supplier_templates_created": 0,
        "stock_items_created": 0,
        "stock_items_updated": 0,
        "menu_templates_created": 0,
        "menu_templates_updated": 0,
        "menu_plans_created": 0,
        "menu_plans_updated": 0,
        "menu_plan_coefficients_created": 0,
        "production_orders_created": 0,
        "production_orders_updated": 0,
        "portion_variants_created": 0,
        "ingredient_overrides_created": 0,
        "goods_receipts_created": 0,
        "stock_transfers_created": 0,
        "inventory_verifications_created": 0,
        "stock_write_offs_created": 0,
    }
    
    root = ET.fromstring(xml_content)
    
    with transaction.atomic():
        # Základní entity (vždy importujeme pokud jsou v XML)
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
        
        # Build category map
        cat_map: Dict[str, Category] = {c.code: c for c in Category.objects.all()}
        
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
            # Obnovení deaktivované suroviny
            is_active = ing_el.get("isActive", "true").lower() != "false"
            if not ing.is_active and is_active:
                ing.is_active = True
                ing.deactivated_at = None
                ing.deactivated_by = None
                changed = True
            if changed or created:
                ing.save()
                if changed and not created:
                    report["ingredients_updated"] += 1
        
        # Build ingredient map
        ingredient_map: Dict[str, Ingredient] = {i.name: i for i in Ingredient.objects.all()}
        
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
                if category_code in cat_map:
                    recipe.category = cat_map[category_code]
                    changed = True
                else:
                    report["missing_references"].append(f"Category {category_code} for recipe {code}")
            
            if base_portions:
                bp = _decimal_or_none(base_portions)
                if bp is not None and recipe.base_portions is None:
                    recipe.base_portions = int(bp)
                    changed = True
            
            if selling_vat_rate:
                svr = _decimal_or_none(selling_vat_rate)
                if svr is not None:
                    recipe.selling_vat_rate = svr
                    changed = True
            
            if changed or created:
                recipe.save()
                if changed and not created:
                    report["recipes_updated"] += 1
            
            # Recipe ingredients
            r_ingredients_el = rec_el.find("Ingredients") or []
            for ri_el in r_ingredients_el:
                ing_name = ri_el.get("name", "").strip()
                if ing_name not in ingredient_map:
                    report["missing_references"].append(f"Ingredient {ing_name} for recipe {code}")
                    continue
                ingredient = ingredient_map[ing_name]
                qpp = ri_el.get("quantityPerPortion", "").strip()
                notes = ri_el.get("notes", "")
                
                ri, ri_created = RecipeIngredient.objects.get_or_create(
                    recipe=recipe, ingredient=ingredient
                )
                if ri_created:
                    report["recipe_ingredients_created"] += 1
                
                ri_changed = False
                if qpp:
                    qpp_val = _decimal_or_none(qpp)
                    if qpp_val is not None:
                        ri.quantity_per_portion = qpp_val
                        ri_changed = True
                if notes:
                    ri.notes = notes
                    ri_changed = True
                
                if ri_changed:
                    ri.save()
                    if not ri_created:
                        report["recipe_ingredients_updated"] += 1
        
        # Build recipe map
        recipe_map: Dict[str, Recipe] = {r.code: r for r in Recipe.objects.all()}
        
        # Canteens (volitelné)
        canteen_map = _import_canteens(root, report)
        
        # Warehouses (volitelné, závisí na canteens)
        warehouse_map = _import_warehouses(root, canteen_map, report)
        
        # Suppliers (volitelné)
        supplier_map = _import_suppliers(root, report)
        
        # Stock items (volitelné, závisí na ingredients a warehouses)
        _import_stock_items(root, ingredient_map, warehouse_map, report)
        
        # Menu templates (volitelné)
        _import_menu_templates(root, report)
        
        # Menu plans (volitelné, závisí na canteens)
        menu_map = _import_menu_plans(root, canteen_map, report)
        
        # Production orders (volitelné, závisí na recipes, menu_plans, canteens)
        _import_production_orders(root, recipe_map, menu_map, canteen_map, ingredient_map, report)
        
        # Goods receipts, stock transfers, inventory verifications, write-offs
        # Tyto entity jsou komplexní a obvykle se neimportují (jsou pro exportní účely)
        # Pokud by byly v XML, pouze je započítáme ale neimportujeme detaily
        
        goods_receipts_el = root.find("GoodsReceipts")
        if goods_receipts_el is not None:
            report["goods_receipts_created"] = 0  # Nepodporujeme import
        
        stock_transfers_el = root.find("StockTransfers")
        if stock_transfers_el is not None:
            report["stock_transfers_created"] = 0  # Nepodporujeme import
        
        inventory_el = root.find("InventoryVerifications")
        if inventory_el is not None:
            report["inventory_verifications_created"] = 0  # Nepodporujeme import
        
        writeoffs_el = root.find("StockWriteOffs")
        if writeoffs_el is not None:
            report["stock_write_offs_created"] = 0  # Nepodporujeme import
        
        if dry_run:
            raise Exception("Dry-run: changes rolled back")
    
    return report


# ============================================================================
# POMOCNÉ FUNKCE PRO UI
# ============================================================================

def get_entity_choices() -> List[Dict[str, Any]]:
    """
    Vrátí seznam entit pro výběr v UI.
    
    Returns:
        Seznam slovníků s klíči: key, label, dependencies, category
    """
    categories = {
        'basic': 'Základní data',
        'reference': 'Referenční data',
        'stock': 'Skladové operace',
        'production': 'Výroba',
    }
    
    entity_categories = {
        ENTITY_INGREDIENTS: 'basic',
        ENTITY_CATEGORIES: 'basic',
        ENTITY_RECIPES: 'basic',
        ENTITY_CANTEENS: 'reference',
        ENTITY_WAREHOUSES: 'reference',
        ENTITY_SUPPLIERS: 'reference',
        ENTITY_STOCK_ITEMS: 'stock',
        ENTITY_GOODS_RECEIPTS: 'stock',
        ENTITY_STOCK_TRANSFERS: 'stock',
        ENTITY_INVENTORY_VERIFICATIONS: 'stock',
        ENTITY_STOCK_WRITE_OFFS: 'stock',
        ENTITY_MENU_TEMPLATES: 'production',
        ENTITY_MENU_PLANS: 'production',
        ENTITY_PRODUCTION_ORDERS: 'production',
    }
    
    result = []
    for entity in ALL_ENTITIES:
        result.append({
            'key': entity,
            'label': ENTITY_LABELS.get(entity, entity),
            'dependencies': ENTITY_DEPENDENCIES.get(entity, []),
            'category': categories.get(entity_categories.get(entity, 'other'), 'Ostatní'),
        })
    
    return result


def validate_entity_selection(selected: List[str]) -> Dict[str, Any]:
    """
    Validuje výběr entit a vrátí informace o závislostech.
    
    Returns:
        Slovník s klíči: valid, missing_dependencies, required_entities, warnings
    """
    required = get_required_entities(selected)
    missing = required - set(selected)
    
    return {
        'valid': True,  # Vždy validní, závislosti se automaticky přidají
        'missing_dependencies': list(missing),
        'required_entities': list(required),
        'warnings': [
            f"Pro správnou funkci bude automaticky přidáno: {ENTITY_LABELS.get(m, m)}"
            for m in missing
        ] if missing else []
    }
