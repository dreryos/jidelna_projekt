from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.contrib.auth import logout
from django.shortcuts import redirect
from django.views.generic import ListView, CreateView, UpdateView, DeleteView
from django.urls import reverse_lazy
from django.contrib.auth.mixins import LoginRequiredMixin
from django.forms import inlineformset_factory

from apps.core.models import Recipe, RecipeIngredient, Ingredient

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


RecipeIngredientFormSet = inlineformset_factory(Recipe, RecipeIngredient, fields=('ingredient','quantity_adult','quantity_child'), extra=1, can_delete=True)


class RecipeCreateView(LoginRequiredMixin, CreateView):
	model = Recipe
	fields = ['name', 'description']
	template_name = 'core/recipe_form.html'
	success_url = reverse_lazy('core:recipe_list')

	def get_context_data(self, **kwargs):
		data = super().get_context_data(**kwargs)
		if self.request.POST:
			data['ingredients'] = RecipeIngredientFormSet(self.request.POST)
		else:
			data['ingredients'] = RecipeIngredientFormSet()
		data['all_ingredients'] = Ingredient.objects.all()
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
	fields = ['name', 'description']
	template_name = 'core/recipe_form.html'
	success_url = reverse_lazy('core:recipe_list')

	def get_context_data(self, **kwargs):
		data = super().get_context_data(**kwargs)
		if self.request.POST:
			data['ingredients'] = RecipeIngredientFormSet(self.request.POST, instance=self.object)
		else:
			data['ingredients'] = RecipeIngredientFormSet(instance=self.object)
		data['all_ingredients'] = Ingredient.objects.all()
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

"""
Tento modul je místo pro view funkce související s jádrem aplikace (recepty, suroviny).
V současné době používáme hlavně Django admin pro CRUD operace, proto zde nejsou implementovány konkrétní view.
"""

# Create your views here.
