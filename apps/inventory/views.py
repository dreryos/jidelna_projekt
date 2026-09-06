from django.urls import reverse_lazy, reverse
from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import ListView, CreateView, UpdateView, DeleteView, DetailView
from django.contrib import messages
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.utils import timezone
from django.http import HttpResponse, JsonResponse
from django.template.loader import render_to_string
from django.core.exceptions import ValidationError, ObjectDoesNotExist
from django.views.decorators.http import require_POST
from django.views.decorators.cache import cache_page
from django.core.cache import cache
from django.db.models import Count, Q
from django.db.models.functions import Collate
from django.conf import settings
from apps.core.views import CanteenAccessMixin, user_can_access_canteen
from decimal import Decimal, InvalidOperation
import logging
import json
from pathlib import Path

from .models import (
    StockItem, GoodsReceipt, GoodsReceiptItem, 
    InventoryVerification, InventoryVerificationItem,
    StockTransfer, StockTransferItem,
    Supplier, SupplierIngredientTemplate,
    StockWriteOff, StockWriteOffItem,
    GoodsReceiptScan
)
from .forms import (
    GoodsReceiptForm, GoodsReceiptItemFormSet,
    InventoryVerificationForm, InventoryVerificationItemFormSet,
    StockTransferForm, StockTransferItemFormSet,
    StockWriteOffForm, StockWriteOffItemFormSet
)
from apps.canteens.models import Warehouse, Canteen
from apps.core.models import Ingredient

logger = logging.getLogger(__name__)


class StockListView(CanteenAccessMixin, ListView):
    model = StockItem
    template_name = 'inventory/stock_list.html'
    context_object_name = 'stock_items'
    
    def get_queryset(self):
        queryset = super().get_queryset().select_related('ingredient', 'warehouse', 'warehouse__canteen')
        
        # Filtrování podle skladu/skladů
        warehouse_ids = self.request.GET.getlist('warehouse')
        
        # Pokud nejsou vybrány sklady a uživatel není superuser, defaultně vyber user's managed warehouses
        if not warehouse_ids and not self.request.user.is_superuser:
            try:
                user_canteens = self.request.user.profile.canteens.all()
                warehouse_ids = list(
                    Warehouse.objects.filter(canteen__in=user_canteens).values_list('id', flat=True)
                )
            except ObjectDoesNotExist:
                warehouse_ids = []
        
        if warehouse_ids:
            queryset = queryset.filter(warehouse_id__in=warehouse_ids)
        else:
            # Pokud není vybrán konkrétní sklad, vyfiltrujeme mezisklady
            if not self.request.GET.get('show_transit'):
                queryset = queryset.exclude(warehouse__is_transit_warehouse=True)
        
        # Řazení podle názvu suroviny
        queryset = queryset.order_by('ingredient__name')
        
        return queryset
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        
        # Filtruj sklady na managed canteens
        if user.is_superuser:
            warehouses = Warehouse.objects.select_related('canteen').all()
            default_warehouse_ids = []
        else:
            try:
                user_canteens = user.profile.canteens.all()
                warehouses = Warehouse.objects.filter(canteen__in=user_canteens).select_related('canteen')
                # Defaultně vyber managed warehouses
                default_warehouse_ids = list(
                    Warehouse.objects.filter(canteen__in=user_canteens).values_list('id', flat=True)
                )
            except ObjectDoesNotExist:
                warehouses = Warehouse.objects.none()
                default_warehouse_ids = []
        
        # Seskupení skladů podle lokace (první část názvu před " - ")
        from collections import OrderedDict
        grouped_warehouses = OrderedDict()
        for warehouse in warehouses.order_by('name'):
            # Získáme lokaci z názvu skladu (část před " - ")
            location = warehouse.name.split(' - ')[0] if ' - ' in warehouse.name else 'Ostatní'
            if location not in grouped_warehouses:
                grouped_warehouses[location] = []
            grouped_warehouses[location].append(warehouse)
        
        context['warehouses'] = warehouses
        context['grouped_warehouses'] = grouped_warehouses
        
        # Pokud nejsou vybrány sklady, použij defaultní
        selected = self.request.GET.getlist('warehouse')
        context['selected_warehouses'] = selected if selected else [str(wid) for wid in default_warehouse_ids]
        context['show_transit'] = self.request.GET.get('show_transit', False)
        
        # Přidáme statistiky
        stock_items = context['stock_items']
        context['stats'] = {
            'available_count': sum(1 for item in stock_items if item.quantity_available > 0),
            'blocked_count': sum(1 for item in stock_items if item.quantity_blocked > 0),
            'low_stock_count': sum(1 for item in stock_items if item.quantity_available <= 10),
        }
        
        # Načteme aktivní převody pro mezisklady
        transit_warehouse_ids = Warehouse.objects.filter(is_transit_warehouse=True).values_list('id', flat=True)
        if transit_warehouse_ids:
            active_transfers = StockTransfer.objects.filter(
                Q(status='IN_TRANSIT'),
                Q(warehouse_from__canteen__warehouses__id__in=transit_warehouse_ids) |
                Q(warehouse_to__canteen__warehouses__id__in=transit_warehouse_ids)
            ).select_related('warehouse_from', 'warehouse_to').prefetch_related('items__ingredient')
            
            # Vytvoříme slovník ingredient_id -> transfer pro rychlé vyhledání
            context['transit_transfers'] = {}
            for transfer in active_transfers:
                for item in transfer.items.all():
                    if item.ingredient_id not in context['transit_transfers']:
                        context['transit_transfers'][item.ingredient_id] = []
                    context['transit_transfers'][item.ingredient_id].append(transfer)
        else:
            context['transit_transfers'] = {}
        
        return context


class StockUpdateView(LoginRequiredMixin, UpdateView):
    model = StockItem
    fields = ['ingredient', 'warehouse', 'quantity', 'price']
    template_name = 'inventory/stock_form.html'
    success_url = reverse_lazy('inventory:stock_list')
    
    def form_valid(self, form):
        messages.success(self.request, f'Skladová položka "{form.instance.ingredient.name}" byla úspěšně upravena.')
        return super().form_valid(form)


class StockDeleteView(LoginRequiredMixin, DeleteView):
    model = StockItem
    template_name = 'inventory/stock_confirm_delete.html'
    success_url = reverse_lazy('inventory:stock_list')
    
    def delete(self, request, *args, **kwargs):
        self.object = self.get_object()
        ingredient_name = self.object.ingredient.name
        messages.success(request, f'Skladová položka "{ingredient_name}" byla smazána.')
        return super().delete(request, *args, **kwargs)


# CRUD pro sklady (Warehouse)

class WarehouseListView(CanteenAccessMixin, ListView):
    model = Warehouse
    template_name = 'inventory/warehouse_list.html'
    context_object_name = 'warehouses'
    
    def get_queryset(self):
        queryset = super().get_queryset()
        from django.db.models import Prefetch
        
        # Prefetch pouze COMPLETED inventur seřazených sestupně
        completed_verifications = InventoryVerification.objects.filter(
            status=InventoryVerification.Status.COMPLETED
        ).order_by('-completed_at')
        
        return Warehouse.objects.select_related('canteen').prefetch_related(
            Prefetch('inventory_verifications', queryset=completed_verifications, to_attr='completed_inventories')
        ).order_by('canteen__name', 'name')


class WarehouseCreateView(LoginRequiredMixin, CreateView):
    model = Warehouse
    fields = ['name', 'canteen']
    template_name = 'inventory/warehouse_form.html'
    success_url = reverse_lazy('inventory:warehouse_list')
    
    def form_valid(self, form):
        messages.success(self.request, f'Sklad "{form.instance.name}" byl úspěšně vytvořen.')
        return super().form_valid(form)


class WarehouseUpdateView(LoginRequiredMixin, UpdateView):
    model = Warehouse
    fields = ['name', 'canteen']
    template_name = 'inventory/warehouse_form.html'
    success_url = reverse_lazy('inventory:warehouse_list')
    
    def form_valid(self, form):
        messages.success(self.request, f'Sklad "{form.instance.name}" byl úspěšně upraven.')
        return super().form_valid(form)


class WarehouseDeleteView(LoginRequiredMixin, DeleteView):
    model = Warehouse
    template_name = 'inventory/warehouse_confirm_delete.html'
    success_url = reverse_lazy('inventory:warehouse_list')
    
    def delete(self, request, *args, **kwargs):
        self.object = self.get_object()
        warehouse_name = self.object.name
        messages.success(request, f'Sklad "{warehouse_name}" byl smazán.')
        return super().delete(request, *args, **kwargs)


# CRUD pro jídelny (Canteen)

class CanteenListView(LoginRequiredMixin, ListView):
    model = Canteen
    template_name = 'inventory/canteen_list.html'
    context_object_name = 'canteens'
    
    def get_queryset(self):
        return Canteen.objects.prefetch_related('warehouses').order_by('name')


class CanteenCreateView(LoginRequiredMixin, CreateView):
    model = Canteen
    fields = ['name', 'address']
    template_name = 'inventory/canteen_form.html'
    success_url = reverse_lazy('inventory:canteen_list')
    
    def form_valid(self, form):
        messages.success(self.request, f'Jídelna "{form.instance.name}" byla úspěšně vytvořena.')
        return super().form_valid(form)


class CanteenUpdateView(LoginRequiredMixin, UpdateView):
    model = Canteen
    fields = ['name', 'address']
    template_name = 'inventory/canteen_form.html'
    success_url = reverse_lazy('inventory:canteen_list')
    
    def form_valid(self, form):
        messages.success(self.request, f'Jídelna "{form.instance.name}" byla úspěšně upravena.')
        return super().form_valid(form)


class CanteenDeleteView(LoginRequiredMixin, DeleteView):
    model = Canteen
    template_name = 'inventory/canteen_confirm_delete.html'
    success_url = reverse_lazy('inventory:canteen_list')
    
    def delete(self, request, *args, **kwargs):
        self.object = self.get_object()
        canteen_name = self.object.name
        messages.success(request, f'Jídelna "{canteen_name}" byla smazána.')
        return super().delete(request, *args, **kwargs)


# Unified Management View - Správa jídelen a skladů

class CanteenWarehouseManagementView(LoginRequiredMixin, ListView):
    model = Canteen
    template_name = 'inventory/management.html'
    context_object_name = 'canteens'
    
    def get_queryset(self):
        return Canteen.objects.prefetch_related(
            'warehouses__stock_items__ingredient',
            'warehouses__inventory_verifications'
        ).order_by('name')
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        # KPI statistiky
        total_canteens = Canteen.objects.count()
        total_warehouses = Warehouse.objects.count()
        locked_warehouses = Warehouse.objects.filter(is_locked=True).count()
        total_stock_items = StockItem.objects.count()
        
        context['kpi'] = {
            'total_canteens': total_canteens,
            'total_warehouses': total_warehouses,
            'locked_warehouses': locked_warehouses,
            'total_stock_items': total_stock_items,
        }
        
        return context


# AJAX Endpoints pro jídelny

@login_required
@require_POST
def canteen_ajax_create(request):
    """AJAX endpoint pro vytvoření nové jídelny"""
    try:
        data = json.loads(request.body)
        name = data.get('name', '').strip()
        address = data.get('address', '').strip()
        
        # Validace
        if not name:
            return JsonResponse({'success': False, 'error': 'Název jídelny je povinný.'}, status=400)
        
        if Canteen.objects.filter(name=name).exists():
            return JsonResponse({'success': False, 'error': 'Jídelna s tímto názvem už existuje.'}, status=400)
        
        # Vytvoření jídelny
        canteen = Canteen.objects.create(name=name, address=address)
        
        return JsonResponse({
            'success': True,
            'message': f'Jídelna "{canteen.name}" byla úspěšně vytvořena.',
            'canteen': {
                'id': canteen.id,
                'name': canteen.name,
                'address': canteen.address,
                'warehouse_count': 0,
                'stock_item_count': 0,
            }
        })
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Neplatná data.'}, status=400)
    except Exception as e:
        logger.error(f'Error creating canteen via AJAX: {e}')
        return JsonResponse({'success': False, 'error': 'Chyba při vytváření jídelny.'}, status=500)


@login_required
@require_POST
def canteen_ajax_update(request, pk):
    """AJAX endpoint pro úpravu jídelny"""
    try:
        canteen = get_object_or_404(Canteen, pk=pk)
        data = json.loads(request.body)
        name = data.get('name', '').strip()
        address = data.get('address', '').strip()
        
        # Validace
        if not name:
            return JsonResponse({'success': False, 'error': 'Název jídelny je povinný.'}, status=400)
        
        if Canteen.objects.filter(name=name).exclude(pk=pk).exists():
            return JsonResponse({'success': False, 'error': 'Jídelna s tímto názvem už existuje.'}, status=400)
        
        # Úprava jídelny
        canteen.name = name
        canteen.address = address
        canteen.save()
        
        return JsonResponse({
            'success': True,
            'message': f'Jídelna "{canteen.name}" byla úspěšně upravena.',
            'canteen': {
                'id': canteen.id,
                'name': canteen.name,
                'address': canteen.address,
            }
        })
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Neplatná data.'}, status=400)
    except Exception as e:
        logger.error(f'Error updating canteen via AJAX: {e}')
        return JsonResponse({'success': False, 'error': 'Chyba při úpravě jídelny.'}, status=500)


@login_required
@require_POST
def canteen_ajax_delete(request, pk):
    """AJAX endpoint pro smazání jídelny"""
    try:
        canteen = get_object_or_404(Canteen, pk=pk)
        canteen_name = canteen.name
        warehouse_count = canteen.warehouses.count()
        
        # Smazání jídelny (automaticky smaže sklady díky CASCADE)
        canteen.delete()
        
        return JsonResponse({
            'success': True,
            'message': f'Jídelna "{canteen_name}" a {warehouse_count} skladů bylo smazáno.',
        })
    except Exception as e:
        logger.error(f'Error deleting canteen via AJAX: {e}')
        return JsonResponse({'success': False, 'error': 'Chyba při mazání jídelny.'}, status=500)


# AJAX Endpoints pro sklady

@login_required
@require_POST
def warehouse_ajax_create(request):
    """AJAX endpoint pro vytvoření nového skladu"""
    try:
        data = json.loads(request.body)
        name = data.get('name', '').strip()
        canteen_id = data.get('canteen_id')
        
        # Validace
        if not name:
            return JsonResponse({'success': False, 'error': 'Název skladu je povinný.'}, status=400)
        
        if not canteen_id:
            return JsonResponse({'success': False, 'error': 'Jídelna musí být vybrána.'}, status=400)
        
        canteen = get_object_or_404(Canteen, pk=canteen_id)
        
        # Kontrola unique_together (name, canteen)
        if Warehouse.objects.filter(name=name, canteen=canteen).exists():
            return JsonResponse({'success': False, 'error': 'Sklad s tímto názvem už v této jídelně existuje.'}, status=400)
        
        # Vytvoření skladu
        warehouse = Warehouse.objects.create(name=name, canteen=canteen)
        
        return JsonResponse({
            'success': True,
            'message': f'Sklad "{warehouse.name}" byl úspěšně vytvořen.',
            'warehouse': {
                'id': warehouse.id,
                'name': warehouse.name,
                'canteen_id': warehouse.canteen_id,
                'is_locked': warehouse.is_locked,
                'stock_item_count': 0,
            }
        })
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Neplatná data.'}, status=400)
    except Exception as e:
        logger.error(f'Error creating warehouse via AJAX: {e}')
        return JsonResponse({'success': False, 'error': 'Chyba při vytváření skladu.'}, status=500)


@login_required
@require_POST
def warehouse_ajax_update(request, pk):
    """AJAX endpoint pro úpravu skladu"""
    try:
        warehouse = get_object_or_404(Warehouse, pk=pk)
        data = json.loads(request.body)
        name = data.get('name', '').strip()
        
        # Validace
        if not name:
            return JsonResponse({'success': False, 'error': 'Název skladu je povinný.'}, status=400)
        
        # Kontrola unique_together (name, canteen)
        if Warehouse.objects.filter(name=name, canteen=warehouse.canteen).exclude(pk=pk).exists():
            return JsonResponse({'success': False, 'error': 'Sklad s tímto názvem už v této jídelně existuje.'}, status=400)
        
        # Úprava skladu
        warehouse.name = name
        warehouse.save()
        
        return JsonResponse({
            'success': True,
            'message': f'Sklad "{warehouse.name}" byl úspěšně upraven.',
            'warehouse': {
                'id': warehouse.id,
                'name': warehouse.name,
            }
        })
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Neplatná data.'}, status=400)
    except Exception as e:
        logger.error(f'Error updating warehouse via AJAX: {e}')
        return JsonResponse({'success': False, 'error': 'Chyba při úpravě skladu.'}, status=500)


@login_required
@require_POST
def warehouse_ajax_delete(request, pk):
    """AJAX endpoint pro smazání skladu"""
    try:
        warehouse = get_object_or_404(Warehouse, pk=pk)
        warehouse_name = warehouse.name
        stock_item_count = warehouse.stock_items.count()
        
        # Kontrola, zda není zamčený
        if warehouse.is_locked:
            return JsonResponse({
                'success': False,
                'error': f'Sklad "{warehouse_name}" je zamčený kvůli inventuře a nelze ho smazat.'
            }, status=400)
        
        # Smazání skladu
        warehouse.delete()
        
        return JsonResponse({
            'success': True,
            'message': f'Sklad "{warehouse_name}" a {stock_item_count} položek bylo smazáno.',
        })
    except Exception as e:
        logger.error(f'Error deleting warehouse via AJAX: {e}')
        return JsonResponse({'success': False, 'error': 'Chyba při mazání skladu.'}, status=500)


# CRUD pro příjem zboží (GoodsReceipt)

class GoodsReceiptListView(CanteenAccessMixin, ListView):
    model = GoodsReceipt
    template_name = 'inventory/goods_receipt_list.html'
    context_object_name = 'goods_receipts'
    paginate_by = 20
    
    def get_queryset(self):
        queryset = super().get_queryset().select_related('warehouse', 'warehouse__canteen', 'created_by')
        
        # Filtrování podle skladu
        warehouse_id = self.request.GET.get('warehouse')
        if warehouse_id:
            queryset = queryset.filter(warehouse_id=warehouse_id)
        
        # Filtrování podle stavu
        status = self.request.GET.get('status')
        if status:
            queryset = queryset.filter(status=status)
        
        return queryset.order_by('-created_at')
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        
        # Filtruj sklady na managed canteens
        if user.is_superuser:
            context['warehouses'] = Warehouse.objects.select_related('canteen').all()
        else:
            try:
                user_canteens = user.profile.canteens.all()
                context['warehouses'] = Warehouse.objects.filter(canteen__in=user_canteens).select_related('canteen')
            except ObjectDoesNotExist:
                context['warehouses'] = Warehouse.objects.none()
        
        context['selected_warehouse'] = self.request.GET.get('warehouse', '')
        context['selected_status'] = self.request.GET.get('status', '')
        context['statuses'] = GoodsReceipt.Status.choices
        return context


class GoodsReceiptDetailView(LoginRequiredMixin, DetailView):
    model = GoodsReceipt
    template_name = 'inventory/goods_receipt_detail.html'
    context_object_name = 'goods_receipt'
    
    def get_queryset(self):
        return GoodsReceipt.objects.select_related('warehouse', 'warehouse__canteen', 'created_by').prefetch_related('items__ingredient')


@login_required
def goods_receipt_create(request):
    """Vytvoření nového příjmu zboží pomocí Django formsets"""
    if request.method == 'POST':
        form = GoodsReceiptForm(request.POST, user=request.user)
        formset = GoodsReceiptItemFormSet(request.POST, form_kwargs={'user': request.user})
        
        # Očistit zcela prázdné řádky (přidané přes JavaScript ale nevyplněné)
        # Django by to měl udělat automaticky, ale formset má min_num=1
        formset_data = []
        total_forms = int(request.POST.get('items-TOTAL_FORMS', 0))
        for i in range(total_forms):
            prefix = f'items-{i}'
            # Zkontrolovat zda je alespoň jedno pole vyplněné
            ingredient = request.POST.get(f'{prefix}-ingredient', '').strip()
            warehouse = request.POST.get(f'{prefix}-warehouse', '').strip()
            quantity = request.POST.get(f'{prefix}-quantity', '').strip()
            price_without_vat = request.POST.get(f'{prefix}-price_without_vat', '').strip()
            price_with_vat = request.POST.get(f'{prefix}-price', '').strip()
            vat_rate = request.POST.get(f'{prefix}-vat_rate', '').strip()
            delete_flag = request.POST.get(f'{prefix}-DELETE', '').strip()
            
            # Uchovej řádek pokud:
            # - není označen ke smazání (DELETE=on)
            # - a má nějaká vyplněná data
            if delete_flag != 'on' and (ingredient or warehouse or quantity or price_without_vat or price_with_vat or vat_rate):
                formset_data.append(i)
        
        # Pokud jsou všechny řádky prázdné, snízíme TOTAL_FORMS
        if not formset_data:
            request.POST._mutable = True if hasattr(request.POST, '_mutable') else None
            request.POST['items-TOTAL_FORMS'] = '1'
            request.POST._mutable = False if hasattr(request.POST, '_mutable') else None
            # Znovu vytvořit formset s aktualizovanými daty
            formset = GoodsReceiptItemFormSet(request.POST)
        
        if form.is_valid() and formset.is_valid():
            try:
                with transaction.atomic():
                    # Uložit hlavní příjem
                    goods_receipt = form.save(commit=False)
                    # Nastavit warehouse z default_warehouse
                    default_warehouse = form.cleaned_data.get('default_warehouse')
                    if default_warehouse:
                        # Kontrola oprávnění - přístup k jídelně skladu
                        if not user_can_access_canteen(request.user, default_warehouse.canteen):
                            messages.error(request, 'Nemáte oprávnění zapisovat do tohoto skladu.')
                            return redirect('inventory:goods_receipt_create')
                        goods_receipt.warehouse = default_warehouse
                    goods_receipt.created_by = request.user
                    goods_receipt.save()
                    
                    # Uložit pouze vyplněné položky
                    formset.instance = goods_receipt
                    items = formset.save(commit=False)
                    
                    for item in items:
                        # calculate_vat_fields() se volá automaticky v save()
                        item.save()
                    
                    # Zpracování smazaných položek
                    for obj in formset.deleted_objects:
                        obj.delete()
                    
                    messages.success(
                        request, 
                        f'Příjem zboží "{goods_receipt.receipt_number}" byl úspěšně vytvořen s {len(items)} položkami.'
                    )
                    return redirect('inventory:goods_receipt_detail', pk=goods_receipt.pk)
            
            except Exception as e:
                messages.error(request, f'Chyba při vytváření příjmu: {str(e)}')
        else:
            # Zobrazení chyb formuláře
            if not form.is_valid():
                for field, errors in form.errors.items():
                    for error in errors:
                        messages.error(request, f'{field}: {error}')
            if not formset.is_valid():
                for i, form_errors in enumerate(formset.errors):
                    if form_errors:
                        messages.error(request, f'Položka {i+1}: {form_errors}')
                if formset.non_form_errors():
                    for error in formset.non_form_errors():
                        messages.error(request, f'Formset chyba: {error}')
    else:
        # GET - prázdný formulář
        form = GoodsReceiptForm(user=request.user)
        formset = GoodsReceiptItemFormSet(form_kwargs={'user': request.user})
    
    # Načtení aktivních dodavatelů pro rychlé šablony
    active_suppliers = Supplier.objects.filter(is_active=True).order_by('name')
    
    context = {
        'form': form,
        'formset': formset,
        'active_suppliers': active_suppliers,
    }
    
    return render(request, 'inventory/goods_receipt_form.html', context)


@login_required
def goods_receipt_edit(request, pk):
    """Editace příjmu zboží ve stavu Koncept"""
    goods_receipt = get_object_or_404(GoodsReceipt, pk=pk)

    # Kontrola oprávnění - přístup k jídelně skladu
    if not user_can_access_canteen(request.user, goods_receipt.warehouse.canteen):
        messages.error(request, 'Nemáte oprávnění k této akci.')
        return redirect('inventory:goods_receipt_list')

    if goods_receipt.status != GoodsReceipt.Status.DRAFT:
        messages.warning(request, 'Nelze upravit příjem, který již byl potvrzen.')
        return redirect('inventory:goods_receipt_detail', pk=pk)

    if request.method == 'POST':
        form = GoodsReceiptForm(request.POST, instance=goods_receipt, user=request.user)
        formset = GoodsReceiptItemFormSet(request.POST, instance=goods_receipt, form_kwargs={'user': request.user})

        # Očistit zcela prázdné řádky
        total_forms = int(request.POST.get('items-TOTAL_FORMS', 0))
        formset_data = []
        for i in range(total_forms):
            prefix = f'items-{i}'
            ingredient = request.POST.get(f'{prefix}-ingredient', '').strip()
            warehouse = request.POST.get(f'{prefix}-warehouse', '').strip()
            quantity = request.POST.get(f'{prefix}-quantity', '').strip()
            price_without_vat = request.POST.get(f'{prefix}-price_without_vat', '').strip()
            price_with_vat = request.POST.get(f'{prefix}-price', '').strip()
            vat_rate = request.POST.get(f'{prefix}-vat_rate', '').strip()
            delete_flag = request.POST.get(f'{prefix}-DELETE', '').strip()

            if delete_flag != 'on' and (ingredient or warehouse or quantity or price_without_vat or price_with_vat or vat_rate):
                formset_data.append(i)

        if not formset_data:
            request.POST._mutable = True if hasattr(request.POST, '_mutable') else None
            request.POST['items-TOTAL_FORMS'] = '1'
            request.POST._mutable = False if hasattr(request.POST, '_mutable') else None
            formset = GoodsReceiptItemFormSet(request.POST, instance=goods_receipt, form_kwargs={'user': request.user})

        if form.is_valid() and formset.is_valid():
            try:
                with transaction.atomic():
                    updated_receipt = form.save(commit=False)
                    default_warehouse = form.cleaned_data.get('default_warehouse')
                    if default_warehouse:
                        # Kontrola oprávnění - přístup k jídelně skladu
                        if not user_can_access_canteen(request.user, default_warehouse.canteen):
                            messages.error(request, 'Nemáte oprávnění zapisovat do tohoto skladu.')
                            return redirect('inventory:goods_receipt_edit', pk=pk)
                        updated_receipt.warehouse = default_warehouse
                    updated_receipt.save()

                    formset.instance = updated_receipt
                    items = formset.save(commit=False)

                    for item in items:
                        item.save()

                    for obj in formset.deleted_objects:
                        obj.delete()

                    messages.success(
                        request,
                        f'Příjem zboží "{updated_receipt.receipt_number}" byl úspěšně upraven.'
                    )
                    return redirect('inventory:goods_receipt_detail', pk=updated_receipt.pk)

            except Exception as e:
                messages.error(request, f'Chyba při ukládání příjmu: {str(e)}')
        else:
            if not form.is_valid():
                for field, errors in form.errors.items():
                    for error in errors:
                        messages.error(request, f'{field}: {error}')
            if not formset.is_valid():
                for i, form_errors in enumerate(formset.errors):
                    if form_errors:
                        messages.error(request, f'Položka {i+1}: {form_errors}')
                if formset.non_form_errors():
                    for error in formset.non_form_errors():
                        messages.error(request, f'Formset chyba: {error}')
    else:
        # GET - předvyplnit formulář existujícími daty
        form = GoodsReceiptForm(instance=goods_receipt, initial={'default_warehouse': goods_receipt.warehouse}, user=request.user)
        formset = GoodsReceiptItemFormSet(instance=goods_receipt, form_kwargs={'user': request.user})

    active_suppliers = Supplier.objects.filter(is_active=True).order_by('name')

    context = {
        'form': form,
        'formset': formset,
        'active_suppliers': active_suppliers,
        'editing': True,
        'goods_receipt': goods_receipt,
    }

    return render(request, 'inventory/goods_receipt_form.html', context)


@login_required
def goods_receipt_confirm(request, pk):
    """Potvrzení příjmu zboží - aktualizuje sklady a ceny"""
    goods_receipt = get_object_or_404(GoodsReceipt, pk=pk)
    
    # Kontrola oprávnění - přístup k jídelně skladu
    if not user_can_access_canteen(request.user, goods_receipt.warehouse.canteen):
        messages.error(request, 'Nemáte oprávnění k této akci.')
        return redirect('inventory:goods_receipt_list')
    
    if goods_receipt.status != GoodsReceipt.Status.DRAFT:
        messages.warning(request, 'Tento příjem již byl potvrzen.')
        return redirect('inventory:goods_receipt_detail', pk=pk)
    
    # Nesrovnané měrné jednotky posíláme rovnou tam, kde se dají doplnit,
    # ať uživatel nekouká na chybu bez cesty ven.
    if goods_receipt.unit_conflicts:
        messages.warning(
            request,
            'Než příjemku potvrdíte, doplňte přepočet měrných jednotek.'
        )
        return redirect('inventory:goods_receipt_resolve_units', pk=pk)
    
    if request.method == 'POST':
        try:
            goods_receipt.confirm()
            # Fotka dokladu už není k ničemu – rozpoznaná data jsou v příjemce
            # a anotace zůstává u skenu kvůli dohledatelnosti.
            scan = getattr(goods_receipt, 'scan', None)
            if scan is not None:
                scan.delete_file()
            messages.success(
                request, 
                f'Příjem zboží "{goods_receipt.receipt_number}" byl potvrzen. '
                f'Sklady byly aktualizovány.'
            )
        except Exception as e:
            messages.error(request, f'Chyba při potvrzování příjmu: {str(e)}')
        
        return redirect('inventory:goods_receipt_detail', pk=pk)
    
    # GET - zobrazíme potvrzovací stránku
    context = {
        'goods_receipt': goods_receipt,
    }
    return render(request, 'inventory/goods_receipt_confirm.html', context)


@login_required
def goods_receipt_delete(request, pk):
    """Smazání příjmu zboží - pouze pokud není potvrzen"""
    goods_receipt = get_object_or_404(GoodsReceipt, pk=pk)
    
    # Kontrola oprávnění - přístup k jídelně skladu
    if not user_can_access_canteen(request.user, goods_receipt.warehouse.canteen):
        messages.error(request, 'Nemáte oprávnění k této akci.')
        return redirect('inventory:goods_receipt_list')
    
    if goods_receipt.status == GoodsReceipt.Status.CONFIRMED:
        messages.error(request, 'Nelze smazat potvrzený příjem zboží.')
        return redirect('inventory:goods_receipt_detail', pk=pk)
    
    if request.method == 'POST':
        receipt_number = goods_receipt.receipt_number
        goods_receipt.delete()
        messages.success(request, f'Příjem zboží "{receipt_number}" byl smazán.')
        return redirect('inventory:goods_receipt_list')
    
    context = {
        'goods_receipt': goods_receipt,
    }
    return render(request, 'inventory/goods_receipt_confirm_delete.html', context)


# Bidfood XML Import

from .bidfood_parser import parse_bidfood_xml
from .supplier_csv_parser import parse_supplier_csv
from .matching import IngredientResolver, find_supplier
from .units import conversion_factor, convert_line, units_are_compatible


@login_required
def bidfood_xml_import_step1(request):
    """Krok 1: Upload XML souboru a výběr výchozího skladu"""
    if request.method == 'POST':
        xml_file = request.FILES.get('xml_file')
        default_warehouse_id = request.POST.get('warehouse')
        
        if not xml_file or not default_warehouse_id:
            messages.error(request, 'Musíte vybrat XML soubor a výchozí sklad.')
            return redirect('inventory:bidfood_import_step1')
        
        try:
            # Parsování XML
            receipt_data = parse_bidfood_xml(xml_file)
            
            # Uložení do session (konverze na JSON-serializovatelná data)
            request.session['bidfood_receipt_data'] = {
                'receipt_number': receipt_data['receipt_number'],
                'receipt_date': receipt_data['receipt_date'].isoformat(),
                'supplier': receipt_data['supplier'],
                'items': [
                    {
                        'item_id': item['item_id'],
                        'item_name': item['item_name'],
                        'quantity': str(item['quantity']),
                        'unit': item['unit'],
                        'unit_mapped': item['unit_mapped'],
                        'price_per_unit_net': str(item['price_per_unit_net']),
                        'price_per_unit_gross': str(item['price_per_unit_gross']),
                        'vat_rate': str(item['vat_rate']),
                        'vat_amount': str(item['vat_amount']),
                        'total_price': str(item['total_price']),
                    }
                    for item in receipt_data['items']
                ]
            }
            request.session['bidfood_default_warehouse'] = default_warehouse_id
            
            messages.success(request, f'XML načten: {len(receipt_data["items"])} položek')
            return redirect('inventory:bidfood_import_step2')
            
        except Exception as e:
            messages.error(request, f'Chyba při načítání XML: {e}')
    
    warehouses = Warehouse.objects.select_related('canteen').all()
    if not request.user.is_superuser:
        try:
            user_canteens = request.user.profile.canteens.all()
            warehouses = warehouses.filter(canteen__in=user_canteens)
        except ObjectDoesNotExist:
            warehouses = Warehouse.objects.none()
    return render(request, 'inventory/bidfood_import_step1.html', {
        'warehouses': warehouses
    })


def _apply_ingredient_matching(receipt_data, all_ingredients):
    """
    Doplní k položkám dokladu navrženou surovinu.

    Hledání dělá `IngredientResolver` – nejdřív mapování, která už někdo
    potvrdil, teprve pak odhad podle podobnosti názvu. Do položek zapisuje
    i klíče, které používaly starší šablony (`suggested_ingredient_*`,
    `match_ratio`), aby se nemusely přepisovat naráz.

    Returns:
        IngredientResolver – tentýž, který se použije při dokončení importu,
        aby se rozhodnutí uživatele uložila ke správnému dodavateli.
    """
    supplier = find_supplier(
        name=receipt_data.get('supplier'),
        ico=receipt_data.get('supplier_ico'),
    )
    resolver = IngredientResolver(supplier=supplier, ingredients=all_ingredients)

    for item in receipt_data['items']:
        match = resolver.resolve(item['item_name'], unit=item.get('unit_mapped'))
        item.update(match.as_dict())
        # Klíče pro stávající šablony.
        item['suggested_ingredient_id'] = item['ingredient_id']
        item['suggested_ingredient_name'] = item['ingredient_name']
        item['suggested_ingredient_unit'] = item['ingredient_unit']

    receipt_data['supplier_id'] = supplier.id if supplier else None
    return resolver


def _convert_to_stock_unit(item, ingredient, quantity, price_net, price_gross):
    """
    Přepočte řádek dokladu na skladovou jednotku suroviny.

    `GoodsReceiptItem.quantity` se při potvrzení přičítá rovnou do skladu,
    takže musí být ve skladové jednotce. Dodavatel ale fakturuje v tom,
    co se mu hodí.

    Jednoznačný převod (kg ↔ g, l ↔ ml) se udělá sám. U nejednoznačného
    (ks → kg) se množství nechá tak, jak přišlo, a poměr zůstane 1 –
    položka se tím označí jako nedořešená a `GoodsReceipt.confirm()` ji
    na sklad nepustí, dokud poměr někdo nedoplní.

    Returns:
        dict s hodnotami pro `GoodsReceiptItem`.
    """
    source_unit = item.get('unit_mapped') or item.get('unit') or ''
    factor = conversion_factor(source_unit, ingredient.base_unit) or Decimal('1')

    converted_quantity, converted_net = convert_line(quantity, price_net, factor)
    _unused, converted_gross = convert_line(Decimal('1'), price_gross, factor)

    return {
        'quantity': converted_quantity,
        'price_without_vat': converted_net,
        'price': converted_gross,
        'vat_amount': converted_gross - converted_net,
        'source_name': item.get('item_name', '')[:255],
        'source_unit': source_unit,
        'source_quantity': quantity,
        'unit_factor': factor,
    }


def _remember_ingredient_mapping(receipt_data, mappings, user):
    """
    Uloží, jak uživatel namapoval položky dokladu, aby to příště sedlo samo.

    Volá se po vytvoření příjemky. Když se doklad nepodařilo přiřadit ke
    konkrétnímu dodavateli, resolver si nic neuloží – globální alias platí
    pro všechny dodavatele a nemá vznikat jen proto, že jsme nevěděli,
    od koho doklad je.

    Args:
        receipt_data: data dokladu ze session
        mappings: seznam dvojic (položka dokladu, surovina)
        user: kdo mapování potvrdil
    """
    supplier = find_supplier(
        name=receipt_data.get('supplier'),
        ico=receipt_data.get('supplier_ico'),
    )
    if supplier is None:
        return 0

    resolver = IngredientResolver(supplier=supplier, ingredients=[])
    remembered = 0
    for item, ingredient in mappings:
        alias = resolver.remember(
            item['item_name'],
            ingredient=ingredient,
            unit=item.get('unit', ''),
            user=user,
        )
        if alias is not None:
            remembered += 1
    return remembered


@login_required
def bidfood_xml_import_step2(request):
    """Krok 2: Preview, mapování surovin, editace jednotek a skladů"""
    receipt_data = request.session.get('bidfood_receipt_data')
    if not receipt_data:
        messages.error(request, 'Session vypršela. Začněte znovu.')
        return redirect('inventory:bidfood_import_step1')
    
    default_warehouse_id = int(request.session.get('bidfood_default_warehouse'))
    warehouses = Warehouse.objects.all()
    if not request.user.is_superuser:
        try:
            user_canteens = request.user.profile.canteens.all()
            warehouses = warehouses.filter(canteen__in=user_canteens)
        except ObjectDoesNotExist:
            warehouses = Warehouse.objects.none()
    all_ingredients = list(Ingredient.objects.all())

    _apply_ingredient_matching(receipt_data, all_ingredients)

    context = {
        'receipt_data': receipt_data,
        'warehouses': warehouses,
        'default_warehouse_id': default_warehouse_id,
        'all_ingredients': all_ingredients,
    }
    
    return render(request, 'inventory/bidfood_import_step2.html', context)


@login_required
@transaction.atomic
def bidfood_xml_import_step3(request):
    """Krok 3: Vytvoření GoodsReceipt s položkami"""
    if request.method != 'POST':
        return redirect('inventory:bidfood_import_step1')
    
    receipt_data = request.session.get('bidfood_receipt_data')
    if not receipt_data:
        messages.error(request, 'Session vypršela. Začněte znovu.')
        return redirect('inventory:bidfood_import_step1')
    
    default_warehouse_id = request.session.get('bidfood_default_warehouse')
    default_warehouse = Warehouse.objects.get(id=default_warehouse_id)
    
    # Kontrola oprávnění - přístup k jídelně skladu
    if not user_can_access_canteen(request.user, default_warehouse.canteen):
        messages.error(request, 'Nemáte oprávnění zapisovat do tohoto skladu.')
        return redirect('inventory:bidfood_import_step1')
    
    # Vytvoření GoodsReceipt
    goods_receipt = GoodsReceipt.objects.create(
        warehouse=default_warehouse,
        receipt_number=receipt_data['receipt_number'],
        receipt_date=receipt_data['receipt_date'],
        supplier=receipt_data['supplier'],
        status=GoodsReceipt.Status.DRAFT,
        created_by=request.user,
        notes=f"Importováno z Bidfood XML"
    )
    
    # Zpracování položek
    created_ingredients_count = 0
    mappings = []
    
    for idx, item in enumerate(receipt_data['items']):
        # Načtení dat z formuláře
        create_new = request.POST.get(f'create_new_{idx}') == 'on'
        ingredient_id = request.POST.get(f'ingredient_{idx}')
        quantity_str = request.POST.get(f'quantity_{idx}', item['quantity'])
        unit = request.POST.get(f'unit_{idx}', item['unit_mapped'])
        warehouse_id = request.POST.get(f'warehouse_{idx}')
        
        # Převod množství (nahrazení čárky tečkou)
        quantity = Decimal(quantity_str.replace(',', '.'))
        
        # Validace skladu
        if not warehouse_id:
            messages.warning(request, f'Položka "{item["item_name"]}" přeskočena - nebyl vybrán sklad.')
            continue
        
        try:
            warehouse = Warehouse.objects.get(id=warehouse_id)
        except Warehouse.DoesNotExist:
            messages.warning(request, f'Sklad s ID {warehouse_id} neexistuje.')
            continue
        
        # Získání nebo vytvoření suroviny
        if create_new:
            # Vytvoření nové suroviny (nebo použití existující, pokud už existuje)
            ingredient, created = Ingredient.objects.get_or_create(
                name=item['item_name'],
                defaults={
                    'unit': unit,
                    'base_unit': unit,
                    'recipe_unit': 'g' if unit == 'kg' else ('ml' if unit == 'l' else 'ks'),
                    'conversion_factor': Decimal('1000') if unit in ['kg', 'l'] else Decimal('1')
                }
            )
            if created:
                created_ingredients_count += 1
        else:
            # Použití existující suroviny
            if not ingredient_id:
                messages.warning(request, f'Položka "{item["item_name"]}" přeskočena - nebyla vybrána surovina.')
                continue
            
            try:
                ingredient = Ingredient.objects.get(id=ingredient_id)
            except Ingredient.DoesNotExist:
                messages.warning(request, f'Surovina s ID {ingredient_id} neexistuje.')
                continue
        
        # Validace DPH sazby proti povoleným hodnotám
        vat_rate = Decimal(item['vat_rate'])
        from .forms import VAT_RATE_CHOICES
        allowed_vat_rates = [choice[0] for choice in VAT_RATE_CHOICES]
        
        if vat_rate not in allowed_vat_rates:
            messages.warning(
                request,
                f'Položka "{item["item_name"]}" má neplatnou DPH sazbu {vat_rate}%. '
                f'Povolené sazby: {", ".join(str(r) for r in allowed_vat_rates)}%'
            )
            continue
        
        # Přepočet na skladovou jednotku. Co se přepočítat nedá, projde
        # s poměrem 1 a příjemka se bez doplnění poměru nepotvrdí.
        converted = _convert_to_stock_unit(
            item, ingredient, quantity,
            Decimal(item['price_per_unit_net']),
            Decimal(item['price_per_unit_gross']),
        )
        
        # Vytvoření položky příjmu s DPH
        GoodsReceiptItem.objects.create(
            goods_receipt=goods_receipt,
            ingredient=ingredient,
            warehouse=warehouse,
            vat_rate=vat_rate,
            notes=f"Kód: {item['item_id']}",
            **converted,
        )
        mappings.append((item, ingredient))
    
    # Zapamatování mapování pro příští doklad od téhož dodavatele
    _remember_ingredient_mapping(receipt_data, mappings, request.user)
    
    # Vyčištění session
    del request.session['bidfood_receipt_data']
    del request.session['bidfood_default_warehouse']
    
    messages.success(
        request,
        f'Příjem {goods_receipt.receipt_number} byl vytvořen s {goods_receipt.items.count()} položkami. '
        f'Vytvořeno nových surovin: {created_ingredients_count}.'
    )
    
    return redirect('inventory:goods_receipt_detail', pk=goods_receipt.pk)


# CRUD a akce pro inventuru (InventoryVerification)


class InventoryVerificationListView(CanteenAccessMixin, ListView):
    """Seznam všech inventur."""
    model = InventoryVerification
    template_name = 'inventory/inventory_verification_list.html'
    context_object_name = 'verifications'
    
    def get_queryset(self):
        queryset = super().get_queryset().select_related(
            'warehouse', 'warehouse__canteen', 'started_by', 'completed_by', 'created_by'
        )
        
        # Filtrování podle skladu
        warehouse_id = self.request.GET.get('warehouse')
        if warehouse_id:
            queryset = queryset.filter(warehouse_id=warehouse_id)
        
        # Filtrování podle statusu
        status = self.request.GET.get('status')
        if status:
            queryset = queryset.filter(status=status)
        
        return queryset.order_by('-started_at', '-created_at')
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        
        # Filtruj sklady na managed canteens
        if user.is_superuser:
            context['warehouses'] = Warehouse.objects.select_related('canteen').all()
        else:
            try:
                user_canteens = user.profile.canteens.all()
                context['warehouses'] = Warehouse.objects.filter(canteen__in=user_canteens).select_related('canteen')
            except ObjectDoesNotExist:
                context['warehouses'] = Warehouse.objects.none()
        
        context['statuses'] = InventoryVerification.Status.choices
        return context


class InventoryVerificationCreateView(LoginRequiredMixin, CreateView):
    """Vytvoření nové inventury."""
    model = InventoryVerification
    form_class = InventoryVerificationForm
    template_name = 'inventory/inventory_verification_form.html'
    
    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs
    
    def get_initial(self):
        """Předvyplnění skladu z URL parametru."""
        initial = super().get_initial()
        warehouse_id = self.request.GET.get('warehouse')
        if warehouse_id:
            initial['warehouse'] = warehouse_id
        return initial
    
    def form_valid(self, form):
        form.instance.created_by = self.request.user
        messages.success(
            self.request,
            f'Inventura skladu "{form.instance.warehouse.name}" byla vytvořena. '
            f'Pro zahájení použijte tlačítko "Zahájit inventuru".'
        )
        return super().form_valid(form)
    
    def get_success_url(self):
        return reverse('inventory:inventory_verification_detail', kwargs={'pk': self.object.pk})


class InventoryVerificationDetailView(LoginRequiredMixin, DetailView):
    """Detail inventury včetně seznamu položek."""
    model = InventoryVerification
    template_name = 'inventory/inventory_verification_detail.html'
    context_object_name = 'verification'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        verification = self.object
        
        # Načteme položky inventury
        items = verification.items.select_related('ingredient').order_by('ingredient__name')
        context['items'] = items
        
        # Statistiky
        context['stats'] = {
            'total_items': items.count(),
            'counted_items': items.filter(counted_quantity__isnull=False).count(),
            'discrepancies': items.exclude(difference=0).count() if verification.status == InventoryVerification.Status.COMPLETED else 0,
        }
        
        return context


@login_required
def inventory_verification_count(request, pk):
    """Formulář pro zadání spočítaných množství."""
    verification = get_object_or_404(InventoryVerification, pk=pk)
    
    # Kontrola oprávnění - přístup k jídelně
    if not user_can_access_canteen(request.user, verification.warehouse.canteen):
        messages.error(request, 'Nemáte oprávnění k této akci.')
        return redirect('inventory:inventory_verification_detail', pk=pk)
    
    # Kontrola stavu
    if verification.status != InventoryVerification.Status.IN_PROGRESS:
        messages.error(request, 'Inventura není v probíhajícím stavu.')
        return redirect('inventory:inventory_verification_detail', pk=pk)
    
    if request.method == 'POST':
        formset = InventoryVerificationItemFormSet(request.POST, instance=verification)
        
        if formset.is_valid():
            # Debug: zkontroluj, kolik formulářů má změny
            changed_forms = [f for f in formset.forms if f.has_changed()]
            
            formset.save()
            messages.success(
                request, 
                f'Spočítaná množství byla uložena. Aktualizováno položek: {len(changed_forms)}'
            )
            return redirect('inventory:inventory_verification_detail', pk=pk)
        else:
            # Zobraz konkrétní chyby validace pro ladění
            for i, form in enumerate(formset.forms):
                if form.errors:
                    for field, errors in form.errors.items():
                        messages.error(request, f'Formulář {i}: {field} - {", ".join(errors)}')
    else:
        formset = InventoryVerificationItemFormSet(instance=verification)
    
    context = {
        'verification': verification,
        'formset': formset,
    }
    return render(request, 'inventory/inventory_verification_count.html', context)


@login_required
def inventory_verification_start(request, pk):
    """Zahájení inventury - zamkne sklad."""
    verification = get_object_or_404(InventoryVerification, pk=pk)
    
    # Kontrola oprávnění - přístup k jídelně
    if not user_can_access_canteen(request.user, verification.warehouse.canteen):
        messages.error(request, 'Nemáte oprávnění k této akci.')
        return redirect('inventory:inventory_verification_detail', pk=pk)
    
    if request.method == 'POST':
        try:
            verification.start(request.user)
            messages.success(
                request,
                f'Inventura skladu "{verification.warehouse.name}" byla zahájena. '
                f'Sklad je nyní uzamčen.'
            )
            return redirect('inventory:inventory_verification_started', pk=pk)
        except ValidationError as e:
            messages.error(request, str(e))
            return redirect('inventory:inventory_verification_detail', pk=pk)
    
    # GET - zobrazíme potvrzovací stránku
    context = {
        'verification': verification,
    }
    return render(request, 'inventory/inventory_verification_start_confirm.html', context)


@login_required
def inventory_verification_started(request, pk):
    """Stránka po zahájení inventury s doporučením papírové inventury."""
    verification = get_object_or_404(InventoryVerification, pk=pk)
    
    # Kontrola oprávnění - přístup k jídelně
    if not user_can_access_canteen(request.user, verification.warehouse.canteen):
        messages.error(request, 'Nemáte oprávnění k této akci.')
        return redirect('inventory:inventory_verification_list')
    
    # Kontrola stavu
    if verification.status != InventoryVerification.Status.IN_PROGRESS:
        messages.warning(request, 'Inventura není v probíhajícím stavu.')
        return redirect('inventory:inventory_verification_detail', pk=pk)
    
    context = {
        'verification': verification,
    }
    return render(request, 'inventory/inventory_verification_started.html', context)


@login_required
def inventory_verification_complete(request, pk):
    """Dokončení inventury - aktualizuje stavy a odemkne sklad."""
    verification = get_object_or_404(InventoryVerification, pk=pk)
    
    # Kontrola oprávnění - přístup k jídelně
    if not user_can_access_canteen(request.user, verification.warehouse.canteen):
        messages.error(request, 'Nemáte oprávnění k této akci.')
        return redirect('inventory:inventory_verification_detail', pk=pk)
    
    if request.method == 'POST':
        try:
            verification.complete(request.user)
            messages.success(
                request,
                f'Inventura skladu "{verification.warehouse.name}" byla dokončena. '
                f'Skladové stavy byly aktualizovány a sklad byl odemčen.'
            )
        except ValidationError as e:
            messages.error(request, str(e))
        
        return redirect('inventory:inventory_verification_detail', pk=pk)
    
    # GET - zobrazíme potvrzovací stránku
    items = verification.items.select_related('ingredient').order_by('ingredient__name')
    context = {
        'verification': verification,
        'items': items,
        'items_with_discrepancies': items.exclude(counted_quantity=None).exclude(difference=0),
    }
    return render(request, 'inventory/inventory_verification_complete_confirm.html', context)


@login_required
def inventory_verification_zero_out(request, pk):
    """Vynuluje všechny položky inventury a rovnou ji dokončí (sklad na nulu)."""
    verification = get_object_or_404(InventoryVerification, pk=pk)

    if not user_can_access_canteen(request.user, verification.warehouse.canteen):
        messages.error(request, 'Nemáte oprávnění k této akci.')
        return redirect('inventory:inventory_verification_detail', pk=pk)

    if request.method == 'POST':
        try:
            verification.zero_out_and_complete(request.user)
            messages.success(
                request,
                f'Sklad "{verification.warehouse.name}" byl vynulován a inventura dokončena.'
            )
        except ValidationError as e:
            messages.error(request, str(e))

        return redirect('inventory:inventory_verification_detail', pk=pk)

    context = {
        'verification': verification,
        'items_count': verification.items.count(),
    }
    return render(request, 'inventory/inventory_verification_zero_out_confirm.html', context)


@login_required
def inventory_verification_cancel(request, pk):
    """Zrušení probíhající inventury - odemkne sklad bez aktualizace."""
    verification = get_object_or_404(InventoryVerification, pk=pk)
    
    # Kontrola oprávnění - přístup k jídelně
    if not user_can_access_canteen(request.user, verification.warehouse.canteen):
        messages.error(request, 'Nemáte oprávnění k této akci.')
        return redirect('inventory:inventory_verification_detail', pk=pk)
    
    # Kontrola oprávnění - pouze ten kdo zahájil
    if verification.started_by != request.user:
        messages.error(
            request,
            f'Inventuru může zrušit pouze uživatel, který ji zahájil '
            f'({verification.started_by.get_full_name() or verification.started_by.username}).'
        )
        return redirect('inventory:inventory_verification_detail', pk=pk)
    
    if request.method == 'POST':
        try:
            verification.cancel(request.user)
            messages.warning(
                request,
                f'Inventura skladu "{verification.warehouse.name}" byla zrušena. '
                f'Sklad byl odemčen, stavy nebyly změněny.'
            )
        except ValidationError as e:
            messages.error(request, str(e))
        
        return redirect('inventory:inventory_verification_list')
    
    # GET - zobrazíme potvrzovací stránku
    context = {
        'verification': verification,
    }
    return render(request, 'inventory/inventory_verification_cancel_confirm.html', context)


@login_required
def inventory_verification_pdf(request, pk):
    """Export inventury do PDF (tisk inventurního soupisu)."""
    verification = get_object_or_404(
        InventoryVerification.objects.select_related('warehouse', 'warehouse__canteen'),
        pk=pk
    )
    
    # Kontrola oprávnění - přístup k jídelně
    if not user_can_access_canteen(request.user, verification.warehouse.canteen):
        messages.error(request, 'Nemáte oprávnění k této akci.')
        return redirect('inventory:inventory_verification_detail', pk=pk)
    
    # Načteme položky
    items = verification.items.select_related('ingredient').order_by('ingredient__name')
    
    context = {
        'verification': verification,
        'items': items,
        'generated_at': timezone.now(),
        'generated_by': request.user,
    }
    
    # Renderování HTML template
    html_string = render_to_string('inventory/verification_pdf.html', context)
    
    # Generování PDF pomocí WeasyPrint
    try:
        from weasyprint import HTML
        
        html = HTML(string=html_string, base_url=request.build_absolute_uri('/'))
        response = HttpResponse(content_type='application/pdf')
        
        filename = f'inventura_{verification.warehouse.name}_{verification.started_at.strftime("%Y%m%d") if verification.started_at else "koncept"}.pdf'
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        
        html.write_pdf(response)
        
        return response
    except ImportError:
        messages.error(request, 'WeasyPrint není nainstalován. PDF export není dostupný.')
        return redirect('inventory:inventory_verification_detail', pk=pk)
    except Exception as e:
        logger.error(f'Error generating PDF for verification {pk}: {e}', exc_info=True)
        messages.error(request, f'Chyba při generování PDF: {str(e)}')
        return redirect('inventory:inventory_verification_detail', pk=pk)


# ==============================
# Stock Transfer Views (Převodky)
# ==============================


class StockTransferListView(CanteenAccessMixin, ListView):
    """Seznam převodek s filtrováním."""
    model = StockTransfer
    template_name = 'inventory/stock_transfer_list.html'
    context_object_name = 'transfers'
    paginate_by = 20
    
    def get_queryset(self):
        # Nemůžeme direktně filtrovat StockTransfer přes warehouse__canteen
        # protože má warehouse_from a warehouse_to, ne warehouse
        # Takže zde je custom filtrování
        queryset = StockTransfer.objects.select_related(
            'warehouse_from', 'warehouse_to',
            'warehouse_from__canteen', 'warehouse_to__canteen',
            'created_by'
        ).prefetch_related('items__ingredient')
        
        user = self.request.user
        if not user.is_superuser:
            try:
                user_canteens = user.profile.canteens.all()
                # Filtruj na transfery kde oba sklady patří managed canteens
                queryset = queryset.filter(
                    Q(warehouse_from__canteen__in=user_canteens) | Q(warehouse_to__canteen__in=user_canteens)
                )
            except ObjectDoesNotExist:
                queryset = queryset.none()
        
        # Filtrování podle skladu (from nebo to)
        warehouse_id = self.request.GET.get('warehouse')
        if warehouse_id:
            queryset = queryset.filter(
                Q(warehouse_from_id=warehouse_id) | Q(warehouse_to_id=warehouse_id)
            )
        
        # Filtrování podle statusu
        status = self.request.GET.get('status')
        if status:
            queryset = queryset.filter(status=status)
        
        return queryset.order_by('-created_at')
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        
        # Filtruj warehouses na managed canteens
        if user.is_superuser:
            context['warehouses'] = Warehouse.objects.filter(is_transit_warehouse=False).select_related('canteen')
        else:
            try:
                user_canteens = user.profile.canteens.all()
                context['warehouses'] = Warehouse.objects.filter(
                    canteen__in=user_canteens,
                    is_transit_warehouse=False
                ).select_related('canteen')
            except ObjectDoesNotExist:
                context['warehouses'] = Warehouse.objects.none()
        
        context['selected_warehouse'] = self.request.GET.get('warehouse', '')
        context['selected_status'] = self.request.GET.get('status', '')
        context['status_choices'] = StockTransfer.STATUS_CHOICES
        return context


class StockTransferCreateView(LoginRequiredMixin, CreateView):
    """Vytvoření nové převodky."""
    model = StockTransfer
    form_class = StockTransferForm
    template_name = 'inventory/stock_transfer_form.html'
    
    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs
    
    def _build_post_formset(self, form, instance=None):
        """Sestaví formset z POST dat vždy se stejným warehouse_from,
        aby validace při zobrazení chyb odpovídala validaci při ukládání."""
        warehouse_from = None
        if hasattr(form, 'cleaned_data'):
            warehouse_from = form.cleaned_data.get('warehouse_from')
        return StockTransferItemFormSet(
            self.request.POST,
            instance=instance,
            form_kwargs={'warehouse_from': warehouse_from},
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        if 'formset' not in context:
            if self.request.POST:
                context['formset'] = self._build_post_formset(context['form'])
            else:
                context['formset'] = StockTransferItemFormSet()
        return context

    def form_valid(self, form):
        form.instance.created_by = self.request.user
        # Formset validujeme PŘED uložením hlavičky - jinak by se při
        # nevalidních položkách ukládaly prázdné převodky.
        formset = self._build_post_formset(form, instance=form.instance)

        if not formset.is_valid():
            return self.render_to_response(
                self.get_context_data(form=form, formset=formset)
            )

        with transaction.atomic():
            self.object = form.save()
            formset.save()

        messages.success(self.request, f'Převodka {self.object.transfer_number} byla vytvořena.')
        return redirect('inventory:stock_transfer_detail', pk=self.object.pk)
    
    def get_success_url(self):
        return reverse('inventory:stock_transfer_detail', kwargs={'pk': self.object.pk})


class StockTransferDetailView(LoginRequiredMixin, DetailView):
    """Detail převodky."""
    model = StockTransfer
    template_name = 'inventory/stock_transfer_detail.html'
    context_object_name = 'transfer'

    def get_queryset(self):
        queryset = StockTransfer.objects.select_related(
            'warehouse_from', 'warehouse_to',
            'warehouse_from__canteen', 'warehouse_to__canteen',
            'created_by'
        ).prefetch_related('items__ingredient')

        # Stejné omezení jako v seznamu - detail cizí převodky nesmí být vidět
        user = self.request.user
        if not user.is_superuser:
            try:
                user_canteens = user.profile.canteens.all()
                queryset = queryset.filter(
                    Q(warehouse_from__canteen__in=user_canteens) | Q(warehouse_to__canteen__in=user_canteens)
                )
            except ObjectDoesNotExist:
                queryset = queryset.none()
        return queryset


@login_required
@require_POST
def stock_transfer_start(request, pk):
    """Zahájit převod - přesun do meziskladu."""
    transfer = get_object_or_404(StockTransfer, pk=pk)
    
    if not user_can_access_canteen(request.user, transfer.warehouse_from.canteen):
        messages.error(request, 'Nemáte oprávnění k této akci.')
        return redirect('inventory:stock_transfer_detail', pk=pk)
    
    try:
        with transaction.atomic():
            transfer.start_transfer()
            messages.success(request, f'Převodka {transfer.transfer_number} byla zahájena. Zboží je nyní v meziskladu.')
    except ValidationError as e:
        messages.error(request, f'Chyba při zahájení převodu: {e.message}')
    except Exception as e:
        logger.error(f'Error starting transfer {pk}: {e}', exc_info=True)
        messages.error(request, f'Neočekávaná chyba: {str(e)}')
    
    return redirect('inventory:stock_transfer_detail', pk=pk)


@login_required
@require_POST
def stock_transfer_complete(request, pk):
    """Dokončit převod - přesun z meziskladu do cílového skladu."""
    transfer = get_object_or_404(StockTransfer, pk=pk)

    # Dokončení naskladňuje do cílového skladu - vyžaduje přístup k cílové jídelně
    if not user_can_access_canteen(request.user, transfer.warehouse_to.canteen):
        messages.error(request, 'Nemáte oprávnění k této akci.')
        return redirect('inventory:stock_transfer_detail', pk=pk)
    
    try:
        with transaction.atomic():
            transfer.complete_transfer()
            messages.success(request, f'Převodka {transfer.transfer_number} byla dokončena. Zboží je nyní v cílovém skladu.')
    except ValidationError as e:
        messages.error(request, f'Chyba při dokončení převodu: {e.message}')
    except Exception as e:
        logger.error(f'Error completing transfer {pk}: {e}', exc_info=True)
        messages.error(request, f'Neočekávaná chyba: {str(e)}')
    
    return redirect('inventory:stock_transfer_detail', pk=pk)


@login_required
@require_POST
def stock_transfer_start_and_complete(request, pk):
    """Zahájit a okamžitě dokončit převod (bez meziskladu)."""
    transfer = get_object_or_404(StockTransfer, pk=pk)

    # Okamžitý převod hýbe oběma sklady - vyžaduje přístup k oběma jídelnám
    if not (user_can_access_canteen(request.user, transfer.warehouse_from.canteen)
            and user_can_access_canteen(request.user, transfer.warehouse_to.canteen)):
        messages.error(request, 'Nemáte oprávnění k této akci.')
        return redirect('inventory:stock_transfer_detail', pk=pk)
    
    try:
        with transaction.atomic():
            transfer.start_and_complete()
            messages.success(request, f'Převodka {transfer.transfer_number} byla okamžitě dokončena.')
    except ValidationError as e:
        messages.error(request, f'Chyba při převodu: {e.message}')
    except Exception as e:
        logger.error(f'Error in instant transfer {pk}: {e}', exc_info=True)
        messages.error(request, f'Neočekávaná chyba: {str(e)}')
    
    return redirect('inventory:stock_transfer_detail', pk=pk)


@login_required
@require_POST
def stock_transfer_cancel(request, pk):
    """Zrušit převod."""
    transfer = get_object_or_404(StockTransfer, pk=pk)
    
    if not user_can_access_canteen(request.user, transfer.warehouse_from.canteen):
        messages.error(request, 'Nemáte oprávnění k této akci.')
        return redirect('inventory:stock_transfer_detail', pk=pk)
    
    try:
        with transaction.atomic():
            transfer.cancel()
            messages.success(request, f'Převodka {transfer.transfer_number} byla zrušena.')
    except ValidationError as e:
        messages.error(request, f'Chyba při rušení převodu: {e.message}')
    except Exception as e:
        logger.error(f'Error cancelling transfer {pk}: {e}', exc_info=True)
        messages.error(request, f'Neočekávaná chyba: {str(e)}')
    
    return redirect('inventory:stock_transfer_detail', pk=pk)


@login_required
def stock_transfer_pdf(request, pk):
    """Export převodky do PDF (průvodka k převodu)."""
    transfer = get_object_or_404(
        StockTransfer.objects.select_related(
            'warehouse_from', 'warehouse_to',
            'warehouse_from__canteen', 'warehouse_to__canteen',
            'created_by'
        ).prefetch_related('items__ingredient'),
        pk=pk
    )
    
    # Kontrola oprávnění - přístup k jídelně
    if not user_can_access_canteen(request.user, transfer.warehouse_from.canteen):
        messages.error(request, 'Nemáte oprávnění k této akci.')
        return redirect('inventory:stock_transfer_detail', pk=pk)
    
    context = {
        'transfer': transfer,
        'items': transfer.items.all().order_by('ingredient__name'),
        'generated_at': timezone.now(),
        'generated_by': request.user,
    }
    
    # Renderování HTML template
    html_string = render_to_string('inventory/transfer_pdf.html', context)
    
    # Generování PDF pomocí WeasyPrint
    try:
        from weasyprint import HTML, CSS
        from io import BytesIO
        
        pdf_file = BytesIO()
        HTML(string=html_string).write_pdf(pdf_file)
        pdf_file.seek(0)
        
        response = HttpResponse(pdf_file.read(), content_type='application/pdf')
        response['Content-Disposition'] = f'inline; filename="prevodka_{transfer.pk}_{transfer.transfer_number}.pdf"'
        
        return response
    except ImportError:
        messages.error(request, 'WeasyPrint není nainstalován. PDF nelze vygenerovat.')
        return redirect('inventory:stock_transfer_detail', pk=pk)
    except Exception as e:
        logger.error(f'Error generating PDF: {e}', exc_info=True)
        messages.error(request, f'Chyba při generování PDF: {str(e)}')
        return redirect('inventory:stock_transfer_detail', pk=pk)


@login_required
def get_stock_item_price(request):
    """AJAX endpoint pro získání ceny a dostupného množství suroviny ze skladu."""
    ingredient_id = request.GET.get('ingredient')
    warehouse_id = request.GET.get('warehouse')
    
    if not ingredient_id or not warehouse_id:
        return JsonResponse({
            'success': False,
            'error': 'Chybí parametry ingredient nebo warehouse'
        })
    
    try:
        stock_item = StockItem.objects.get(
            ingredient_id=ingredient_id,
            warehouse_id=warehouse_id
        )
        
        return JsonResponse({
            'success': True,
            'price': str(stock_item.price),
            'available_quantity': str(stock_item.quantity_available),
            'quantity': str(stock_item.quantity),
            'quantity_blocked': str(stock_item.quantity_blocked),
            'unit': stock_item.ingredient.base_unit
        })

    except StockItem.DoesNotExist:
        return JsonResponse({
            'success': False,
            'error': 'Surovina není na tomto skladu'
        })
    except Exception as e:
        logger.error(f'Error fetching stock item price: {e}', exc_info=True)
        return JsonResponse({
            'success': False,
            'error': str(e)
        })


@login_required
def get_warehouse_ingredients(request):
    """AJAX endpoint: seznam surovin, které jsou skladem ve zvoleném skladu.

    Vrací i neaktivní suroviny - pokud jsou fyzicky na skladě, musí jít převést.
    """
    warehouse_id = request.GET.get('warehouse')
    if not warehouse_id:
        return JsonResponse({
            'success': False,
            'error': 'Chybí parametr warehouse'
        })

    try:
        warehouse = Warehouse.objects.select_related('canteen').get(pk=warehouse_id)
    except (Warehouse.DoesNotExist, ValueError):
        return JsonResponse({
            'success': False,
            'error': 'Sklad nenalezen'
        })

    if not user_can_access_canteen(request.user, warehouse.canteen):
        return JsonResponse({
            'success': False,
            'error': 'Nemáte oprávnění k tomuto skladu'
        }, status=403)

    stock_items = StockItem.objects.filter(
        warehouse=warehouse,
        quantity__gt=0
    ).select_related('ingredient').order_by(Collate('ingredient__name', 'czech'))

    ingredients = [
        {
            'id': si.ingredient_id,
            'name': si.ingredient.name,
            'unit': si.ingredient.base_unit,
            'available_quantity': str(si.quantity_available),
            'quantity_blocked': str(si.quantity_blocked),
            'price': str(si.price),
        }
        for si in stock_items
    ]

    return JsonResponse({'success': True, 'ingredients': ingredients})


@login_required
@cache_page(60 * 15)  # Cache na 15 minut
def get_supplier_template(request, supplier_slug):
    """
    AJAX endpoint pro načítání šablon surovin podle dodavatele.
    Vrací JSON s přednastavenými surovinami a jejich výchozími cenami.
    """
    try:
        # Pokusíme se načíst z cache
        cache_key = f"supplier_template_{supplier_slug}"
        cached_data = cache.get(cache_key)
        
        if cached_data:
            return JsonResponse(cached_data)
        
        # Načteme dodavatele a jeho šablonu surovin
        supplier = get_object_or_404(Supplier, slug=supplier_slug, is_active=True)
        
        template_items = supplier.get_template_ingredients()
        
        # Připravíme data pro frontend
        ingredients_data = []
        for template_item in template_items:
            ingredient_data = {
                'ingredient_id': template_item.ingredient.id,
                'ingredient_name': template_item.ingredient.name,
                'unit': template_item.ingredient.base_unit,
                'default_price_without_vat': str(template_item.default_price_without_vat) if template_item.default_price_without_vat else '',
                'default_vat_rate': str(template_item.default_vat_rate),
                'default_price_with_vat': str(template_item.default_price_with_vat) if template_item.default_price_with_vat else '',
                'sort_order': template_item.sort_order
            }
            ingredients_data.append(ingredient_data)
        
        response_data = {
            'success': True,
            'supplier_name': supplier.name,
            'supplier_slug': supplier.slug,
            'ingredients': ingredients_data,
            'total_count': len(ingredients_data)
        }
        
        # Uložíme do cache
        cache.set(cache_key, response_data, 60 * 60)  # Cache na 1 hodinu
        
        return JsonResponse(response_data)
    
    except Supplier.DoesNotExist:
        return JsonResponse({
            'success': False,
            'error': f'Dodavatel "{supplier_slug}" nenalezen nebo není aktivní'
        })
    except Exception as e:
        logger.error(f'Error loading supplier template for {supplier_slug}: {e}', exc_info=True)
        return JsonResponse({
            'success': False,
            'error': 'Chyba při načítání šablony dodavatele'
        })


@login_required
def generate_receipt_number(request):
    """
    AJAX endpoint pro generování jedinečného čísla příjmu zboží.
    Vrací číslo ve formátu PZ-YYYY-MM-NNNN na základě posledního čísla v databázi.
    """
    try:
        from datetime import datetime
        
        current_date = datetime.now()
        year = current_date.year
        month = current_date.month
        
        # Najít poslední příjem v aktuálním měsíci
        month_prefix = f"PZ-{year}-{month:02d}-"
        
        last_receipt = GoodsReceipt.objects.filter(
            receipt_number__startswith=month_prefix
        ).order_by('-receipt_number').first()
        
        if last_receipt:
            # Extrahovat číselnou část z posledního čísla
            try:
                last_number_str = last_receipt.receipt_number.split('-')[-1]
                last_number = int(last_number_str)
                next_number = last_number + 1
            except (ValueError, IndexError):
                # Pokud se nepodaří parsovat, začneme od 1
                next_number = 1
        else:
            # První příjem v měsíci
            next_number = 1
        
        # Vygenerovat nové číslo
        receipt_number = f"PZ-{year}-{month:02d}-{next_number:04d}"
        
        # Kontrola jedinečnosti (pro případ souběžného vytváření)
        while GoodsReceipt.objects.filter(receipt_number=receipt_number).exists():
            next_number += 1
            receipt_number = f"PZ-{year}-{month:02d}-{next_number:04d}"
        
        return JsonResponse({
            'success': True,
            'receipt_number': receipt_number,
            'year': year,
            'month': month,
            'sequence': next_number
        })
    
    except Exception as e:
        logger.error(f'Error generating receipt number: {e}', exc_info=True)
        return JsonResponse({
            'success': False,
            'error': 'Chyba při generování čísla dokladu'
        })


# ===== ODEPSÁNÍ MIMO RECEPTY (STOCK WRITE-OFFS) =====

class StockWriteOffListView(CanteenAccessMixin, ListView):
    """Seznam odepsání mimo recepty"""
    model = StockWriteOff
    template_name = 'inventory/stock_write_off_list.html'
    context_object_name = 'write_offs'
    paginate_by = 20
    
    def get_queryset(self):
        queryset = super().get_queryset().select_related('warehouse', 'warehouse__canteen', 'created_by').prefetch_related('items')
        
        # Filtrování podle skladu
        warehouse_id = self.request.GET.get('warehouse')
        if warehouse_id:
            queryset = queryset.filter(warehouse_id=warehouse_id)
        
        # Filtrování podle kategorie
        category = self.request.GET.get('category')
        if category:
            queryset = queryset.filter(category=category)
        
        # Filtrování podle data
        date_from = self.request.GET.get('date_from')
        if date_from:
            queryset = queryset.filter(write_off_date__gte=date_from)
        
        date_to = self.request.GET.get('date_to')
        if date_to:
            queryset = queryset.filter(write_off_date__lte=date_to)
        
        return queryset.order_by('-write_off_date', '-created_at')
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        # Získáme seznam skladů pro filtr
        user = self.request.user
        if user.is_superuser:
            warehouses = Warehouse.objects.all()
        else:
            try:
                user_canteens = user.profile.canteens.all()
                warehouses = Warehouse.objects.filter(canteen__in=user_canteens)
            except:
                warehouses = Warehouse.objects.none()
        
        context['warehouses'] = warehouses
        context['categories'] = StockWriteOff.Category.choices
        
        # Kumulativní statistiky pro aktuální filtr
        write_offs = self.get_queryset()
        total_cost = Decimal('0')
        
        for wo in write_offs:
            total_cost += wo.get_total_cost()
        
        context['total_cost'] = total_cost
        
        return context


@login_required
def stock_write_off_create(request):
    """Vytvoření nového odepsání"""
    if request.method == 'POST':
        form = StockWriteOffForm(request.POST, user=request.user)
        
        # Debug: Zobrazit počet formulářů
        form_is_valid = form.is_valid()
        
        warehouse = form.cleaned_data.get('warehouse') if form_is_valid else None
        formset = StockWriteOffItemFormSet(request.POST, form_kwargs={'warehouse': warehouse})
        formset_is_valid = formset.is_valid()
        
        if form_is_valid and formset_is_valid:
            # Kontrola, zda jsou nějaké vyplněné položky
            has_items = any(
                form.cleaned_data.get('ingredient') 
                for form in formset.forms 
                if form.cleaned_data and not form.cleaned_data.get('DELETE', False)
            )
            
            if not has_items:
                messages.error(request, 'Prosím vyplňte alespoň jednu položku odepsání!')
            else:
                try:
                    with transaction.atomic():
                        write_off = form.save(commit=False)
                        write_off.created_by = request.user
                        write_off.save()
                        
                        # Nastavíme instance pro formset a uložíme
                        formset.instance = write_off
                        formset.save()
                        
                        messages.success(request, f'Odepsání bylo úspěšně vytvořeno. Celkem: {write_off.get_total_cost()} Kč')
                        return redirect('inventory:stock_write_off_detail', pk=write_off.pk)
                        
                except ValidationError as e:
                    messages.error(request, f'Chyba při vytváření odepsání: {e}')
                except Exception as e:
                    messages.error(request, f'Chyba při vytváření odepsání: {str(e)}')
        else:
            # Zobrazit chyby
            if not form_is_valid:
                for error in form.non_field_errors():
                    messages.error(request, f'Chyba v hlavním formuláři: {error}')
            if not formset_is_valid:
                for error in formset.non_form_errors():
                    messages.error(request, f'Chyba v položkách: {error}')
                # Zobrazit chyby v jednotlivých formulářích
                for i, form in enumerate(formset.forms):
                    for error in form.non_field_errors():
                        messages.error(request, f'Chyba v položce {i+1}: {error}')
    else:
        form = StockWriteOffForm(user=request.user)
        formset = StockWriteOffItemFormSet()
    
    # Připravíme data surovin pro autocomplete jako JSON.
    # Musí odpovídat querysetu ve StockWriteOffItemForm – tj. aktivní suroviny
    # plus neaktivní se zásobou na skladě. Jinak by autocomplete nabídl surovinu,
    # kterou formulář následně odmítne chybou "Vyberte platnou možnost".
    import json
    selectable_ingredients = Ingredient.objects.filter(
        Q(is_active=True) | Q(pk__in=StockItem.objects.values('ingredient'))
    ).order_by('name')
    ingredients_list = [
        {
            'id': ing.id,
            'name': ing.name,
            'unit': ing.recipe_unit,
            'base_unit': ing.base_unit
        }
        for ing in selectable_ingredients
    ]
    
    return render(request, 'inventory/stock_write_off_form.html', {
        'form': form,
        'formset': formset,
        'all_ingredients': json.dumps(ingredients_list),
    })


class StockWriteOffDetailView(CanteenAccessMixin, DetailView):
    """Detail odepsání"""
    model = StockWriteOff
    template_name = 'inventory/stock_write_off_detail.html'
    context_object_name = 'write_off'
    
    def get_queryset(self):
        return super().get_queryset().select_related('warehouse', 'warehouse__canteen', 'created_by').prefetch_related('items__ingredient')


class StockWriteOffDeleteView(CanteenAccessMixin, DeleteView):
    """Smazání odepsání s vrácením položek na sklad"""
    model = StockWriteOff
    template_name = 'inventory/stock_write_off_confirm_delete.html'
    success_url = reverse_lazy('inventory:stock_write_off_list')
    context_object_name = 'write_off'

    def get_queryset(self):
        return super().get_queryset().select_related('warehouse', 'warehouse__canteen', 'created_by').prefetch_related('items__ingredient')

    def post(self, request, *args, **kwargs):
        self.object = self.get_object()
        write_off_id = self.object.pk
        items_count = self.object.items.count()
        messages.success(
            request,
            f'Odepsání #{write_off_id} bylo smazáno a {items_count} položek bylo vráceno na sklad.'
        )
        return super().delete(request, *args, **kwargs)


@login_required
def stock_write_off_pdf(request, pk):
    """Export odepsání do PDF"""
    write_off = get_object_or_404(
        StockWriteOff.objects.select_related('warehouse', 'warehouse__canteen', 'created_by').prefetch_related('items__ingredient'),
        pk=pk
    )
    
    # Kontrola oprávnění
    if not request.user.is_superuser:
        try:
            user_canteens = request.user.profile.canteens.all()
            if write_off.warehouse.canteen not in user_canteens:
                messages.error(request, 'Nemáte oprávnění k tomuto odepsání')
                return redirect('inventory:stock_write_off_list')
        except:
            messages.error(request, 'Nemáte oprávnění k tomuto odepsání')
            return redirect('inventory:stock_write_off_list')
    
    # Vygenerujeme HTML
    html_string = render_to_string('inventory/stock_write_off_pdf.html', {
        'write_off': write_off,
    })
    
    # Vytvoříme PDF (podobně jako u ostatních dokladů)
    try:
        from weasyprint import HTML, CSS
        from io import BytesIO
        
        pdf_file = BytesIO()
        HTML(string=html_string).write_pdf(pdf_file)
        pdf_file.seek(0)
        
        response = HttpResponse(pdf_file.read(), content_type='application/pdf')
        response['Content-Disposition'] = f'inline; filename="odepsani_{write_off.pk}_{write_off.write_off_date.strftime("%Y%m%d")}.pdf"'
        
        return response
    except ImportError:
        messages.error(request, 'WeasyPrint není nainstalován. PDF nelze vygenerovat.')
        return redirect('inventory:stock_write_off_detail', pk=pk)
    except Exception as e:
        logger.error(f'Error generating PDF: {e}', exc_info=True)
        messages.error(request, f'Chyba při generování PDF: {str(e)}')
        return redirect('inventory:stock_write_off_detail', pk=pk)


# Supplier CSV Import (Makro)

@login_required
def supplier_csv_import_step1(request):
    """Krok 1: Upload CSV souboru a výběr výchozího skladu"""
    if request.method == 'POST':
        csv_file = request.FILES.get('csv_file')
        default_warehouse_id = request.POST.get('warehouse')
        
        if not csv_file or not default_warehouse_id:
            messages.error(request, 'Musíte vybrat CSV soubor a výchozí sklad.')
            return redirect('inventory:supplier_csv_import_step1')
        
        try:
            # Parsování CSV
            receipt_data = parse_supplier_csv(csv_file)
            
            # Uložení do session (konverze na JSON-serializovatelná data)
            request.session['supplier_csv_receipt_data'] = {
                'receipt_number': receipt_data['receipt_number'],
                'receipt_date': receipt_data['receipt_date'].isoformat(),
                'supplier': receipt_data['supplier'],
                'items': [
                    {
                        'item_id': item['item_id'],
                        'item_name': item['item_name'],
                        'quantity': str(item['quantity']),
                        'unit': item['unit'],
                        'unit_mapped': item['unit_mapped'],
                        'price_per_unit_net': str(item['price_per_unit_net']),
                        'price_per_unit_gross': str(item['price_per_unit_gross']),
                        'vat_rate': str(item['vat_rate']),
                        'vat_amount': str(item['vat_amount']),
                        'total_price': str(item['total_price']),
                    }
                    for item in receipt_data['items']
                ]
            }
            request.session['supplier_csv_default_warehouse'] = default_warehouse_id
            
            messages.success(request, f'CSV načten: {len(receipt_data["items"])} položek')
            return redirect('inventory:supplier_csv_import_step2')
            
        except Exception as e:
            messages.error(request, f'Chyba při načítání CSV: {e}')
    
    warehouses = Warehouse.objects.select_related('canteen').all()
    if not request.user.is_superuser:
        try:
            user_canteens = request.user.profile.canteens.all()
            warehouses = warehouses.filter(canteen__in=user_canteens)
        except ObjectDoesNotExist:
            warehouses = Warehouse.objects.none()
    return render(request, 'inventory/supplier_csv_import_step1.html', {
        'warehouses': warehouses
    })


@login_required
def supplier_csv_import_step2(request):
    """Krok 2: Preview, mapování surovin, editace jednotek a skladů"""
    receipt_data = request.session.get('supplier_csv_receipt_data')
    if not receipt_data:
        messages.error(request, 'Session vypršela. Začněte znovu.')
        return redirect('inventory:supplier_csv_import_step1')
    
    default_warehouse_id = int(request.session.get('supplier_csv_default_warehouse'))
    warehouses = Warehouse.objects.all()
    if not request.user.is_superuser:
        try:
            user_canteens = request.user.profile.canteens.all()
            warehouses = warehouses.filter(canteen__in=user_canteens)
        except ObjectDoesNotExist:
            warehouses = Warehouse.objects.none()
    all_ingredients = list(Ingredient.objects.all())

    _apply_ingredient_matching(receipt_data, all_ingredients)

    context = {
        'receipt_data': receipt_data,
        'warehouses': warehouses,
        'default_warehouse_id': default_warehouse_id,
        'all_ingredients': all_ingredients,
    }
    
    return render(request, 'inventory/supplier_csv_import_step2.html', context)


@login_required
@transaction.atomic
def supplier_csv_import_step3(request):
    """Krok 3: Vytvoření GoodsReceipt s položkami"""
    if request.method != 'POST':
        return redirect('inventory:supplier_csv_import_step1')
    
    receipt_data = request.session.get('supplier_csv_receipt_data')
    if not receipt_data:
        messages.error(request, 'Session vypršela. Začněte znovu.')
        return redirect('inventory:supplier_csv_import_step1')
    
    default_warehouse_id = request.session.get('supplier_csv_default_warehouse')
    default_warehouse = Warehouse.objects.get(id=default_warehouse_id)
    
    # Kontrola oprávnění - přístup k jídelně skladu
    if not user_can_access_canteen(request.user, default_warehouse.canteen):
        messages.error(request, 'Nemáte oprávnění zapisovat do tohoto skladu.')
        return redirect('inventory:supplier_csv_import_step1')
    
    # Vytvoření GoodsReceipt
    goods_receipt = GoodsReceipt.objects.create(
        warehouse=default_warehouse,
        receipt_number=receipt_data['receipt_number'],
        receipt_date=receipt_data['receipt_date'],
        supplier=receipt_data['supplier'],
        status=GoodsReceipt.Status.DRAFT,
        created_by=request.user,
        notes=f"Importováno z CSV (Makro)"
    )
    
    # Zpracování položek
    created_ingredients_count = 0
    mappings = []
    
    for idx, item in enumerate(receipt_data['items']):
        # Načtení dat z formuláře
        create_new = request.POST.get(f'create_new_{idx}') == 'on'
        
        if create_new:
            # Vytvoření nové suroviny
            ingredient_name = request.POST.get(f'ingredient_name_{idx}', item['item_name'])
            ingredient_unit = request.POST.get(f'ingredient_unit_{idx}', item['unit_mapped'])
            
            ingredient, created = Ingredient.objects.get_or_create(
                name=ingredient_name,
                defaults={
                    'unit': ingredient_unit,
                    'category_id': 1,  # Default category
                }
            )
            if created:
                created_ingredients_count += 1
        else:
            ingredient_id = request.POST.get(f'ingredient_{idx}')
            if not ingredient_id:
                messages.error(request, f'Položka {idx + 1}: Musíte vybrat surovinu nebo vytvořit novou.')
                # Příjemka je už založená a `transaction.atomic` na `return`
                # nereaguje – bez tohohle by v databázi zůstala rozdělaná.
                transaction.set_rollback(True)
                return redirect('inventory:supplier_csv_import_step2')
            ingredient = Ingredient.objects.get(id=ingredient_id)
        
        # Získání skladu pro tuto položku
        warehouse_id = request.POST.get(f'warehouse_{idx}', default_warehouse_id)
        warehouse = Warehouse.objects.get(id=warehouse_id)
        
        # Přepočet na skladovou jednotku. Co se přepočítat nedá, projde
        # s poměrem 1 a příjemka se bez doplnění poměru nepotvrdí.
        converted = _convert_to_stock_unit(
            item, ingredient,
            Decimal(str(item['quantity'])),
            Decimal(str(item['price_per_unit_net'])),
            Decimal(str(item['price_per_unit_gross'])),
        )
        
        # Vytvoření položky příjmu
        GoodsReceiptItem.objects.create(
            goods_receipt=goods_receipt,
            ingredient=ingredient,
            warehouse=warehouse,
            vat_rate=item['vat_rate'],
            **converted,
        )
        mappings.append((item, ingredient))
    
    # Zapamatování mapování pro příští doklad od téhož dodavatele
    _remember_ingredient_mapping(receipt_data, mappings, request.user)
    
    messages.success(request, f'Příjem vytvořen: {len(receipt_data["items"])} položek, {created_ingredients_count} nových surovin.')
    return redirect('inventory:goods_receipt_detail', pk=goods_receipt.pk)


# ============================================================================
# Import příjemky z fotky dokladu (Mistral OCR)
# ============================================================================

# Nad tuhle velikost soubor odmítneme dřív, než se začne zpracovávat.
# Fotka z mobilu má i ve vysokém rozlišení jednotky megabajtů.
MAX_SCAN_UPLOAD_BYTES = 25 * 1024 * 1024

# Skeny ukládá `ocr.storage` podle typu, takže přípona určuje, čím se mají
# poslat zpátky. PDF poslané jako obrázek prohlížeč nezobrazí.
SCAN_CONTENT_TYPES = {
    '.jpg': 'image/jpeg',
    '.jpeg': 'image/jpeg',
    '.png': 'image/png',
    '.pdf': 'application/pdf',
}


def _serialize_receipt_data(receipt_data):
    """
    Převede `receipt_data` do podoby, kterou snese session.

    Session se serializuje do JSONu, takže `date` a `Decimal` musí ven.
    Zpátky se nepřevádí – šablona i krok 3 si s řetězci vystačí, stejně jako
    u importu z CSV a XML.
    """
    serialized = dict(receipt_data)
    serialized['receipt_date'] = receipt_data['receipt_date'].isoformat()
    serialized['totals'] = {
        key: (str(value) if value is not None else None)
        for key, value in receipt_data['totals'].items()
    }
    serialized['items'] = [
        {
            key: (str(value) if isinstance(value, Decimal) else value)
            for key, value in item.items()
        }
        for item in receipt_data['items']
    ]
    return serialized


@login_required
def photo_import_step1(request):
    """
    Krok 1: nahrání fotky dokladu a spuštění OCR.

    Fotka se zmenší, uloží do dočasného úložiště a pošle do Mistral OCR.
    Rozpoznaná data putují do session, sken zůstává na disku kvůli náhledu
    v kroku 2 – po potvrzení příjemky se maže.
    """
    from .ocr.client import OcrError, prepare_image, run_ocr
    from .ocr.normalize import to_receipt_data
    from .ocr.storage import maybe_purge, save_scan

    warehouses = Warehouse.objects.select_related('canteen').all()
    if not request.user.is_superuser:
        try:
            user_canteens = request.user.profile.canteens.all()
            warehouses = warehouses.filter(canteen__in=user_canteens)
        except ObjectDoesNotExist:
            warehouses = Warehouse.objects.none()

    if request.method == 'POST':
        scan_file = request.FILES.get('scan_file')
        warehouse_id = request.POST.get('warehouse')

        if not scan_file or not warehouse_id:
            messages.error(request, 'Vyberte fotku dokladu a sklad.')
            return redirect('inventory:photo_import_step1')

        if scan_file.size > MAX_SCAN_UPLOAD_BYTES:
            messages.error(
                request,
                f'Soubor je příliš velký ({scan_file.size // (1024 * 1024)} MB). '
                f'Maximum je {MAX_SCAN_UPLOAD_BYTES // (1024 * 1024)} MB.'
            )
            return redirect('inventory:photo_import_step1')

        warehouse = get_object_or_404(warehouses, id=warehouse_id)
        if not user_can_access_canteen(request.user, warehouse.canteen):
            messages.error(request, 'Nemáte oprávnění zapisovat do tohoto skladu.')
            return redirect('inventory:photo_import_step1')

        try:
            image_bytes, mime = prepare_image(scan_file.read(), scan_file.name)
            # Ukládáme zmenšenou podobu, ne originál – na náhled stačí
            # a na disku se drží jen do potvrzení příjemky.
            scan_path = save_scan(image_bytes, mime)
            # Posíláme už zmenšenou podobu, ať se JPEG nekóduje podruhé.
            result = run_ocr(image_bytes, scan_file.name, mime_type=mime)
            receipt_data = to_receipt_data(result['annotation'])
        except OcrError as exc:
            messages.error(request, str(exc))
            return redirect('inventory:photo_import_step1')
        except Exception as exc:
            logger.exception('Neočekávaná chyba při zpracování skenu dokladu')
            messages.error(request, f'Doklad se nepodařilo zpracovat: {exc}')
            return redirect('inventory:photo_import_step1')

        supplier = find_supplier(
            name=receipt_data['supplier'], ico=receipt_data['supplier_ico'],
        )
        receipt_data['supplier_id'] = supplier.id if supplier else None

        scan = GoodsReceiptScan.objects.create(
            file_path=scan_path,
            original_filename=scan_file.name[:255],
            annotation=result['annotation'],
            markdown=result['markdown'],
            ocr_model=settings.MISTRAL_OCR_MODEL,
            uploaded_by=request.user,
        )

        request.session['photo_receipt_data'] = _serialize_receipt_data(receipt_data)
        request.session['photo_default_warehouse'] = str(warehouse.id)
        request.session['photo_scan_id'] = scan.id

        # Úklid prošlých skenů se veze na nahrávání – projekt nemá plánovač.
        # Sken uživatele je v tuhle chvíli už uložený a v session; kdyby
        # úklid cizích starých souborů spadl (souběh dvou workerů, sklad
        # bez oprávnění zapisovat), nesmí to strhnout celý upload do 500 –
        # uživatel by pak neměl jak doklad vůbec dostat do systému.
        try:
            maybe_purge()
        except Exception:
            logger.exception('Úklid prošlých skenů dokladů selhal, pokračuje se bez něj')

        pocet = len([i for i in receipt_data['items'] if not i['is_ignored']])
        messages.success(request, f'Doklad načten: {pocet} položek zboží.')
        return redirect('inventory:photo_import_step2')

    return render(request, 'inventory/photo_import_step1.html', {
        'warehouses': warehouses,
        'ocr_available': bool(settings.MISTRAL_API_KEY),
    })


def _collect_import_warnings(receipt_data, warehouse):
    """
    Pojistky, které se ukážou v kroku 2.

    Nic neblokují – každá má legitimní výjimku. Jen upozorní na to, co
    ostatní kontroly nezachytí, protože doklad si sedí sám se sebou:
    dvakrát naskladněný dodák a překlep OCR v ceně.
    """
    from .receipt_checks import (
        check_duplicate_receipt, check_price_deviation, check_price_precision,
    )

    supplier = Supplier.objects.filter(id=receipt_data.get('supplier_id')).first()
    duplicate = check_duplicate_receipt(
        receipt_data.get('receipt_number'),
        supplier=supplier,
        supplier_name=receipt_data.get('supplier', ''),
    )

    price_warnings = []
    unit_warnings = []
    ingredients = {
        ingredient.id: ingredient
        for ingredient in Ingredient.objects.filter(
            id__in=[i['ingredient_id'] for i in receipt_data['items'] if i.get('ingredient_id')]
        )
    }

    for item in receipt_data['items']:
        if item['is_ignored'] or not item.get('ingredient_id'):
            continue
        ingredient = ingredients.get(item['ingredient_id'])

        if item.get('needs_unit_check'):
            unit_warnings.append(
                f'„{item["item_name"]}": doklad je v jednotce {item["source_unit"]}, '
                f'sklad vede {item["ingredient_name"]} v {item["target_unit"]}. '
                f'Doplňte, kolik {item["target_unit"]} je jedna {item["source_unit"]}.'
            )
            # Dokud se jednotky nesrovnají, cenu porovnávat nemá smysl.
            continue

        precision = check_price_precision(
            Decimal(item['price_per_unit_gross']), item.get('unit_factor', '1'),
        )
        if precision:
            price_warnings.append(
                f'„{item["item_name"]}": po přepočtu na {item["target_unit"]} '
                f'vychází cena {precision["exact"]} Kč, ale sklad ji umí uložit '
                f'jen jako {precision["stored"]} Kč. Ocenění skladu bude '
                f'o {precision["error"] * 100:.0f} % vedle. Zvažte, jestli má '
                f'{item["ingredient_name"]} zůstat v {item["target_unit"]}.'
            )

        deviation = check_price_deviation(
            ingredient, warehouse, Decimal(item['price_per_unit_gross']),
        )
        if deviation:
            price_warnings.append(
                f'„{item["item_name"]}": cena {deviation["current"]} Kč je proti '
                f'poslední známé ({deviation["previous"]} Kč) {deviation["direction"]} '
                f'o {abs(deviation["ratio"]) * 100:.0f} %. Ověřte ji na dokladu.'
            )

    return {'duplicate': duplicate, 'prices': price_warnings, 'units': unit_warnings}


@login_required
def photo_import_step2(request):
    """Krok 2: kontrola rozpoznaných dat proti fotce a mapování surovin."""
    receipt_data = request.session.get('photo_receipt_data')
    if not receipt_data:
        messages.error(request, 'Session vypršela. Začněte znovu.')
        return redirect('inventory:photo_import_step1')

    # Sestavení návrhu je citlivé na obsah dokladu i na relaci (neočekávaný
    # formát čísla, chybějící pole u starého skenu, poškozená nebo zastaralá
    # `photo_default_warehouse` v relaci apod.) – neošetřená výjimka by tu
    # spadla do holé 500 bez stopy, co přesně selhalo. Zabalené je celé tělo
    # od prvního přístupu k relaci až po render, ať se nezapomene na kus mezi
    # nimi. Radši konkrétní hláška a čitelný záznam v logu, ať je to
    # dohledatelné i bez přístupu k živému serveru.
    try:
        default_warehouse_id = int(request.session['photo_default_warehouse'])
        warehouses = Warehouse.objects.select_related('canteen').all()
        if not request.user.is_superuser:
            try:
                user_canteens = request.user.profile.canteens.all()
                warehouses = warehouses.filter(canteen__in=user_canteens)
            except ObjectDoesNotExist:
                warehouses = Warehouse.objects.none()

        all_ingredients = list(Ingredient.objects.filter(is_active=True))
        _apply_ingredient_matching(receipt_data, all_ingredients)
        request.session['photo_receipt_data'] = receipt_data

        default_warehouse = Warehouse.objects.filter(id=default_warehouse_id).first()
        checks = _collect_import_warnings(receipt_data, default_warehouse)
    except Exception as exc:
        logger.exception(
            'Návrh příjemky z fotky selhal (doklad %s, sken %s)',
            receipt_data.get('receipt_number'), request.session.get('photo_scan_id'),
        )
        messages.error(
            request,
            f'Návrh příjemky se nepodařilo připravit ({exc}). Zkuste doklad '
            f'nahrát znovu; pokud to nepomůže, nahlaste to i s tímhle popisem.'
        )
        return redirect('inventory:photo_import_step1')

    return render(request, 'inventory/photo_import_step2.html', {
        'receipt_data': receipt_data,
        'warehouses': warehouses,
        'default_warehouse_id': default_warehouse_id,
        'all_ingredients': all_ingredients,
        'scan_id': request.session.get('photo_scan_id'),
        'suppliers': Supplier.objects.filter(is_active=True),
        'duplicate_receipt': checks['duplicate'],
        'price_warnings': checks['prices'],
        'unit_warnings': checks['units'],
    })


@login_required
@transaction.atomic
def photo_import_step3(request):
    """Krok 3: vytvoření příjemky z potvrzených řádků."""
    if request.method != 'POST':
        return redirect('inventory:photo_import_step1')

    receipt_data = request.session.get('photo_receipt_data')
    if not receipt_data:
        messages.error(request, 'Session vypršela. Začněte znovu.')
        return redirect('inventory:photo_import_step1')

    default_warehouse_id = request.session['photo_default_warehouse']
    default_warehouse = get_object_or_404(Warehouse, id=default_warehouse_id)
    if not user_can_access_canteen(request.user, default_warehouse.canteen):
        messages.error(request, 'Nemáte oprávnění zapisovat do tohoto skladu.')
        return redirect('inventory:photo_import_step1')

    supplier_id = request.POST.get('supplier_obj') or receipt_data.get('supplier_id')
    supplier_obj = Supplier.objects.filter(id=supplier_id).first() if supplier_id else None

    # Nejdřív se ověří všechny řádky, teprve pak se zapisuje. Kdyby se
    # příjemka založila dopředu a některý řádek pak neprošel, zůstala by
    # v databázi rozdělaná – `transaction.atomic` na `return` nereaguje,
    # roluje zpět jen výjimku.
    planned = []
    skipped = []
    new_ingredient_names = []

    # Validace řádků čte přímo pole z dokladu (`item['price_per_unit_net']`
    # apod.) – u staršího nebo neobvyklého skenu můžou chybět nebo mít tvar,
    # který `Decimal(...)`/`convert_line(...)` nesloví. To je jiná chyba než
    # ty, co si uživatel může sám opravit na kroku 2 výše (proto zvlášť,
    # ne jen další `except` u nich) – tady se jen zaloguje a diagnostikuje,
    # u kterého řádku to bylo, ať to zase nespadne do holé 500.
    idx = None
    try:
        for idx, item in enumerate(receipt_data['items']):
            # Nezaškrtnutý řádek na sklad nejde. Uživatel takhle odmítá
            # zaokrouhlení, dopravu a obaly – a my si to zapamatujeme.
            if request.POST.get(f'include_{idx}') != 'on':
                skipped.append(item)
                continue

            if request.POST.get(f'create_new_{idx}') == 'on':
                new_ingredient_names.append(
                    (idx, request.POST.get(f'ingredient_name_{idx}') or item['item_name'])
                )
                ingredient = None
            else:
                ingredient = Ingredient.objects.filter(
                    id=request.POST.get(f'ingredient_{idx}')
                ).first()
                if ingredient is None:
                    messages.error(
                        request,
                        f'Řádek {idx + 1} „{item["item_name"]}": vyberte surovinu, '
                        f'založte novou, nebo řádek odškrtněte.'
                    )
                    return redirect('inventory:photo_import_step2')

            warehouse = Warehouse.objects.filter(
                id=request.POST.get(f'warehouse_{idx}', default_warehouse_id)
            ).first()
            if warehouse is None:
                messages.error(request, f'Řádek {idx + 1}: vybraný sklad neexistuje.')
                return redirect('inventory:photo_import_step2')

            # Jednotky, které se automaticky nepřevedou (např. „ks" na
            # dokladu vs. vlastní jednotka skladu jako „bochník") – bez
            # zásahu člověka nevíme, jestli je poměr 1:1, nebo úplně jiný.
            unit_conflict = (
                ingredient is not None
                and not units_are_compatible(item['unit_mapped'], ingredient.base_unit)
            )

            # Přepočet na skladovou jednotku. Bez něj by se do skladu, který
            # vede gramy, přičetlo množství v kilech.
            #
            # Nevyplněný/nedořešený přepočet se v session i ve formuláři
            # předvyplňuje nulou, ne jedničkou – jednička je totiž i platná
            # odpověď („1 ks = 1 bochník"), takže by šlo těžko poznat, jestli
            # ji tam nechal uživatel, nebo je to jen nedotčený výchozí stav.
            # Nula je jednoznačně „nevyplněno", takže stačí jediná kontrola.
            factor = _decimal_from_post(
                request.POST.get(f'unit_factor_{idx}'), item.get('unit_factor', '0')
            )
            # Záporné číslo je vždycky jen překlep, ne nevyplněné pole –
            # ať se to nesplete s „ještě nedořešeno" u nuly.
            if factor < 0:
                messages.error(
                    request,
                    f'Řádek {idx + 1} „{item["item_name"]}": přepočet jednotek '
                    f'musí být kladné číslo.'
                )
                return redirect('inventory:photo_import_step2')
            if factor == 0:
                if unit_conflict:
                    messages.error(
                        request,
                        f'Řádek {idx + 1} „{item["item_name"]}": doklad je '
                        f'v jednotce {item["unit_mapped"]}, sklad vede '
                        f'{ingredient.name} v {ingredient.base_unit}. Doplňte přepočet.'
                    )
                else:
                    messages.error(
                        request,
                        f'Řádek {idx + 1} „{item["item_name"]}": přepočet jednotek '
                        f'musí být kladné číslo.'
                    )
                return redirect('inventory:photo_import_step2')

            # Cena jde upravit na kroku 2 – doklad bez vytištěné ceny (např.
            # rozvozový list řidiče místo dodacího listu) ji OCR předvyplní
            # nulou, jinak by nešla doplnit vůbec.
            price_net_per_unit = _decimal_from_post(
                request.POST.get(f'price_{idx}'), item['price_per_unit_net']
            )
            if price_net_per_unit < 0:
                messages.error(
                    request,
                    f'Řádek {idx + 1} „{item["item_name"]}": cena nesmí být záporná.'
                )
                return redirect('inventory:photo_import_step2')

            # Cena s DPH se dopočítá ze (případně upravené) ceny bez DPH, ne
            # ze samostatně přečteného pole – jinak by po úpravě ceny přestaly
            # sedět k sobě.
            vat_multiplier = Decimal('1') + (Decimal(item['vat_rate']) / Decimal('100'))
            price_gross_per_unit = (price_net_per_unit * vat_multiplier).quantize(Decimal('0.01'))

            source_quantity = _decimal_from_post(
                request.POST.get(f'quantity_{idx}'), item['quantity']
            )
            quantity, unit_price_net = convert_line(
                source_quantity, price_net_per_unit, factor,
            )
            _quantity_gross, unit_price_gross = convert_line(
                Decimal('1'), price_gross_per_unit, factor,
            )

            planned.append({
                'index': idx,
                'item': item,
                'ingredient': ingredient,
                'warehouse': warehouse,
                'quantity': quantity,
                'source_quantity': source_quantity,
                'unit_factor': factor,
                'unit_resolved': unit_conflict,
                'price_net': unit_price_net,
                'price_gross': unit_price_gross,
            })
    except Exception as exc:
        radek = '?' if idx is None else str(idx + 1)
        logger.exception(
            'Ověření řádků příjemky z fotky selhalo (doklad %s, řádek %s)',
            receipt_data.get('receipt_number'), radek,
        )
        messages.error(
            request,
            f'Řádek {radek} se nepodařilo zpracovat ({exc}). Zkuste doklad '
            f'nahrát znovu; pokud to nepomůže, nahlaste to i s tímhle popisem.'
        )
        return redirect('inventory:photo_import_step2')

    if not planned:
        messages.error(request, 'Není co naskladnit – všechny řádky jsou odškrtnuté.')
        return redirect('inventory:photo_import_step2')

    # Od téhle chvíle se jen zapisuje a nic nemůže poslat uživatele zpátky
    # přes `return redirect(...)` – `transaction.atomic` totiž reaguje jen na
    # neodchycenou výjimku, ne na to, co view vrátí. Neočekávaná chyba (např.
    # nesmyslná cena z OCR, na kterou tu nikdo nenarazil dřív) by tak spadla
    # do holé 500 bez stopy, co přesně a u kterého řádku selhalo. Radši se
    # transakce zruší ručně a uživatel i log dostanou konkrétní důvod.
    try:
        created_ingredients_count = 0
        for idx, name in new_ingredient_names:
            row = next(row for row in planned if row['index'] == idx)
            ingredient, created = Ingredient.objects.get_or_create(
                name=name,
                defaults={
                    'unit': row['item']['unit_mapped'],
                    'base_unit': row['item']['unit_mapped'],
                },
            )
            row['ingredient'] = ingredient
            created_ingredients_count += int(created)

        goods_receipt = GoodsReceipt.objects.create(
            warehouse=default_warehouse,
            receipt_number=request.POST.get('receipt_number') or receipt_data['receipt_number'],
            receipt_date=request.POST.get('receipt_date') or receipt_data['receipt_date'],
            supplier=receipt_data['supplier'],
            supplier_obj=supplier_obj,
            status=GoodsReceipt.Status.DRAFT,
            created_by=request.user,
            notes='Načteno z fotky dokladu',
        )

        mappings = []
        for row in planned:
            item = row['item']
            GoodsReceiptItem.objects.create(
                goods_receipt=goods_receipt,
                ingredient=row['ingredient'],
                warehouse=row['warehouse'],
                quantity=row['quantity'],
                price_without_vat=row['price_net'],
                vat_rate=Decimal(item['vat_rate']),
                vat_amount=row['price_gross'] - row['price_net'],
                price=row['price_gross'],
                notes=f"Z dokladu: {item['item_name']}"[:100],
                source_name=item['item_name'][:255],
                source_unit=item['unit_mapped'],
                source_quantity=row['source_quantity'],
                unit_factor=row['unit_factor'],
                # Bez tohohle by se položka po založení tvářila dál jako
                # konfliktní (viz `has_unit_conflict`) – přepočet 1 je i
                # platná odpověď, jen se od výchozí hodnoty nedá rozeznat
                # bez příznaku.
                unit_resolved=row['unit_resolved'],
            )
            mappings.append((item, row['ingredient'], row['unit_factor'], row['unit_resolved']))

        _remember_photo_mapping(supplier_obj, mappings, skipped, request.user)

        scan_id = request.session.get('photo_scan_id')
        if scan_id:
            GoodsReceiptScan.objects.filter(id=scan_id).update(goods_receipt=goods_receipt)
    except Exception as exc:
        # Transakci je potřeba zrušit ručně – zůstáváme uvnitř view, kterou
        # `@transaction.atomic` obaluje, takže na obyčejný `except` nereaguje.
        transaction.set_rollback(True)
        logger.exception(
            'Vytvoření příjemky z fotky selhalo (doklad %s, sklad %s)',
            receipt_data.get('receipt_number'), default_warehouse_id,
        )
        messages.error(
            request,
            f'Příjemku se nepodařilo založit ({exc}). Zkuste to znovu; '
            f'pokud to nepomůže, nahlaste to i s tímhle popisem.'
        )
        return redirect('inventory:photo_import_step2')

    for key in ('photo_receipt_data', 'photo_default_warehouse', 'photo_scan_id'):
        request.session.pop(key, None)

    messages.success(
        request,
        f'Příjemka vytvořena: {len(mappings)} položek'
        + (f', {created_ingredients_count} nových surovin' if created_ingredients_count else '')
        + (f', {len(skipped)} řádků přeskočeno' if skipped else '')
        + '.'
    )
    return redirect('inventory:goods_receipt_detail', pk=goods_receipt.pk)


def _decimal_from_post(value, fallback):
    """Načte množství z formuláře; při nesmyslné hodnotě vezme to z dokladu."""
    try:
        return Decimal(str(value).replace(',', '.'))
    except (InvalidOperation, ValueError, TypeError, AttributeError):
        return Decimal(str(fallback))


def _remember_photo_mapping(supplier, mappings, skipped, user):
    """
    Uloží rozhodnutí uživatele – jak namapoval položky i které řádky odmítl.

    Odmítnuté řádky se ukládají jako nezbožní aliasy, takže se doučí obalový
    materiál a služby, které obecné pravidlo v `ocr.quirks` schválně nechytá.
    """
    if supplier is None:
        return 0

    resolver = IngredientResolver(supplier=supplier, ingredients=[])
    remembered = 0

    for item, ingredient, unit_factor, unit_resolved in mappings:
        if resolver.remember(item['item_name'], ingredient=ingredient,
                             unit=item.get('unit_mapped') or item.get('unit', ''),
                             unit_factor=unit_factor, user=user,
                             # `False` by mohlo degradovat dřív potvrzený
                             # alias na nerozhodnutý (viz `remember()`) – tam,
                             # kde tenhle import o jednotkách nic neřeší, se
                             # radši nevyjadřujeme vůbec.
                             unit_resolved=True if unit_resolved else None):
            remembered += 1

    for item in skipped:
        if resolver.remember(item['item_name'], is_ignored=True,
                             unit=item.get('unit', ''), user=user):
            remembered += 1

    return remembered


@login_required
def photo_import_scan(request, pk):
    """
    Vrátí naskenovaný doklad k náhledu.

    Skeny jdou přes view, ne přes MEDIA_URL – jsou to dodavatelské doklady
    s cenami, takže se nemají válet na veřejné adrese. Vidí je ten, kdo je
    nahrál, a kdo má přístup k jídelně příslušné příjemky.
    """
    from django.http import FileResponse, Http404
    from django.core.files.storage import default_storage

    scan = get_object_or_404(GoodsReceiptScan, pk=pk)

    allowed = request.user.is_superuser or scan.uploaded_by_id == request.user.id
    if not allowed and scan.goods_receipt_id:
        allowed = user_can_access_canteen(
            request.user, scan.goods_receipt.warehouse.canteen
        )
    if not allowed:
        raise Http404

    if not scan.has_file or not default_storage.exists(scan.file_path):
        raise Http404

    # PDF se nesmí poslat jako obrázek – prohlížeč by ho nezobrazil.
    content_type = SCAN_CONTENT_TYPES.get(
        Path(scan.file_path).suffix.lower(), 'application/octet-stream',
    )
    return FileResponse(default_storage.open(scan.file_path), content_type=content_type)


@login_required
def goods_receipt_resolve_units(request, pk):
    """
    Doplnění přepočtu u položek, kde se jednotka z dokladu neshoduje
    se skladovou jednotkou suroviny.

    Sem vede cesta z potvrzení příjemky, které takové položky odmítne.
    Zadaný poměr se uloží k položce a zároveň do aliasu dodavatele, takže
    se na totéž zboží podruhé neptáme.
    """
    goods_receipt = get_object_or_404(
        GoodsReceipt.objects.select_related('warehouse__canteen', 'supplier_obj'), pk=pk,
    )

    if not user_can_access_canteen(request.user, goods_receipt.warehouse.canteen):
        messages.error(request, 'Nemáte oprávnění k této akci.')
        return redirect('inventory:goods_receipt_list')

    if goods_receipt.status != GoodsReceipt.Status.DRAFT:
        messages.warning(request, 'Potvrzenou příjemku už upravovat nelze.')
        return redirect('inventory:goods_receipt_detail', pk=pk)

    conflicts = [
        item for item in goods_receipt.items.select_related('ingredient', 'warehouse')
        if item.has_unit_conflict
    ]

    if not conflicts:
        messages.success(request, 'Všechny položky mají srovnané měrné jednotky.')
        return redirect('inventory:goods_receipt_detail', pk=pk)

    if request.method == 'POST':
        resolver = (
            IngredientResolver(supplier=goods_receipt.supplier_obj, ingredients=[])
            if goods_receipt.supplier_obj else None
        )

        # Nejdřív se ověří všechny zadané poměry a teprve pak se zapisuje.
        # `return` uvnitř `transaction.atomic()` transakci potvrdí, ne zruší,
        # takže při opačném pořadí by se změny u dřívějších položek uložily
        # a příjemka by zůstala v půli přepočtená.
        factors = {}
        for item in conflicts:
            raw = request.POST.get(f'factor_{item.pk}', '').strip().replace(',', '.')
            try:
                factor = Decimal(raw)
            except (InvalidOperation, ValueError):
                messages.error(
                    request,
                    f'„{item.ingredient.name}": zadejte přepočet jako číslo.'
                )
                return redirect('inventory:goods_receipt_resolve_units', pk=pk)

            if factor <= 0:
                messages.error(
                    request,
                    f'„{item.ingredient.name}": přepočet jednotek musí být '
                    f'kladné číslo.'
                )
                return redirect('inventory:goods_receipt_resolve_units', pk=pk)

            factors[item.pk] = factor

        with transaction.atomic():
            for item in conflicts:
                factor = factors[item.pk]
                item.apply_unit_factor(factor)

                # Ať se na totéž zboží podruhé neptáme.
                if resolver and item.source_name:
                    resolver.remember(
                        item.source_name, ingredient=item.ingredient,
                        unit=item.source_unit, unit_factor=factor,
                        user=request.user, unit_resolved=True,
                    )

        # Hlásit úspěch podle počtu zpracovaných řádků je slib naslepo –
        # rozhoduje stav po zápisu, ne kolik položek do smyčky vlezlo.
        zbyva = goods_receipt.unit_conflicts
        if zbyva:
            messages.warning(
                request,
                f'Měrné jednotky srovnány u {len(conflicts) - len(zbyva)} '
                f'z {len(conflicts)} položek. Potvrdit zatím nejde: '
                + '; '.join(item.unit_conflict_label for item in zbyva) + '.'
            )
            return redirect('inventory:goods_receipt_resolve_units', pk=pk)

        messages.success(
            request,
            f'Měrné jednotky srovnány u {len(conflicts)} položek. '
            f'Příjemku teď jde potvrdit.'
        )
        return redirect('inventory:goods_receipt_detail', pk=pk)

    return render(request, 'inventory/goods_receipt_resolve_units.html', {
        'goods_receipt': goods_receipt,
        'conflicts': conflicts,
    })
