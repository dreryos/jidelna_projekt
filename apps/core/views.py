from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.contrib.auth import logout
from django.shortcuts import redirect
from django.views.generic import ListView, CreateView, UpdateView, DeleteView
from django.urls import reverse_lazy
from django.contrib.auth.mixins import LoginRequiredMixin
from django.forms import inlineformset_factory

from apps.core.models import Recipe, RecipeIngredient, Ingredient
from apps.core.forms import RecipeIngredientForm, RecipeForm, IngredientForm

"""
Tento modul je místo pro view funkce související s jádrem aplikace (recepty, suroviny).
V současné době používáme hlavně Django admin pro CRUD operace, proto zde nejsou implementovány konkrétní view.
"""

def index(request):
	return render(request, 'core/index.html', {})

@login_required
def home(request):
	# Simple homepage showing links based on permissions
	return render(request, 'home.html', {'user': request.user})


from django.views.decorators.http import require_POST


@require_POST
def logout_view(request):
	"""Log out a user on POST and redirect to login. GET will return 405."""
	logout(request)
	return redirect('login')


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
		self.object = form.save()
		if ingredients.is_valid():
			ingredients.instance = self.object
			ingredients.save()
		return super().form_valid(form)


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
		self.object = form.save()
		if ingredients.is_valid():
			ingredients.instance = self.object
			ingredients.save()
		return super().form_valid(form)


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


from django.http import JsonResponse
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
