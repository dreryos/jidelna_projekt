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
from functools import wraps
from typing import Any, Dict, Type, TYPE_CHECKING, cast
from collections import defaultdict

from django.db import models
from django.db.models import F, Sum
from django.db.models.query import QuerySet
from django.http import HttpRequest, HttpResponse
from django.core.exceptions import PermissionDenied, ObjectDoesNotExist
from django.http import JsonResponse, Http404
from django.db import transaction

from .models import ProductionOrder, PickingList, MenuPlan
from .forms import MenuPlanForm, MenuPlanCoefficientFormSet
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
                'order': coef.order
            }
            for coef in self.object.default_coefficients.all().order_by('order')
        ]
        
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


# ---------------------------------------------------------------------------
# Visual editor for MenuPlan (adapter for template-based visual editor)
# ---------------------------------------------------------------------------
class MenuPlanVisualEditView(CanteenOwnerMixin, UpdateView):
    """Vizuální editor pro manuální jídelníček (adapter používá šablonový UI)"""
    model = MenuPlan
    template_name = 'production/menu_template_visual_edit.html'
    fields = []

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # Build schedule dict in the same shape as MenuTemplate.parse_schedule_to_dict()
        from collections import defaultdict
        schedule = defaultdict(list)
        date_from = self.object.date_from
        for order in self.object.production_orders.all().select_related('recipe'):
            day_index = (order.date - date_from).days
            schedule[day_index].append({
                'recipe_code': order.recipe.code,
                'meal_type': order.meal_type,
                'note': '',
                'unique_id': f'order-{order.id}',
                'order_id': order.id,
                'portion_count': None
            })

        import json
        context['schedule_dict'] = schedule
        context['schedule_dict_json'] = json.dumps({str(k): v for k, v in schedule.items()})

        # Recipes choices for Select2 (use recipe.code to match template format)
        recipes = Recipe.objects.all().order_by('name')
        context['recipe_choices'] = json.dumps([
            {'id': r.code, 'text': r.name}
            for r in recipes
        ])

        # Meal type choices
        from .models import ProductionOrder
        context['meal_type_choices'] = [
            {'value': choice[0], 'label': choice[1]}
            for choice in ProductionOrder.MealType.choices
        ]
        context['meal_type_choices_json'] = json.dumps(context['meal_type_choices'])

        # Simple stats
        context['stats'] = {
            'days': self.object.get_days_count(),
            'total_meals': self.object.get_total_orders(),
            'total_portions': 0
        }

        # Provide AJAX endpoints for the template JS to call
        from django.urls import reverse
        ajax_urls = {
            'addMeal': reverse('production:menu_visual_add_meal_ajax', kwargs={'menu_pk': self.object.pk}),
            'removeMeal': reverse('production:menu_visual_remove_meal_ajax', kwargs={'menu_pk': self.object.pk}),
            'reorder': reverse('production:menu_visual_reorder_ajax', kwargs={'menu_pk': self.object.pk}),
            'copyDay': reverse('production:menu_visual_copy_day_ajax', kwargs={'menu_pk': self.object.pk}),
            'clearDay': reverse('production:menu_visual_clear_day_ajax', kwargs={'menu_pk': self.object.pk}),
        }
        context['ajax_urls'] = json.dumps(ajax_urls)

        # Maximum days
        context['max_days'] = 30

        return context


@login_required
@user_can_access_canteen_object(MenuPlan)
def menu_visual_add_meal_ajax(request, menu_pk, *args, **kwargs):
    """AJAX: Přidání jídla do MenuPlan prostřednictvím vizuálního editoru"""
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Pouze POST metoda'}, status=405)

    menu_plan = request.instance

    try:
        data = json.loads(request.body)
        day_index = int(data.get('day_index'))
        recipe_code = data['recipe_code']
        meal_type = data.get('meal_type', 'LUNCH')
        note = data.get('note', '')
        portion_count = data.get('portion_count')

        recipe = get_object_or_404(Recipe, code=recipe_code)
        meal_date = menu_plan.date_from + timedelta(days=day_index)

        with transaction.atomic():
            order = ProductionOrder.objects.create(
                menu_plan=menu_plan,
                recipe=recipe,
                date=meal_date,
                meal_type=meal_type
            )

        meal_obj = {
            'recipe_code': recipe.code,
            'meal_type': meal_type,
            'note': note,
            'unique_id': f'order-{order.id}',
            'order_id': order.id,
            'portion_count': portion_count
        }

        stats = {
            'days': menu_plan.get_days_count(),
            'total_meals': menu_plan.get_total_orders(),
            'total_portions': 0
        }

        return JsonResponse({'success': True, 'meal': meal_obj, 'stats': stats})

    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as e:
        logger.error(f"Error in menu_visual_add_meal_ajax for menu {menu_pk}: {e}", exc_info=True)
        return JsonResponse({'success': False, 'error': 'Invalid data provided.'}, status=400)


@login_required
@user_can_access_canteen_object(MenuPlan)
def menu_visual_remove_meal_ajax(request, menu_pk, *args, **kwargs):
    """AJAX: Odstranění jídla (podpora unique_id nebo order_id)"""
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Pouze POST metoda'}, status=405)

    menu_plan = request.instance

    try:
        data = json.loads(request.body)
        order_id = data.get('order_id')
        unique_id = data.get('unique_id')

        if unique_id and unique_id.startswith('order-'):
            try:
                order_id = int(unique_id.split('-', 1)[1])
            except Exception:
                order_id = None

        if not order_id:
            return JsonResponse({'success': False, 'error': 'Chybí order_id'}, status=400)

        order = get_object_or_404(ProductionOrder, pk=order_id, menu_plan=menu_plan)

        if order.has_issued_picking_list():
            return JsonResponse({'success': False, 'error': 'Nelze odstranit jídlo s vydanou výdejkou.'}, status=403)

        with transaction.atomic():
            removed_id = order.id
            order.delete()

        stats = {
            'days': menu_plan.get_days_count(),
            'total_meals': menu_plan.get_total_orders(),
            'total_portions': 0
        }

        return JsonResponse({'success': True, 'removed_order_id': removed_id, 'stats': stats})

    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as e:
        logger.error(f"Error in menu_visual_remove_meal_ajax for menu {menu_pk}: {e}", exc_info=True)
        return JsonResponse({'success': False, 'error': 'Invalid data provided.'}, status=400)


@login_required
@user_can_access_canteen_object(MenuPlan)
def menu_visual_reorder_ajax(request, menu_pk, *args, **kwargs):
    """AJAX: Reorder within day - no-op for now (frontend persists order)"""
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Pouze POST metoda'}, status=405)

    return JsonResponse({'success': True})


@login_required
@user_can_access_canteen_object(MenuPlan)
def menu_visual_copy_day_ajax(request, menu_pk, *args, **kwargs):
    """AJAX: Copy meals from one day to another (simple implementation)"""
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Pouze POST metoda'}, status=405)

    menu_plan = request.instance

    try:
        data = json.loads(request.body)
        source_day = int(data['source_day'])
        target_day = int(data['target_day'])

        source_date = menu_plan.date_from + timedelta(days=source_day)
        target_date = menu_plan.date_from + timedelta(days=target_day)

        source_orders = menu_plan.production_orders.filter(date=source_date).exclude(picking_list_items__document__isnull=False)
        copied_meals = []
        with transaction.atomic():
            for ord in source_orders:
                new_ord = ProductionOrder.objects.create(
                    menu_plan=menu_plan,
                    recipe=ord.recipe,
                    date=target_date,
                    meal_type=ord.meal_type
                )
                copied_meals.append({
                    'recipe_code': new_ord.recipe.code,
                    'meal_type': new_ord.meal_type,
                    'note': '',
                    'unique_id': f'order-{new_ord.id}',
                    'order_id': new_ord.id,
                    'portion_count': None
                })

        stats = {
            'days': menu_plan.get_days_count(),
            'total_meals': menu_plan.get_total_orders(),
            'total_portions': 0
        }

        return JsonResponse({'success': True, 'copied_meals': copied_meals, 'stats': stats})

    except Exception as e:
        logger.error(f"Error in menu_visual_copy_day_ajax for menu {menu_pk}: {e}", exc_info=True)
        return JsonResponse({'success': False, 'error': 'Chyba při kopírování dne.'}, status=400)


@login_required
@user_can_access_canteen_object(MenuPlan)
def menu_visual_clear_day_ajax(request, menu_pk, *args, **kwargs):
    """AJAX: Clear all meals for a day in MenuPlan"""
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Pouze POST metoda'}, status=405)

    menu_plan = request.instance

    try:
        data = json.loads(request.body)
        day_index = int(data['day_index'])
        target_date = menu_plan.date_from + timedelta(days=day_index)

        orders_to_delete = menu_plan.production_orders.filter(date=target_date).exclude(picking_list_items__document__isnull=False)
        count = orders_to_delete.count()
        with transaction.atomic():
            orders_to_delete.delete()

        stats = {
            'days': menu_plan.get_days_count(),
            'total_meals': menu_plan.get_total_orders(),
            'total_portions': 0
        }

        return JsonResponse({'success': True, 'removed_count': count, 'stats': stats})

    except Exception as e:
        logger.error(f"Error in menu_visual_clear_day_ajax for menu {menu_pk}: {e}", exc_info=True)
        return JsonResponse({'success': False, 'error': 'Chyba při čištění dne.'}, status=400)


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
                ProductionOrderPortionVariant.objects.create(
                    production_order=order,
                    name=variant_info.get('name', ''),
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

    if order.has_issued_picking_list():
        return JsonResponse({'success': False, 'error': 'Nelze smazat jídlo s vydanou výdejkou.'}, status=403)

    try:
        with transaction.atomic():
            order_id = order.id
            order.delete()
        
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
    
    canteens = Canteen.objects.all()
    
    # Získání user profile pro filtraci jídelen
    if not request.user.is_superuser:
        try:
            user_profile = request.user.userprofile
            canteens = user_profile.canteens.all()
        except:
            canteens = Canteen.objects.none()
    
    # Načtení existujících dokumentů výdejek
    documents = PickingListDocument.objects.all()
    if not request.user.is_superuser:
        try:
            user_profile = request.user.userprofile
            documents = documents.filter(canteen__in=user_profile.canteens.all())
        except:
            documents = PickingListDocument.objects.none()
    
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
                try:
                    user_profile = request.user.userprofile
                    if canteen not in user_profile.canteens.all():
                        raise PermissionDenied("Nemáte oprávnění k této jídelně")
                except:
                    raise PermissionDenied("Nemáte přiřazený profil")
            
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
                if not order.picking_list_items.exists():
                    order.generate_picking_list()
                
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
                    'portions': order.total_portions,
                    'ingredients': order_ingredients
                })
            
            # Seřadíme dny
            sorted_daily_data = sorted(daily_picking_data.items())
            
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
        
        # Kontrola oprávnění
        if not request.user.is_superuser:
            try:
                user_profile = request.user.userprofile
                if document.canteen not in user_profile.canteens.all():
                    raise PermissionDenied("Nemáte oprávnění k této jídelně")
            except:
                raise PermissionDenied("Nemáte přiřazený profil")
        
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
            # Zpracování formuláře s editací skutečných množství
            updated_count = 0
            
            # Zpracujeme agregované položky (po ingrediencích)
            for key, value in request.POST.items():
                if key.startswith('quantity_actual_ingredient_'):
                    ingredient_id = int(key.replace('quantity_actual_ingredient_', ''))
                    status_key = f'status_ingredient_{ingredient_id}'
                    
                    quantity_str = value.strip()
                    if quantity_str:
                        try:
                            quantity = Decimal(quantity_str.replace(',', '.'))
                            status = request.POST.get(status_key, 'PENDING')
                            
                            # Aktualizujeme všechny picking list items pro tuto surovinu
                            items = picking_items.filter(ingredient_id=ingredient_id)
                            for item in items:
                                # Rozpočítáme množství proporcionálně podle plánovaného množství
                                total_planned = items.aggregate(total=models.Sum('quantity_planned'))['total']
                                if total_planned > 0:
                                    proportion = item.quantity_planned / total_planned
                                    item.quantity_actual = quantity * proportion
                                else:
                                    item.quantity_actual = quantity / items.count()
                                
                                item.status = status
                                item.save()
                                updated_count += 1
                        except (ValueError, InvalidOperation):
                            from apps.core.models import Ingredient
                            try:
                                ingredient = Ingredient.objects.get(id=ingredient_id)
                                messages.error(request, f'Neplatné množství pro {ingredient.name}')
                            except Ingredient.DoesNotExist:
                                messages.error(request, f'Neplatné množství pro surovinu ID {ingredient_id}')
            
            messages.success(request, f'Aktualizováno {updated_count} položek.')
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
                'portions': order.total_portions,
                'ingredients': order_ingredients
            })
        
        # Seřadíme dny
        sorted_daily_data = sorted(daily_picking_data.items())
        
        # Seřadíme ingredience abecedně
        sorted_ingredients = sorted(ingredient_totals.values(), key=lambda x: x['ingredient'].name)
        
        # Počítáme problematické položky
        missing_count = sum(1 for i in ingredient_totals.values() if not i['has_stock'])
        insufficient_count = sum(1 for i in ingredient_totals.values() if i['has_stock'] and not i['is_sufficient'])
        
        context = {
            'document': document,
            'ingredient_totals': sorted_ingredients,
            'daily_picking_data': sorted_daily_data,
        }
        
        return render(request, 'production/picking_list_edit.html', context)
        
    except PickingListDocument.DoesNotExist:
        messages.error(request, 'Dokument výdejky neexistuje.')
        return redirect('production:picking_list_generator')
    except PermissionDenied as e:
        messages.error(request, str(e))
        return redirect('production:picking_list_generator')


@login_required
def picking_list_pdf(request, document_id):
    """
    View pro regeneraci PDF z existujícího dokumentu výdejky.
    """
    from .models import PickingListDocument
    
    try:
        document = PickingListDocument.objects.get(id=document_id)
        
        # Kontrola oprávnění
        if not request.user.is_superuser:
            try:
                user_profile = request.user.userprofile
                if document.canteen not in user_profile.canteens.all():
                    raise PermissionDenied("Nemáte oprávnění k této jídelně")
            except:
                raise PermissionDenied("Nemáte přiřazený profil")
        
        # Načteme všechny ProductionOrders souvisící s tímto dokumentem
        orders = ProductionOrder.objects.filter(
            picking_list_items__document=document
        ).distinct().select_related('recipe', 'canteen', 'menu_plan').prefetch_related(
            'portion_variants',
            'picking_list_items'
        ).order_by('date', 'recipe__name')
        
        # Agregujeme suroviny z picking list items tohoto dokumentu
        ingredient_totals = {}
        
        # Připravíme data strukturovaná podle dnů a jídel pro PDF
        daily_picking_data = {}
        
        for order in orders:
            # Agregace pro celkový přehled (zachováno pro kompatibilitu)
            for item in order.picking_list_items.filter(document=document):
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
                'portions': order.total_portions,
                'ingredients': order_ingredients
            })
        
        # Seřadíme dny
        sorted_daily_data = sorted(daily_picking_data.items())
        
        # Seřadíme ingredience abecedně
        sorted_ingredients = sorted(ingredient_totals.values(), key=lambda x: x['ingredient'].name)
        
        # Počítáme problematické položky
        missing_count = sum(1 for i in ingredient_totals.values() if not i['has_stock'])
        insufficient_count = sum(1 for i in ingredient_totals.values() if i['has_stock'] and not i['is_sufficient'])
        
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
        }
        
        # Vygenerujeme PDF
        from django.template.loader import render_to_string
        try:
            from weasyprint import HTML
        except OSError as e:
            if "libgobject" in str(e) or "cannot load library" in str(e):
                messages.error(request, "Chyba: V systému chybí knihovny GTK3 potřebné pro generování PDF (WeasyPrint). Prosím nainstalujte GTK3 Runtime.")
                logger.error(f"WeasyPrint GTK3 libraries missing: {e}")
                return redirect('production:picking_list_generator')
            raise e

        from django.http import HttpResponse
        
        html_string = render_to_string('production/picking_list_pdf.html', context)
        html = HTML(string=html_string, base_url=request.build_absolute_uri())
        
        response = HttpResponse(content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="{document.name}_{document.canteen.name}.pdf"'
        html.write_pdf(response)
        
        return response
        
    except PickingListDocument.DoesNotExist:
        messages.error(request, 'Dokument výdejky neexistuje.')
        return redirect('production:picking_list_generator')
    except PermissionDenied as e:
        messages.error(request, str(e))
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
