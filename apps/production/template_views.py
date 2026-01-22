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
from django.views.decorators.http import require_POST
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Dict
import json

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
    
    def get_success_url(self):
        # Po vytvoření přesměrujeme na vizuální editor
        return reverse('production:template_visual_edit', kwargs={'pk': self.object.pk})
    
    def form_valid(self, form):
        messages.success(self.request, f'Šablona "{form.instance.name}" byla úspěšně vytvořena. Nyní můžete přidat jídla pomocí vizuálního editoru.')
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


class MenuTemplateCreateVisualView(LoginRequiredMixin, IsStaffMixin, CreateView):
    """Vizuální vytvoření nové šablony s možností importu XML"""
    model = MenuTemplate
    template_name = 'production/menu_template_create_visual.html'
    fields = []  # Nepoužíváme formulář, vše je přes AJAX
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        # Kontrola existence draftu
        draft_key = f'template_draft_{self.request.user.id}'
        if draft_key in self.request.session:
            draft_data = self.request.session[draft_key]
            # Kontrola, zda draft není starší 24 hodin
            from datetime import datetime
            if 'timestamp' in draft_data:
                import time
                draft_timestamp = draft_data['timestamp']
                current_timestamp = time.time()
                # 24 hodin = 86400 sekund
                if current_timestamp - draft_timestamp > 86400:
                    # Draft je starší 24 hodin, smažeme ho
                    del self.request.session[draft_key]
                    context['has_draft'] = False
                else:
                    context['has_draft'] = True
                    context['draft_data'] = draft_data
            else:
                context['has_draft'] = True
                context['draft_data'] = draft_data
        else:
            context['has_draft'] = False
        
        # Připravíme seznam všech receptů pro Select2
        recipes = Recipe.objects.all().order_by('name')
        context['recipe_choices'] = json.dumps([
            {'id': r.code, 'text': r.name}
            for r in recipes
        ])
        
        # Připravíme volby typů jídel
        from .models import ProductionOrder
        context['meal_type_choices'] = [
            {'value': choice[0], 'label': choice[1]}
            for choice in ProductionOrder.MealType.choices
        ]
        context['meal_type_choices_json'] = json.dumps(context['meal_type_choices'])
        
        # Prázdný schedule pro novou šablonu
        context['schedule_dict'] = {}
        context['schedule_dict_json'] = json.dumps({})
        
        # Nastavení pro UI
        context['is_new_template'] = True
        context['max_file_size_mb'] = 5
        context['max_days'] = 30
        
        return context


class MenuTemplateVisualEditView(LoginRequiredMixin, IsStaffMixin, UpdateView):
    """Vizuální editor pro úpravu harmonogramu šablony"""
    model = MenuTemplate
    template_name = 'production/menu_template_visual_edit.html'
    fields = []  # Nepoužíváme formulář
    
    def get_success_url(self):
        return reverse('production:template_visual_edit', kwargs={'pk': self.object.pk})
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        # Načteme schedule jako slovník
        schedule_dict = self.object.parse_schedule_to_dict()
        
        # Převedeme klíče na stringy pro JSON
        import json
        context['schedule_dict'] = schedule_dict
        context['schedule_dict_json'] = json.dumps({str(k): v for k, v in schedule_dict.items()})
        
        # Připravíme seznam všech receptů pro Select2
        recipes = Recipe.objects.all().order_by('name')
        context['recipe_choices'] = json.dumps([
            {'id': r.code, 'text': r.name}
            for r in recipes
        ])
        
        # Připravíme volby typů jídel
        from .models import ProductionOrder
        context['meal_type_choices'] = [
            {'value': choice[0], 'label': choice[1]}
            for choice in ProductionOrder.MealType.choices
        ]
        context['meal_type_choices_json'] = json.dumps(context['meal_type_choices'])
        
        # Statistiky šablony
        context['stats'] = self.object.get_stats()
        
        # Maximum dnů pro UI (můžeme upravit)
        context['max_days'] = 30
        
        return context


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
                    
                    # Vygenerovat picking list pro tento order
                    order.generate_picking_list()
                    
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


# --- AJAX endpointy pro vizuální editor šablon ---

@login_required
@require_POST
def template_add_meal_ajax(request, pk):
    """
    AJAX endpoint pro přidání jídla do dne v šabloně.
    
    Očekává JSON: {
        'day_index': int,
        'recipe_code': str,
        'meal_type': str,
        'note': str (optional),
        'portion_count': int (optional)
    }
    """
    try:
        template = get_object_or_404(MenuTemplate, pk=pk)
        data = json.loads(request.body)
        
        # Validace vstupních dat
        day_index = int(data.get('day_index'))
        recipe_code = data.get('recipe_code', '').strip()
        meal_type = data.get('meal_type', 'LUNCH')
        note = data.get('note', '').strip()
        portion_count = data.get('portion_count')
        
        if not recipe_code:
            return JsonResponse({'success': False, 'error': 'Kód receptu nesmí být prázdný'}, status=400)
        
        # Načteme aktuální schedule
        with transaction.atomic():
            schedule_dict = template.parse_schedule_to_dict()
            
            # Inicializujeme den pokud neexistuje
            if day_index not in schedule_dict:
                schedule_dict[day_index] = []
            
            # Přidáme nové jídlo
            import uuid
            new_meal = {
                'recipe_code': recipe_code,
                'meal_type': meal_type,
                'note': note,
                'unique_id': str(uuid.uuid4()),
                'portion_count': int(portion_count) if portion_count else None
            }
            
            schedule_dict[day_index].append(new_meal)
            
            # Uložíme zpět do XML
            template.update_schedule_from_dict(schedule_dict)
            template.save()
        
        return JsonResponse({
            'success': True,
            'meal': new_meal,
            'stats': template.get_stats()
        })
        
    except ValueError as e:
        return JsonResponse({'success': False, 'error': f'Neplatná data: {str(e)}'}, status=400)
    except ValidationError as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=400)
    except Exception as e:
        return JsonResponse({'success': False, 'error': f'Neočekávaná chyba: {str(e)}'}, status=500)


@login_required
@require_POST
def template_remove_meal_ajax(request, pk):
    """
    AJAX endpoint pro odstranění jídla z dne.
    
    Očekává JSON: {
        'day_index': int,
        'meal_index': int
    }
    """
    try:
        template = get_object_or_404(MenuTemplate, pk=pk)
        data = json.loads(request.body)
        
        day_index = int(data.get('day_index'))
        meal_index = int(data.get('meal_index'))
        
        with transaction.atomic():
            schedule_dict = template.parse_schedule_to_dict()
            
            if day_index not in schedule_dict:
                return JsonResponse({'success': False, 'error': 'Den neexistuje'}, status=404)
            
            if meal_index < 0 or meal_index >= len(schedule_dict[day_index]):
                return JsonResponse({'success': False, 'error': 'Jídlo neexistuje'}, status=404)
            
            # Odstraníme jídlo
            removed_meal = schedule_dict[day_index].pop(meal_index)
            
            # Pokud je den prázdný, odstraníme ho
            if not schedule_dict[day_index]:
                del schedule_dict[day_index]
            
            # Uložíme zpět
            template.update_schedule_from_dict(schedule_dict)
            template.save()
        
        return JsonResponse({
            'success': True,
            'removed_meal': removed_meal,
            'stats': template.get_stats()
        })
        
    except ValueError as e:
        return JsonResponse({'success': False, 'error': f'Neplatná data: {str(e)}'}, status=400)
    except ValidationError as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=400)
    except Exception as e:
        return JsonResponse({'success': False, 'error': f'Neočekávaná chyba: {str(e)}'}, status=500)


@login_required
@require_POST
def template_reorder_ajax(request, pk):
    """
    AJAX endpoint pro přeuspořádání jídel v rámci dne.
    
    Očekává JSON: {
        'day_index': int,
        'meal_indices': [int, int, ...]  # nové pořadí indexů
    }
    """
    try:
        template = get_object_or_404(MenuTemplate, pk=pk)
        data = json.loads(request.body)
        
        day_index = int(data.get('day_index'))
        meal_indices = data.get('meal_indices', [])
        
        if not isinstance(meal_indices, list):
            return JsonResponse({'success': False, 'error': 'meal_indices musí být seznam'}, status=400)
        
        with transaction.atomic():
            schedule_dict = template.parse_schedule_to_dict()
            
            if day_index not in schedule_dict:
                return JsonResponse({'success': False, 'error': 'Den neexistuje'}, status=404)
            
            original_meals = schedule_dict[day_index]
            
            # Validace indexů
            if len(meal_indices) != len(original_meals):
                return JsonResponse({'success': False, 'error': 'Počet indexů neodpovídá počtu jídel'}, status=400)
            
            if set(meal_indices) != set(range(len(original_meals))):
                return JsonResponse({'success': False, 'error': 'Neplatné indexy'}, status=400)
            
            # Přeuspořádáme
            reordered_meals = [original_meals[i] for i in meal_indices]
            schedule_dict[day_index] = reordered_meals
            
            # Uložíme
            template.update_schedule_from_dict(schedule_dict)
            template.save()
        
        return JsonResponse({
            'success': True,
            'stats': template.get_stats()
        })
        
    except ValueError as e:
        return JsonResponse({'success': False, 'error': f'Neplatná data: {str(e)}'}, status=400)
    except ValidationError as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=400)
    except Exception as e:
        return JsonResponse({'success': False, 'error': f'Neočekávaná chyba: {str(e)}'}, status=500)


@login_required
@require_POST
def template_copy_day_ajax(request, pk):
    """
    AJAX endpoint pro zkopírování jídel z jednoho dne do druhého.
    
    Očekává JSON: {
        'source_day': int,
        'target_day': int
    }
    """
    try:
        template = get_object_or_404(MenuTemplate, pk=pk)
        data = json.loads(request.body)
        
        source_day = int(data.get('source_day'))
        target_day = int(data.get('target_day'))
        
        if source_day == target_day:
            return JsonResponse({'success': False, 'error': 'Zdrojový a cílový den nemohou být stejné'}, status=400)
        
        with transaction.atomic():
            schedule_dict = template.parse_schedule_to_dict()
            
            if source_day not in schedule_dict:
                return JsonResponse({'success': False, 'error': 'Zdrojový den neobsahuje žádná jídla'}, status=404)
            
            # Zkopírujeme jídla s novými unique_id
            import uuid
            copied_meals = []
            for meal in schedule_dict[source_day]:
                copied_meal = meal.copy()
                copied_meal['unique_id'] = str(uuid.uuid4())
                copied_meals.append(copied_meal)
            
            # Přidáme/přepíšeme cílový den
            schedule_dict[target_day] = copied_meals
            
            # Uložíme
            template.update_schedule_from_dict(schedule_dict)
            template.save()
        
        return JsonResponse({
            'success': True,
            'copied_meals': copied_meals,
            'stats': template.get_stats()
        })
        
    except ValueError as e:
        return JsonResponse({'success': False, 'error': f'Neplatná data: {str(e)}'}, status=400)
    except ValidationError as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=400)
    except Exception as e:
        return JsonResponse({'success': False, 'error': f'Neočekávaná chyba: {str(e)}'}, status=500)


@login_required
@require_POST
def template_clear_day_ajax(request, pk):
    """
    AJAX endpoint pro vymazání všech jídel z dne.
    
    Očekává JSON: {
        'day_index': int
    }
    """
    try:
        template = get_object_or_404(MenuTemplate, pk=pk)
        data = json.loads(request.body)
        
        day_index = int(data.get('day_index'))
        
        with transaction.atomic():
            schedule_dict = template.parse_schedule_to_dict()
            
            if day_index not in schedule_dict:
                return JsonResponse({'success': False, 'error': 'Den neobsahuje žádná jídla'}, status=404)
            
            # Odstraníme den
            removed_count = len(schedule_dict[day_index])
            del schedule_dict[day_index]
            
            # Uložíme
            template.update_schedule_from_dict(schedule_dict)
            template.save()
        
        return JsonResponse({
            'success': True,
            'removed_count': removed_count,
            'stats': template.get_stats()
        })
        
    except ValueError as e:
        return JsonResponse({'success': False, 'error': f'Neplatná data: {str(e)}'}, status=400)
    except ValidationError as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=400)
    except Exception as e:
        return JsonResponse({'success': False, 'error': f'Neočekávaná chyba: {str(e)}'}, status=500)


# --- AJAX endpointy pro vizuální vytváření šablon ---

@login_required
@require_POST
def template_preview_xml_ajax(request):
    """
    AJAX endpoint pro preview XML souboru před vytvořením šablony.
    
    Očekává JSON: {
        'xml_content': str,
        'filename': str (volitelné)
    }
    
    Vrací: {
        'success': bool,
        'template_name': str (název z XML nebo z filename),
        'recipe_count': int,
        'day_count': int,
        'missing_recipes': [{'code': str, 'name': str, 'ingredients': [...]}],
        'ambiguous_ingredients': [{
            'xml_name': str,
            'matches': [{'id': int, 'name': str, 'similarity': float}]
        }],
        'preview_key': str (klíč do session)
    }
    """
    from .xml_parser import parse_menu_template_xml, fuzzy_match_ingredients
    import time
    
    try:
        data = json.loads(request.body)
        xml_content = data.get('xml_content', '')
        filename = data.get('filename', '')
        
        if not xml_content:
            return JsonResponse({'success': False, 'error': 'XML obsah je prázdný'}, status=400)
        
        # Parsování XML
        parsed_data = parse_menu_template_xml(xml_content)
        
        # Zjistíme, které recepty chybí v databázi
        existing_recipe_codes = set(Recipe.objects.values_list('code', flat=True))
        missing_recipes = []
        
        for recipe_data in parsed_data.get('recipes', []):
            if recipe_data['code'] not in existing_recipe_codes:
                missing_recipes.append({
                    'code': recipe_data['code'],
                    'name': recipe_data['name'],
                    'category': recipe_data.get('category', ''),
                    'ingredients': recipe_data.get('ingredients', [])
                })
        
        # Najdeme ambiguózní ingredience (více matchů s 70%+)
        ambiguous_ingredients = []
        seen_ingredients = set()
        
        for recipe_data in parsed_data.get('recipes', []):
            for ingredient_data in recipe_data.get('ingredients', []):
                ing_name = ingredient_data['name']
                
                # Přeskočíme pokud jsme už tuto ingredienci zpracovali
                if ing_name in seen_ingredients:
                    continue
                seen_ingredients.add(ing_name)
                
                # Fuzzy matching
                matches = fuzzy_match_ingredients(ing_name, threshold=70)
                
                # Pokud jsou 2+ matche, je to ambiguózní
                if len(matches) >= 2:
                    ambiguous_ingredients.append({
                        'xml_name': ing_name,
                        'matches': [
                            {
                                'id': match[0].id,
                                'name': match[0].name,
                                'similarity': round(match[1], 1)
                            }
                            for match in matches[:5]  # Max 5 kandidátů
                        ]
                    })
        
        # Extrahovat název šablony z filename nebo použít výchozí
        template_name = filename.replace('.xml', '') if filename else 'Nová šablona'
        
        # Uložit do session pro pozdější použití
        timestamp = time.time()
        preview_key = f'xml_preview_data_{timestamp}'
        request.session[preview_key] = {
            'xml_content': xml_content,
            'parsed_data': _convert_decimals_to_float(parsed_data),
            'template_name': template_name,
            'timestamp': timestamp
        }
        
        return JsonResponse({
            'success': True,
            'template_name': template_name,
            'recipe_count': len(parsed_data.get('recipes', [])),
            'day_count': len(parsed_data.get('schedule', [])),
            'missing_recipes': missing_recipes,
            'ambiguous_ingredients': ambiguous_ingredients,
            'preview_key': preview_key,
            'warnings': parsed_data.get('warnings', [])
        })
        
    except ValidationError as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=400)
    except Exception as e:
        return JsonResponse({'success': False, 'error': f'Chyba při parsování XML: {str(e)}'}, status=500)


@login_required
@require_POST
def template_create_ajax(request):
    """
    AJAX endpoint pro vytvoření šablony z preview dat nebo prázdné šablony.
    
    Očekává JSON: {
        'name': str,
        'days': int (pro prázdnou šablonu),
        'preview_key': str (volitelné, pro XML import),
        'create_missing_recipes': bool (volitelné),
        'ingredient_mappings': {xml_name: db_ingredient_id} (volitelné)
    }
    
    Vrací: {
        'success': bool,
        'template_id': int,
        'created_recipes': int,
        'created_ingredients': int,
        'validation_summary': {...}
    }
    """
    from .xml_parser import create_empty_template_xml, fuzzy_match_ingredients, validate_units
    
    try:
        data = json.loads(request.body)
        name = data.get('name', '').strip()
        days = data.get('days')
        preview_key = data.get('preview_key')
        create_missing_recipes = data.get('create_missing_recipes', False)
        ingredient_mappings = data.get('ingredient_mappings', {})
        
        if not name:
            return JsonResponse({'success': False, 'error': 'Název šablony je povinný'}, status=400)
        
        # Kontrola duplicity názvu
        if MenuTemplate.objects.filter(name__iexact=name).exists():
            return JsonResponse({
                'success': False,
                'error': f'Šablona s názvem "{name}" již existuje. Prosím zvolte jiný název.'
            }, status=400)
        
        created_recipes_count = 0
        created_ingredients_count = 0
        xml_content = None
        
        with transaction.atomic():
            # Scénář 1: XML import z preview
            if preview_key and preview_key in request.session:
                preview_data = request.session[preview_key]
                xml_content = preview_data['xml_content']
                parsed_data = preview_data['parsed_data']
                
                # Pokud chceme vytvořit chybějící recepty
                if create_missing_recipes:
                    existing_recipe_codes = set(Recipe.objects.values_list('code', flat=True))
                    recipes_to_create = []
                    ingredients_to_create = []
                    recipe_ingredients_to_create = []
                    
                    for recipe_data in parsed_data.get('recipes', []):
                        if recipe_data['code'] not in existing_recipe_codes:
                            # Získat kategorii
                            category = None
                            category_code = recipe_data.get('category', '')
                            if category_code:
                                try:
                                    category = Category.objects.get(code=category_code)
                                except Category.DoesNotExist:
                                    pass  # Necháme None
                            
                            # Vytvořit recept
                            recipe = Recipe(
                                code=recipe_data['code'],
                                name=recipe_data['name'],
                                category=category,
                                base_portions=recipe_data.get('base_portions', 10)
                            )
                            recipes_to_create.append(recipe)
                            
                            # Zpracovat ingredience
                            for ing_data in recipe_data.get('ingredients', []):
                                ing_name = ing_data['name']
                                unit = ing_data.get('unit', 'kg')
                                
                                # Validace jednotky
                                if not validate_units(unit):
                                    return JsonResponse({
                                        'success': False,
                                        'error': f'Neplatná jednotka "{unit}" u ingredience "{ing_name}"'
                                    }, status=400)
                                
                                # Najít nebo vytvořit ingredienci
                                ingredient = None
                                
                                # 1. Pokud máme mapping od uživatele, použijeme ho
                                if ing_name in ingredient_mappings:
                                    ing_id = ingredient_mappings[ing_name]
                                    try:
                                        ingredient = Ingredient.objects.get(id=ing_id)
                                    except Ingredient.DoesNotExist:
                                        pass
                                
                                # 2. Jinak zkusíme fuzzy matching
                                if not ingredient:
                                    matches = fuzzy_match_ingredients(ing_name, threshold=70)
                                    if matches:
                                        # Použijeme nejlepší match
                                        ingredient = matches[0][0]
                                
                                # 3. Pokud stále nemáme ingredienci, vytvoříme ji
                                if not ingredient:
                                    ingredient = Ingredient(name=ing_name)
                                    ingredients_to_create.append(ingredient)
                                    created_ingredients_count += 1
                                
                                # Připravíme RecipeIngredient (vytvoříme později)
                                recipe_ingredients_to_create.append({
                                    'recipe_code': recipe_data['code'],
                                    'ingredient': ingredient,
                                    'quantity_per_portion': ing_data.get('quantity_per_portion', 0)
                                })
                    
                    # Bulk vytvoření receptů
                    if recipes_to_create:
                        Recipe.objects.bulk_create(recipes_to_create)
                        created_recipes_count = len(recipes_to_create)
                    
                    # Vytvoření ingrediencí pomocí get_or_create (ne bulk_create)
                    # abychom předešli UNIQUE constraint chybám
                    for ingredient in ingredients_to_create:
                        Ingredient.objects.get_or_create(
                            name=ingredient.name,
                            defaults={
                                'unit': ingredient.unit if hasattr(ingredient, 'unit') else 'kg',
                                'base_unit': ingredient.base_unit if hasattr(ingredient, 'base_unit') else 'kg',
                            }
                        )
                        created_ingredients_count += 1
                    
                    # Vytvoření RecipeIngredient vazeb
                    for ri_data in recipe_ingredients_to_create:
                        recipe = Recipe.objects.get(code=ri_data['recipe_code'])
                        ingredient_name = ri_data['ingredient'].name
                        
                        # Získáme ingredienci z databáze (buď právě vytvořenou nebo existující)
                        ingredient = Ingredient.objects.get(name=ingredient_name)
                        
                        RecipeIngredient.objects.create(
                            recipe=recipe,
                            ingredient=ingredient,
                            quantity_per_portion=Decimal(str(ri_data['quantity_per_portion']))
                        )
                
                # Smazat preview data ze session
                del request.session[preview_key]
            
            # Scénář 2: Prázdná šablona
            elif days:
                try:
                    days = int(days)
                    if not (1 <= days <= 30):
                        return JsonResponse({
                            'success': False,
                            'error': 'Počet dnů musí být mezi 1 a 30'
                        }, status=400)
                    
                    xml_content = create_empty_template_xml(days)
                except ValueError:
                    return JsonResponse({'success': False, 'error': 'Neplatný počet dnů'}, status=400)
            
            else:
                return JsonResponse({
                    'success': False,
                    'error': 'Musíte zadat buď preview_key nebo days'
                }, status=400)
            
            # Vytvoření šablony
            template = MenuTemplate.objects.create(
                name=name,
                xml_content=xml_content
            )
            
            # Smazat draft ze session (pokud existuje)
            draft_key = f'template_draft_{request.user.id}'
            if draft_key in request.session:
                del request.session[draft_key]
        
        # Validační souhrn
        validation_summary = {
            'name': template.name,
            'days': template.get_stats()['days'],
            'recipes_created': created_recipes_count,
            'ingredients_created': created_ingredients_count
        }
        
        return JsonResponse({
            'success': True,
            'template_id': template.id,
            'created_recipes': created_recipes_count,
            'created_ingredients': created_ingredients_count,
            'validation_summary': validation_summary,
            'redirect_url': reverse('production:template_visual_edit', kwargs={'pk': template.pk})
        })
        
    except ValidationError as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=400)
    except Exception as e:
        return JsonResponse({'success': False, 'error': f'Chyba při vytváření šablony: {str(e)}'}, status=500)


@login_required
def template_check_name_ajax(request):
    """
    AJAX endpoint pro kontrolu duplicity názvu šablony.
    
    Očekává GET: ?name=string
    
    Vrací: {
        'exists': bool,
        'suggestion': str (pokud existuje)
    }
    """
    name = request.GET.get('name', '').strip()
    
    if not name:
        return JsonResponse({'exists': False})
    
    exists = MenuTemplate.objects.filter(name__iexact=name).exists()
    
    suggestion = None
    if exists:
        # Nabídneme alternativní název s číslem
        base_name = name
        counter = 1
        while MenuTemplate.objects.filter(name__iexact=f"{base_name} ({counter})").exists():
            counter += 1
        suggestion = f"{base_name} ({counter})"
    
    return JsonResponse({
        'exists': exists,
        'suggestion': suggestion
    })


@login_required
@require_POST
def template_autosave_ajax(request):
    """
    AJAX endpoint pro auto-save draftu šablony během vytváření.
    
    Očekává JSON: {
        'name': str,
        'days': int,
        'schedule_data': {...} (volitelné)
    }
    
    Vrací: {
        'success': bool,
        'saved_at': float (timestamp)
    }
    """
    import time
    
    try:
        data = json.loads(request.body)
        
        # Uložit draft do session
        draft_key = f'template_draft_{request.user.id}'
        timestamp = time.time()
        
        request.session[draft_key] = {
            'name': data.get('name', ''),
            'days': data.get('days'),
            'schedule_data': data.get('schedule_data', {}),
            'timestamp': timestamp
        }
        
        return JsonResponse({
            'success': True,
            'saved_at': timestamp
        })
        
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)
