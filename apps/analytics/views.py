"""
Views pro modul analýzy a statistik jídelny.

Tento modul poskytuje:
- Seznam jídelníčků s průměrnými náklady na jedno jídlo
- Detail jídelníčku s náklady jednotlivých jídel
- Analýza nákladů receptů napříč časem
"""

from django.shortcuts import render, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Avg, Count, Q, Sum, Prefetch
from django.core.exceptions import ObjectDoesNotExist
from decimal import Decimal
from datetime import timedelta
from django.utils import timezone

from apps.production.models import MenuPlan, ProductionOrder
from apps.core.models import Recipe, Category
from apps.canteens.models import Canteen, Warehouse
from apps.inventory.models import StockItem, StockWriteOff, StockWriteOffItem


@login_required
def menu_analytics_list(request):
    """
    Zobrazí seznam všech jídelníčků s průměrnými náklady na jedno jídlo.
    Filtruje na managed_canteens uživatele.
    """
    user = request.user
    
    # Superuser vidí všechno, ostatní vidí jen jejich jídelny
    if user.is_superuser:
        menu_plans_qs = MenuPlan.objects.all().select_related('canteen').order_by('-created_at')
    else:
        try:
            user_canteens = user.profile.canteens.all()
            menu_plans_qs = MenuPlan.objects.filter(canteen__in=user_canteens).select_related('canteen').order_by('-created_at')
        except ObjectDoesNotExist:
            menu_plans_qs = MenuPlan.objects.none()

    # Stránkování: 15 jídelníčků na stránku, aby se nepočítalo vše najednou
    paginator = Paginator(menu_plans_qs, 15)
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)

    # Pro každý jídelníček na aktuální stránce vypočítáme analytické údaje
    analytics_data = []
    for menu_plan in page_obj:
        # Získáme příkazy s minimálním prefetch (jen to co opravdu potřebujeme)
        orders = menu_plan.production_orders.select_related(
            'recipe', 'canteen',
        ).prefetch_related(
            'portion_variants',
            'recipe__recipeingredient_set',
        )

        if not orders.exists():
            continue
            
        # Vypočítáme celkové náklady a průměr
        total_cost = Decimal('0')
        total_meals = 0
        cost_per_person = Decimal('0')  # Součet cen za porci všech jídel
        
        for order in orders:
            # Vypočítáme náklady pro tento výrobní příkaz
            canteen = order.resolved_canteen
            if not canteen:
                continue
                
            # Získáme celkový počet porcí
            portions = order.get_total_effective_portions()
            if portions > 0:
                # Vypočítáme cenu za všechny porce s použitím historických cen
                price_info = order.recipe.calculate_portion_price(
                    canteen, 
                    portions=int(portions),
                    price_date=order.date
                )
                total_cost += price_info['total']
                total_meals += int(portions)
                # Přidáme cenu za porci tohoto jídla do celkové ceny na osobu
                cost_per_person += price_info['per_portion']
        
        # Vypočítáme průměr
        avg_cost_per_meal = total_cost / Decimal(str(total_meals)) if total_meals > 0 else Decimal('0')
        
        analytics_data.append({
            'menu_plan': menu_plan,
            'total_meals': total_meals,
            'total_cost': round(total_cost, 2),
            'avg_cost_per_meal': round(avg_cost_per_meal, 2),
            'cost_per_person': round(cost_per_person, 2),  # Nová metrika: cena na osobu
            'meals_count': orders.count(),
        })
    
    context = {
        'analytics_data': analytics_data,
        'page_obj': page_obj,
        'paginator': paginator,
    }
    
    return render(request, 'analytics/menu_list.html', context)


@login_required
def menu_detail_analytics(request, menu_id):
    """
    Zobrazí detail jídelníčku s náklady pro jednotlivá jídla.
    """
    menu_plan = get_object_or_404(MenuPlan, pk=menu_id)
    
    # Získáme všechny výrobní příkazy pro tento jídelníček
    orders = menu_plan.production_orders.all().select_related('recipe', 'canteen').prefetch_related(
        'portion_variants',
        'recipe__recipeingredient_set__ingredient',
        'canteen__warehouses',
    )
    
    # Pro každý výrobní příkaz vypočítáme náklady
    meals_data = []
    total_cost = Decimal('0')
    total_cost_with_vat = Decimal('0')
    total_vat_amount = Decimal('0')
    total_portions = 0
    cost_per_person = Decimal('0')  # Součet cen za porci všech jídel (bez DPH)
    cost_per_person_with_vat = Decimal('0')  # Součet cen za porci s DPH
    
    for order in orders:
        canteen = order.resolved_canteen
        if not canteen:
            continue
            
        # Získáme celkový počet porcí
        portions = order.get_total_effective_portions()
        if portions <= 0:
            continue
            
        # Vypočítáme cenu za všechny porce i s rozpisem ingrediencí najednou (bez opakovaných dotazů)
        price_info = order.recipe.calculate_portion_price(
            canteen, 
            portions=int(portions),
            price_date=order.date,
            vat_rate=order.selling_vat_rate,
            return_breakdown=True,
        )
        
        meals_data.append({
            'order': order,
            'recipe': order.recipe,
            'date': order.date,
            'portions': int(portions),
            'total_cost': price_info['total'],
            'cost_per_portion': price_info['per_portion'],
            'total_cost_with_vat': price_info.get('total_with_vat', price_info['total']),
            'cost_per_portion_with_vat': price_info.get('per_portion_with_vat', price_info['per_portion']),
            'vat_amount': price_info.get('vat_amount', Decimal('0')),
            'vat_amount_per_portion': price_info.get('vat_amount_per_portion', Decimal('0')),
            'vat_rate': price_info.get('vat_rate', order.selling_vat_rate),
            'ingredients': price_info.get('ingredients', []),
        })
        
        total_cost += price_info['total']
        total_portions += int(portions)
        # Přidáme cenu za porci tohoto jídla do celkové ceny na osobu
        cost_per_person += price_info['per_portion']
        
        # DPH údaje
        if 'total_with_vat' in price_info:
            total_cost_with_vat += price_info['total_with_vat']
            total_vat_amount += price_info['vat_amount']
            cost_per_person_with_vat += price_info['per_portion_with_vat']
        else:
            total_cost_with_vat += price_info['total']
            cost_per_person_with_vat += price_info['per_portion']
    
    avg_cost = total_cost / Decimal(str(total_portions)) if total_portions > 0 else Decimal('0')
    avg_cost_with_vat = total_cost_with_vat / Decimal(str(total_portions)) if total_portions > 0 else Decimal('0')
    
    context = {
        'menu_plan': menu_plan,
        'meals_data': meals_data,
        'total_cost': round(total_cost, 2),
        'total_cost_with_vat': round(total_cost_with_vat, 2),
        'total_vat_amount': round(total_vat_amount, 2),
        'total_portions': total_portions,
        'avg_cost': round(avg_cost, 2),
        'avg_cost_with_vat': round(avg_cost_with_vat, 2),
        'cost_per_person': round(cost_per_person, 2),
        'cost_per_person_with_vat': round(cost_per_person_with_vat, 2),
    }
    
    return render(request, 'analytics/menu_detail.html', context)


@login_required
def recipe_cost_analysis(request):
    """
    Zobrazí analýzu nákladů receptů napříč časem.
    Zobrazuje průměrné náklady pro každý recept na základě historických dat.
    """
    # Filtry
    canteen_id = request.GET.get('canteen')
    category_id = request.GET.get('category')
    
    # Získáme všechny recepty s počtem použití
    recipes_query = Recipe.objects.all().select_related('category').prefetch_related('recipeingredient_set__ingredient')
    
    # Aplikujeme filtry pokud jsou zadány
    if category_id:
        recipes_query = recipes_query.filter(category_id=category_id)
    
    recipes = recipes_query
    
    # Vypočítáme statistiky pro každý recept
    recipes_data = []
    for recipe in recipes:
        # Najdeme všechny výrobní příkazy s tímto receptem
        orders_query = ProductionOrder.objects.filter(recipe=recipe).select_related('canteen', 'menu_plan')
        
        # Aplikujeme filtry pokud jsou zadány
        if canteen_id:
            orders_query = orders_query.filter(
                Q(canteen_id=canteen_id) | Q(menu_plan__canteen_id=canteen_id)
            )
        
        orders = orders_query.all()
        
        if not orders.exists():
            continue
        
        # Vypočítáme průměrné náklady přes všechna použití
        costs_list = []
        usage_dates = []
        
        for order in orders:
            canteen = order.resolved_canteen
            if not canteen:
                continue
            
            portions = order.get_total_effective_portions()
            if portions <= 0:
                continue
            
            # Použijeme historické ceny pro každé datum použití
            price_info = recipe.calculate_portion_price(
                canteen, 
                portions=1,
                price_date=order.date
            )
            costs_list.append(price_info['per_portion'])
            usage_dates.append(order.date)
        
        if not costs_list:
            continue
        
        # Vypočítáme statistiky
        avg_cost = sum(costs_list) / len(costs_list)
        min_cost = min(costs_list)
        max_cost = max(costs_list)
        usage_count = len(costs_list)
        
        # Seřadíme datumy a vezmeme první a poslední
        if usage_dates:
            usage_dates.sort()
            first_used = usage_dates[0]
            last_used = usage_dates[-1]
        else:
            first_used = None
            last_used = None
        
        recipes_data.append({
            'recipe': recipe,
            'avg_cost': round(avg_cost, 2),
            'min_cost': round(min_cost, 2),
            'max_cost': round(max_cost, 2),
            'usage_count': usage_count,
            'first_used': first_used,
            'last_used': last_used,
        })
    
    # Seřadíme podle průměrných nákladů (sestupně)
    recipes_data.sort(key=lambda x: x['avg_cost'], reverse=True)
    
    # Získáme seznam jídelen a kategorií pro filtry
    canteens = Canteen.objects.all()
    categories = Category.objects.all()
    
    context = {
        'recipes_data': recipes_data,
        'canteens': canteens,
        'categories': categories,
        'selected_canteen': canteen_id,
        'selected_category': category_id,
    }
    
    return render(request, 'analytics/recipe_cost_analysis.html', context)


@login_required
def recipe_cost_detail(request, recipe_id):
    """
    Zobrazí detailní analýzu nákladů pro konkrétní recept včetně historie použití.
    """
    recipe = get_object_or_404(Recipe, pk=recipe_id)
    
    # Najdeme všechny výrobní příkazy s tímto receptem
    orders = ProductionOrder.objects.filter(recipe=recipe).select_related('canteen', 'menu_plan').prefetch_related('portion_variants').order_by('-date')
    
    # Vypočítáme náklady pro každé použití
    usage_history = []
    costs_list = []
    costs_with_vat_list = []
    
    for order in orders:
        canteen = order.resolved_canteen
        if not canteen:
            continue
        
        portions = order.get_total_effective_portions()
        if portions <= 0:
            continue
        
        # Použijeme historické ceny pro datum objednávky a DPH z objednávky
        price_info = recipe.calculate_portion_price(
            canteen, 
            portions=1,
            price_date=order.date,
            vat_rate=order.selling_vat_rate
        )
        cost_per_portion = price_info['per_portion']
        costs_list.append(cost_per_portion)
        
        cost_per_portion_with_vat = price_info.get('per_portion_with_vat', cost_per_portion)
        costs_with_vat_list.append(cost_per_portion_with_vat)
        
        usage_history.append({
            'date': order.date,
            'canteen': canteen,
            'menu_plan': order.menu_plan,
            'portions': int(portions),
            'cost_per_portion': cost_per_portion,
            'cost_per_portion_with_vat': cost_per_portion_with_vat,
            'vat_amount_per_portion': price_info.get('vat_amount_per_portion', Decimal('0')),
            'vat_rate': price_info.get('vat_rate', order.selling_vat_rate),
        })
    
    # Vypočítáme statistiky
    if costs_list:
        avg_cost = sum(costs_list) / len(costs_list)
        min_cost = min(costs_list)
        max_cost = max(costs_list)
        avg_cost_with_vat = sum(costs_with_vat_list) / len(costs_with_vat_list)
        min_cost_with_vat = min(costs_with_vat_list)
        max_cost_with_vat = max(costs_with_vat_list)
    else:
        avg_cost = Decimal('0')
        min_cost = Decimal('0')
        max_cost = Decimal('0')
        avg_cost_with_vat = Decimal('0')
        min_cost_with_vat = Decimal('0')
        max_cost_with_vat = Decimal('0')
    
    # Získáme aktuální rozklad surovin
    # Hledáme nejnovější ceny ze všech skladů (IngredientPriceHistory + StockItem fallback)
    ingredients_breakdown = []
    
    for recipe_ingredient in recipe.recipeingredient_set.all():
        from apps.inventory.models import IngredientPriceHistory
        
        # Najdeme nejnovější nenulovou cenu přes všechny sklady
        latest_price_record = IngredientPriceHistory.objects.filter(
            ingredient=recipe_ingredient.ingredient,
            price__gt=0,
        ).order_by('-valid_from').first()
        
        if latest_price_record:
            best_price = latest_price_record.price
        else:
            # Fallback: průměrná nenulová cena ze všech StockItem
            avg_price_data = StockItem.objects.filter(
                ingredient=recipe_ingredient.ingredient,
            ).exclude(price=0).aggregate(avg_price=Avg('price'))
            best_price = avg_price_data.get('avg_price') or Decimal('0')
        
        # Vypočítáme množství v receptových jednotkách a cenu pro 1 porci
        quantity_base = recipe_ingredient.get_quantity_in_base_unit(1, 1.0)
        ingredient_cost = quantity_base * best_price
        
        ingredients_breakdown.append({
            'ingredient': recipe_ingredient.ingredient,
            'quantity': round(recipe_ingredient.quantity_per_portion, 3),
            'unit': recipe_ingredient.ingredient.recipe_unit,
            'price_per_unit': round(best_price, 2),
            'price_per_unit_label': recipe_ingredient.ingredient.base_unit,
            'cost_per_portion': round(ingredient_cost, 2),
        })
    
    context = {
        'recipe': recipe,
        'avg_cost': round(avg_cost, 2),
        'min_cost': round(min_cost, 2),
        'max_cost': round(max_cost, 2),
        'avg_cost_with_vat': round(avg_cost_with_vat, 2),
        'min_cost_with_vat': round(min_cost_with_vat, 2),
        'max_cost_with_vat': round(max_cost_with_vat, 2),
        'usage_count': len(costs_list),
        'usage_history': usage_history,
        'ingredients_breakdown': ingredients_breakdown,
    }
    
    return render(request, 'analytics/recipe_cost_detail.html', context)


@login_required
def write_off_analytics(request):
    """
    Zobrazí analytiku odepisovaného zboží mimo recepty.
    Zahrnuje:
    - Spotřebu podle kategorií (HYGIENE, BUFFET, OTHER)
    - Náklady a výnosy podle kategorií
    - Top 10 nejčastěji odepsaného zboží
    - Trend nákladů v čase
    """
    user = request.user
    
    # Superuser vidí všechno, ostatní vidí jen sklady jejich jídelen
    if user.is_superuser:
        write_offs = StockWriteOff.objects.all().select_related('warehouse', 'created_by')
    else:
        try:
            user_canteens = user.profile.canteens.all()
            warehouse_ids = Canteen.objects.filter(id__in=user_canteens).values_list('warehouse_id', flat=True)
            write_offs = StockWriteOff.objects.filter(warehouse_id__in=warehouse_ids).select_related('warehouse', 'created_by')
        except ObjectDoesNotExist:
            write_offs = StockWriteOff.objects.none()
    
    # Filtry z formuláře
    warehouse_id = request.GET.get('warehouse')
    category = request.GET.get('category')
    date_from = request.GET.get('date_from')
    date_to = request.GET.get('date_to')
    
    if warehouse_id:
        write_offs = write_offs.filter(warehouse_id=warehouse_id)
    if category:
        write_offs = write_offs.filter(category=category)
    if date_from:
        write_offs = write_offs.filter(write_off_date__gte=date_from)
    if date_to:
        write_offs = write_offs.filter(write_off_date__lte=date_to)
    
    # Agregovaná data podle kategorií
    category_stats = {}
    for category_choice in StockWriteOff.Category.choices:
        cat_code = category_choice[0]
        cat_label = category_choice[1]
        cat_items = write_offs.filter(category=cat_code)
        
        total_cost = cat_items.aggregate(total=Sum('items__unit_cost'))['total'] or Decimal('0')
        total_quantity = cat_items.aggregate(total=Sum('items__quantity'))['total'] or 0
        
        if total_quantity > 0 or total_cost > 0:
            category_stats[cat_code] = {
                'label': cat_label,
                'count': cat_items.count(),
                'quantity': total_quantity,
                'total_cost': round(total_cost, 2),
            }
    
    # Top 10 nejčastěji odepsaného zboží
    top_items = StockWriteOffItem.objects.filter(
        write_off__in=write_offs
    ).values('ingredient__name').annotate(
        total_quantity=Sum('quantity'),
        total_cost=Sum('unit_cost'),
        count=Count('id')
    ).order_by('-count')[:10]
    
    # Trend nákladů podle dne (poslední 30 dní)
    thirty_days_ago = timezone.now().date() - timedelta(days=30)
    daily_costs = write_offs.filter(
        write_off_date__gte=thirty_days_ago
    ).values('write_off_date').annotate(
        daily_cost=Sum('items__unit_cost'),
        item_count=Count('items')
    ).order_by('write_off_date')
    
    # Celkové statistiky
    total_stats = {
        'total_write_offs': write_offs.count(),
        'total_cost': round(write_offs.aggregate(total=Sum('items__unit_cost'))['total'] or Decimal('0'), 2),
        'avg_cost_per_write_off': Decimal('0'),
    }
    
    if write_offs.count() > 0:
        total_stats['avg_cost_per_write_off'] = round(total_stats['total_cost'] / write_offs.count(), 2)
    
    # Dostupné sklady pro filtr
    if user.is_superuser:
        available_warehouses = Warehouse.objects.values_list('id', 'name').distinct()
    else:
        available_warehouses = Warehouse.objects.filter(canteen__in=user.profile.canteens.all()).values_list('id', 'name').distinct()
    
    context = {
        'write_offs': write_offs,
        'category_stats': category_stats,
        'top_items': top_items,
        'daily_costs': daily_costs,
        'total_stats': total_stats,
        'available_warehouses': available_warehouses,
        'category_choices': StockWriteOff.Category.choices,
        'selected_warehouse': warehouse_id,
        'selected_category': category,
        'selected_date_from': date_from,
        'selected_date_to': date_to,
    }
    
    return render(request, 'analytics/write_off_analytics.html', context)


@login_required
def cook_analytics(request):
    """
    Analytika podle kuchařů.
    Zobrazuje přehled výdejek přiřazených jednotlivým kuchařům:
    - Počet výdejek
    - Celkové plánované a skutečné náklady (v Kč)
    - Průměrná cena porce
    - Odchylka skutečných nákladů od plánovaných v %
    - Detail výdejek za zvolené období
    """
    from django.contrib.auth import get_user_model
    from apps.production.models import PickingListDocument, PickingList

    User = get_user_model()
    user = request.user

    # Filtry
    date_from_str = request.GET.get('date_from', '')
    date_to_str = request.GET.get('date_to', '')
    canteen_id = request.GET.get('canteen', '')

    # Základní QS dokumentů přístupných tomuto uživateli
    if user.is_superuser:
        docs_qs = PickingListDocument.objects.select_related('cook', 'canteen')
        canteens_qs = Canteen.objects.all().order_by('name')
    else:
        try:
            user_canteens = user.profile.canteens.all()
        except ObjectDoesNotExist:
            user_canteens = Canteen.objects.none()
        docs_qs = PickingListDocument.objects.filter(canteen__in=user_canteens).select_related('cook', 'canteen')
        canteens_qs = user_canteens.order_by('name')

    # Aplikujeme filtry
    if date_from_str:
        docs_qs = docs_qs.filter(date_from__gte=date_from_str)
    if date_to_str:
        docs_qs = docs_qs.filter(date_to__lte=date_to_str)
    if canteen_id:
        docs_qs = docs_qs.filter(canteen_id=canteen_id)

    # Deep prefetch – eliminuje N+1 na production_order a jeho závislosti.
    # Výsledek: konstantní počet DB dotazů bez ohledu na počet výdejek/položek.
    # Zahrnuje i recipeingredient_set__ingredient, které čte calculate_portion_price interně.
    from apps.production.models import PickingList as _PL
    docs_qs = docs_qs.prefetch_related(
        Prefetch(
            'items',
            queryset=_PL.objects.select_related(
                'production_order__recipe',
                'production_order__canteen',
                'production_order__menu_plan__canteen',
            ).prefetch_related(
                'production_order__portion_variants',
                'production_order__recipe__recipeingredient_set__ingredient',
            ),
        )
    )

    UNASSIGNED_KEY = '__unassigned__'
    cook_stats = {}

    # Cache cen: (recipe_id, canteen_id, date) -> Decimal (cena za porci)
    # Zamezuje opakovanému volání calculate_portion_price pro stejnou kombinaci.
    price_cache = {}

    for doc in docs_qs:
        cook = doc.cook
        key = cook.id if cook else UNASSIGNED_KEY
        label = (cook.get_full_name() or cook.username) if cook else '— nepřiřazen —'

        if key not in cook_stats:
            cook_stats[key] = {
                'cook': cook,
                'label': label,
                'doc_count': 0,
                'cost_planned': Decimal('0'),
                'cost_actual': Decimal('0'),
                'total_portions': 0,
                'completed_items': 0,
                'pending_items': 0,
                'documents': [],
            }

        cost_planned = Decimal('0')
        cost_actual = Decimal('0')
        total_portions = 0
        completed = 0
        pending = 0

        # Deduplikace per výrobní příkaz: calculate_portion_price se volá JEDNOU
        # per unikátní (recept, jídelna, datum), ne per každou ingredienci/položku.
        seen_orders = {}  # order_id -> {'cost_per_portion': Decimal, 'eff_portions': int, 'completed_items': int, 'total_items': int}

        for item in doc.items.all():
            if item.status == _PL.Status.COMPLETED:
                completed += 1
            elif item.status == _PL.Status.PENDING:
                pending += 1

            order = item.production_order
            if not order or not order.recipe:
                continue

            canteen = order.resolved_canteen
            if not canteen:
                continue

            order_id = order.pk
            if order_id not in seen_orders:
                eff_portions = int(order.total_effective_portions)
                if eff_portions <= 0:
                    seen_orders[order_id] = None
                    continue

                cache_key = (order.recipe_id, canteen.id, doc.date_from)
                if cache_key not in price_cache:
                    price_info = order.recipe.calculate_portion_price(
                        canteen, portions=1, price_date=doc.date_from
                    )
                    price_cache[cache_key] = price_info['per_portion']

                seen_orders[order_id] = {
                    'cost_per_portion': price_cache[cache_key],
                    'eff_portions': eff_portions,
                    'completed_items': 0,
                    'total_items': 0,
                }

            entry = seen_orders[order_id]
            if entry is None:
                continue

            entry['total_items'] += 1
            if item.status == _PL.Status.COMPLETED:
                entry['completed_items'] += 1

        # Sečteme náklady – jednou per výrobní příkaz
        for entry in seen_orders.values():
            if entry is None:
                continue
            cost_for_order = entry['cost_per_portion'] * entry['eff_portions']
            cost_planned += cost_for_order
            total_portions += entry['eff_portions']
            # Skutečné náklady počítáme jen u plně dokončených výrobních příkazů
            if entry['total_items'] > 0 and entry['completed_items'] == entry['total_items']:
                cost_actual += cost_for_order

        cook_stats[key]['doc_count'] += 1
        cook_stats[key]['cost_planned'] += cost_planned
        cook_stats[key]['cost_actual'] += cost_actual
        cook_stats[key]['total_portions'] += total_portions
        cook_stats[key]['completed_items'] += completed
        cook_stats[key]['pending_items'] += pending

        cook_stats[key]['documents'].append({
            'doc': doc,
            'cost_planned': round(cost_planned, 2),
            'cost_actual': round(cost_actual, 2) if cost_actual > 0 else None,
            'completed': completed,
            'pending': pending,
        })

    # Finalizace – odchylka a řazení (kuchaři abecedně, nepřiřazeno na konec)
    cook_stats_list = []
    for key, data in cook_stats.items():
        cost_planned = data['cost_planned']
        cost_actual = data['cost_actual']
        total_portions = data['total_portions']

        avg_cost_per_portion = (
            cost_actual / Decimal(str(total_portions)) if total_portions > 0 else Decimal('0')
        )
        deviation_pct = (
            round((cost_actual - cost_planned) / cost_planned * 100, 1)
            if cost_planned else Decimal('0')
        )

        data['avg_cost_per_portion'] = round(avg_cost_per_portion, 2)
        data['deviation_pct'] = deviation_pct
        data['cost_planned'] = round(cost_planned, 2)
        data['cost_actual'] = round(cost_actual, 2)
        data['total_portions'] = total_portions
        cook_stats_list.append((key, data))

    cook_stats_list.sort(key=lambda x: (x[0] == UNASSIGNED_KEY, str(x[1]['label'])))

    context = {
        'cook_stats_list': cook_stats_list,
        'canteens': canteens_qs,
        'selected_date_from': date_from_str,
        'selected_date_to': date_to_str,
        'selected_canteen': canteen_id,
    }
    return render(request, 'analytics/cook_analytics.html', context)
