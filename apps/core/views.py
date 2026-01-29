from django.shortcuts import render
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, JsonResponse
from django.contrib.auth import logout
from django.shortcuts import redirect, get_object_or_404
from django.views.generic import ListView, CreateView, UpdateView, DeleteView
from django.urls import reverse_lazy
from django.contrib.auth.mixins import LoginRequiredMixin
from django.forms import inlineformset_factory
from django.core.exceptions import ObjectDoesNotExist
from django.db.models import Model, ProtectedError
from typing import Type, Any
from functools import wraps

from apps.core.models import Recipe, RecipeIngredient, Ingredient
from apps.core.forms import RecipeIngredientForm, RecipeForm, IngredientForm
from apps.core.backup import export_backup_xml, import_backup_xml

"""
Tento modul je místo pro view funkce související s jádrem aplikace (recepty, suroviny).
V současné době používáme hlavně Django admin pro CRUD operace, proto zde nejsou implementovány konkrétní view.
"""

# --- Authorization Mixins ---

class CanteenAccessMixin(LoginRequiredMixin):
	"""
	Mixin pro filtrování objektů na základě přiřazených jídelen uživatele.
	- Superuser vidí všechno
	- Ostatní vidí jen objekty spojené s jejich managed_canteens (přes warehouse__canteen)
	"""
	def get_queryset(self):
		queryset = super().get_queryset()
		user = self.request.user
		
		# Superuser vidí všechno
		if user.is_superuser:
			return queryset
		
		# Ostatní vidí jen objekty z jejich jídelen
		try:
			user_canteens = user.profile.canteens.all()
			if hasattr(self.model, 'warehouse'):
				# Pro StockItem, GoodsReceipt, atd. s warehouse.canteen
				queryset = queryset.filter(warehouse__canteen__in=user_canteens)
			elif hasattr(self.model, 'canteen'):
				# Pro objekty s direct canteen FK
				queryset = queryset.filter(canteen__in=user_canteens)
		except (ObjectDoesNotExist, AttributeError):
			return queryset.none()
		
		return queryset


def user_can_access_canteen(user, canteen) -> bool:
	"""
	Pomocná funkce pro kontrolu přístupu uživatele k jídelně.
	- True pokud je superuser nebo má canteen v managed_canteens
	- False jinak
	"""
	if user.is_superuser:
		return True
	try:
		return canteen in user.profile.canteens.all()
	except (ObjectDoesNotExist, AttributeError):
		return False

def index(request):
	return render(request, 'core/index.html', {})

@login_required
def home(request):
    # Simple homepage showing links based on permissions
    # Načteme probíhající inventury pro upozornění
    from apps.inventory.models import InventoryVerification
    
    active_verifications = InventoryVerification.objects.filter(
        status=InventoryVerification.Status.IN_PROGRESS
    ).select_related('warehouse', 'started_by').order_by('-started_at')[:5]
    
    context = {
        'user': request.user,
        'active_verifications': active_verifications,
    }
    return render(request, 'home.html', context)


from django.views.decorators.http import require_POST


@require_POST
def logout_view(request):
	"""Log out a user on POST and redirect to login. GET will return 405."""
	logout(request)
	return redirect('login')


@login_required
def backup_export_xml_view(request):
	if not request.user.is_superuser:
		return HttpResponse(status=403)

	# Získáme vybrané entity z GET parametrů
	selected_entities = request.GET.getlist('entities')
	
	# Pokud nejsou vybrány žádné entity, použijeme výchozí
	if not selected_entities:
		selected_entities = None

	xml_bytes = export_backup_xml(selected_entities)
	
	# Generujeme název souboru podle obsahu
	if selected_entities:
		filename = f"backup_{'_'.join(selected_entities[:3])}.xml"
		if len(selected_entities) > 3:
			filename = f"backup_partial_{len(selected_entities)}_entities.xml"
	else:
		filename = "backup_default.xml"
	
	response = HttpResponse(xml_bytes, content_type='application/xml')
	response['Content-Disposition'] = f'attachment; filename="{filename}"'
	return response


@login_required
@require_POST
def backup_import_xml_view(request):
	if not request.user.is_superuser:
		return JsonResponse({'success': False, 'error': 'Forbidden'}, status=403)

	dry_run = request.GET.get('dry_run') == '1' or request.POST.get('dry_run') == '1'

	if request.FILES:
		xml_content = next(iter(request.FILES.values())).read()
	else:
		xml_content = request.body

	if not xml_content:
		return JsonResponse({'success': False, 'error': 'Prázdný XML obsah'}, status=400)

	try:
		report = import_backup_xml(xml_content, dry_run=dry_run)
		return JsonResponse({'success': True, 'dry_run': dry_run, 'report': report})
	except Exception as e:
		return JsonResponse({'success': False, 'error': str(e)}, status=400)


@login_required
def backup_page(request):
	if not request.user.is_superuser:
		return HttpResponse(status=403)

	if request.method == 'POST':
		dry_run = request.POST.get('dry_run') == '1'
		file = request.FILES.get('file')
		if not file:
			messages.error(request, 'Nahrajte prosím XML soubor.')
			return redirect('core:backup_page')
		try:
			report = import_backup_xml(file.read(), dry_run=dry_run)
			if dry_run:
				messages.warning(request, f"Dry-run: žádné změny neuloženy. Report: {report}")
			else:
				messages.success(request, f"Import dokončen. Report: {report}")
		except Exception as e:
			messages.error(request, f'Chyba při importu: {e}')
		return redirect('core:backup_page')

	return render(request, 'core/backup.html')


class RecipeListView(LoginRequiredMixin, ListView):
	model = Recipe
	template_name = 'core/recipe_list.html'
	
	def get_queryset(self):
		queryset = super().get_queryset().select_related('category')
		category_id = self.request.GET.get('category')
		if category_id:
			queryset = queryset.filter(category_id=category_id)
		return queryset.order_by('category__code', 'code')
	
	def get_context_data(self, **kwargs):
		context = super().get_context_data(**kwargs)
		from apps.core.models import Category
		context['categories'] = Category.objects.all()
		context['selected_category'] = self.request.GET.get('category', '')
		return context


RecipeIngredientFormSet = inlineformset_factory(
    Recipe, 
    RecipeIngredient, 
    form=RecipeIngredientForm,
    extra=1, 
    can_delete=True
)


class RecipeCreateView(LoginRequiredMixin, CreateView):
	model = Recipe
	form_class = RecipeForm
	template_name = 'core/recipe_form.html'
	success_url = reverse_lazy('core:recipe_list')

	def get_context_data(self, **kwargs):
		data = super().get_context_data(**kwargs)
		if self.request.POST:
			data['ingredients'] = RecipeIngredientFormSet(self.request.POST)
		else:
			data['ingredients'] = RecipeIngredientFormSet()
		
		# Připravíme data surovin pro autocomplete jako JSON
		import json
		ingredients_list = [
			{
				'id': ing.id, 
				'name': ing.name,
				'unit': ing.recipe_unit,
				'base_unit': ing.base_unit
			} 
			for ing in Ingredient.objects.all().order_by('name')
		]
		data['all_ingredients'] = json.dumps(ingredients_list)
		return data

	def form_valid(self, form):
		context = self.get_context_data()
		ingredients = context['ingredients']
		if ingredients.is_valid():
			self.object = form.save()
			ingredients.instance = self.object
			ingredients.save()
			return super().form_valid(form)
		else:
			return self.render_to_response(context)


class RecipeUpdateView(LoginRequiredMixin, UpdateView):
	model = Recipe
	form_class = RecipeForm
	template_name = 'core/recipe_form.html'
	success_url = reverse_lazy('core:recipe_list')

	def get_context_data(self, **kwargs):
		data = super().get_context_data(**kwargs)
		if self.request.POST:
			data['ingredients'] = RecipeIngredientFormSet(self.request.POST, instance=self.object)
		else:
			data['ingredients'] = RecipeIngredientFormSet(instance=self.object)
		
		# Připravíme data surovin pro autocomplete jako JSON
		import json
		ingredients_list = [
			{
				'id': ing.id, 
				'name': ing.name,
				'unit': ing.recipe_unit,
				'base_unit': ing.base_unit
			} 
			for ing in Ingredient.objects.all().order_by('name')
		]
		data['all_ingredients'] = json.dumps(ingredients_list)
		return data

	def form_valid(self, form):
		context = self.get_context_data()
		ingredients = context['ingredients']
		if ingredients.is_valid():
			self.object = form.save()
			ingredients.instance = self.object
			ingredients.save()
			return super().form_valid(form)
		else:
			return self.render_to_response(context)


class RecipeDeleteView(LoginRequiredMixin, DeleteView):
	model = Recipe
	template_name = 'core/recipe_confirm_delete.html'
	success_url = reverse_lazy('core:recipe_list')


# Views pro správu surovin

class IngredientListView(LoginRequiredMixin, ListView):
	model = Ingredient
	template_name = 'core/ingredient_list.html'
	context_object_name = 'ingredients'
	ordering = ['name']
	
	def get_queryset(self):
		"""Filtrovat pouze aktivní suroviny pokud není požadováno jinak"""
		queryset = super().get_queryset()
		# Zobrazit i neaktivní pouze když je explicitně vyžádáno
		show_inactive = self.request.GET.get('show_inactive', 'false') == 'true'
		if not show_inactive:
			queryset = queryset.filter(is_active=True)
		return queryset


class IngredientCreateView(LoginRequiredMixin, CreateView):
	model = Ingredient
	form_class = IngredientForm
	template_name = 'core/ingredient_form.html'
	success_url = reverse_lazy('core:ingredient_list')


class IngredientUpdateView(LoginRequiredMixin, UpdateView):
	model = Ingredient
	form_class = IngredientForm
	template_name = 'core/ingredient_form.html'
	success_url = reverse_lazy('core:ingredient_list')


class IngredientDeleteView(LoginRequiredMixin, DeleteView):
	model = Ingredient
	template_name = 'core/ingredient_confirm_delete.html'
	success_url = reverse_lazy('core:ingredient_list')
	
	def post(self, request, *args, **kwargs):
		"""
		Přepsaná metoda pro ošetření ProtectedError při mazání.
		Zobrazí uživatelsky přívětivou chybovou hlášku.
		"""
		self.object = self.get_object()
		
		try:
			return super().post(request, *args, **kwargs)
		except ProtectedError as e:
			# Zjistíme, které objekty brání smazání
			protected_objects = e.protected_objects
			
			# Vytvoříme seznam typů objektů
			object_types = {}
			for protected_obj in protected_objects:
				obj_type = type(protected_obj).__name__
				if obj_type in object_types:
					object_types[obj_type] += 1
				else:
					object_types[obj_type] = 1
			
			# Vytvoříme čitelnou zprávu
			items_list = []
			for obj_type, count in object_types.items():
				# Přeložíme názvy modelů do češtiny
				translations = {
					'PickingList': 'výdejky',
					'GoodsReceiptItem': 'položky příjmu zboží',
					'InventoryVerificationItem': 'položky inventury',
					'StockTransferItem': 'položky převodky',
					'ProductionOrderIngredientOverride': 'úpravy surovin ve výrobních příkazech'
				}
				translated_name = translations.get(obj_type, obj_type)
				items_list.append(f"{count}× {translated_name}")
			
			message = (
				f'Nelze smazat surovinu "{self.object.name}", protože je použita v následujících záznamech: '
				f'{", ".join(items_list)}. '
				f'Nejprve odstraňte nebo upravte tyto záznamy.'
			)
			
			messages.error(request, message)
			return redirect('core:ingredient_list')


from django.views.decorators.http import require_POST
from decimal import Decimal


@login_required
@require_POST
def ajax_add_ingredient(request):
	"""AJAX endpoint pro přidání nové suroviny z modálního okna"""
	try:
		name = request.POST.get('name', '').strip()
		base_unit = request.POST.get('base_unit', 'kg')
		recipe_unit = request.POST.get('recipe_unit', 'g')
		conversion_factor = request.POST.get('conversion_factor', '1000')
		
		if not name:
			return JsonResponse({'success': False, 'error': 'Název suroviny je povinný'}, status=400)
		
		# Kontrola, zda surovina již neexistuje
		if Ingredient.objects.filter(name__iexact=name).exists():
			return JsonResponse({'success': False, 'error': f'Surovina "{name}" již existuje'}, status=400)
		
		# Vytvoření nové suroviny
		ingredient = Ingredient.objects.create(
			name=name,
			unit=base_unit,  # Pro zpětnou kompatibilitu
			base_unit=base_unit,
			recipe_unit=recipe_unit,
			conversion_factor=Decimal(conversion_factor)
		)
		
		return JsonResponse({
			'success': True,
			'ingredient': {
				'id': ingredient.id,
				'name': ingredient.name,
				'unit': ingredient.recipe_unit,
				'base_unit': ingredient.base_unit
			}
		})
		
	except Exception as e:
		return JsonResponse({'success': False, 'error': str(e)}, status=500)
