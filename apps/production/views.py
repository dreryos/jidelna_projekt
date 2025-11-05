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
from decimal import Decimal, InvalidOperation
import json
import logging
from functools import wraps
from typing import Any, Dict, Type, TYPE_CHECKING, cast

from django.db import models
from django.db.models.query import QuerySet
from django.http import HttpRequest, HttpResponse
from django.core.exceptions import PermissionDenied, ObjectDoesNotExist
from django.http import JsonResponse, Http404
from django.db import transaction

from .models import ProductionOrder, PickingList, MenuPlan
from .forms import ProductionOrderForm, ProductionOrderFormAdvanced, MenuPlanForm, MenuPlanCoefficientFormSet
from apps.core.models import Recipe
from apps.canteens.models import Canteen

if TYPE_CHECKING:
    from django.contrib.auth.models import User
    from apps.core.models import UserProfile

logger = logging.getLogger(__name__)

# --- Authorization Helpers ---

class CanteenOwnerMixin(LoginRequiredMixin):
    """
    Ensures the user can only access objects related to their assigned canteens
    by checking the relationship through the UserProfile model.
    """
    model: Type[models.Model]
    request: HttpRequest

    def get_queryset(self) -> QuerySet:
        queryset = super().get_queryset()  # type: ignore
        user = cast('User', self.request.user)
        if not user.is_superuser:
            try:
                # Filter objects by the canteens assigned to the user's profile
                user_canteens = user.profile.canteens.all() # type: ignore
                queryset = queryset.filter(canteen__in=user_canteens)
            except ObjectDoesNotExist:
                # If profile doesn't exist, deny access
                return queryset.none()
        return queryset

def user_can_access_canteen_object(model: Type[models.Model]):
    """
    Decorator for function-based views to check if a user has permission
    to access an object based on their assigned canteens via their profile.
    """
    def decorator(view_func):
        @wraps(view_func)
        def _wrapped_view(request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
            pk = kwargs.get('pk') or kwargs.get('menu_pk') or kwargs.get('order_pk')
            if pk is None:
                logger.error("Authorization check failed: No PK found in kwargs.")
                return JsonResponse({'success': False, 'error': 'Primary key not provided.'}, status=400)

            try:
                obj = get_object_or_404(model, pk=pk)
            except Http404:
                return JsonResponse({'success': False, 'error': 'Object not found.'}, status=404)

            user = cast('User', request.user)
            if not user.is_superuser:
                try:
                    user_canteens = user.profile.canteens.all() # type: ignore
                    canteen = getattr(obj, 'canteen', None)
                    if not canteen and hasattr(obj, 'menu_plan'):
                        canteen = obj.menu_plan.canteen

                    if canteen not in user_canteens:
                        logger.warning(
                            f"Permission denied for user {user.id} on {model.__name__} {pk}." # type: ignore
                        )
                        return JsonResponse({'success': False, 'error': 'Permission denied.'}, status=403)
                except ObjectDoesNotExist:
                    logger.warning(f"User {user.id} has no profile, denying access.") # type: ignore
                    return JsonResponse({'success': False, 'error': 'Permission denied.'}, status=403)
            
            setattr(request, 'instance', obj)
            return view_func(request, *args, **kwargs)
        return _wrapped_view
    return decorator


# --- Views ---

"""
Viewy pro plánování výroby, vytváření jídelníčků a správu výdejek.
"""


# Formset pro správu jídel v jídelníčku
ProductionOrderFormSet = inlineformset_factory(
    MenuPlan,
    ProductionOrder,
    fields=['recipe', 'date', 'portions_adult', 'portions_child', 'portion_coefficient'],
    extra=0,
    can_delete=True,
    widgets={
        'date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control meal-date'}),
        'portions_adult': forms.NumberInput(attrs={'min': '0', 'class': 'form-control portions-adult'}),
        'portions_child': forms.NumberInput(attrs={'min': '0', 'class': 'form-control portions-child'}),
        'portion_coefficient': forms.NumberInput(attrs={'step': '0.01', 'min': '0.1', 'class': 'form-control portion-coefficient'}),
        'recipe': forms.Select(attrs={'class': 'form-control'}),
    }
)


class MenuPlanListView(CanteenOwnerMixin, ListView):
    model = MenuPlan
    template_name = 'production/menu_list.html'
    context_object_name = 'menu_plans'
    paginate_by = 10
    
    def get_queryset(self) -> QuerySet[MenuPlan]:
        queryset = super().get_queryset().select_related('canteen').prefetch_related('production_orders').order_by('-created_at')
        
        canteen_filter = self.request.GET.get('canteen')
        if canteen_filter:
            user = cast('User', self.request.user)
            try:
                if user.is_superuser or user.profile.canteens.filter(pk=canteen_filter).exists(): # type: ignore
                    queryset = queryset.filter(canteen_id=canteen_filter)
            except ObjectDoesNotExist:
                return queryset.none()
            
        return queryset
    
    def get_context_data(self, **kwargs: Any) -> Dict[str, Any]:
        context = super().get_context_data(**kwargs)
        user = cast('User', self.request.user)
        if user.is_superuser:
            context['canteens'] = Canteen.objects.all()
        else:
            try:
                context['canteens'] = user.profile.canteens.all() # type: ignore
            except ObjectDoesNotExist:
                context['canteens'] = Canteen.objects.none()
        context['selected_canteen'] = self.request.GET.get('canteen', '')
        context['today'] = date.today()
        return context


class MenuPlanCreateView(CanteenOwnerMixin, CreateView):
    model = MenuPlan
    form_class = MenuPlanForm
    template_name = 'production/menu_form.html'
    
    def get_form_kwargs(self):
        """Pass the current user to the form."""
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        if self.request.POST:
            context['coefficient_formset'] = MenuPlanCoefficientFormSet(self.request.POST, instance=self.object)
        else:
            context['coefficient_formset'] = MenuPlanCoefficientFormSet(instance=self.object)
        return context
    
    @transaction.atomic
    def form_valid(self, form):
        context = self.get_context_data()
        coefficient_formset = context['coefficient_formset']
        
        if coefficient_formset.is_valid():
            self.object = form.save()
            coefficient_formset.instance = self.object
            coefficient_formset.save()
            messages.success(self.request, f'Jídelníček "{self.object.name}" byl úspěšně vytvořen.')
            return redirect('production:menu_detail', pk=self.object.pk)
        else:
            return self.render_to_response(self.get_context_data(form=form))
    
    def get_success_url(self):
        return reverse_lazy('production:menu_detail', kwargs={'pk': self.object.pk})


class MenuPlanDetailView(CanteenOwnerMixin, UpdateView):
    model = MenuPlan
    form_class = MenuPlanForm
    template_name = 'production/menu_detail.html'
    context_object_name = 'menu_plan'
    
    def get_form_kwargs(self):
        """Pass the current user to the form."""
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        if self.request.POST:
            context['orders_formset'] = ProductionOrderFormSet(self.request.POST, instance=self.object)
        else:
            context['orders_formset'] = ProductionOrderFormSet(instance=self.object)
        
        context['recipes'] = Recipe.objects.all()
        
        # Vytvoříme datum range a seskupíme příkazy podle dní
        date_range = self.get_date_range()
        orders_by_date = {}
        
        for order in self.object.production_orders.all().select_related('recipe', 'recipe__category').prefetch_related('portion_variants'):
            date_key = order.date
            if date_key not in orders_by_date:
                orders_by_date[date_key] = []
            orders_by_date[date_key].append(order)
        
        context['date_range'] = date_range
        context['orders_by_date'] = orders_by_date
        
        return context
    
    def get_date_range(self):
        """Vytvoří seznam všech dat v rozmezí jídelníčku"""
        dates = []
        current_date = self.object.date_from
        while current_date <= self.object.date_to:
            dates.append(current_date)
            current_date += timedelta(days=1)
        return dates
    
    @transaction.atomic
    def form_valid(self, form):
        context = self.get_context_data()
        orders_formset = context['orders_formset']
        
        if orders_formset.is_valid():
            self.object = form.save()
            orders_formset.instance = self.object
            
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


class MenuPlanDeleteView(CanteenOwnerMixin, DeleteView):
    model = MenuPlan
    template_name = 'production/menu_confirm_delete.html'
    success_url = reverse_lazy('production:menu_list')
    
    @transaction.atomic
    def delete(self, request, *args, **kwargs):
        self.object = self.get_object()
        menu_name = self.object.name
        response = super().delete(request, *args, **kwargs)
        messages.success(request, f'Jídelníček "{menu_name}" byl smazán.')
        return response


@login_required
@user_can_access_canteen_object(MenuPlan)
def add_meal_to_menu(request, menu_pk, *args, **kwargs):
    """AJAX view pro přidání jídla do jídelníčku"""
    from .models import ProductionOrderPortionVariant
    
    menu_plan = request.instance  # Object from decorator
    
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Invalid request method.'}, status=405)

    try:
        data = json.loads(request.body)
        recipe_id = data['recipe_id']
        meal_date = data['date']
        variants = data.get('variants', [])
        
        recipe = get_object_or_404(Recipe, pk=recipe_id)
        
        with transaction.atomic():
            order = ProductionOrder.objects.create(
                menu_plan=menu_plan,
                recipe=recipe,
                canteen=menu_plan.canteen,
                date=meal_date,
                portions_adult=0,
                portions_child=0,
                portion_coefficient=Decimal('1.0')
            )
            
            if variants:
                for variant_data in variants:
                    ProductionOrderPortionVariant.objects.create(
                        production_order=order,
                        coefficient=Decimal(str(variant_data['coefficient'])),
                        portions=int(variant_data['portions']),
                        order=int(variant_data.get('order', 0))
                    )
            else:
                total_portions = int(data.get('total_portions', 0))
                portion_coefficient = Decimal(str(data.get('portion_coefficient', '1.0')))
                ProductionOrderPortionVariant.objects.create(
                    production_order=order,
                    coefficient=portion_coefficient,
                    portions=total_portions,
                    order=0
                )
            
            order.generate_picking_list()
            
        return JsonResponse({
            'success': True,
            'order_id': order.id,
            'recipe_name': recipe.name
        })
            
    except (json.JSONDecodeError, KeyError, TypeError, ValueError, InvalidOperation, ObjectDoesNotExist) as e:
        logger.error(f"Error in add_meal_to_menu for menu_plan {menu_pk}: {e}", exc_info=True)
        return JsonResponse({'success': False, 'error': 'Invalid data provided.'}, status=400)


@login_required
@user_can_access_canteen_object(MenuPlan)
def update_portions_bulk(request, menu_pk, *args, **kwargs):
    """AJAX view pro hromadnou úpravu porcí"""
    menu_plan = request.instance
    
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Invalid request method.'}, status=405)

    try:
        data = json.loads(request.body)
        total_portions = int(data['total_portions'])
        portion_coefficient = Decimal(str(data['portion_coefficient']))
        meal_date = data['date']
        
        with transaction.atomic():
            orders = menu_plan.production_orders.filter(date=meal_date)
            updated_count = orders.update(
                portions_adult=total_portions,
                portions_child=0,
                portion_coefficient=portion_coefficient
            )
            
        return JsonResponse({'success': True, 'updated_count': updated_count})
            
    except (json.JSONDecodeError, KeyError, TypeError, ValueError, InvalidOperation) as e:
        logger.error(f"Error in update_portions_bulk for menu_plan {menu_pk}: {e}", exc_info=True)
        return JsonResponse({'success': False, 'error': 'Invalid data provided.'}, status=400)


@login_required
@user_can_access_canteen_object(ProductionOrder)
def update_order_portions(request, order_pk, *args, **kwargs):
    """AJAX view pro úpravu porcí jednoho výrobního příkazu"""
    order = request.instance
    
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Invalid request method.'}, status=405)

    try:
        data = json.loads(request.body)
        total_portions = int(data['total_portions'])
        portion_coefficient = Decimal(str(data['portion_coefficient']))
        
        with transaction.atomic():
            order.portions_adult = total_portions
            order.portions_child = 0
            order.portion_coefficient = portion_coefficient
            order.save()
            
        return JsonResponse({'success': True, 'order_id': order.id})
            
    except (json.JSONDecodeError, KeyError, TypeError, ValueError, InvalidOperation) as e:
        logger.error(f"Error in update_order_portions for order {order_pk}: {e}", exc_info=True)
        return JsonResponse({'success': False, 'error': 'Invalid data provided.'}, status=400)


@login_required
@user_can_access_canteen_object(ProductionOrder)
def update_order_variants(request, order_pk, *args, **kwargs):
    """AJAX view pro úpravu variant porcí výrobního příkazu"""
    from .models import ProductionOrderPortionVariant
    
    order = request.instance
    
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Invalid request method.'}, status=405)

    try:
        data = json.loads(request.body)
        variants_data = data['variants']
        
        with transaction.atomic():
            order.portion_variants.all().delete()
            
            for variant_info in variants_data:
                ProductionOrderPortionVariant.objects.create(
                    production_order=order,
                    coefficient=Decimal(str(variant_info['coefficient'])),
                    portions=int(variant_info['portions']),
                    order=int(variant_info.get('order', 0))
                )
            
            order.generate_picking_list()
            
        return JsonResponse({'success': True, 'order_id': order.id})
            
    except (json.JSONDecodeError, KeyError, TypeError, ValueError, InvalidOperation) as e:
        logger.error(f"Error in update_order_variants for order {order_pk}: {e}", exc_info=True)
        return JsonResponse({'success': False, 'error': 'Invalid data provided.'}, status=400)


@login_required
@user_can_access_canteen_object(ProductionOrder)
def delete_order_ajax(request, order_pk, *args, **kwargs):
    """AJAX view pro smazání výrobního příkazu"""
    order = request.instance
    
    if request.method != 'DELETE':
        return JsonResponse({'success': False, 'error': 'Invalid request method.'}, status=405)

    try:
        with transaction.atomic():
            order_id = order.id
            order.delete()
        
        return JsonResponse({'success': True, 'order_id': order_id})
            
    except Exception as e: # Catch potential db integrity errors
        logger.error(f"Error deleting order {order_pk}: {e}", exc_info=True)
        return JsonResponse({'success': False, 'error': 'Could not delete the order.'}, status=500)


# Původní views pro jednotlivé výrobní příkazy (zachováváme pro zpětnou kompatibilitu)

class ProductionOrderListView(CanteenOwnerMixin, ListView):
    model = ProductionOrder
    template_name = 'production/order_list.html'
    context_object_name = 'orders'
    paginate_by = 20
    
    def get_queryset(self) -> QuerySet[ProductionOrder]:
        queryset = super().get_queryset().select_related('recipe', 'canteen', 'menu_plan').order_by('-date', 'recipe__name')
        
        recipe_filter = self.request.GET.get('recipe')
        if recipe_filter:
            queryset = queryset.filter(recipe_id=recipe_filter)
        
        canteen_filter = self.request.GET.get('canteen')
        user = cast('User', self.request.user)
        if canteen_filter:
            try:
                if user.is_superuser or user.profile.canteens.filter(pk=canteen_filter).exists(): # type: ignore
                    queryset = queryset.filter(canteen_id=canteen_filter)
            except ObjectDoesNotExist:
                return queryset.none()
            
        date_filter = self.request.GET.get('date')
        if date_filter:
            queryset = queryset.filter(date=date_filter)
            
        return queryset
    
    def get_context_data(self, **kwargs: Any) -> Dict[str, Any]:
        context = super().get_context_data(**kwargs)
        context['recipes'] = Recipe.objects.all()
        user = cast('User', self.request.user)
        if user.is_superuser:
            context['canteens'] = Canteen.objects.all()
        else:
            try:
                context['canteens'] = user.profile.canteens.all() # type: ignore
            except ObjectDoesNotExist:
                context['canteens'] = Canteen.objects.none()
        context['selected_recipe'] = self.request.GET.get('recipe', '')
        context['selected_canteen'] = self.request.GET.get('canteen', '')
        context['selected_date'] = self.request.GET.get('date', '')
        return context


class ProductionOrderCreateView(CanteenOwnerMixin, CreateView):
    model = ProductionOrder
    form_class = ProductionOrderForm
    template_name = 'production/order_form.html'
    success_url = reverse_lazy('production:order_list')
    
    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, f'Výrobní příkaz pro recept "{self.object.recipe.name}" byl vytvořen.')
        return response


class ProductionOrderUpdateView(CanteenOwnerMixin, UpdateView):
    model = ProductionOrder
    form_class = ProductionOrderForm
    template_name = 'production/order_form.html'
    success_url = reverse_lazy('production:order_list')
    
    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, f'Výrobní příkaz pro recept "{self.object.recipe.name}" byl upraven.')
        return response


class ProductionOrderDeleteView(CanteenOwnerMixin, DeleteView):
    model = ProductionOrder
    template_name = 'production/order_confirm_delete.html'
    success_url = reverse_lazy('production:order_list')
    
    def delete(self, request, *args, **kwargs):
        self.object = self.get_object()
        recipe_name = self.object.recipe.name
        response = super().delete(request, *args, **kwargs)
        messages.success(request, f'Výrobní příkaz pro recept "{recipe_name}" byl smazán.')
        return response


@login_required
@user_can_access_canteen_object(ProductionOrder)
def production_order_detail(request, pk, *args, **kwargs):
    """Detailní pohled na výrobní příkaz s výdejkou."""
    order = request.instance
    
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
    
    user = cast('User', request.user)
    orders_query = ProductionOrder.objects.filter(date=picking_date)
    
    # Filter by user's accessible canteens
    if not user.is_superuser:
        try:
            user_canteens = user.profile.canteens.all() # type: ignore
            orders_query = orders_query.filter(canteen__in=user_canteens)
        except ObjectDoesNotExist:
            orders_query = orders_query.none()

    selected_canteen = None
    if canteen_id:
        try:
            # Ensure the user can access the selected canteen
            if user.is_superuser or user.profile.canteens.filter(pk=canteen_id).exists(): # type: ignore
                orders_query = orders_query.filter(canteen_id=canteen_id)
                selected_canteen = get_object_or_404(Canteen, pk=canteen_id)
            else:
                messages.error(request, 'Nemáte oprávnění pro přístup k této jídelně.')
                return redirect('production:menu_list')
        except ObjectDoesNotExist:
            messages.error(request, 'Nemáte oprávnění pro přístup k této jídelně.')
            return redirect('production:menu_list')

    orders = orders_query.select_related('recipe', 'canteen', 'menu_plan').prefetch_related(
        'recipe__recipeingredient_set__ingredient',
        'portion_variants'
    )
    
    ingredient_totals = {}
    total_portions = Decimal('0')
    
    for order in orders:
        effective_portions = order.get_total_effective_portions()
        total_portions += effective_portions
        
        for recipe_ingredient in order.recipe.recipeingredient_set.all():
            ingredient = recipe_ingredient.ingredient
            key = (ingredient.id, ingredient.name, ingredient.base_unit)
            
            variants = order.portion_variants.all()
            needed_amount = Decimal('0')
            
            if variants.exists():
                for variant in variants:
                    variant_amount = recipe_ingredient.get_quantity_in_base_unit(
                        portions=variant.portions,
                        coefficient=float(variant.coefficient)
                    )
                    needed_amount += variant_amount
                
                portions_desc = " + ".join([
                    f"{variant.portions}×{variant.coefficient}"
                    for variant in variants
                ])
            else:
                needed_amount = recipe_ingredient.get_quantity_in_base_unit(
                    portions=order.total_portions,
                    coefficient=float(order.portion_coefficient)
                )
                portions_desc = f"{order.total_portions}×{order.portion_coefficient}"
            
            if key in ingredient_totals:
                ingredient_totals[key]['amount'] += needed_amount
                ingredient_totals[key]['orders'].append({
                    'recipe': order.recipe.name,
                    'canteen': order.canteen.name if order.canteen else 'Bez jídelny',
                    'portions': portions_desc,
                    'effective_portions': effective_portions,
                    'amount': needed_amount
                })
            else:
                ingredient_totals[key] = {
                    'ingredient': ingredient,
                    'amount': needed_amount,
                    'orders': [{
                        'recipe': order.recipe.name,
                        'canteen': order.canteen.name if order.canteen else 'Bez jídelny',
                        'portions': portions_desc,
                        'effective_portions': effective_portions,
                        'amount': needed_amount
                    }]
                }
    
    sorted_ingredients = sorted(ingredient_totals.values(), key=lambda x: x['ingredient'].name)
    
    context = {
        'picking_date': picking_date,
        'selected_canteen': selected_canteen,
        'orders': orders,
        'ingredient_totals': sorted_ingredients,
        'total_orders': orders.count(),
        'total_portions': total_portions
    }
    
    if format_type == 'pdf':
        return render(request, 'production/daily_picking_list_pdf.html', context)
    else:
        return render(request, 'production/daily_picking_list.html', context)


@login_required
@user_can_access_canteen_object(ProductionOrder)
def picking_list_print(request, order_pk, *args, **kwargs):
    """Zobrazení výdejky pro tisk."""
    order = request.instance
    picking_list, created = PickingList.objects.get_or_create(production_order=order)
    
    context = {
        'order': order,
        'picking_list': picking_list,
        'required_ingredients': order.get_required_ingredients(),
    }
    
    return render(request, 'production/picking_list_print.html', context)
