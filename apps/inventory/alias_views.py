"""
Správa aliasů dodavatelských názvů (`SupplierItemAlias`).

Aliasy vznikají samy při potvrzení importu, ale jejich oprava dřív šla jen
v administraci. Špatně naučený alias se přitom opakuje při každém dalším
importu: `Chléb konz. BK Rohlik` → Rohlík se v datech trefil u čtyř položek,
než ho někdo našel. Tady jde alias vidět, doplnit, opravit i smazat.

Aliasy nejsou vázané na jídelnu: dodavatel a surovina jsou sdílené katalogy
(viz CLAUDE.md), takže ani tady se nescopuje. Zápis uživatelům s `is_readonly`
blokuje `ReadOnlyUserMiddleware` pro každé non-GET.
"""
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.http import HttpResponseRedirect
from django.urls import reverse
from django.views.generic import CreateView, DeleteView, ListView, UpdateView

from apps.core.models import Ingredient

from .forms import SupplierItemAliasForm
from .models import Supplier, SupplierItemAlias


class AliasListView(LoginRequiredMixin, ListView):
    model = SupplierItemAlias
    template_name = 'inventory/alias_list.html'
    context_object_name = 'aliases'
    paginate_by = 50

    def get_queryset(self):
        qs = SupplierItemAlias.objects.select_related('ingredient', 'supplier')
        params = self.request.GET

        q = params.get('q', '').strip()
        if q:
            qs = qs.filter(
                Q(raw_name__icontains=q) | Q(item_code__icontains=q)
                | Q(ingredient__name__icontains=q)
            )
        if params.get('supplier', '').isdigit():
            qs = qs.filter(supplier_id=params['supplier'])
        elif params.get('supplier') == 'global':
            qs = qs.filter(supplier__isnull=True)
        if params.get('ingredient', '').isdigit():
            qs = qs.filter(ingredient_id=params['ingredient'])
        if params.get('bez_kodu') == '1':
            qs = qs.filter(item_code='')
        if params.get('nezbozni') == '1':
            qs = qs.filter(is_ignored=True)
        return qs.order_by('ingredient__name', 'supplier__name', 'raw_name')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['suppliers'] = Supplier.objects.order_by('name')
        ingredient_id = self.request.GET.get('ingredient', '')
        context['ingredient'] = (
            Ingredient.objects.filter(pk=ingredient_id).first()
            if ingredient_id.isdigit() else None
        )
        # Stránkování zachovává filtry, jen mění číslo stránky.
        query = self.request.GET.copy()
        query.pop('page', None)
        context['filter_query'] = query.urlencode()
        context['filters'] = self.request.GET
        return context


class _AliasFormMixin(LoginRequiredMixin):
    model = SupplierItemAlias
    form_class = SupplierItemAliasForm
    template_name = 'inventory/alias_form.html'

    def form_valid(self, form):
        """
        Uloží alias; kolizi názvu z konkurenčního požadavku vrátí jako chybu
        u pole. Kontrola v `clean()` a zápis nejsou jedna transakce, takže
        dva souběžné požadavky projdou oba a unikátnost pak shodí až databáze.
        """
        try:
            with transaction.atomic():
                return self._save(form)
        except IntegrityError:
            form.add_error(
                'raw_name',
                'Alias s tímto názvem u tohoto dodavatele mezitím vznikl, '
                'upravte ten stávající.'
            )
            return self.form_invalid(form)

    def _save(self, form):
        return super().form_valid(form)

    def get_success_url(self):
        ingredient_id = self.object.ingredient_id
        url = reverse('inventory:alias_list')
        return f'{url}?ingredient={ingredient_id}' if ingredient_id else url


class AliasCreateView(_AliasFormMixin, CreateView):
    def get_initial(self):
        initial = super().get_initial()
        # Z detailu suroviny (`?ingredient=`) nebo z filtru dodavatele.
        for field in ('ingredient', 'supplier'):
            value = self.request.GET.get(field, '')
            if value.isdigit():
                initial[field] = value
        return initial

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # `?synonym=1` z detailu suroviny: stejný formulář, jen s vysvětlením.
        context['is_synonym'] = self.request.GET.get('synonym') == '1'
        return context

    def _save(self, form):
        form.instance.created_by = self.request.user
        response = super()._save(form)
        messages.success(self.request, f'Alias „{self.object.raw_name}" byl přidán.')
        return response


class AliasUpdateView(_AliasFormMixin, UpdateView):
    def _save(self, form):
        # Jen upravená pole. Plné `save()` by zapsalo zpět i `times_used` a
        # `last_used_at` z doby načtení formuláře a smazalo by použití, které
        # mezitím zaznamenal import. Klíče počítá `save()` z názvu, proto jdou
        # s sebou.
        self.object = form.save(commit=False)
        self.object.save(update_fields=[*form.fields, 'raw_key', 'core_key'])
        messages.success(self.request, f'Alias „{self.object.raw_name}" byl upraven.')
        return HttpResponseRedirect(self.get_success_url())


class AliasDeleteView(LoginRequiredMixin, DeleteView):
    model = SupplierItemAlias
    template_name = 'inventory/alias_confirm_delete.html'

    def get_success_url(self):
        return reverse('inventory:alias_list')

    def form_valid(self, form):
        name = self.object.raw_name
        response = super().form_valid(form)
        messages.success(self.request, f'Alias „{name}" byl smazán.')
        return response
