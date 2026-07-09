import difflib
from datetime import date
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from apps.canteens.models import Canteen, Warehouse
from apps.core.models import Ingredient
from apps.core.views import user_can_access_canteen
from apps.inventory.models import StockWriteOff, StockWriteOffItem

from .fiskalpro_parser import parse_bufet_file, parse_export_date
from .models import BufetImport, BufetImportItem

NUMERIC_FIELDS = ('quantity',)
MATCH_THRESHOLD = 0.45


# ---------------------------------------------------------------------------
# Přístupová práva
# ---------------------------------------------------------------------------

def _get_user_canteens(user):
    """
    Vrátí queryset jídelen, ke kterým má uživatel přístup.
    None znamená bez omezení (superuser), prázdný queryset = uživatel bez profilu.
    """
    if user.is_superuser:
        return None
    try:
        return user.profile.canteens.all()
    except ObjectDoesNotExist:
        return Canteen.objects.none()


def _get_user_warehouses(user):
    qs = Warehouse.objects.select_related('canteen').filter(is_transit_warehouse=False)
    canteens = _get_user_canteens(user)
    if canteens is not None:
        qs = qs.filter(canteen__in=canteens)
    return qs


def _filter_imports_for_user(queryset, user):
    canteens = _get_user_canteens(user)
    if canteens is not None:
        queryset = queryset.filter(warehouse__canteen__in=canteens)
    return queryset


def _can_upload(user):
    """Uživatel může nahrávat importy, pokud není v režimu pouze pro čtení."""
    try:
        return not user.profile.is_readonly
    except ObjectDoesNotExist:
        return False


# ---------------------------------------------------------------------------
# Párování surovin
# ---------------------------------------------------------------------------

def _normalize(text: str) -> str:
    """Odstraní diakritiku, převede na malá písmena, ponechá jen alfanumerické znaky."""
    import re
    import unicodedata
    text = unicodedata.normalize('NFD', text)
    text = ''.join(c for c in text if unicodedata.category(c) != 'Mn')
    return re.sub(r'[^a-z0-9 ]', ' ', text.lower()).strip()


def _build_ingredient_name_index(ingredients):
    """Předpočítá normalizované názvy surovin jednou pro celý import (ne pro každou položku)."""
    return [(ing, _normalize(ing.name)) for ing in ingredients]


def _suggest_ingredient(csv_name: str, name_index: list) -> tuple:
    """
    Najde nejlepší shodu suroviny pro položku importu podle názvu.

    Args:
        csv_name: název položky z importu
        name_index: list (Ingredient, normalizovaný_název) (viz _build_ingredient_name_index)

    Returns:
        tuple (Ingredient nebo None, skóre shody 0-100)
    """
    norm_csv = _normalize(csv_name)
    best_score = 0.0
    best = None

    for ingredient, norm_name in name_index:
        score = difflib.SequenceMatcher(None, norm_csv, norm_name).ratio()
        if score > best_score:
            best_score = score
            best = ingredient

    if best_score >= MATCH_THRESHOLD and best is not None:
        return best, round(best_score * 100)
    return None, 0


# ---------------------------------------------------------------------------
# (De)serializace položek pro uložení do session
# ---------------------------------------------------------------------------

def _serialize_bufet_item(raw: dict) -> dict:
    """Připraví agregovanou položku CSV pro uložení do session (JSON-serializovatelné)."""
    return {
        'article_code': raw['article_code'],
        'name': raw['name'],
        'quantity': str(raw['quantity']),
        'unit': raw['unit'],
        'establishments': ', '.join(raw['establishments']),
    }


def _deserialize_bufet_item(item: dict) -> dict:
    """Převede číselná pole položky ze session zpět na Decimal."""
    parsed = dict(item)
    for field in NUMERIC_FIELDS:
        try:
            parsed[field] = Decimal(item[field])
        except (InvalidOperation, TypeError):
            parsed[field] = Decimal('0')
    return parsed


# ---------------------------------------------------------------------------
# Potvrzení importu – helpery
# ---------------------------------------------------------------------------

def _create_bufet_import(warehouse, filename, export_date, user, notes):
    return BufetImport.objects.create(
        warehouse=warehouse,
        filename=filename,
        export_date=export_date,
        status=BufetImport.Status.DRAFT,
        notes=notes,
        created_by=user,
    )


def _create_bufet_import_items(bufet_import, items, post_data):
    for idx, item in enumerate(items):
        parsed = _deserialize_bufet_item(item)
        ingredient_id = post_data.get(f'ingredient_{idx}')
        skip = post_data.get(f'skip_{idx}') == 'on'
        ingredient = None
        if ingredient_id and not skip:
            try:
                ingredient = Ingredient.objects.get(id=ingredient_id)
            except Ingredient.DoesNotExist:
                pass

        BufetImportItem.objects.create(
            bufet_import=bufet_import,
            article_code=parsed['article_code'],
            name=parsed['name'],
            quantity=parsed['quantity'],
            unit=parsed['unit'],
            establishments=parsed['establishments'],
            ingredient=ingredient,
            skip=skip,
        )


def _aggregate_import_items_by_ingredient(bufet_import) -> dict:
    """
    Agreguje množství po surovině — tatáž surovina může být namapována z více artiklů,
    zatímco StockWriteOffItem povoluje jen jeden záznam na dvojici (write_off, ingredient).
    """
    ingredient_data: dict = {}
    for import_item in bufet_import.items.filter(skip=False, ingredient__isnull=False):
        iid = import_item.ingredient_id
        bucket = ingredient_data.setdefault(
            iid,
            {'ingredient': import_item.ingredient, 'quantity': Decimal('0'), 'names': []},
        )
        bucket['quantity'] += import_item.quantity
        bucket['names'].append(import_item.name)
    return ingredient_data


def _create_bufet_write_off(bufet_import, warehouse, export_date, filename, user):
    return StockWriteOff.objects.create(
        warehouse=warehouse,
        category=StockWriteOff.Category.BUFET_SALE,
        write_off_date=export_date,
        notes=f"Import z FiskalPRO: {filename}",
        created_by=user,
        cash_register_import_id=f"bufet_import_{bufet_import.id}",
        imported_at=timezone.now(),
    )


# ---------------------------------------------------------------------------
# Views
# ---------------------------------------------------------------------------

@login_required
def bufet_list(request):
    imports = BufetImport.objects.select_related('warehouse', 'created_by').order_by('-created_at')
    imports = _filter_imports_for_user(imports, request.user)
    return render(request, 'bufet/bufet_list.html', {
        'imports': imports,
        'can_upload': _can_upload(request.user),
    })


@login_required
def bufet_upload_step1(request):
    """Krok 1: Upload CSV souboru a výběr skladu."""
    warehouses = _get_user_warehouses(request.user)

    if request.method == 'POST':
        upload = request.FILES.get('csv_file')
        warehouse_id = request.POST.get('warehouse')

        if not upload or not warehouse_id:
            messages.error(request, 'Musíte vybrat soubor XLSX a sklad.')
            return render(request, 'bufet/bufet_upload_step1.html', {'warehouses': warehouses})

        try:
            warehouse = Warehouse.objects.get(id=warehouse_id)
        except (Warehouse.DoesNotExist, ValueError):
            messages.error(request, 'Vybraný sklad neexistuje.')
            return render(request, 'bufet/bufet_upload_step1.html', {'warehouses': warehouses})

        if not user_can_access_canteen(request.user, warehouse.canteen):
            messages.error(request, 'Nemáte přístup k tomuto skladu.')
            return render(request, 'bufet/bufet_upload_step1.html', {'warehouses': warehouses})

        try:
            items = parse_bufet_file(upload, upload.name)
        except ValueError as e:
            messages.error(request, f'Chyba při načítání souboru: {e}')
            return render(request, 'bufet/bufet_upload_step1.html', {'warehouses': warehouses})

        if not items:
            messages.error(request, 'Soubor neobsahuje žádné prodané položky.')
            return render(request, 'bufet/bufet_upload_step1.html', {'warehouses': warehouses})

        export_date = parse_export_date(upload.name)

        # Uložení do session
        request.session['bufet_warehouse_id'] = warehouse_id
        request.session['bufet_filename'] = upload.name
        request.session['bufet_export_date'] = export_date.isoformat() if export_date else None
        request.session['bufet_items'] = [_serialize_bufet_item(it) for it in items]

        messages.success(request, f'Soubor načten: {len(items)} položek.')
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
    name_index = _build_ingredient_name_index(all_ingredients)

    for item in items:
        ingredient, score = _suggest_ingredient(item['name'], name_index)
        item['suggested_id'] = ingredient.id if ingredient else None
        item['suggested_name'] = ingredient.name if ingredient else None
        item['match_score'] = score

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

    export_date = date.fromisoformat(export_date_str) if export_date_str else timezone.now().date()

    bufet_import = _create_bufet_import(
        warehouse, filename, export_date, request.user, request.POST.get('notes', '')
    )
    _create_bufet_import_items(bufet_import, items, request.POST)

    write_off = _create_bufet_write_off(bufet_import, warehouse, export_date, filename, request.user)
    ingredient_data = _aggregate_import_items_by_ingredient(bufet_import)

    skipped_no_stock = []
    written_off_count = 0

    for data in ingredient_data.values():
        notes = 'Bufet prodej: ' + ', '.join(data['names'])
        try:
            StockWriteOffItem.objects.create(
                write_off=write_off,
                ingredient=data['ingredient'],
                quantity=data['quantity'],
                notes=notes[:200],
                unit_cost=Decimal('0'),  # save() přepíše hodnotou ze skladu
            )
            written_off_count += 1
        except ValidationError as e:
            skipped_no_stock.append(f"{data['ingredient'].name}: {e.message}")

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
        'items': bufet_import.items.select_related('ingredient'),
        'write_off': write_off,
    })
