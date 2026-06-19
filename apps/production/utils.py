"""
Utility funkce pro production app.
"""
import time
import logging
from decimal import Decimal
from collections import defaultdict
from io import BytesIO
from django.core.files.base import ContentFile
from django.template.loader import render_to_string
from django.db.models import F, Prefetch
from django.utils import timezone

from .models import ProductionOrder, PickingList, PickingListDocument
from apps.inventory.models import StockItem
from apps.core.models import UserProfile

logger = logging.getLogger(__name__)

# Pořadí typů jídel pro řazení ve výdejkách
MEAL_TYPE_ORDER = {
    'BREAKFAST': 0,
    'SNACK_MORNING': 1,
    'LUNCH': 2,
    'SNACK_AFTERNOON': 3,
    'DINNER': 4,
}


def generate_picking_list_pdf_file(document, base_url='/', save=True):
    """
    Vygeneruje PDF soubor pro výdejku a uloží ho do document.pdf_file.
    
    Args:
        document: PickingListDocument instance
        base_url: Base URL pro WeasyPrint (default '/')
        save: Pokud True, uloží PDF do document.pdf_file; pokud False, vrátí BytesIO objekt (default True)
    
    Returns:
        bool: True při úspěchu (pokud save=True)
        BytesIO: PDF soubor v paměti (pokud save=False)
    
    Raises:
        Exception: Při jakékoliv chybě během generování (WeasyPrint missing, MemoryError, atd.)
    """
    try:
        gen_start = time.monotonic()
        
        # Načteme orders s Prefetch filtrovaným na tento dokument
        orders = ProductionOrder.objects.filter(
            picking_list_items__document=document
        ).distinct().select_related(
            'recipe', 'canteen', 'menu_plan'
        ).prefetch_related(
            'portion_variants',
            Prefetch(
                'picking_list_items',
                queryset=PickingList.objects.filter(document=document).select_related('ingredient'),
                to_attr='document_items'
            )
        ).order_by('date', 'recipe__name')

        # Sesbíráme všechny unikátní ingredient IDs jedním průchodem
        all_ingredient_ids = set()
        for order in orders:
            for item in order.document_items:
                all_ingredient_ids.add(item.ingredient_id)

        # Batch načtení skladových zásob
        stock_by_ingredient = defaultdict(list)
        if all_ingredient_ids:
            stock_qs = StockItem.objects.filter(
                ingredient_id__in=all_ingredient_ids,
                warehouse__canteen=document.canteen
            ).select_related('warehouse').annotate(
                available=F('quantity') - F('quantity_blocked')
            )
            for si in stock_qs:
                stock_by_ingredient[si.ingredient_id].append(si)

        # Pomocná funkce pro zpracování skladových zásob
        def _get_stock_info(ingredient_id):
            stock_items = stock_by_ingredient.get(ingredient_id, [])
            available_stock = sum(
                si.available for si in stock_items if si.available > 0
            ) or Decimal('0')
            warehouses_with_stock = []
            for si in stock_items:
                if si.quantity > 0 or si.quantity_blocked > 0:
                    available = si.quantity - si.quantity_blocked
                    warehouses_with_stock.append(
                        (si.warehouse.name, si.quantity, si.quantity_blocked, available)
                    )
            return available_stock, warehouses_with_stock

        # Single-pass agregace
        ingredient_totals = {}
        daily_picking_data = {}

        for order in orders:
            order_ingredients = []

            for item in order.document_items:
                key = item.ingredient_id

                # Agregace pro celkový přehled
                if key in ingredient_totals:
                    ingredient_totals[key]['planned'] += item.quantity_planned
                    ingredient_totals[key]['orders'].append({
                        'date': order.date,
                        'recipe': order.recipe.name,
                        'portions': order.total_portions,
                        'effective_portions': order.total_effective_portions,
                        'quantity': item.quantity_planned
                    })
                else:
                    available_stock, warehouses_with_stock = _get_stock_info(key)

                    ingredient_totals[key] = {
                        'ingredient': item.ingredient,
                        'planned': item.quantity_planned,
                        'unit': item.ingredient.base_unit,
                        'available_stock': available_stock,
                        'has_stock': available_stock > 0,
                        'is_sufficient': available_stock >= item.quantity_planned,
                        'warehouses_info': warehouses_with_stock,
                        'orders': [{
                            'date': order.date,
                            'recipe': order.recipe.name,
                            'portions': order.total_portions,
                            'effective_portions': order.total_effective_portions,
                            'quantity': item.quantity_planned
                        }],
                        'picking_items': []
                    }

                ingredient_totals[key]['picking_items'].append(item)

                # Současně plníme data pro denní přehled
                order_ingredients.append({
                    'ingredient_id': item.ingredient_id,  # Pro pozdější lookup
                    'name': item.ingredient.name,
                    'quantity': item.quantity_planned,
                    'unit': item.ingredient.base_unit,
                    'warehouses_info': ingredient_totals[key]['warehouses_info'],
                })

            # Seřadíme suroviny abecedně
            order_ingredients.sort(key=lambda x: x['name'])

            if order.date not in daily_picking_data:
                daily_picking_data[order.date] = []

            daily_picking_data[order.date].append({
                'recipe_name': order.recipe.name,
                'meal_type': order.meal_type,
                'portions': order.total_portions,
                'ingredients': order_ingredients,
                'is_customized': order.has_overrides
            })

        # Aktualizace is_sufficient po finální agregaci
        for totals in ingredient_totals.values():
            totals['is_sufficient'] = totals['available_stock'] >= totals['planned']
        
        # Aktualizace flagů v daily_picking_data podle finálních hodnot z ingredient_totals
        for date_meals in daily_picking_data.values():
            for meal in date_meals:
                for ing in meal['ingredients']:
                    total_info = ingredient_totals.get(ing['ingredient_id'])
                    if total_info:
                        ing['has_stock'] = total_info['has_stock']
                        ing['is_sufficient'] = total_info['is_sufficient']
        
        # Seřadíme dny a jídla
        sorted_daily_data = sorted(daily_picking_data.items())
        sorted_daily_data = [
            (d, sorted(meals, key=lambda m: MEAL_TYPE_ORDER.get(m.get('meal_type', ''), 99)))
            for d, meals in sorted_daily_data
        ]
        
        # Seřadíme ingredience abecedně
        sorted_ingredients = sorted(ingredient_totals.values(), key=lambda x: x['ingredient'].name)
        
        # Počítáme problematické položky
        missing_count = sum(1 for i in ingredient_totals.values() if not i['has_stock'])
        insufficient_count = sum(1 for i in ingredient_totals.values() if i['has_stock'] and not i['is_sufficient'])

        num_days = len(sorted_daily_data)
        total_items = sum(len(meals) for _, meals in sorted_daily_data)
        
        context = {
            'canteen': document.canteen,
            'date_from': document.date_from,
            'date_to': document.date_to,
            'orders': orders,
            'ingredient_totals': sorted_ingredients,
            'daily_picking_data': sorted_daily_data,
            'total_orders': orders.count(),
            'generated_at': timezone.now(),
            'missing_count': missing_count,
            'insufficient_count': insufficient_count,
            'large_document': total_items > 40,
        }

        data_time = time.monotonic() - gen_start
        
        # Vygenerujeme PDF
        try:
            from weasyprint import HTML
        except OSError as e:
            if "libgobject" in str(e) or "cannot load library" in str(e):
                logger.error(f"WeasyPrint GTK3 libraries missing: {e}")
                raise Exception("WeasyPrint GTK3 knihovny nejsou nainstalovány") from e
            raise e

        html_string = render_to_string('production/picking_list_pdf.html', context)

        pdf_start = time.monotonic()
        html = HTML(string=html_string, base_url=base_url)
        
        # Vygenerujeme PDF do paměti
        pdf_file = BytesIO()
        html.write_pdf(pdf_file)
        pdf_file.seek(0)
        
        if save:
            # Uložíme do FileField
            filename = f"{document.name}_{document.canteen.id}_{timezone.now().strftime('%Y%m%d_%H%M%S')}.pdf"
            document.pdf_file.save(filename, ContentFile(pdf_file.read()), save=False)
            document.pdf_generated_at = timezone.now()
            document.save(update_fields=['pdf_file', 'pdf_generated_at'])

            total_time = time.monotonic() - gen_start
            pdf_time = time.monotonic() - pdf_start
            logger.info(
                f"Picking list PDF file saved: document={document.id}, days={num_days}, "
                f"meals={total_items}, ingredients={len(ingredient_totals)}, "
                f"data={data_time:.2f}s, pdf={pdf_time:.2f}s, total={total_time:.2f}s"
            )
            
            return True
        else:
            # Vrátíme BytesIO objekt pro on-the-fly servování
            total_time = time.monotonic() - gen_start
            pdf_time = time.monotonic() - pdf_start
            logger.info(
                f"Picking list PDF generated on-the-fly: document={document.id}, days={num_days}, "
                f"meals={total_items}, ingredients={len(ingredient_totals)}, "
                f"data={data_time:.2f}s, pdf={pdf_time:.2f}s, total={total_time:.2f}s"
            )
            
            return pdf_file
        
    except MemoryError:
        logger.error(f"MemoryError generating picking list PDF: document={document.id}")
        raise
    except Exception as e:
        logger.exception(f"Error generating picking list PDF file for document {document.id}")
        raise
