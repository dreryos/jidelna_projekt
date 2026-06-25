from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.urls import reverse_lazy, reverse
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
from unidecode import unidecode
from functools import wraps
from typing import Any, Dict, Type, TYPE_CHECKING, cast
from collections import defaultdict

# Pořadí typů jídel pro řazení ve výdejkách
MEAL_TYPE_ORDER = {
    'BREAKFAST': 0,
    'SNACK_MORNING': 1,
    'LUNCH': 2,
    'SNACK_AFTERNOON': 3,
    'DINNER': 4,
}

from django.db import models
from django.db.models import F, Sum, Prefetch, Q
from django.db.models.query import QuerySet
from django.http import HttpRequest, HttpResponse, FileResponse
from django.core.exceptions import PermissionDenied, ObjectDoesNotExist
from django.http import JsonResponse, Http404
from django.db import transaction

from .models import ProductionOrder, PickingList, MenuPlan
from .forms import MenuPlanForm, MenuPlanCoefficientFormSet, MenuPlanCoefficientFormSetNoExtra
from apps.core.models import Recipe, UserProfile
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
                logger.warning(f"{model.__name__} with pk={pk} not found (404)")
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


# ProductionOrderFormSet byl odstraněn – jídla se nyní přidávají pouze přes AJAX endpoint (add_meal_to_menu).
# Formset není součástí kódu a neměl by být používán.
# Pro historickou referenci viz git commit před migrací 0010_remove_deprecated_fields.


class MenuPlanListView(CanteenOwnerMixin, ListView):
    model = MenuPlan
    template_name = 'production/menu_list.html'
    context_object_name = 'menu_plans'
    # Pagination removed to allow grouping of all plans
    # paginate_by = 10 
    
    def get_queryset(self) -> QuerySet[MenuPlan]:
        queryset = super().get_queryset().select_related('canteen').prefetch_related(
            'production_orders__picking_list_items__document'
        ).order_by('-created_at')
        
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
        
        # Categorize menu plans
        menu_plans = context['menu_plans']
        prepared_plans = []
        in_progress_plans = []
        archived_plans = []
        
        for plan in menu_plans:
            plan_items_count = 0
            archived_items_count = 0
            items_with_doc_count = 0
            
            orders = plan.production_orders.all()
            if not orders:
                prepared_plans.append(plan)
                continue
                
            for order in orders:
                items = order.picking_list_items.all()
                for item in items:
                    plan_items_count += 1
                    if item.document:
                        items_with_doc_count += 1
                        if item.document.archived:
                            archived_items_count += 1
            
            if plan_items_count == 0:
                prepared_plans.append(plan)
            elif archived_items_count == plan_items_count:
                archived_plans.append(plan)
            elif items_with_doc_count > 0:
                in_progress_plans.append(plan)
            else:
                # Items exist but no document -> Prepared
                prepared_plans.append(plan)
                
        context['prepared_plans'] = prepared_plans
        context['in_progress_plans'] = in_progress_plans
        context['archived_plans'] = archived_plans
        
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
        
        context['recipes'] = Recipe.objects.all()
        
        # Definice pořadí meal_types pro konzistentní zobrazení
        MEAL_TYPE_ORDER = [
            'BREAKFAST',
            'SNACK_MORNING',
            'LUNCH',
            'SNACK_AFTERNOON',
            'DINNER'
        ]
        context['MEAL_TYPE_ORDER'] = MEAL_TYPE_ORDER
        
        # Vytvoříme datum range a seskupíme příkazy podle dní a typu jídla
        date_range = self.get_date_range()
        orders_by_date_and_type = defaultdict(lambda: defaultdict(list))
        
        for order in self.object.production_orders.all().select_related('recipe', 'recipe__category').prefetch_related('portion_variants'):
            orders_by_date_and_type[order.date][order.meal_type].append(order)
        
        # Seřadíme meal_types podle definovaného pořadí
        sorted_orders = {}
        for date_key, meal_types in orders_by_date_and_type.items():
            sorted_orders[date_key] = {
                mt: meal_types[mt] 
                for mt in MEAL_TYPE_ORDER 
                if mt in meal_types
            }
        
        context['date_range'] = date_range
        context['orders_by_date_and_type'] = sorted_orders
        
        # Přidáme výchozí koeficienty pro JavaScript (konvertujeme Decimal na float)
        context['default_coefficients'] = [
            {
                'name': coef.name,
                'coefficient': float(coef.coefficient),
                'order': coef.order,
                'default_portions': coef.default_portions,
            }
            for coef in self.object.default_coefficients.all().order_by('order')
        ]

        # Formset pro editaci výchozích koeficientů v hlavičce (bez extra prázdného řádku)
        if self.request.POST and 'coefficient_formset-TOTAL_FORMS' in self.request.POST:
            context['coefficient_formset'] = MenuPlanCoefficientFormSetNoExtra(
                self.request.POST,
                instance=self.object,
                prefix='coefficient_formset',
            )
        else:
            context['coefficient_formset'] = MenuPlanCoefficientFormSetNoExtra(
                instance=self.object,
                prefix='coefficient_formset',
            )
        
        return context
    
    def get_date_range(self):
        """Vytvoří seznam všech dat v rozmezí jídelníčku"""
        dates = []
        current_date = self.object.date_from
        while current_date <= self.object.date_to:
            dates.append(current_date)
            current_date += timedelta(days=1)
        return dates

    def post(self, request, *args, **kwargs):
        self.object = self.get_object()
        if request.POST.get('form_action') == 'update_coefficients':
            return self._handle_coefficient_update(request)
        return super().post(request, *args, **kwargs)

    @transaction.atomic
    def _handle_coefficient_update(self, request):
        from .models import ProductionOrderPortionVariant
        coefficient_formset = MenuPlanCoefficientFormSetNoExtra(
            request.POST,
            instance=self.object,
            prefix='coefficient_formset',
        )
        if coefficient_formset.is_valid():
            coefficient_formset.save()

            # Přepsat varianty porcí u nezamčených jídel v tomto jídelníčku
            updated_coefficients = list(
                self.object.default_coefficients.all().order_by('order')
            )
            updated_count = 0
            for order in self.object.production_orders.prefetch_related('portion_variants', 'picking_list_items__document'):
                if order.has_issued_picking_list():
                    continue
                order.portion_variants.all().delete()
                for coef in updated_coefficients:
                    ProductionOrderPortionVariant.objects.create(
                        production_order=order,
                        name=coef.name,
                        coefficient=coef.coefficient,
                        portions=coef.default_portions,
                        order=coef.order,
                    )
                updated_count += 1

            if updated_count > 0:
                messages.success(request, f'Výchozí hodnoty uloženy a aplikovány na {updated_count} jídel.')
            else:
                messages.success(request, 'Výchozí počty porcí byly úspěšně uloženy.')
        else:
            messages.error(request, 'Chyba při ukládání výchozích počtů porcí.')
        return redirect('production:menu_detail', pk=self.object.pk)

    @transaction.atomic
    def form_valid(self, form):
        self.object = form.save()
        messages.success(self.request, 'Jídelníček byl úspěšně aktualizován.')
        return redirect('production:menu_detail', pk=self.object.pk)
    
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
        meal_type = data.get('meal_type', 'LUNCH')  # Výchozí typ je oběd
        variants = data.get('variants', [])
        
        recipe = get_object_or_404(Recipe, pk=recipe_id)
        
        with transaction.atomic():
            order = ProductionOrder.objects.create(
                menu_plan=menu_plan,
                recipe=recipe,
                date=meal_date,
                meal_type=meal_type
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
            'recipe_name': recipe.name,
            'meal_type_display': order.get_meal_type_display()
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
            # Filter out orders that have issued picking lists
            orders = menu_plan.production_orders.filter(date=meal_date).exclude(picking_list_items__document__isnull=False)
            
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

    if order.has_issued_picking_list():
        return JsonResponse({'success': False, 'error': 'Nelze upravit jídlo s vydanou výdejkou.'}, status=403)

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

    if order.has_issued_picking_list():
        return JsonResponse({'success': False, 'error': 'Nelze upravit jídlo s vydanou výdejkou.'}, status=403)

    try:
        data = json.loads(request.body)
        variants_data = data['variants']
        
        with transaction.atomic():
            order.portion_variants.all().delete()
            
            for variant_info in variants_data:
                raw_coefficient = variant_info['coefficient']
                if raw_coefficient == '' or raw_coefficient is None:
                    return JsonResponse({'success': False, 'error': 'Koeficient varianty nesmí být prázdný.'}, status=400)
                ProductionOrderPortionVariant.objects.create(
                    production_order=order,
                    name=variant_info.get('name', ''),
                    coefficient=Decimal(str(raw_coefficient)),
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
    
    logger.info(f"Delete request for ProductionOrder {order_pk} by user {request.user.id}")
    
    if request.method != 'DELETE':
        logger.warning(f"Invalid method {request.method} for delete_order_ajax")
        return JsonResponse({'success': False, 'error': 'Invalid request method.'}, status=405)

    if order.has_issued_picking_list():
        logger.info(f"Cannot delete order {order_pk}: has issued picking list")
        return JsonResponse({'success': False, 'error': 'Nelze smazat jídlo s vydanou výdejkou.'}, status=403)

    try:
        with transaction.atomic():
            order_id = order.id
            recipe_name = order.recipe.name
            order.delete()
        
        logger.info(f"Successfully deleted ProductionOrder {order_id} ({recipe_name}) by user {request.user.id}")
        return JsonResponse({'success': True, 'order_id': order_id})
            
    except Exception as e: # Catch potential db integrity errors
        logger.error(f"Error deleting order {order_pk}: {e}", exc_info=True)
        return JsonResponse({'success': False, 'error': 'Could not delete the order.'}, status=500)


# Detail výrobního příkazu (read-only, přístupný z jídelníčku)

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
                        coefficient=variant.coefficient
                    )
                    needed_amount += variant_amount
                
                portions_desc = " + ".join([
                    f"{variant.portions}×{variant.coefficient}"
                    for variant in variants
                ])
            else:
                needed_amount = recipe_ingredient.get_quantity_in_base_unit(
                    portions=order.total_portions,
                    coefficient=order.portion_coefficient
                )
                portions_desc = f"{order.total_portions}×{order.portion_coefficient}"
            
            if key in ingredient_totals:
                ingredient_totals[key]['amount'] += needed_amount
                ingredient_totals[key]['orders'].append({
                    'recipe': order.recipe.name,
                    'canteen': order.get_canteen().name if order.get_canteen() else 'Bez jídelny',
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
                        'canteen': order.get_canteen().name if order.get_canteen() else 'Bez jídelny',
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


@login_required
def picking_list_generator(request):
    """
    View pro generování výdejek pro kuchaře.
    Umožňuje výběr jídelny a časového úseku, generuje PDF s plánovaným a skutečným množstvím.
    """
    from .models import PickingListDocument
    
    # Získání jídelen podle profilu uživatele
    profile = None
    if request.user.is_superuser:
        canteens = Canteen.objects.all()
    else:
        profile, _ = UserProfile.objects.get_or_create(user=request.user)
        canteens = profile.canteens.all()
    
    # Načtení existujících dokumentů výdejek
    documents = PickingListDocument.objects.all()
    if request.user.is_superuser:
        documents = documents
    else:
        # profile je již načten výše
        documents = documents.filter(canteen__in=profile.canteens.all()) if profile else PickingListDocument.objects.none()
    
    if request.method == 'POST':
        canteen_id = request.POST.get('canteen')
        date_from = request.POST.get('date_from')
        date_to = request.POST.get('date_to')
        
        if not all([canteen_id, date_from, date_to]):
            messages.error(request, 'Všechna pole musí být vyplněna.')
            return redirect('production:picking_list_generator')
        
        try:
            canteen = Canteen.objects.get(id=canteen_id)
            date_from_obj = timezone.datetime.strptime(date_from, '%Y-%m-%d').date()
            date_to_obj = timezone.datetime.strptime(date_to, '%Y-%m-%d').date()
            
            # Kontrola oprávnění
            if not request.user.is_superuser:
                # profile je načten výše; fallback pro jistotu
                profile = profile or UserProfile.objects.get_or_create(user=request.user)[0]
                if canteen not in profile.canteens.all():
                    raise PermissionDenied("Nemáte oprávnění k této jídelně")
            
            # Najdeme všechny ProductionOrders v daném rozsahu pro tuto jídelnu
            # Exclude orders that are already part of a picking list document (active or archived)
            orders = ProductionOrder.objects.filter(
                canteen=canteen,
                date__gte=date_from_obj,
                date__lte=date_to_obj
            ).exclude(
                picking_list_items__document__isnull=False
            ).select_related('recipe', 'canteen', 'menu_plan').prefetch_related(
                'portion_variants',
                'picking_list_items'
            ).order_by('date', 'recipe__name')
            
            if not orders.exists():
                messages.warning(request, f'Nenalezeny žádné nové výrobní příkazy pro {canteen.name} v období {date_from} - {date_to}.')
                return redirect('production:picking_list_generator')
            
            # Agregujeme suroviny napříč všemi příkazy
            ingredient_totals = {}
            warnings = []
            
            for order in orders:
                # Vygenerujeme picking list položky pokud neexistují
                # NEBO pokud všechny existující položky mají quantity_planned == 0
                # (což může nastat u starých záznamů vytvořených před opravou)
                regenerated = False
                if not order.picking_list_items.exists():
                    order.generate_picking_list()
                    regenerated = True
                else:
                    # Zkontrolujeme, zda některá položka má nulové množství
                    has_zero_quantities = order.picking_list_items.filter(
                        quantity_planned=Decimal('0')
                    ).exists()
                    
                    if has_zero_quantities:
                        # Smažeme všechny položky a vygenerujeme nové
                        order.picking_list_items.all().delete()
                        order.generate_picking_list()
                        regenerated = True
                
                # Po regeneraci invalidujeme prefetch cache, aby se načetly
                # čerstvé položky z DB místo stale prefetch dat
                if regenerated and hasattr(order, '_prefetched_objects_cache'):
                    order._prefetched_objects_cache.pop('picking_list_items', None)
                
                # Zpracujeme picking list položky
                for item in order.picking_list_items.all():
                    key = item.ingredient.id
                    
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
                        # Zkontrolujeme dostupnost na VŠECH skladech přidružených k jídelně
                        # Používáme quantity - quantity_blocked pro výpočet dostupného množství
                        from apps.inventory.models import StockItem
                        
                        # Výpočet celkového dostupného množství (quantity - quantity_blocked)
                        stock_items = StockItem.objects.filter(
                            ingredient=item.ingredient,
                            warehouse__canteen=canteen
                        ).annotate(
                            available=F('quantity') - F('quantity_blocked')
                        )
                        
                        available_stock = sum(
                            si.available for si in stock_items if si.available > 0
                        ) or Decimal('0')
                        
                        # Získáme seznam skladů s touto surovinou pro informaci (včetně blokovaného množství)
                        warehouses_with_stock = []
                        for si in stock_items:
                            if si.quantity > 0 or si.quantity_blocked > 0:
                                available = si.quantity - si.quantity_blocked
                                warehouses_with_stock.append(
                                    (si.warehouse.name, si.quantity, si.quantity_blocked, available)
                                )
                        
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
                    
                    # Přidáme referenci na picking list item pro pozdější blokování
                    ingredient_totals[key]['picking_items'].append(item)
            
            # Kontrola dostupnosti surovin a vytvoření varování
            missing_ingredients = []
            insufficient_ingredients = []
            
            for ing_data in ingredient_totals.values():
                if not ing_data['has_stock']:
                    missing_ingredients.append(
                        f"{ing_data['ingredient'].name} (potřeba: {ing_data['planned']:.2f} {ing_data['unit']})"
                    )
                elif not ing_data['is_sufficient']:
                    insufficient_ingredients.append(
                        f"{ing_data['ingredient'].name} (potřeba: {ing_data['planned']:.2f} {ing_data['unit']}, "
                        f"dostupné: {ing_data['available_stock']:.2f} {ing_data['unit']})"
                    )
            
            # Pokud chybí kritické suroviny, upozorníme uživatele
            if missing_ingredients or insufficient_ingredients:
                warning_msg = []
                if missing_ingredients:
                    warning_msg.append(f"<strong>Chybí na skladě ({len(missing_ingredients)}):</strong><br>" + 
                                     "<br>".join(missing_ingredients))
                if insufficient_ingredients:
                    warning_msg.append(f"<strong>Nedostatečné množství ({len(insufficient_ingredients)}):</strong><br>" + 
                                     "<br>".join(insufficient_ingredients))
                
                from django.utils.safestring import mark_safe
                messages.warning(
                    request, 
                    mark_safe("<strong>Varování o zásobách:</strong><br><br>" + "<br><br>".join(warning_msg))
                )
            
            # Seřadíme ingredience abecedně
            sorted_ingredients = sorted(ingredient_totals.values(), key=lambda x: x['ingredient'].name)
            
            # Vytvoříme dokument výdejky
            document_name = f"výdejka-{date_from_obj.strftime('%d%m')}"
            picking_document = PickingListDocument.objects.create(
                name=document_name,
                canteen=canteen,
                date_from=date_from_obj,
                date_to=date_to_obj,
                created_by=request.user
            )
            
            # Označíme všechny picking list items jako PENDING a propojíme s dokumentem
            for ing_data in ingredient_totals.values():
                for item in ing_data['picking_items']:
                    if item.status != PickingList.Status.PENDING:
                        item.status = PickingList.Status.PENDING
                    item.document = picking_document
                    item.save(update_fields=['status', 'document'])
            
            # Vygenerujeme PDF soubor a uložíme ho
            try:
                from .utils import generate_picking_list_pdf_file
                generate_picking_list_pdf_file(picking_document, base_url=request.build_absolute_uri('/'))
                logger.info(f"PDF file generated and saved for picking document {picking_document.id}")
            except Exception as e:
                # Pokud generování PDF selže, logujeme ale pokračujeme (PDF se vygeneruje on-demand později)
                logger.error(f"Failed to generate PDF file for picking document {picking_document.id}: {e}")
                messages.warning(request, 'Výdejka byla vytvořena, ale nepodařilo se vygenerovat PDF. Bude vygenerováno při prvním stažení.')
            
            # Počítáme problematické položky
            missing_count = len(missing_ingredients)
            insufficient_count = len(insufficient_ingredients)
            
            # Připravíme data strukturovaná podle dnů a jídel pro PDF
            daily_picking_data = {}
            
            for order in orders:
                if order.date not in daily_picking_data:
                    daily_picking_data[order.date] = []
                
                order_ingredients = []
                for item in order.picking_list_items.all():
                    # Získáme info o dostupnosti z agregovaných dat
                    total_info = ingredient_totals.get(item.ingredient.id)
                    
                    order_ingredients.append({
                        'name': item.ingredient.name,
                        'quantity': item.quantity_planned,
                        'unit': item.ingredient.base_unit,
                        'has_stock': total_info['has_stock'] if total_info else True,
                        'is_sufficient': total_info['is_sufficient'] if total_info else True,
                        'warehouses_info': total_info['warehouses_info'] if total_info else [],
                    })
                
                # Seřadíme suroviny abecedně
                order_ingredients.sort(key=lambda x: x['name'])
                
                daily_picking_data[order.date].append({
                    'recipe_name': order.recipe.name,
                    'meal_type': order.meal_type,
                    'portions': order.total_portions,
                    'ingredients': order_ingredients,
                    'is_customized': order.has_overrides
                })
            
            # Seřadíme dny a jídla v každém dni podle typu jídla
            sorted_daily_data = sorted(daily_picking_data.items())
            sorted_daily_data = [
                (d, sorted(meals, key=lambda m: MEAL_TYPE_ORDER.get(m.get('meal_type', ''), 99)))
                for d, meals in sorted_daily_data
            ]
            
            context = {
                'canteen': canteen,
                'date_from': date_from_obj,
                'date_to': date_to_obj,
                'orders': orders,
                'ingredient_totals': sorted_ingredients,
                'daily_picking_data': sorted_daily_data,
                'total_orders': orders.count(),
                'generated_at': timezone.now(),
                'missing_count': missing_count,
                'insufficient_count': insufficient_count,
            }
            
            # Vygenerujeme PDF - PŮVODNÍ KÓD NAHRAZEN PŘESMĚROVÁNÍM
            # Místo přímého vrácení PDF přesměrujeme zpět na stránku s parametrem pro stažení
            messages.success(request, f'Výdejka byla úspěšně vytvořena a suroviny zablokovány.')
            
            url = reverse('production:picking_list_generator')
            return redirect(f'{url}?download_pdf={picking_document.id}')
            
        except Canteen.DoesNotExist:
            messages.error(request, 'Vybraná jídelna neexistuje.')
        except PermissionDenied as e:
            messages.error(request, str(e))
        except Exception as e:
            messages.error(request, f'Chyba při generování výdejky: {str(e)}')
            logger.exception("Error generating picking list PDF")
    
    context = {
        'canteens': canteens,
        'today': date.today(),
        'active_documents': documents.filter(archived=False),
        'archived_documents': documents.filter(archived=True),
    }
    
    # Pokud je v GET parametru požadavek na stažení PDF, přidáme ho do kontextu
    if 'download_pdf' in request.GET:
        try:
            doc_id = int(request.GET['download_pdf'])
            # Ověříme, že dokument existuje (zjednodušeně, detailní kontrola je ve view pro PDF)
            if documents.filter(id=doc_id).exists():
                context['download_pdf_id'] = doc_id
        except ValueError:
            pass
    
    return render(request, 'production/picking_list_generator.html', context)


@login_required
def picking_list_edit(request, document_id):
    """
    View pro editaci skutečných množství ve výdejce.
    """
    from .models import PickingListDocument
    
    try:
        document = PickingListDocument.objects.get(id=document_id)
        logger.info(
            "picking_list_edit opened: document_id=%s user_id=%s method=%s",
            document_id,
            request.user.id,
            request.method,
        )
        
        # Kontrola oprávnění
        if not request.user.is_superuser:
            profile, _ = UserProfile.objects.get_or_create(user=request.user)
            if document.canteen not in profile.canteens.all():
                raise PermissionDenied("Nemáte oprávnění k této jídelně")
        
        # Načteme všechny picking list items tohoto dokumentu
        picking_items = PickingList.objects.filter(document=document).select_related(
            'ingredient', 'production_order__recipe', 'warehouse'
        ).order_by('ingredient__name')
        
        # Kontrola zda některý sklad není uzamčen
        locked_warehouses = set()
        for item in picking_items:
            if item.warehouse and item.warehouse.is_locked:
                locked_warehouses.add(item.warehouse)
        
        if locked_warehouses:
            logger.warning(
                "picking_list_edit blocked by locked warehouses: document_id=%s user_id=%s locked_count=%s",
                document_id,
                request.user.id,
                len(locked_warehouses),
            )
            for warehouse in locked_warehouses:
                messages.error(
                    request,
                    f"Sklad '{warehouse.name}' je uzamčen kvůli probíhající inventuře "
                    f"zahájené {warehouse.locked_by_inventory.started_by.get_full_name() or warehouse.locked_by_inventory.started_by.username} "
                    f"dne {warehouse.locked_by_inventory.started_at.strftime('%d.%m.%Y %H:%M')}. "
                    f"Nelze editovat výdejky na uzamčených skladech."
                )
            # Zobrazíme detail, ale bez možnosti editace
            context = {
                'document': document,
                'locked': True,
            }
            return render(request, 'production/picking_list_edit.html', context)
        
        if request.method == 'POST':
            # Zpracování formuláře s editací skutečných množství (per-item)
            updated_count = 0
            processed_count = 0
            added_count = 0
            missing_quantity_fields = 0
            item_validation_errors = 0
            completed_count_after_save = 0
            pending_count_after_save = 0
            # Re-fetch picking items fresh (nekombinujeme s pre-evaluovaným QS z locked check)
            # Načteme pouze položky s production_order (položky mimo jídla se needitují v této smyčce)
            picking_items_fresh = list(
                PickingList.objects.filter(
                    document=document,
                    production_order__isnull=False
                ).select_related('ingredient', 'warehouse')
            )
            picking_items_map = {item.id: item for item in picking_items_fresh}
            
            # Debug: Ověříme, že žádná položka v mapě nemá production_order=None
            for item in picking_items_map.values():
                if item.production_order is None:
                    logger.error(
                        f"CRITICAL: Item {item.id} in picking_items_map has production_order=None! "
                        f"This should never happen. Document={document_id}"
                    )

            qty_keys_in_post = [k for k in request.POST.keys() if k.startswith('quantity_actual_item_')]
            status_keys_in_post = [k for k in request.POST.keys() if k.startswith('status_item_')]
            debug_qty_count = request.POST.get('debug_qty_count', 'missing')
            logger.info(
                "picking_list_edit POST start: document_id=%s user_id=%s post_keys=%s item_count=%s "
                "qty_fields_in_post=%s status_fields_in_post=%s debug_qty_count=%s "
                "sample_post_keys=%s",
                document_id,
                request.user.id,
                len(request.POST.keys()),
                len(picking_items_map),
                len(qty_keys_in_post),
                len(status_keys_in_post),
                debug_qty_count,
                list(request.POST.keys())[:10],
            )

            # Uložení kuchaře
            from django.contrib.auth import get_user_model
            User = get_user_model()
            cook_id_str = request.POST.get('cook', '').strip()
            if cook_id_str:
                try:
                    cook_obj = User.objects.get(id=int(cook_id_str))
                    document.cook = cook_obj
                    document.save(update_fields=['cook'])
                except (ValueError, User.DoesNotExist):
                    messages.error(request, 'Zadaný kuchař neexistuje.')
            else:
                # Prázdný výběr = odebrat kuchaře
                document.cook = None
                document.save(update_fields=['cook'])
            
            for item_id, item in picking_items_map.items():
                quantity_key = f'quantity_actual_item_{item_id}'
                status_key = f'status_item_{item_id}'
                had_quantity_in_post = quantity_key in request.POST

                quantity_str = request.POST.get(quantity_key, '').strip()
                # Prohlížeč může poslat prázdný řetězec pro pre-filled <input type="number">
                # pokud hodnota selže HTML5 validaci (step/min) nebo pole vůbec neodešle.
                if not quantity_str:
                    if not had_quantity_in_post:
                        missing_quantity_fields += 1
                    if item.quantity_actual is not None:
                        quantity_str = str(item.quantity_actual)
                    else:
                        quantity_str = str(item.quantity_planned)

                try:
                    from django.core.exceptions import ValidationError as DjangoValidationError
                    quantity = Decimal(quantity_str.replace(',', '.'))
                    status = request.POST.get(status_key, PickingList.Status.PENDING)
                    old_quantity_actual = item.quantity_actual
                    old_status = item.status

                    item.quantity_actual = quantity
                    item.status = status

                    has_changed = (old_quantity_actual != item.quantity_actual) or (old_status != item.status)
                    if has_changed:
                        item.save()
                        updated_count += 1

                    processed_count += 1
                    if item.status == PickingList.Status.COMPLETED:
                        completed_count_after_save += 1
                    elif item.status == PickingList.Status.PENDING:
                        pending_count_after_save += 1
                except (ValueError, InvalidOperation):
                    item_validation_errors += 1
                    logger.warning(
                        "picking_list_edit invalid quantity: document_id=%s item_id=%s ingredient=%s raw_value=%s",
                        document_id,
                        item_id,
                        item.ingredient.name,
                        quantity_str,
                    )
                    messages.error(request, f'Neplatné množství pro {item.ingredient.name}')
                except DjangoValidationError as e:
                    item_validation_errors += 1
                    logger.warning(
                        "picking_list_edit validation error: document_id=%s item_id=%s ingredient=%s error=%s",
                        document_id,
                        item_id,
                        item.ingredient.name,
                        '; '.join(e.messages),
                    )
                    messages.error(request, f'Chyba validace pro {item.ingredient.name}: {"; ".join(e.messages)}')
            
            # Zpracování nových položek přidaných uživatelem
            from apps.core.models import Ingredient as IngredientModel
            from apps.canteens.models import Warehouse
            
            # Sestáváme skupiny nových položek: new_order__{order_id}__{idx}
            new_order_ids = set()
            for key in request.POST.keys():
                if key.startswith('new_ingredient_order_'):
                    parts = key.split('_')  # new, ingredient, order, {order_id}, {idx}
                    if len(parts) >= 5:
                        try:
                            # parts[3] = order_id, parts[4] = idx
                            new_order_ids.add((int(parts[3]), int(parts[4])))
                        except (ValueError, IndexError):
                            pass
            
            # Platné orders pro tento dokument
            valid_order_ids = set(
                ProductionOrder.objects.filter(
                    picking_list_items__document=document
                ).values_list('id', flat=True)
            )
            
            for order_id_new, idx in sorted(new_order_ids):
                if order_id_new not in valid_order_ids:
                    messages.error(request, 'Neplatný výrobní příkaz.')
                    continue
                
                ingredient_id_str = request.POST.get(f'new_ingredient_order_{order_id_new}_{idx}', '').strip()
                warehouse_id_str = request.POST.get(f'new_warehouse_order_{order_id_new}_{idx}', '').strip()
                quantity_str = request.POST.get(f'new_quantity_order_{order_id_new}_{idx}', '').strip()
                
                if not ingredient_id_str or not warehouse_id_str or not quantity_str:
                    continue
                
                try:
                    ingredient_id_new = int(ingredient_id_str)
                    warehouse_id_new = int(warehouse_id_str)
                    quantity_new = Decimal(quantity_str.replace(',', '.'))
                    if quantity_new <= 0:
                        messages.error(request, 'Množství musí být kladné.')
                        continue
                except (ValueError, InvalidOperation):
                    messages.error(request, 'Neplatné hodnoty pro novou surovinu.')
                    continue
                
                try:
                    order_obj = ProductionOrder.objects.get(id=order_id_new)
                    ingredient_obj = IngredientModel.objects.get(id=ingredient_id_new, is_active=True)
                    warehouse_obj = Warehouse.objects.get(id=warehouse_id_new, canteen=document.canteen)
                except (ProductionOrder.DoesNotExist, IngredientModel.DoesNotExist, Warehouse.DoesNotExist):
                    messages.error(request, 'Některý ze zadaných údajů (jídlo / surovina / sklad) nebyl nalezen.')
                    continue
                
                # Vytvoření override pro trvalé uložení přidané suroviny
                from .models import ProductionOrderIngredientOverride
                ProductionOrderIngredientOverride.objects.create(
                    production_order=order_obj,
                    ingredient=ingredient_obj,
                    quantity_per_portion=None,  # pro přidané suroviny je None
                    original_quantity=Decimal('0'),
                    is_added=True,
                    is_removed=False,
                    notes=''
                )
                
                PickingList.objects.create(
                    production_order=order_obj,
                    document=document,
                    warehouse=warehouse_obj,
                    ingredient=ingredient_obj,
                    quantity_planned=quantity_new,
                    quantity_actual=quantity_new,
                    status=PickingList.Status.COMPLETED,
                )
                added_count += 1
            
            # Zpracování nových položek bez ProductionOrder (mimo jídla)
            new_without_order_ids = set()
            for key in request.POST.keys():
                if key.startswith('new_ingredient_without_order_'):
                    parts = key.split('_')  # new, ingredient, without, order, {idx}
                    if len(parts) >= 5:
                        try:
                            # parts[4] = idx
                            new_without_order_ids.add(int(parts[4]))
                        except (ValueError, IndexError):
                            pass
            
            for idx in sorted(new_without_order_ids):
                ingredient_id_str = request.POST.get(f'new_ingredient_without_order_{idx}', '').strip()
                warehouse_id_str = request.POST.get(f'new_warehouse_without_order_{idx}', '').strip()
                quantity_str = request.POST.get(f'new_quantity_without_order_{idx}', '').strip()
                
                if not ingredient_id_str or not warehouse_id_str or not quantity_str:
                    continue
                
                try:
                    ingredient_id_new = int(ingredient_id_str)
                    warehouse_id_new = int(warehouse_id_str)
                    quantity_new = Decimal(quantity_str.replace(',', '.'))
                    if quantity_new <= 0:
                        messages.error(request, 'Množství musí být kladné.')
                        continue
                except (ValueError, InvalidOperation):
                    messages.error(request, 'Neplatné hodnoty pro novou surovinu.')
                    continue
                
                try:
                    ingredient_obj = IngredientModel.objects.get(id=ingredient_id_new, is_active=True)
                    warehouse_obj = Warehouse.objects.get(id=warehouse_id_new, canteen=document.canteen)
                except (IngredientModel.DoesNotExist, Warehouse.DoesNotExist):
                    messages.error(request, 'Některý ze zadaných údajů (surovina / sklad) nebyl nalezen.')
                    continue
                
                PickingList.objects.create(
                    production_order=None,
                    document=document,
                    warehouse=warehouse_obj,
                    ingredient=ingredient_obj,
                    quantity_planned=quantity_new,
                    quantity_actual=quantity_new,
                    status=PickingList.Status.COMPLETED,
                )
                added_count += 1
            
            if added_count:
                messages.success(request, f'Přidáno {added_count} nových položek.')

            # Debug: Logujeme stav položek bez production_order
            items_without_order_before = list(
                PickingList.objects.filter(
                    document=document,
                    production_order__isnull=True
                ).values('id', 'ingredient__name', 'status')
            )
            if items_without_order_before:
                logger.info(
                    f"Items without production_order for document {document_id}: {items_without_order_before}"
                )

            # Přepočítáme statistiky včetně položek mimo jídla
            all_items_stats = PickingList.objects.filter(document=document).values_list('status', flat=True)
            completed_count_after_save = sum(1 for s in all_items_stats if s == PickingList.Status.COMPLETED)
            pending_count_after_save = sum(1 for s in all_items_stats if s == PickingList.Status.PENDING)

            logger.info(
                "picking_list_edit POST summary: document_id=%s user_id=%s processed=%s updated=%s added=%s completed=%s pending=%s missing_quantity_fields=%s item_validation_errors=%s",
                document_id,
                request.user.id,
                processed_count,
                updated_count,
                added_count,
                completed_count_after_save,
                pending_count_after_save,
                missing_quantity_fields,
                item_validation_errors,
            )

            messages.success(
                request,
                f'Aktualizováno {updated_count} položek. Vydáno: {completed_count_after_save}, čeká na vydání: {pending_count_after_save}.'
            )
            return redirect('production:picking_list_edit', document_id=document_id)
        
        # Agregujeme suroviny stejně jako v PDF
        orders = ProductionOrder.objects.filter(
            picking_list_items__document=document
        ).distinct().select_related('recipe', 'canteen').order_by('date', 'recipe__name')
        
        ingredient_totals = {}
        
        # Připravíme data strukturovaná podle dnů a jídel pro PDF
        daily_picking_data = {}
        
        for order in orders:
            # Agregace pro celkový přehled (zachováno pro kompatibilitu)
            for item in order.picking_list_items.filter(document=document):
                key = item.ingredient.id
                
                if key in ingredient_totals:
                    ingredient_totals[key]['planned'] += item.quantity_planned
                    if item.quantity_actual is not None:
                        if ingredient_totals[key]['quantity_actual'] is None:
                            ingredient_totals[key]['quantity_actual'] = item.quantity_actual
                        else:
                            ingredient_totals[key]['quantity_actual'] += item.quantity_actual
                    # Pokud je alespoň jedna položka PENDING, celkový status je PENDING
                    if item.status == 'PENDING':
                        ingredient_totals[key]['status'] = 'PENDING'
                    ingredient_totals[key]['orders'].append({
                        'date': order.date,
                        'recipe': order.recipe.name,
                        'portions': order.total_portions,
                        'effective_portions': order.total_effective_portions,
                        'quantity': item.quantity_planned
                    })
                else:
                    # Zkontrolujeme dostupnost na VŠECH skladech (quantity - quantity_blocked)
                    from apps.inventory.models import StockItem
                    
                    stock_items = StockItem.objects.filter(
                        ingredient=item.ingredient,
                        warehouse__canteen=document.canteen
                    ).annotate(
                        available=F('quantity') - F('quantity_blocked')
                    )
                    
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
                    
                    ingredient_totals[key] = {
                        'ingredient': item.ingredient,
                        'planned': item.quantity_planned,
                        'quantity_actual': item.quantity_actual,
                        'status': item.status,
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

            # Příprava dat pro denní přehled
            if order.date not in daily_picking_data:
                daily_picking_data[order.date] = []
            
            order_ingredients = []
            for item in order.picking_list_items.filter(document=document):
                # Získáme info o dostupnosti z agregovaných dat
                total_info = ingredient_totals.get(item.ingredient.id)
                
                order_ingredients.append({
                    'item_id': item.id,
                    'name': item.ingredient.name,
                    'quantity': item.quantity_planned,
                    'quantity_actual': item.quantity_actual,
                    'status': item.status,
                    'unit': item.ingredient.base_unit,
                    'has_stock': total_info['has_stock'] if total_info else True,
                    'is_sufficient': total_info['is_sufficient'] if total_info else True,
                    'warehouses_info': total_info['warehouses_info'] if total_info else [],
                })
            
            # Seřadíme suroviny abecedně
            order_ingredients.sort(key=lambda x: x['name'])
            
            daily_picking_data[order.date].append({
                'order_id': order.id,
                'recipe_name': order.recipe.name,
                'meal_type': order.meal_type,
                'portions': order.total_portions,
                'ingredients': order_ingredients,
                'is_customized': order.has_overrides
            })
        
        # Seřadíme dny a jídla v každém dni podle typu jídla
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
        
        # Získáme položky bez ProductionOrder (mimo jídla)
        items_without_orders = PickingList.objects.filter(
            document=document,
            production_order__isnull=True
        ).select_related('ingredient', 'warehouse').order_by('ingredient__name')
        
        from apps.core.models import Ingredient as IngredientModel
        from apps.canteens.models import Warehouse
        from django.contrib.auth import get_user_model
        User = get_user_model()

        canteen_warehouses = Warehouse.objects.filter(
            canteen=document.canteen, is_locked=False, is_transit_warehouse=False
        ).order_by('name')
        all_ingredients = IngredientModel.objects.filter(is_active=True).order_by('name')
        available_cooks = User.objects.filter(is_active=True).order_by('last_name', 'first_name', 'username')

        context = {
            'document': document,
            'ingredient_totals': sorted_ingredients,
            'daily_picking_data': sorted_daily_data,
            'items_without_orders': items_without_orders,
            'canteen_warehouses': canteen_warehouses,
            'all_ingredients': all_ingredients,
            'available_cooks': available_cooks,
        }
        
        return render(request, 'production/picking_list_edit.html', context)
        
    except PickingListDocument.DoesNotExist:
        messages.error(request, 'Dokument výdejky neexistuje.')
        return redirect('production:picking_list_generator')
    except PermissionDenied as e:
        messages.error(request, str(e))
        return redirect('production:picking_list_generator')


def _picking_pdf_response(document, file_obj, cache=True):
    """Helper pro vytvoření FileResponse s PDF souborem výdejky."""
    response = FileResponse(file_obj, content_type='application/pdf')
    response['Content-Disposition'] = (
        f'attachment; filename="{document.name}_{document.canteen.name}.pdf"'
    )
    if cache:
        response['Cache-Control'] = 'private, max-age=3600'
    return response


@login_required
def picking_list_pdf(request, document_id):
    """
    View pro stažení PDF výdejky.
    Vrací pre-generovaný PDF soubor pokud existuje, jinak vygeneruje on-the-fly.
    """
    from .models import PickingListDocument
    from .utils import generate_picking_list_pdf_file

    try:
        document = PickingListDocument.objects.get(id=document_id)
        
        # Kontrola oprávnění
        if not request.user.is_superuser:
            profile, _ = UserProfile.objects.get_or_create(user=request.user)
            if document.canteen not in profile.canteens.all():
                raise PermissionDenied("Nemáte oprávnění k této jídelně")
        
        # Pokud existuje pre-generovaný PDF soubor, vrátíme ho
        if document.pdf_file and document.pdf_file.storage.exists(document.pdf_file.name):
            logger.info(f"Serving pre-generated PDF for document {document_id}")
            return _picking_pdf_response(document, document.pdf_file.open('rb'))
        
        # Pokusíme se vygenerovat a uložit (pokud není archivováno)
        should_save = not document.archived
        
        if should_save:
            try:
                generate_picking_list_pdf_file(document, base_url=request.build_absolute_uri('/'))
                document.refresh_from_db()
                
                if document.pdf_file and document.pdf_file.storage.exists(document.pdf_file.name):
                    logger.info(f"Serving newly generated PDF for document {document_id}")
                    return _picking_pdf_response(document, document.pdf_file.open('rb'))
                else:
                    logger.warning(f"PDF file not present after generation for document {document_id}")
            except Exception as e:
                logger.error(f"Failed to generate and save PDF for document {document_id}: {e}")
                # fall through to on-the-fly path
        
        # Fallback: on-the-fly generování (pro archivované nebo při selhání uložení)
        logger.info(f"Generating on-the-fly PDF for document {document_id}")
        pdf_fileobj = generate_picking_list_pdf_file(
            document,
            base_url=request.build_absolute_uri('/'),
            save=False,
        )
        return _picking_pdf_response(document, pdf_fileobj, cache=False)
        
    except PickingListDocument.DoesNotExist:
        messages.error(request, 'Dokument výdejky neexistuje.')
        return redirect('production:picking_list_generator')
    except PermissionDenied as e:
        messages.error(request, str(e))
        return redirect('production:picking_list_generator')
    except MemoryError:
        logger.error(f"MemoryError generating picking list PDF: document={document_id}")
        messages.error(
            request,
            'Generování PDF selhalo — dokument je příliš velký. '
            'Zkuste rozdělit výdejku na menší časové úseky (např. po týdnech).'
        )
        return redirect('production:picking_list_generator')
    except Exception as e:
        messages.error(request, f'Chyba při generování PDF: {str(e)}')
        logger.exception("Error generating picking list PDF from document")
        return redirect('production:picking_list_generator')


@login_required
def archive_picking_list(request, document_id):
    """
    View pro archivaci výdejky.
    Výdejka může být archivována pouze když všechny položky mají status COMPLETED.
    """
    from .models import PickingListDocument
    
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Invalid request method.'}, status=405)
    
    try:
        document = PickingListDocument.objects.get(id=document_id)
        
        # Kontrola oprávnění
        if not request.user.is_superuser:
            try:
                user_profile = request.user.profile
                if document.canteen not in user_profile.canteens.all():
                    return JsonResponse({'success': False, 'error': 'Nemáte oprávnění k této jídelně.'}, status=403)
            except:
                return JsonResponse({'success': False, 'error': 'Nemáte přiřazený profil.'}, status=403)
        
        # Kontrola, zda mohou být všechny položky archivovány
        if not document.can_be_archived():
            return JsonResponse({
                'success': False, 
                'error': 'Výdejka nemůže být archivována. Všechny položky musí mít status "Vydáno".'
            }, status=400)
        
        # Archivace dokumentu
        document.archived = True
        document.archived_at = timezone.now()
        
        # Smažeme PDF soubor při archivaci (úspora místa na disku)
        if document.pdf_file:
            try:
                document.pdf_file.delete(save=False)
                logger.info(f"Deleted PDF file for archived document {document_id}")
            except FileNotFoundError:
                # Soubor už neexistuje, to je v pořádku
                logger.warning(f"PDF file not found when archiving document {document_id}")
            except Exception as e:
                # Logujeme chybu, ale pokračujeme s archivací
                logger.error(f"Error deleting PDF file for document {document_id}: {e}")
        
        # Vymažeme i timestamp pro konzistenci stavu
        document.pdf_generated_at = None
        
        document.save()
        
        return JsonResponse({
            'success': True,
            'message': f'Výdejka "{document.name}" byla úspěšně archivována.'
        })
        
    except PickingListDocument.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Dokument výdejky neexistuje.'}, status=404)
    except Exception as e:
        logger.error(f"Error archiving picking list document {document_id}: {e}", exc_info=True)
        return JsonResponse({'success': False, 'error': 'Chyba při archivaci výdejky.'}, status=500)


@login_required
def picking_list_delete(request, document_id):
    """
    View pro smazání výdejky.
    Při smazání se odblokují všechny PENDING položky na skladě.
    Archivované výdejky nelze smazat.
    COMPLETED položky se nerevertují (skutečná spotřeba ze skladu zůstane odečtena).
    """
    from .models import PickingListDocument, PickingList
    from apps.inventory.models import StockItem

    try:
        document = PickingListDocument.objects.get(id=document_id)
    except PickingListDocument.DoesNotExist:
        messages.error(request, 'Výdejka neexistuje.')
        return redirect('production:picking_list_generator')

    # Kontrola oprávnění
    if not request.user.is_superuser:
        try:
            user_profile = request.user.profile
            if document.canteen not in user_profile.canteens.all():
                messages.error(request, 'Nemáte oprávnění k této výdejce.')
                return redirect('production:picking_list_generator')
        except Exception:
            messages.error(request, 'Nemáte přiřazený profil.')
            return redirect('production:picking_list_generator')

    # Archivované dokumenty nelze smazat
    if document.archived:
        messages.error(request, 'Archivovanou výdejku nelze smazat.')
        return redirect('production:picking_list_generator')

    pending_items = document.items.filter(status=PickingList.Status.PENDING).select_related('ingredient', 'warehouse')
    completed_items = document.items.filter(status=PickingList.Status.COMPLETED).select_related('ingredient', 'warehouse')

    if request.method == 'POST':
        # Odblokovat všechny PENDING položky
        for item in pending_items:
            try:
                stock_item = StockItem.objects.get(warehouse=item.warehouse, ingredient=item.ingredient)
                stock_item.unblock_quantity(item.quantity_planned)
            except StockItem.DoesNotExist:
                pass
            except Exception as e:
                logger.error(f"Error unblocking stock item during picking list deletion: {e}", exc_info=True)

        doc_name = document.name
        document.delete()
        messages.success(request, f'Výdejka "{doc_name}" byla smazána a blokované suroviny byly odblokování.')
        return redirect('production:picking_list_generator')

    return render(request, 'production/picking_list_confirm_delete.html', {
        'document': document,
        'pending_items': pending_items,
        'completed_items': completed_items,
    })


# --- Ingredient Override Views ---

@login_required
@user_can_access_canteen_object(ProductionOrder)
def get_meal_ingredients(request, order_pk, *args, **kwargs):
    """AJAX view pro získání seznamu ingrediencí jídla včetně overrides"""
    production_order = request.instance
    
    if request.method != 'GET':
        return JsonResponse({'success': False, 'error': 'Invalid request method.'}, status=405)
    
    try:
        # Získáme overrides
        overrides_dict = {}
        for override in production_order.ingredient_overrides.select_related('ingredient'):
            overrides_dict[override.ingredient_id] = {
                'quantity_per_portion': str(override.quantity_per_portion) if override.quantity_per_portion else None,
                'original_quantity': str(override.original_quantity),
                'is_added': override.is_added,
                'is_removed': override.is_removed,
                'notes': override.notes,
                'id': override.id
            }
        
        # Sestavíme seznam ingrediencí
        ingredients = []
        
        # Ingredience z receptu
        for recipe_ing in production_order.recipe.recipeingredient_set.select_related('ingredient'):
            ingredient = recipe_ing.ingredient
            ingredient_id = ingredient.id
            
            is_removed = ingredient_id in overrides_dict and overrides_dict[ingredient_id]['is_removed']
            is_modified = ingredient_id in overrides_dict and not overrides_dict[ingredient_id]['is_added'] and not is_removed
            
            current_quantity = (
                overrides_dict[ingredient_id]['quantity_per_portion'] 
                if is_modified and overrides_dict[ingredient_id]['quantity_per_portion'] 
                else str(recipe_ing.quantity_per_portion)
            )
            
            ingredients.append({
                'id': ingredient_id,
                'name': ingredient.name,
                'quantity_per_portion': current_quantity,
                'original_quantity': str(recipe_ing.quantity_per_portion),
                'unit': ingredient.recipe_unit,
                'is_removed': is_removed,
                'is_modified': is_modified,
                'is_added': False,
                'notes': overrides_dict[ingredient_id]['notes'] if ingredient_id in overrides_dict else '',
                'override_id': overrides_dict[ingredient_id]['id'] if ingredient_id in overrides_dict else None
            })
        
        # Přidané ingredience
        for override in production_order.ingredient_overrides.filter(is_added=True).select_related('ingredient'):
            ingredient = override.ingredient
            ingredients.append({
                'id': ingredient.id,
                'name': ingredient.name,
                'quantity_per_portion': str(override.quantity_per_portion) if override.quantity_per_portion else '0',
                'original_quantity': '0',
                'unit': ingredient.recipe_unit,
                'is_removed': False,
                'is_modified': False,
                'is_added': True,
                'notes': override.notes,
                'override_id': override.id
            })
        
        return JsonResponse({
            'success': True,
            'ingredients': ingredients,
            'recipe_name': production_order.recipe.name,
            'has_issued_picking_list': production_order.has_issued_picking_list()
        })
        
    except Exception as e:
        logger.error(f"Error in get_meal_ingredients for order {order_pk}: {e}", exc_info=True)
        return JsonResponse({'success': False, 'error': 'Chyba při načítání ingrediencí.'}, status=500)


@login_required
@user_can_access_canteen_object(ProductionOrder)
def save_meal_ingredients(request, order_pk, *args, **kwargs):
    """AJAX view pro uložení upravených ingrediencí jídla"""
    production_order = request.instance
    
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Invalid request method.'}, status=405)
    
    # Kontrola, zda existuje vydaná výdejka
    if production_order.has_issued_picking_list():
        return JsonResponse({
            'success': False, 
            'error': 'Nelze upravit ingredience - výdejka již byla vydána.'
        }, status=400)
    
    try:
        from .models import ProductionOrderIngredientOverride, ProductionOrderRecipeOverride
        from apps.core.models import Ingredient
        
        data = json.loads(request.body)
        ingredients_data = data.get('ingredients', [])
        customization_note = data.get('customization_note', '')
        
        with transaction.atomic():
            # Smažeme všechny existující overrides
            production_order.ingredient_overrides.all().delete()
            
            # Slovník pro sledování ingrediencí z receptu
            recipe_ingredient_ids = set(
                production_order.recipe.recipeingredient_set.values_list('ingredient_id', flat=True)
            )
            
            has_any_override = False
            
            for ing_data in ingredients_data:
                ingredient_id = int(ing_data['id'])
                is_removed = ing_data.get('is_removed', False)
                is_added = ing_data.get('is_added', False)
                quantity_str = ing_data.get('quantity_per_portion', '0')
                notes = ing_data.get('notes', '')
                
                # Získáme ingredienci
                ingredient = get_object_or_404(Ingredient, pk=ingredient_id)
                
                # Validace množství
                try:
                    quantity = Decimal(quantity_str) if quantity_str else Decimal('0')
                    if quantity < 0:
                        return JsonResponse({
                            'success': False, 
                            'error': f'Množství pro {ingredient.name} musí být nezáporné.'
                        }, status=400)
                except (ValueError, InvalidOperation):
                    return JsonResponse({
                        'success': False, 
                        'error': f'Neplatné množství pro {ingredient.name}.'
                    }, status=400)
                
                # Zjistíme původní množství
                original_quantity = Decimal('0')
                if ingredient_id in recipe_ingredient_ids:
                    recipe_ing = production_order.recipe.recipeingredient_set.get(ingredient_id=ingredient_id)
                    original_quantity = recipe_ing.quantity_per_portion
                
                # Kontrola, zda je potřeba vytvořit override
                need_override = False
                
                if is_removed:
                    # Ingredience odstraněna z receptu
                    need_override = True
                elif is_added:
                    # Nově přidaná ingredience
                    need_override = True
                elif ingredient_id in recipe_ingredient_ids and quantity != original_quantity:
                    # Upravené množství existující ingredience
                    need_override = True
                
                if need_override:
                    has_any_override = True
                    ProductionOrderIngredientOverride.objects.create(
                        production_order=production_order,
                        ingredient=ingredient,
                        quantity_per_portion=None if is_removed else quantity,
                        original_quantity=original_quantity,
                        is_added=is_added,
                        is_removed=is_removed,
                        notes=notes
                    )
            
            # Vytvoř nebo aktualizuj ProductionOrderRecipeOverride
            if has_any_override:
                ProductionOrderRecipeOverride.objects.update_or_create(
                    production_order=production_order,
                    defaults={
                        'is_customized': True,
                        'customization_note': customization_note
                    }
                )
            else:
                # Žádné overrides - smažeme i recipe override pokud existuje
                ProductionOrderRecipeOverride.objects.filter(
                    production_order=production_order
                ).delete()
            
            # Regenerujeme výdejku
            production_order.picking_list_items.all().delete()
            production_order.generate_picking_list()
        
        return JsonResponse({
            'success': True,
            'message': 'Ingredience byly úspěšně uloženy.',
            'has_overrides': has_any_override
        })
        
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as e:
        logger.error(f"Error in save_meal_ingredients for order {order_pk}: {e}", exc_info=True)
        return JsonResponse({'success': False, 'error': 'Neplatná data.'}, status=400)
    except Exception as e:
        logger.error(f"Error in save_meal_ingredients for order {order_pk}: {e}", exc_info=True)
        return JsonResponse({'success': False, 'error': 'Chyba při ukládání ingrediencí.'}, status=500)


@login_required
def search_ingredients(request):
    """AJAX view pro vyhledávání ingrediencí (autocomplete)"""
    if request.method != 'GET':
        return JsonResponse({'success': False, 'error': 'Invalid request method.'}, status=405)
    
    try:
        from apps.core.models import Ingredient
        
        query = request.GET.get('q', '').strip()
        
        if len(query) < 2:
            return JsonResponse({'success': True, 'results': []})
        
        # Vyhledáme ingredience - kombinace původního i ASCII verze dotazu (podpora bez diakritiky)
        query_ascii = unidecode(query)
        ingredients = Ingredient.objects.filter(
            Q(name__icontains=query) | Q(name__icontains=query_ascii)
        ).order_by('name')[:20]
        
        results = [
            {
                'id': ing.id,
                'name': ing.name,
                'unit': ing.recipe_unit
            }
            for ing in ingredients
        ]
        
        return JsonResponse({'success': True, 'results': results})
        
    except Exception as e:
        logger.error(f"Error in search_ingredients: {e}", exc_info=True)
        return JsonResponse({'success': False, 'error': 'Chyba při vyhledávání.'}, status=500)


@login_required
@user_can_access_canteen_object(ProductionOrder)
def copy_meal_overrides(request, order_pk, *args, **kwargs):
    """AJAX view pro zkopírování overrides z jednoho jídla do jiného"""
    source_order = request.instance
    
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Invalid request method.'}, status=405)
    
    try:
        from .models import ProductionOrderIngredientOverride, ProductionOrderRecipeOverride
        
        data = json.loads(request.body)
        target_order_id = int(data['target_order_id'])
        
        # Získáme cílový production order
        target_order = get_object_or_404(ProductionOrder, pk=target_order_id)
        
        # Kontrola oprávnění - musí patřit do stejného MenuPlan
        if target_order.menu_plan_id != source_order.menu_plan_id:
            return JsonResponse({
                'success': False, 
                'error': 'Lze kopírovat pouze mezi jídly ve stejném jídelníčku.'
            }, status=403)
        
        # Kontrola canteen ownership přes dekorátor už proběhla pro source_order
        # Pro target_order musíme zkontrolovat také
        user = cast('User', request.user)
        if not user.is_superuser:
            try:
                target_canteen = target_order.get_canteen()
                user_canteens = user.profile.canteens.all()  # type: ignore
                if target_canteen not in user_canteens:
                    raise PermissionDenied("Nemáte přístup k jídelně cílového jídla.")
            except ObjectDoesNotExist:
                raise PermissionDenied("Nemáte přístup k jídelně cílového jídla.")
        
        # Kontrola, zda cílové jídlo nemá vydanou výdejku
        if target_order.has_issued_picking_list():
            return JsonResponse({
                'success': False, 
                'error': 'Cílové jídlo již má vydanou výdejku - nelze upravit.'
            }, status=400)
        
        # Kontrola, zda source má overrides
        if not source_order.has_overrides:
            return JsonResponse({
                'success': False, 
                'error': 'Zdrojové jídlo nemá žádné úpravy ke zkopírování.'
            }, status=400)
        
        with transaction.atomic():
            # Smažeme existující overrides cílového jídla
            target_order.ingredient_overrides.all().delete()
            
            # Zkopírujeme overrides
            for source_override in source_order.ingredient_overrides.all():
                ProductionOrderIngredientOverride.objects.create(
                    production_order=target_order,
                    ingredient=source_override.ingredient,
                    quantity_per_portion=source_override.quantity_per_portion,
                    original_quantity=source_override.original_quantity,
                    is_added=source_override.is_added,
                    is_removed=source_override.is_removed,
                    notes=source_override.notes
                )
            
            # Zkopírujeme recipe override
            try:
                source_recipe_override = source_order.recipe_override
                ProductionOrderRecipeOverride.objects.update_or_create(
                    production_order=target_order,
                    defaults={
                        'is_customized': source_recipe_override.is_customized,
                        'customization_note': source_recipe_override.customization_note
                    }
                )
            except ProductionOrderRecipeOverride.DoesNotExist:
                # Source nemá recipe override, vytvoříme nový
                ProductionOrderRecipeOverride.objects.update_or_create(
                    production_order=target_order,
                    defaults={
                        'is_customized': True,
                        'customization_note': f'Zkopírováno z: {source_order.recipe.name} ({source_order.date})'
                    }
                )
            
            # Regenerujeme výdejku cílového jídla
            target_order.picking_list_items.all().delete()
            target_order.generate_picking_list()
        
        return JsonResponse({
            'success': True,
            'message': f'Úpravy byly zkopírovány do jídla "{target_order.recipe.name}".'
        })
        
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as e:
        logger.error(f"Error in copy_meal_overrides for order {order_pk}: {e}", exc_info=True)
        return JsonResponse({'success': False, 'error': 'Neplatná data.'}, status=400)
    except ProductionOrder.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Cílové jídlo nebylo nalezeno.'}, status=404)
    except PermissionDenied as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=403)
    except Exception as e:
        logger.error(f"Error in copy_meal_overrides for order {order_pk}: {e}", exc_info=True)
        return JsonResponse({'success': False, 'error': 'Chyba při kopírování úprav.'}, status=500)


@login_required
@user_can_access_canteen_object(MenuPlan)
def bulk_reset_overrides(request, menu_pk, *args, **kwargs):
    """AJAX view pro hromadné resetování overrides vybraných jídel"""
    menu_plan = request.instance
    
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Invalid request method.'}, status=405)
    
    try:
        from .models import ProductionOrderRecipeOverride
        
        data = json.loads(request.body)
        order_ids = data.get('order_ids', [])
        
        if not order_ids:
            return JsonResponse({'success': False, 'error': 'Nebyla vybrána žádná jídla.'}, status=400)
        
        # Získáme production orders
        orders = ProductionOrder.objects.filter(
            id__in=order_ids,
            menu_plan=menu_plan
        )
        
        # Kontrola, že všechny ordery patří do menu_plan (bezpečnostní opatření)
        if orders.count() != len(order_ids):
            return JsonResponse({
                'success': False, 
                'error': 'Některá jídla nepatří do tohoto jídelníčku.'
            }, status=400)
        
        # Kontrola, že žádné z orders nemá vydanou výdejku
        orders_with_issued = []
        for order in orders:
            if order.has_issued_picking_list():
                orders_with_issued.append(order.recipe.name)
        
        if orders_with_issued:
            return JsonResponse({
                'success': False, 
                'error': f'Následující jídla již mají vydanou výdejku: {", ".join(orders_with_issued)}'
            }, status=400)
        
        with transaction.atomic():
            reset_count = 0
            for order in orders:
                if order.has_overrides:
                    # Smažeme overrides
                    order.ingredient_overrides.all().delete()
                    ProductionOrderRecipeOverride.objects.filter(
                        production_order=order
                    ).delete()
                    
                    # Regenerujeme výdejku
                    order.picking_list_items.all().delete()
                    order.generate_picking_list()
                    
                    reset_count += 1
        
        return JsonResponse({
            'success': True,
            'message': f'Úpravy byly resetovány u {reset_count} jídel.',
            'reset_count': reset_count
        })
        
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as e:
        logger.error(f"Error in bulk_reset_overrides for menu {menu_pk}: {e}", exc_info=True)
        return JsonResponse({'success': False, 'error': 'Neplatná data.'}, status=400)
    except Exception as e:
        logger.error(f"Error in bulk_reset_overrides for menu {menu_pk}: {e}", exc_info=True)
        return JsonResponse({'success': False, 'error': 'Chyba při resetování úprav.'}, status=500)

