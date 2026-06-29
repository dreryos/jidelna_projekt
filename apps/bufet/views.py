import difflib
import re
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from apps.canteens.models import Warehouse
from apps.core.models import Ingredient
from apps.core.views import user_can_access_canteen
from apps.inventory.models import StockWriteOff, StockWriteOffItem

from .fiskalpro_parser import parse_export_date, parse_fiskalpro_csv
from .models import BufetImport, BufetImportItem


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _normalize(text: str) -> str:
    """Odstraní diakritiku, převede na malá písmena, ponechá jen alfanumerické znaky."""
    import unicodedata
    text = unicodedata.normalize('NFD', text)
    text = ''.join(c for c in text if unicodedata.category(c) != 'Mn')
    return re.sub(r'[^a-z0-9 ]', ' ', text.lower()).strip()


def _ingredient_match_score(csv_name: str, ingredient_name: str, barcode: str, ingredient_barcode: str) -> float:
    """Vrátí skóre shody 0–1 mezi CSV položkou a surovinou."""
    norm_csv = _normalize(csv_name)
    norm_ing = _normalize(ingredient_name)

    # Přesná shoda EAN má nejvyšší prioritu
    if barcode and ingredient_barcode and barcode == ingredient_barcode:
        return 1.0

    ratio = difflib.SequenceMatcher(None, norm_csv, norm_ing).ratio()
    return ratio


def _suggest_ingredient(csv_name: str, barcode: str, all_ingredients) -> dict | None:
    """Najde nejlepší shodu suroviny pro CSV položku."""
    best_score = 0.0
    best = None

    for ing in all_ingredients:
        ing_barcode = getattr(ing, 'barcode', '') or ''
        score = _ingredient_match_score(csv_name, ing.name, barcode, ing_barcode)
        if score > best_score:
            best_score = score
            best = ing

    if best_score >= 0.45:
        return {'id': best.id, 'name': best.name, 'score': round(best_score * 100)}
    return None


def _get_user_warehouses(user):
    qs = Warehouse.objects.select_related('canteen').filter(is_transit_warehouse=False)
    if not user.is_superuser:
        try:
            user_canteens = user.profile.canteens.all()
            qs = qs.filter(canteen__in=user_canteens)
        except ObjectDoesNotExist:
            return Warehouse.objects.none()
    return qs


# ---------------------------------------------------------------------------
# Views
# ---------------------------------------------------------------------------

@login_required
def bufet_list(request):
    imports = BufetImport.objects.select_related('warehouse', 'created_by').order_by('-created_at')
    if not request.user.is_superuser:
        try:
            user_canteens = request.user.profile.canteens.all()
            imports = imports.filter(warehouse__canteen__in=user_canteens)
        except ObjectDoesNotExist:
            imports = BufetImport.objects.none()
    return render(request, 'bufet/bufet_list.html', {'imports': imports})


@login_required
def bufet_upload_step1(request):
    """Krok 1: Upload CSV souboru a výběr skladu."""
    warehouses = _get_user_warehouses(request.user)

    if request.method == 'POST':
        csv_file = request.FILES.get('csv_file')
        warehouse_id = request.POST.get('warehouse')

        if not csv_file or not warehouse_id:
            messages.error(request, 'Musíte vybrat CSV soubor a sklad.')
            return render(request, 'bufet/bufet_upload_step1.html', {'warehouses': warehouses})

        try:
            warehouse = Warehouse.objects.get(id=warehouse_id)
        except Warehouse.DoesNotExist:
            messages.error(request, 'Vybraný sklad neexistuje.')
            return render(request, 'bufet/bufet_upload_step1.html', {'warehouses': warehouses})

        if not user_can_access_canteen(request.user, warehouse.canteen):
            messages.error(request, 'Nemáte přístup k tomuto skladu.')
            return render(request, 'bufet/bufet_upload_step1.html', {'warehouses': warehouses})

        try:
            items = parse_fiskalpro_csv(csv_file)
        except ValueError as e:
            messages.error(request, f'Chyba při načítání CSV: {e}')
            return render(request, 'bufet/bufet_upload_step1.html', {'warehouses': warehouses})

        export_date = parse_export_date(csv_file.name)

        # Uložení do session
        request.session['bufet_warehouse_id'] = warehouse_id
        request.session['bufet_filename'] = csv_file.name
        request.session['bufet_export_date'] = export_date.isoformat() if export_date else None
        request.session['bufet_items'] = [
            {
                'article_code': it['article_code'],
                'barcode': it['barcode'],
                'name': it['name'],
                'group': it['group'],
                'quantity': str(it['quantity']),
                'unit': it['unit'],
                'total_price_with_vat': str(it['total_price_with_vat']),
                'total_price_without_vat': str(it['total_price_without_vat']),
                'establishments': ', '.join(it['establishments']),
            }
            for it in items
        ]

        messages.success(request, f'CSV načteno: {len(items)} unikátních artiklů.')
        return redirect('bufet:upload_step2')

    return render(request, 'bufet/bufet_upload_step1.html', {'warehouses': warehouses})


@login_required
def bufet_upload_step2(request):
    """Krok 2: Náhled položek a párování se surovinami."""
    items = request.session.get('bufet_items')
    if not items:
        messages.error(request, 'Session vypršela. Začněte znovu.')
        return redirect('bufet:upload_step1')

    warehouse_id = request.session.get('bufet_warehouse_id')
    filename = request.session.get('bufet_filename', '')
    export_date = request.session.get('bufet_export_date')

    all_ingredients = list(Ingredient.objects.filter(is_active=True).order_by('name'))

    # Auto-matching
    for item in items:
        suggestion = _suggest_ingredient(item['name'], item['barcode'], all_ingredients)
        if suggestion:
            item['suggested_id'] = suggestion['id']
            item['suggested_name'] = suggestion['name']
            item['match_score'] = suggestion['score']
        else:
            item['suggested_id'] = None
            item['suggested_name'] = None
            item['match_score'] = 0

    try:
        warehouse = Warehouse.objects.get(id=warehouse_id)
    except Warehouse.DoesNotExist:
        messages.error(request, 'Sklad neexistuje. Začněte znovu.')
        return redirect('bufet:upload_step1')

    return render(request, 'bufet/bufet_upload_step2.html', {
        'items': items,
        'warehouse': warehouse,
        'filename': filename,
        'export_date': export_date,
        'all_ingredients': all_ingredients,
    })


@login_required
@transaction.atomic
def bufet_upload_step3(request):
    """Krok 3: Potvrzení – uložení importu a odepsání ze skladu."""
    if request.method != 'POST':
        return redirect('bufet:upload_step1')

    items = request.session.get('bufet_items')
    if not items:
        messages.error(request, 'Session vypršela. Začněte znovu.')
        return redirect('bufet:upload_step1')

    warehouse_id = request.session.get('bufet_warehouse_id')
    filename = request.session.get('bufet_filename', '')
    export_date_str = request.session.get('bufet_export_date')

    try:
        warehouse = Warehouse.objects.get(id=warehouse_id)
    except Warehouse.DoesNotExist:
        messages.error(request, 'Sklad neexistuje.')
        return redirect('bufet:upload_step1')

    if not user_can_access_canteen(request.user, warehouse.canteen):
        messages.error(request, 'Nemáte přístup k tomuto skladu.')
        return redirect('bufet:upload_step1')

    if warehouse.is_locked:
        messages.error(request, f'Sklad {warehouse.name} je uzamčen inventurou.')
        return redirect('bufet:upload_step1')

    from datetime import date
    export_date = date.fromisoformat(export_date_str) if export_date_str else timezone.now().date()

    # Vytvoření BufetImport záznamu
    bufet_import = BufetImport.objects.create(
        warehouse=warehouse,
        filename=filename,
        export_date=export_date,
        status=BufetImport.Status.DRAFT,
        notes=request.POST.get('notes', ''),
        created_by=request.user,
    )

    # Vytvoření položek
    for idx, item in enumerate(items):
        ingredient_id = request.POST.get(f'ingredient_{idx}')
        skip = request.POST.get(f'skip_{idx}') == 'on'
        ingredient = None
        if ingredient_id and not skip:
            try:
                ingredient = Ingredient.objects.get(id=ingredient_id)
            except Ingredient.DoesNotExist:
                pass

        BufetImportItem.objects.create(
            bufet_import=bufet_import,
            article_code=item['article_code'],
            barcode=item['barcode'],
            name=item['name'],
            group=item['group'],
            quantity=Decimal(item['quantity']),
            unit=item['unit'],
            total_price_with_vat=Decimal(item['total_price_with_vat']),
            total_price_without_vat=Decimal(item['total_price_without_vat']),
            establishments=item['establishments'],
            ingredient=ingredient,
            skip=skip,
        )

    # Vytvoření StockWriteOff a odepsání ze skladu
    write_off = StockWriteOff.objects.create(
        warehouse=warehouse,
        category=StockWriteOff.Category.BUFET_SALE,
        write_off_date=export_date,
        notes=f"Import z FiskalPRO: {filename}",
        created_by=request.user,
        cash_register_import_id=f"bufet_import_{bufet_import.id}",
        imported_at=timezone.now(),
    )

    skipped_no_stock = []
    written_off_count = 0

    for import_item in bufet_import.items.filter(skip=False, ingredient__isnull=False):
        try:
            StockWriteOffItem.objects.create(
                write_off=write_off,
                ingredient=import_item.ingredient,
                quantity=import_item.quantity,
                notes=f"Bufet prodej – {import_item.name} (artikl {import_item.article_code})",
                unit_cost=Decimal('0'),  # save() přepíše hodnotou ze skladu
            )
            written_off_count += 1
        except ValidationError as e:
            skipped_no_stock.append(f"{import_item.name}: {e.message}")

    # Propojení importu s write_off a potvrzení
    bufet_import.write_off_id = write_off.id
    bufet_import.status = BufetImport.Status.CONFIRMED
    bufet_import.save(update_fields=['write_off_id', 'status'])

    # Vyčištění session
    for key in ('bufet_items', 'bufet_warehouse_id', 'bufet_filename', 'bufet_export_date'):
        request.session.pop(key, None)

    if skipped_no_stock:
        messages.warning(
            request,
            f'Import potvrzen. {written_off_count} položek odepsáno. '
            f'{len(skipped_no_stock)} položek přeskočeno (nedostatek na skladě): '
            + '; '.join(skipped_no_stock)
        )
    else:
        messages.success(request, f'Import potvrzen. {written_off_count} položek odepsáno ze skladu.')

    return redirect('bufet:detail', pk=bufet_import.pk)


@login_required
def bufet_detail(request, pk):
    bufet_import = get_object_or_404(BufetImport, pk=pk)
    if not user_can_access_canteen(request.user, bufet_import.warehouse.canteen):
        messages.error(request, 'Nemáte přístup k tomuto záznamu.')
        return redirect('bufet:list')

    write_off = None
    if bufet_import.write_off_id:
        try:
            write_off = StockWriteOff.objects.prefetch_related('items__ingredient').get(
                id=bufet_import.write_off_id
            )
        except StockWriteOff.DoesNotExist:
            pass

    return render(request, 'bufet/bufet_detail.html', {
        'import': bufet_import,
        'write_off': write_off,
    })
