from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.urls import reverse_lazy
from django.views.generic import ListView, CreateView, UpdateView, DeleteView
from django.contrib.auth.mixins import LoginRequiredMixin
from django import forms
from django.utils import timezone
from datetime import date, timedelta
from django.forms import inlineformset_factory, modelformset_factory
from django.http import JsonResponse
import json

from .models import ProductionOrder, PickingList, MenuPlan
from apps.core.models import Recipe
from apps.canteens.models import Canteen

"""
Viewy pro plánování výroby, vytváření jídelníčků a správu výdejek.
"""


class MenuPlanForm(forms.ModelForm):
    class Meta:
        model = MenuPlan
        fields = ['name', 'canteen', 'date_from', 'date_to', 'default_portions_adult', 'default_portions_child']
        widgets = {
            'date_from': forms.DateInput(attrs={'type': 'date', 'min': date.today().strftime('%Y-%m-%d')}),
            'date_to': forms.DateInput(attrs={'type': 'date', 'min': date.today().strftime('%Y-%m-%d')}),
            'default_portions_adult': forms.NumberInput(attrs={'min': '0', 'placeholder': 'Výchozí počet dospělých porcí'}),
            'default_portions_child': forms.NumberInput(attrs={'min': '0', 'placeholder': 'Výchozí počet dětských porcí'}),
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['canteen'].empty_label = "Vyberte jídelnu"
        
        # Nastavíme výchozí data
        if not self.instance.pk:
            self.fields['date_from'].initial = date.today() + timedelta(days=1)
            self.fields['date_to'].initial = date.today() + timedelta(days=7)


class ProductionOrderForm(forms.ModelForm):
    class Meta:
        model = ProductionOrder
        fields = ['recipe', 'canteen', 'portions_adult', 'portions_child', 'date']
        widgets = {
            'date': forms.DateInput(attrs={'type': 'date', 'min': date.today().strftime('%Y-%m-%d')}),
            'portions_adult': forms.NumberInput(attrs={'min': '0', 'placeholder': 'Počet dospělých porcí'}),
            'portions_child': forms.NumberInput(attrs={'min': '0', 'placeholder': 'Počet dětských porcí'}),
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['recipe'].empty_label = "Vyberte recept"
        self.fields['canteen'].empty_label = "Vyberte jídelnu"
        
        # Nastavíme výchozí datum na zítra
        if not self.instance.pk:
            self.fields['date'].initial = date.today() + timedelta(days=1)


# Formset pro správu jídel v jídelníčku
ProductionOrderFormSet = inlineformset_factory(
    MenuPlan, 
    ProductionOrder,
    fields=['recipe', 'date', 'portions_adult', 'portions_child'],
    extra=0,
    can_delete=True,
    widgets={
        'date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control meal-date'}),
        'portions_adult': forms.NumberInput(attrs={'min': '0', 'class': 'form-control portions-adult'}),
        'portions_child': forms.NumberInput(attrs={'min': '0', 'class': 'form-control portions-child'}),
        'recipe': forms.Select(attrs={'class': 'form-control'}),
    }
)


class MenuPlanListView(LoginRequiredMixin, ListView):
    model = MenuPlan
    template_name = 'production/menu_list.html'
    context_object_name = 'menu_plans'
    paginate_by = 10
    
    def get_queryset(self):
        queryset = MenuPlan.objects.select_related('canteen').prefetch_related('production_orders').order_by('-created_at')
        
        # Filtrování podle jídelny
        canteen_filter = self.request.GET.get('canteen')
        if canteen_filter:
            queryset = queryset.filter(canteen_id=canteen_filter)
            
        return queryset
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['canteens'] = Canteen.objects.all()
        context['selected_canteen'] = self.request.GET.get('canteen', '')
        context['today'] = date.today()
        return context


class MenuPlanCreateView(LoginRequiredMixin, CreateView):
    model = MenuPlan
    form_class = MenuPlanForm
    template_name = 'production/menu_form.html'
    
    def get_success_url(self):
        return reverse_lazy('production:menu_detail', kwargs={'pk': self.object.pk})
    
    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, f'Jídelníček "{self.object.name}" byl úspěšně vytvořen.')
        return response


class MenuPlanDetailView(LoginRequiredMixin, UpdateView):
    model = MenuPlan
    form_class = MenuPlanForm
    template_name = 'production/menu_detail.html'
    context_object_name = 'menu_plan'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        if self.request.POST:
            context['orders_formset'] = ProductionOrderFormSet(self.request.POST, instance=self.object)
        else:
            context['orders_formset'] = ProductionOrderFormSet(instance=self.object)
        
        context['recipes'] = Recipe.objects.all()
        context['date_range'] = self.get_date_range()
        return context
    
    def get_date_range(self):
        """Vytvoří seznam všech dat v rozmezí jídelníčku"""
        dates = []
        current_date = self.object.date_from
        while current_date <= self.object.date_to:
            dates.append(current_date)
            current_date += timedelta(days=1)
        return dates
    
    def form_valid(self, form):
        context = self.get_context_data()
        orders_formset = context['orders_formset']
        
        if orders_formset.is_valid():
            self.object = form.save()
            orders_formset.instance = self.object
            
            # Nastavíme jídelnu pro všechny příkazy
            for order_form in orders_formset:
                if order_form.cleaned_data and not order_form.cleaned_data.get('DELETE', False):
                    order_form.instance.canteen = self.object.canteen
            
            orders_formset.save()
            
            messages.success(self.request, 'Jídelníček byl úspěšně aktualizován.')
            return redirect('production:menu_detail', pk=self.object.pk)
        else:
            messages.error(self.request, 'Opravte chyby ve formuláři.')
            return self.render_to_response(self.get_context_data(form=form))
    
    def get_success_url(self):
        return reverse_lazy('production:menu_detail', kwargs={'pk': self.object.pk})


class MenuPlanDeleteView(LoginRequiredMixin, DeleteView):
    model = MenuPlan
    template_name = 'production/menu_confirm_delete.html'
    success_url = reverse_lazy('production:menu_list')
    
    def delete(self, request, *args, **kwargs):
        self.object = self.get_object()
        menu_name = self.object.name
        messages.success(request, f'Jídelníček "{menu_name}" byl smazán.')
        return super().delete(request, *args, **kwargs)


@login_required
def add_meal_to_menu(request, menu_pk):
    """AJAX view pro přidání jídla do jídelníčku"""
    menu_plan = get_object_or_404(MenuPlan, pk=menu_pk)
    
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            recipe_id = data.get('recipe_id')
            meal_date = data.get('date')
            portions_adult = int(data.get('portions_adult', menu_plan.default_portions_adult))
            portions_child = int(data.get('portions_child', menu_plan.default_portions_child))
            
            recipe = get_object_or_404(Recipe, pk=recipe_id)
            
            # Vytvoříme nový výrobní příkaz
            order = ProductionOrder.objects.create(
                menu_plan=menu_plan,
                recipe=recipe,
                canteen=menu_plan.canteen,
                date=meal_date,
                portions_adult=portions_adult,
                portions_child=portions_child
            )
            
            return JsonResponse({
                'success': True,
                'order_id': order.id,
                'recipe_name': recipe.name
            })
            
        except Exception as e:
            return JsonResponse({
                'success': False,
                'error': str(e)
            }, status=400)
    
    return JsonResponse({'success': False, 'error': 'Invalid request'}, status=400)


@login_required
def update_portions_bulk(request, menu_pk):
    """AJAX view pro hromadnou úpravu porcí"""
    menu_plan = get_object_or_404(MenuPlan, pk=menu_pk)
    
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            portions_adult = int(data.get('portions_adult', 0))
            portions_child = int(data.get('portions_child', 0))
            meal_date = data.get('date')
            
            # Aktualizujeme všechna jídla pro dané datum
            orders = menu_plan.production_orders.filter(date=meal_date)
            updated_count = orders.update(
                portions_adult=portions_adult,
                portions_child=portions_child
            )
            
            return JsonResponse({
                'success': True,
                'updated_count': updated_count
            })
            
        except Exception as e:
            return JsonResponse({
                'success': False,
                'error': str(e)
            }, status=400)
    
    return JsonResponse({'success': False, 'error': 'Invalid request'}, status=400)


# Původní views pro jednotlivé výrobní příkazy (zachováváme pro zpětnou kompatibilitu)

class ProductionOrderListView(LoginRequiredMixin, ListView):
    model = ProductionOrder
    template_name = 'production/order_list.html'
    context_object_name = 'orders'
    paginate_by = 20
    
    def get_queryset(self):
        queryset = ProductionOrder.objects.select_related('recipe', 'canteen', 'menu_plan').order_by('-date', 'recipe__name')
        
        # Filtrování podle receptu
        recipe_filter = self.request.GET.get('recipe')
        if recipe_filter:
            queryset = queryset.filter(recipe_id=recipe_filter)
        
        # Filtrování podle jídelny
        canteen_filter = self.request.GET.get('canteen')
        if canteen_filter:
            queryset = queryset.filter(canteen_id=canteen_filter)
            
        # Filtrování podle data
        date_filter = self.request.GET.get('date')
        if date_filter:
            queryset = queryset.filter(date=date_filter)
            
        return queryset
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['recipes'] = Recipe.objects.all()
        context['canteens'] = Canteen.objects.all()
        context['selected_recipe'] = self.request.GET.get('recipe', '')
        context['selected_canteen'] = self.request.GET.get('canteen', '')
        context['selected_date'] = self.request.GET.get('date', '')
        return context


class ProductionOrderCreateView(LoginRequiredMixin, CreateView):
    model = ProductionOrder
    form_class = ProductionOrderForm
    template_name = 'production/order_form.html'
    success_url = reverse_lazy('production:order_list')
    
    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, f'Výrobní příkaz pro recept "{self.object.recipe.name}" byl vytvořen.')
        return response


class ProductionOrderUpdateView(LoginRequiredMixin, UpdateView):
    model = ProductionOrder
    form_class = ProductionOrderForm
    template_name = 'production/order_form.html'
    success_url = reverse_lazy('production:order_list')
    
    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, f'Výrobní příkaz pro recept "{self.object.recipe.name}" byl upraven.')
        return response


class ProductionOrderDeleteView(LoginRequiredMixin, DeleteView):
    model = ProductionOrder
    template_name = 'production/order_confirm_delete.html'
    success_url = reverse_lazy('production:order_list')
    
    def delete(self, request, *args, **kwargs):
        self.object = self.get_object()
        recipe_name = self.object.recipe.name
        messages.success(request, f'Výrobní příkaz pro recept "{recipe_name}" byl smazán.')
        return super().delete(request, *args, **kwargs)


@login_required
def production_order_detail(request, pk):
    """Detailní pohled na výrobní příkaz s výdejkou."""
    order = get_object_or_404(ProductionOrder, pk=pk)
    
    # Vytvoříme nebo získáme výdejku pro tento příkaz
    picking_list, created = PickingList.objects.get_or_create(production_order=order)
    
    context = {
        'order': order,
        'picking_list': picking_list,
        'total_portions': order.total_portions,
        'required_ingredients': order.get_required_ingredients(),
    }
    
    return render(request, 'production/order_detail.html', context)


@login_required
def daily_picking_list(request):
    """Zobrazí nebo stáhne výdejku pro konkrétní den."""
    picking_date_str = request.GET.get('date')
    canteen_id = request.GET.get('canteen')
    format_type = request.GET.get('format', 'html')
    
    if not picking_date_str:
        messages.error(request, 'Datum není specifikováno.')
        return redirect('production:menu_list')
    
    try:
        picking_date = timezone.datetime.strptime(picking_date_str, '%Y-%m-%d').date()
    except ValueError:
        messages.error(request, 'Neplatné datum.')
        return redirect('production:menu_list')
    
    # Získáme všechny výrobní příkazy pro daný den
    orders_query = ProductionOrder.objects.filter(date=picking_date)
    
    if canteen_id:
        orders_query = orders_query.filter(canteen_id=canteen_id)
        selected_canteen = get_object_or_404(Canteen, pk=canteen_id)
    else:
        selected_canteen = None
    
    orders = orders_query.select_related('recipe', 'canteen', 'menu_plan').prefetch_related(
        'recipe__recipeingredient_set__ingredient'
    )
    
    # Agregujeme potřebné suroviny
    ingredient_totals = {}
    
    for order in orders:
        for recipe_ingredient in order.recipe.recipeingredient_set.all():
            ingredient = recipe_ingredient.ingredient
            key = (ingredient.id, ingredient.name, ingredient.unit)
            
            # Vypočítáme celkovou potřebu suroviny pro tento příkaz
            adult_amount = recipe_ingredient.quantity_adult * (order.portions_adult or 0)
            child_amount = recipe_ingredient.quantity_child * (order.portions_child or 0)
            needed_amount = adult_amount + child_amount
            
            if key in ingredient_totals:
                ingredient_totals[key]['amount'] += needed_amount
                ingredient_totals[key]['orders'].append({
                    'recipe': order.recipe.name,
                    'canteen': order.canteen.name if order.canteen else 'Bez jídelny',
                    'portions': f"{order.portions_adult or 0}+{order.portions_child or 0}",
                    'amount': needed_amount
                })
            else:
                ingredient_totals[key] = {
                    'ingredient': ingredient,
                    'amount': needed_amount,
                    'orders': [{
                        'recipe': order.recipe.name,
                        'canteen': order.canteen.name if order.canteen else 'Bez jídelny',
                        'portions': f"{order.portions_adult or 0}+{order.portions_child or 0}",
                        'amount': needed_amount
                    }]
                }
    
    # Seřadíme suroviny podle názvu
    sorted_ingredients = sorted(ingredient_totals.values(), key=lambda x: x['ingredient'].name)
    
    context = {
        'picking_date': picking_date,
        'selected_canteen': selected_canteen,
        'orders': orders,
        'ingredient_totals': sorted_ingredients,
        'total_orders': orders.count(),
        'total_portions': sum((order.portions_adult or 0) + (order.portions_child or 0) for order in orders)
    }
    
    if format_type == 'pdf':
        # Pro PDF použijeme odlišnou šablonu optimalizovanou pro tisk
        return render(request, 'production/daily_picking_list_pdf.html', context)
    else:
        # Pro HTML zobrazení
        return render(request, 'production/daily_picking_list.html', context)


@login_required
def picking_list_print(request, order_pk):
    """Zobrazení výdejky pro tisk."""
    order = get_object_or_404(ProductionOrder, pk=order_pk)
    picking_list, created = PickingList.objects.get_or_create(production_order=order)
    
    context = {
        'order': order,
        'picking_list': picking_list,
        'required_ingredients': order.get_required_ingredients(),
    }
    
    return render(request, 'production/picking_list_print.html', context)

class ProductionOrderForm(forms.ModelForm):
    class Meta:
        model = ProductionOrder
        fields = ['recipe', 'canteen', 'portions_adult', 'portions_child', 'date']
        widgets = {
            'date': forms.DateInput(attrs={'type': 'date', 'min': date.today().strftime('%Y-%m-%d')}),
            'portions_adult': forms.NumberInput(attrs={'min': '0', 'placeholder': 'Počet dospělých porcí'}),
            'portions_child': forms.NumberInput(attrs={'min': '0', 'placeholder': 'Počet dětských porcí'}),
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['recipe'].empty_label = "Vyberte recept"
        self.fields['canteen'].empty_label = "Vyberte jídelnu"
        
        # Nastavíme výchozí datum na zítra
        if not self.instance.pk:
            self.fields['date'].initial = date.today() + timedelta(days=1)


class ProductionOrderListView(LoginRequiredMixin, ListView):
    model = ProductionOrder
    template_name = 'production/order_list.html'
    context_object_name = 'orders'
    paginate_by = 20
    
    def get_queryset(self):
        queryset = ProductionOrder.objects.select_related('recipe', 'canteen').order_by('-date', '-created_at')
        
        # Filtrování podle data
        date_filter = self.request.GET.get('date_filter')
        if date_filter == 'today':
            queryset = queryset.filter(date=date.today())
        elif date_filter == 'tomorrow':
            queryset = queryset.filter(date=date.today() + timedelta(days=1))
        elif date_filter == 'week':
            queryset = queryset.filter(date__gte=date.today(), date__lte=date.today() + timedelta(days=7))
        elif date_filter == 'past':
            queryset = queryset.filter(date__lt=date.today())
            
        # Filtrování podle jídelny
        canteen_filter = self.request.GET.get('canteen')
        if canteen_filter:
            queryset = queryset.filter(canteen_id=canteen_filter)
            
        return queryset
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['canteens'] = Canteen.objects.all()
        context['selected_canteen'] = self.request.GET.get('canteen', '')
        context['date_filter'] = self.request.GET.get('date_filter', '')
        context['today'] = date.today()
        return context


class ProductionOrderCreateView(LoginRequiredMixin, CreateView):
    model = ProductionOrder
    form_class = ProductionOrderForm
    template_name = 'production/order_form.html'
    success_url = reverse_lazy('production:order_list')
    
    def form_valid(self, form):
        messages.success(self.request, f'Výrobní příkaz pro "{form.instance.recipe.name}" byl úspěšně vytvořen.')
        return super().form_valid(form)


class ProductionOrderUpdateView(LoginRequiredMixin, UpdateView):
    model = ProductionOrder
    form_class = ProductionOrderForm
    template_name = 'production/order_form.html'
    success_url = reverse_lazy('production:order_list')
    
    def form_valid(self, form):
        messages.success(self.request, f'Výrobní příkaz pro "{form.instance.recipe.name}" byl úspěšně upraven.')
        return super().form_valid(form)


class ProductionOrderDeleteView(LoginRequiredMixin, DeleteView):
    model = ProductionOrder
    template_name = 'production/order_confirm_delete.html'
    success_url = reverse_lazy('production:order_list')
    
    def delete(self, request, *args, **kwargs):
        self.object = self.get_object()
        recipe_name = self.object.recipe.name
        messages.success(request, f'Výrobní příkaz pro "{recipe_name}" byl smazán.')
        return super().delete(request, *args, **kwargs)


@login_required
def production_order_detail(request, pk):
    """Detail výrobního příkazu s výdejkou"""
    order = get_object_or_404(ProductionOrder, pk=pk)
    picking_list = order.picking_list_items.select_related('ingredient', 'warehouse').all()
    
    # Vypočítáme ceny porcí
    price_info = order.recipe.calculate_portion_price(order.canteen)
    total_price = (price_info['adult'] * order.portions_adult) + (price_info['child'] * order.portions_child)
    
    context = {
        'order': order,
        'picking_list': picking_list,
        'price_info': price_info,
        'total_price': total_price,
    }
    
    return render(request, 'production/order_detail.html', context)


@login_required
def update_picking_item(request, order_pk, item_pk):
    """Aktualizace položky výdejky"""
    order = get_object_or_404(ProductionOrder, pk=order_pk)
    item = get_object_or_404(PickingList, pk=item_pk, production_order=order)
    
    if request.method == 'POST':
        warehouse_id = request.POST.get('warehouse')
        quantity_actual = request.POST.get('quantity_actual')
        status = request.POST.get('status')
        
        if warehouse_id:
            from apps.canteens.models import Warehouse
            warehouse = get_object_or_404(Warehouse, pk=warehouse_id, canteen=order.canteen)
            item.warehouse = warehouse
            
        if quantity_actual:
            try:
                item.quantity_actual = float(quantity_actual)
            except ValueError:
                messages.error(request, 'Neplatné množství.')
                return redirect('production:order_detail', pk=order_pk)
                
        if status in [choice[0] for choice in PickingList.Status.choices]:
            item.status = status
            
        try:
            item.save()
            messages.success(request, f'Položka "{item.ingredient.name}" byla aktualizována.')
        except Exception as e:
            messages.error(request, f'Chyba při ukládání: {str(e)}')
    
    return redirect('production:order_detail', pk=order_pk)
