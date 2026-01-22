"""
Views pro modul analýzy a statistik jídelny.

Tento modul poskytuje:
- Seznam jídelníčků s průměrnými náklady na jedno jídlo
- Detail jídelníčku s náklady jednotlivých jídel
- Analýza nákladů receptů napříč časem
"""

from django.shortcuts import render, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.db.models import Avg, Count, Q
from django.core.exceptions import ObjectDoesNotExist
from decimal import Decimal

from apps.production.models import MenuPlan, ProductionOrder
from apps.core.models import Recipe, Category
from apps.canteens.models import Canteen
from apps.inventory.models import StockItem


@login_required
def menu_analytics_list(request):
    """
    Zobrazí seznam všech jídelníčků s průměrnými náklady na jedno jídlo.
    Filtruje na managed_canteens uživatele.
    """
    user = request.user
    
    # Superuser vidí všechno, ostatní vidí jen jejich jídelny
    if user.is_superuser:
        menu_plans = MenuPlan.objects.all().select_related('canteen').order_by('-created_at')
    else:
        try:
            user_canteens = user.profile.canteens.all()
            menu_plans = MenuPlan.objects.filter(canteen__in=user_canteens).select_related('canteen').order_by('-created_at')
        except ObjectDoesNotExist:
            menu_plans = MenuPlan.objects.none()
    
    # Pro každý jídelníček vypočítáme analytické údaje
    analytics_data = []
    for menu_plan in menu_plans:
        # Získáme všechny výrobní příkazy pro tento jídelníček
        orders = menu_plan.production_orders.all().select_related('recipe').prefetch_related('portion_variants')
        
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
    }
    
    return render(request, 'analytics/menu_list.html', context)


@login_required
def menu_detail_analytics(request, menu_id):
    """
    Zobrazí detail jídelníčku s náklady pro jednotlivá jídla.
    """
    menu_plan = get_object_or_404(MenuPlan, pk=menu_id)
    
    # Získáme všechny výrobní příkazy pro tento jídelníček
    orders = menu_plan.production_orders.all().select_related('recipe', 'canteen').prefetch_related('portion_variants')
    
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
            
        # Vypočítáme cenu za všechny porce s použitím historických cen a DPH
        price_info = order.recipe.calculate_portion_price(
            canteen, 
            portions=int(portions),
            price_date=order.date,
            vat_rate=order.selling_vat_rate
        )
        
        # Získáme ingredience a jejich ceny (s historickými cenami)
        ingredients_breakdown = []
        for recipe_ingredient in order.recipe.recipeingredient_set.all():
            # Najdeme průměrnou historickou cenu suroviny k datu objednávky
            from apps.inventory.models import IngredientPriceHistory
            warehouses = canteen.warehouses.all()
            prices = []
            for warehouse in warehouses:
                price = IngredientPriceHistory.get_price_at_date(
                    recipe_ingredient.ingredient,
                    warehouse,
                    order.date
                )
                if price > 0:
                    prices.append(price)
            
            avg_price = sum(prices) / len(prices) if prices else Decimal('0')
            
            # Vypočítáme množství a cenu pro tento počet porcí
            quantity_needed = recipe_ingredient.get_quantity_in_base_unit(int(portions), 1.0)
            ingredient_total_cost = quantity_needed * avg_price
            
            ingredients_breakdown.append({
                'ingredient': recipe_ingredient.ingredient,
                'quantity': round(quantity_needed, 3),
                'unit': recipe_ingredient.ingredient.base_unit,
                'price_per_unit': round(avg_price, 2),
                'total_cost': round(ingredient_total_cost, 2),
            })
        
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
            'ingredients': ingredients_breakdown,
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
    # Používáme první jídelnu pro výpočet aktuálních cen
    # (ceny se mohou lišit mezi jídelnami, proto zobrazujeme konkrétní hodnoty)
    canteen = Canteen.objects.first()
    ingredients_breakdown = []
    
    if canteen:
        for recipe_ingredient in recipe.recipeingredient_set.all():
            # Najdeme průměrnou aktuální cenu suroviny (bez historických cen)
            avg_price_data = StockItem.objects.filter(
                ingredient=recipe_ingredient.ingredient,
                warehouse__canteen=canteen
            ).aggregate(avg_price=Avg('price'))
            
            avg_price = avg_price_data.get('avg_price') or Decimal('0')
            
            # Vypočítáme množství a cenu pro 1 porci
            quantity_needed = recipe_ingredient.get_quantity_in_base_unit(1, 1.0)
            ingredient_cost = quantity_needed * avg_price
            
            ingredients_breakdown.append({
                'ingredient': recipe_ingredient.ingredient,
                'quantity': round(quantity_needed, 3),
                'unit': recipe_ingredient.ingredient.base_unit,
                'price_per_unit': round(avg_price, 2),
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
