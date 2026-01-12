"""
Views pro správu XML šablon jídelníčků a import flow.
"""

from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.contrib import messages
from django.urls import reverse_lazy, reverse
from django.views.generic import ListView, CreateView, UpdateView, DeleteView
from django.http import JsonResponse, HttpResponse
from django.db import transaction
from django.core.exceptions import ValidationError
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Dict

from .models import MenuTemplate, MenuPlan, ProductionOrder, ProductionOrderPortionVariant
from .forms import MenuTemplateForm, MenuImportForm
from apps.core.models import Recipe, RecipeIngredient, Ingredient, Category
from apps.canteens.models import Canteen


# --- Helper funkce ---

def _convert_decimals_to_float(obj):
    """
    Rekurzivně konvertuje všechny Decimal objekty na float pro JSON serializaci.
    Používá se před uložením dat do session.
    """
    if isinstance(obj, Decimal):
        return float(obj)
    elif isinstance(obj, dict):
        return {key: _convert_decimals_to_float(value) for key, value in obj.items()}
    elif isinstance(obj, list):
        return [_convert_decimals_to_float(item) for item in obj]
    else:
        return obj


# --- Šablony jídelníčků ---

class MenuTemplateListView(LoginRequiredMixin, ListView):
    """Seznam všech XML šablon jídelníčků"""
    model = MenuTemplate
    template_name = 'production/menu_template_list.html'
    context_object_name = 'templates'
    paginate_by = 20
    
    def get_queryset(self):
        return MenuTemplate.objects.all().order_by('-created_at')


class IsStaffMixin(UserPassesTestMixin):
    """Mixin pro kontrolu, zda je uživatel staff"""
    def test_func(self):
        return self.request.user.is_staff


class MenuTemplateCreateView(LoginRequiredMixin, IsStaffMixin, CreateView):
    """Vytvoření nové XML šablony jídelníčku"""
    model = MenuTemplate
    form_class = MenuTemplateForm
    template_name = 'production/menu_template_form.html'
    success_url = reverse_lazy('production:template_list')
    
    def form_valid(self, form):
        messages.success(self.request, f'Šablona "{form.instance.name}" byla úspěšně vytvořena.')
        return super().form_valid(form)


class MenuTemplateUpdateView(LoginRequiredMixin, IsStaffMixin, UpdateView):
    """Úprava existující XML šablony"""
    model = MenuTemplate
    form_class = MenuTemplateForm
    template_name = 'production/menu_template_form.html'
    success_url = reverse_lazy('production:template_list')
    
    def form_valid(self, form):
        messages.success(self.request, f'Šablona "{form.instance.name}" byla úspěšně aktualizována.')
        return super().form_valid(form)


class MenuTemplateDeleteView(LoginRequiredMixin, IsStaffMixin, DeleteView):
    """Smazání XML šablony"""
    model = MenuTemplate
    template_name = 'production/menu_template_confirm_delete.html'
    success_url = reverse_lazy('production:template_list')
    
    def form_valid(self, form):
        template_name = self.object.name
        messages.success(self.request, f'Šablona "{template_name}" byla úspěšně smazána.')
        return super().form_valid(form)


@login_required
def duplicate_template(request, pk):
    """Duplikace existující šablony"""
    if not request.user.is_staff:
        messages.error(request, 'Nemáte oprávnění k této akci.')
        return redirect('production:template_list')
    
    if request.method != 'POST':
        messages.error(request, 'Neplatná metoda.')
        return redirect('production:template_list')
    
    original = get_object_or_404(MenuTemplate, pk=pk)
    
    # Vytvoříme kopii
    duplicate = MenuTemplate.objects.create(
        name=f"{original.name} (kopie)",
        description=original.description,
        xml_content=original.xml_content
    )
    
    messages.success(
        request,
        f'Šablona "{original.name}" byla zkopírována jako "{duplicate.name}". '
        f'Nyní ji můžete upravit.'
    )
    
    return redirect('production:template_edit', pk=duplicate.pk)


# --- Import jídelníčku ---

@login_required
def menu_import_step1(request):
    """Krok 1: Výběr šablony nebo nahrání souboru"""
    
    if request.method == 'POST':
        form = MenuImportForm(request.POST, request.FILES, user=request.user)
        
        if form.is_valid():
            # Uložíme data do session (konvertujeme Decimal na float pro JSON serializaci)
            parsed_xml = _convert_decimals_to_float(form.cleaned_data['parsed_xml'])
            
            request.session['import_data'] = {
                'parsed_xml': parsed_xml,
                'canteen_id': form.cleaned_data['canteen'].id,
                'start_date': form.cleaned_data['start_date'].isoformat(),
                'menu_name': form.cleaned_data['menu_name'],
            }
            
            return redirect('production:menu_import_step2')
    else:
        # Předvyplníme template_id pokud je v GET parametru
        initial = {}
        template_id = request.GET.get('template')
        if template_id:
            initial['import_source'] = 'template'
            initial['template'] = template_id
        
        form = MenuImportForm(initial=initial, user=request.user)
    
    return render(request, 'production/menu_import_step1.html', {
        'form': form,
    })


@login_required
def menu_import_step2_preview(request):
    """Krok 2: Náhled importovaných dat a nastavení koeficientů"""
    from .forms import MenuPlanCoefficientFormSet
    
    # Načteme data ze session
    import_data = request.session.get('import_data')
    if not import_data:
        messages.error(request, 'Session vypršela. Začněte prosím znovu.')
        return redirect('production:menu_import_step1')
    
    parsed_xml = import_data['parsed_xml']
    canteen = get_object_or_404(Canteen, id=import_data['canteen_id'])
    start_date = date.fromisoformat(import_data['start_date'])
    
    # Zpracování POST - uložení koeficientů do session a přesměrování na krok 3
    if request.method == 'POST':
        # Vytvoříme dočasný MenuPlan objekt pro validaci formset
        temp_menu_plan = MenuPlan(
            name=import_data['menu_name'],
            canteen=canteen,
            date_from=start_date,
            date_to=start_date
        )
        
        formset = MenuPlanCoefficientFormSet(request.POST, instance=temp_menu_plan)
        
        if formset.is_valid():
            # Uložíme koeficienty do session (konvertujeme Decimal na float)
            coefficients_data = []
            for idx, form in enumerate(formset):
                if form.cleaned_data and not form.cleaned_data.get('DELETE', False):
                    # Načteme počet porcí z POST dat
                    portions_key = f'portions_{idx}'
                    portions = int(request.POST.get(portions_key, 0))
                    
                    coefficients_data.append({
                        'name': form.cleaned_data['name'],
                        'coefficient': float(form.cleaned_data['coefficient']),
                        'order': form.cleaned_data['order'],
                        'portions': portions,
                    })
            
            import_data['coefficients'] = coefficients_data
            request.session['import_data'] = import_data
            request.session.modified = True
            
            return redirect('production:menu_import_step3')
        else:
            # Pokud formset není validní, zobrazíme chyby
            for form in formset:
                if form.errors:
                    for field, errors in form.errors.items():
                        for error in errors:
                            messages.error(request, f'{field}: {error}')
    else:
        # GET - zobrazíme formset s výchozími hodnotami
        temp_menu_plan = MenuPlan(
            name=import_data['menu_name'],
            canteen=canteen,
            date_from=start_date,
            date_to=start_date
        )
        
        # Zkontrolujeme, jestli už máme koeficienty v session
        saved_coefficients = import_data.get('coefficients', [])
        if saved_coefficients:
            # Načteme koeficienty ze session
            initial_data = []
            for coef in saved_coefficients:
                initial_data.append({
                    'name': coef['name'],
                    'coefficient': Decimal(str(coef['coefficient'])),
                    'order': coef['order']
                })
            formset = MenuPlanCoefficientFormSet(instance=temp_menu_plan, initial=initial_data)
        else:
            # Výchozí koeficienty
            formset = MenuPlanCoefficientFormSet(
                instance=temp_menu_plan,
                initial=[
                    {'name': 'Vedoucí', 'coefficient': Decimal('1.0'), 'order': 0},
                    {'name': 'Děti', 'coefficient': Decimal('0.75'), 'order': 1}
                ]
            )
    
    # Vytvoříme mapování recipe_code -> název receptu
    recipe_name_map = {recipe['code']: recipe['name'] for recipe in parsed_xml['recipes']}
    
    # Připravíme harmonogram - rozbalíme meals do plochého seznamu pro zobrazení
    schedule_for_display = []
    for day_idx, day in enumerate(parsed_xml['schedule'], start=1):
        for meal_idx, meal in enumerate(day['meals']):
            recipe_code = meal['recipe_code']
            schedule_for_display.append({
                'day': day_idx,  # Číslo dne (1, 2, 3, ...)
                'day_name': day['name'],  # Název dne (např. "Den 1")
                'date': start_date + timedelta(days=day['date_offset']),
                'meal_type': meal['meal_type'],
                'recipe_code': recipe_code,
                'recipe_name': recipe_name_map.get(recipe_code, recipe_code),  # Název nebo fallback na kód
                'portions': meal['portion_count'] or 50,
                'date_offset': day['date_offset'],
                'meal_index': meal_idx,  # Index jídla v rámci dne pro identifikaci ve formuláři
            })
    
    # Spočítáme počet unikátních dnů
    unique_days = len(parsed_xml['schedule'])
    
    return render(request, 'production/menu_import_preview.html', {
        'recipes': parsed_xml['recipes'],
        'schedule': schedule_for_display,
        'warnings': parsed_xml.get('warnings', []),
        'canteen': canteen,
        'start_date': start_date,
        'menu_name': import_data['menu_name'],
        'coefficient_formset': formset,
        'saved_portions': {idx: coef.get('portions', 0) for idx, coef in enumerate(saved_coefficients)},
        'num_days': unique_days,
    })


@login_required
def menu_import_step3_confirm(request):
    """Krok 3: Zobrazení potvrzení (GET) nebo vytvoření jídelníčku (POST)"""
    
    # Načteme data ze session
    import_data = request.session.get('import_data')
    if not import_data:
        messages.error(request, 'Session vypršela. Začněte prosím znovu.')
        return redirect('production:menu_import_step1')
    
    parsed_xml = import_data['parsed_xml']
    canteen = get_object_or_404(Canteen, id=import_data['canteen_id'])
    start_date = date.fromisoformat(import_data['start_date'])
    menu_name = import_data['menu_name']
    coefficients_data = import_data.get('coefficients', [])
    
    # GET - zobrazíme potvrzovací stránku
    if request.method == 'GET':
        # Vypočítáme end_date
        max_offset = max(day['date_offset'] for day in parsed_xml['schedule'])
        end_date = start_date + timedelta(days=max_offset)
        
        # Spočítáme počet jídel
        meals_count = sum(len(day['meals']) for day in parsed_xml['schedule'])
        
        return render(request, 'production/menu_import_confirm.html', {
            'canteen': canteen,
            'menu_name': menu_name,
            'start_date': start_date,
            'end_date': end_date,
            'recipes_count': len(parsed_xml['recipes']),
            'meals_count': meals_count,
            'coefficients': coefficients_data,
        })
    
    # POST - vytvoříme jídelníček
    with transaction.atomic():
        try:
            # Vytvoříme recepty, které ještě neexistují
            recipes_created = 0
            recipes_existing = 0
            
            for recipe_data in parsed_xml['recipes']:
                recipe, created = _get_or_create_recipe(recipe_data)
                if created:
                    recipes_created += 1
                else:
                    recipes_existing += 1
            
            # Vypočítáme end_date z harmonogramu
            max_offset = max(day['date_offset'] for day in parsed_xml['schedule'])
            end_date = start_date + timedelta(days=max_offset)
            
            # Vytvoříme MenuPlan
            menu_plan = MenuPlan.objects.create(
                name=menu_name,
                canteen=canteen,
                date_from=start_date,
                date_to=end_date,
                default_portions_adult=50,  # Výchozí hodnota
                default_portions_child=0
            )
            
            # Vytvoříme koeficienty
            from .models import MenuPlanCoefficient
            for coef_data in coefficients_data:
                MenuPlanCoefficient.objects.create(
                    menu_plan=menu_plan,
                    name=coef_data['name'],
                    coefficient=Decimal(str(coef_data['coefficient'])),
                    order=coef_data['order']
                )
            
            # Vytvoříme ProductionOrders
            orders_created = 0
            for day_idx, day in enumerate(parsed_xml['schedule']):
                actual_date = start_date + timedelta(days=day['date_offset'])
                
                for meal_idx, meal in enumerate(day['meals']):
                    # Najdeme recept
                    try:
                        recipe = Recipe.objects.get(code=meal['recipe_code'])
                    except Recipe.DoesNotExist:
                        messages.warning(
                            request,
                            f'Recept {meal["recipe_code"]} nebyl nalezen a byl přeskočen.'
                        )
                        continue
                    
                    # Vytvoříme ProductionOrder
                    order = ProductionOrder.objects.create(
                        menu_plan=menu_plan,
                        recipe=recipe,
                        canteen=canteen,
                        date=actual_date,
                        meal_type=meal['meal_type']
                    )
                    
                    # Vytvoříme varianty porcí podle definovaných koeficientů
                    if coefficients_data:
                        for coef_data in coefficients_data:
                            # Použijeme počet porcí z koeficientu, pokud je > 0, jinak výchozí z XML
                            portions_for_variant = coef_data.get('portions', 0)
                            if portions_for_variant <= 0:
                                portions_for_variant = meal.get('portion_count') or 50
                            
                            ProductionOrderPortionVariant.objects.create(
                                production_order=order,
                                name=coef_data.get('name', ''),
                                coefficient=Decimal(str(coef_data['coefficient'])),
                                portions=portions_for_variant,
                                order=coef_data['order']
                            )
                    else:
                        # Pokud nejsou definovány koeficienty, vytvoříme výchozí variantu
                        portion_count = meal.get('portion_count') or 50
                        ProductionOrderPortionVariant.objects.create(
                            production_order=order,
                            name='',
                            coefficient=Decimal('1.0'),
                            portions=portion_count,
                            order=0
                        )
                    
                    orders_created += 1
            
            # Vymažeme session data
            del request.session['import_data']
            
            # Success message
            messages.success(
                request,
                f'Jídelníček "{menu_name}" byl úspěšně vytvořen! '
                f'Vytvořeno receptů: {recipes_created}, '
                f'existující recepty: {recipes_existing}, '
                f'jídel v jídelníčku: {orders_created}.'
            )
            
            return redirect('production:menu_detail', pk=menu_plan.pk)
            
        except Exception as e:
            messages.error(request, f'Chyba při vytváření jídelníčku: {str(e)}')
            return redirect('production:menu_import_step1')


def _get_or_create_recipe(recipe_data: Dict[str, Any]) -> tuple:
    """
    Vytvoří recept pokud neexistuje, jinak vrátí existující.
    Vrací (recipe, created).
    """
    code = recipe_data['code']
    
    # Zkusíme najít existující recept
    try:
        recipe = Recipe.objects.get(code=code)
        return (recipe, False)
    except Recipe.DoesNotExist:
        pass
    
    # Vytvoříme nový recept
    
    # Najdeme nebo vytvoříme kategorii
    category_code = recipe_data['category']
    category, _ = Category.objects.get_or_create(
        code=category_code,
        defaults={'name': category_code}
    )
    
    # Vytvoříme recept
    recipe = Recipe.objects.create(
        code=code,
        name=recipe_data['name'],
        category=category,
        base_portions=recipe_data['base_portions'],
        description=f'Automaticky importováno ze šablony'
    )
    
    # Vytvoříme ingredience
    for ing_data in recipe_data['ingredients']:
        # Najdeme nebo vytvoříme ingredienci
        ingredient, _ = Ingredient.objects.get_or_create(
            name=ing_data['name'],
            defaults={
                'unit': 'kg',
                'base_unit': 'kg',
                'recipe_unit': 'g',
                'conversion_factor': Decimal('1000'),
            }
        )
        
        # Vytvoříme vazbu recept-ingredience
        RecipeIngredient.objects.create(
            recipe=recipe,
            ingredient=ingredient,
            quantity_per_portion=ing_data['quantity_per_portion'],
            notes=f"Import: {ing_data['quantity']} {ing_data['unit']} na {recipe_data['base_portions']} porcí"
        )
    
    return (recipe, True)
