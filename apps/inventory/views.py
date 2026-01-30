from django.urls import reverse_lazy, reverse
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
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
from apps.core.views import CanteenAccessMixin, user_can_access_canteen
from decimal import Decimal, InvalidOperation
import logging
import json

from .models import (
    StockItem, GoodsReceipt, GoodsReceiptItem, 
    InventoryVerification, InventoryVerificationItem,
    StockTransfer, StockTransferItem,
    Supplier, SupplierIngredientTemplate,
    StockWriteOff, StockWriteOffItem
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
        form = GoodsReceiptForm(request.POST)
        formset = GoodsReceiptItemFormSet(request.POST)
        
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
        form = GoodsReceiptForm()
        formset = GoodsReceiptItemFormSet()
    
    # Načtení aktivních dodavatelů pro rychlé šablony
    active_suppliers = Supplier.objects.filter(is_active=True).order_by('name')
    
    context = {
        'form': form,
        'formset': formset,
        'active_suppliers': active_suppliers,
    }
    
    return render(request, 'inventory/goods_receipt_form.html', context)


@login_required
def goods_receipt_confirm(request, pk):
    """Potvrzení příjmu zboží - aktualizuje sklady a ceny"""
    goods_receipt = get_object_or_404(GoodsReceipt, pk=pk)
    
    if goods_receipt.status != GoodsReceipt.Status.DRAFT:
        messages.warning(request, 'Tento příjem již byl potvrzen.')
        return redirect('inventory:goods_receipt_detail', pk=pk)
    
    if request.method == 'POST':
        try:
            goods_receipt.confirm()
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
from difflib import SequenceMatcher


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
    return render(request, 'inventory/bidfood_import_step1.html', {
        'warehouses': warehouses
    })


@login_required
def bidfood_xml_import_step2(request):
    """Krok 2: Preview, mapování surovin, editace jednotek a skladů"""
    receipt_data = request.session.get('bidfood_receipt_data')
    if not receipt_data:
        messages.error(request, 'Session vypršela. Začněte znovu.')
        return redirect('inventory:bidfood_import_step1')
    
    default_warehouse_id = int(request.session.get('bidfood_default_warehouse'))
    warehouses = Warehouse.objects.all()
    all_ingredients = list(Ingredient.objects.all())
    
    # Automatické mapování surovin pomocí fuzzy matching
    for item in receipt_data['items']:
        best_match = None
        best_ratio = 0
        
        for ingredient in all_ingredients:
            # Porovnání názvu z XML s názvem suroviny
            ratio = SequenceMatcher(
                None,
                item['item_name'].lower().strip(),
                ingredient.name.lower().strip()
            ).ratio()
            
            if ratio > best_ratio:
                best_ratio = ratio
                best_match = ingredient
        
        # Pokud je shoda > 60%, navrhne me surovinu
        if best_ratio > 0.6:
            item['suggested_ingredient_id'] = best_match.id
            item['suggested_ingredient_name'] = best_match.name
            item['suggested_ingredient_unit'] = best_match.unit
            item['match_ratio'] = round(best_ratio * 100)
        else:
            item['suggested_ingredient_id'] = None
            item['suggested_ingredient_name'] = None
            item['suggested_ingredient_unit'] = None
            item['match_ratio'] = 0
    
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
        
        # Vytvoření položky příjmu s DPH
        GoodsReceiptItem.objects.create(
            goods_receipt=goods_receipt,
            ingredient=ingredient,
            warehouse=warehouse,
            quantity=quantity,
            price_without_vat=Decimal(item['price_per_unit_net']),
            vat_rate=vat_rate,
            vat_amount=Decimal(item['vat_amount']),
            price=Decimal(item['price_per_unit_gross']),
            notes=f"Kód: {item['item_id']}"
        )
    
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

class IsStaffMixin(UserPassesTestMixin):
    """Mixin pro kontrolu, zda je uživatel staff."""
    def test_func(self):
        return self.request.user.is_staff


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


class InventoryVerificationCreateView(IsStaffMixin, CreateView):
    """Vytvoření nové inventury."""
    model = InventoryVerification
    form_class = InventoryVerificationForm
    template_name = 'inventory/inventory_verification_form.html'
    
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
    
    # Kontrola oprávnění
    if not request.user.is_staff:
        messages.error(request, 'Nemáte oprávnění k této akci.')
        return redirect('inventory:inventory_verification_detail', pk=pk)
    
    # Kontrola stavu
    if verification.status != InventoryVerification.Status.IN_PROGRESS:
        messages.error(request, 'Inventura není v probíhajícím stavu.')
        return redirect('inventory:inventory_verification_detail', pk=pk)
    
    if request.method == 'POST':
        formset = InventoryVerificationItemFormSet(request.POST, instance=verification)
        
        if formset.is_valid():
            formset.save()
            messages.success(request, 'Spočítaná množství byla uložena.')
            return redirect('inventory:inventory_verification_detail', pk=pk)
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
    
    # Kontrola oprávnění
    if not request.user.is_staff:
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
        except ValidationError as e:
            messages.error(request, str(e))
        
        return redirect('inventory:inventory_verification_count', pk=pk)
    
    # GET - zobrazíme potvrzovací stránku
    context = {
        'verification': verification,
    }
    return render(request, 'inventory/inventory_verification_start_confirm.html', context)


@login_required
def inventory_verification_complete(request, pk):
    """Dokončení inventury - aktualizuje stavy a odemkne sklad."""
    verification = get_object_or_404(InventoryVerification, pk=pk)
    
    # Kontrola oprávnění
    if not request.user.is_staff:
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
def inventory_verification_cancel(request, pk):
    """Zrušení probíhající inventury - odemkne sklad bez aktualizace."""
    verification = get_object_or_404(InventoryVerification, pk=pk)
    
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
    
    # Kontrola oprávnění
    if not request.user.is_staff:
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
        
        html = HTML(string=html_string, base_url=request.build_absolute_uri())
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

class IsStaffMixin(UserPassesTestMixin):
    """Mixin pro kontrolu, zda je uživatel staff."""
    def test_func(self):
        return self.request.user.is_staff


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


class StockTransferCreateView(IsStaffMixin, CreateView):
    """Vytvoření nové převodky."""
    model = StockTransfer
    form_class = StockTransferForm
    template_name = 'inventory/stock_transfer_form.html'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        if self.request.POST:
            context['formset'] = StockTransferItemFormSet(self.request.POST)
        else:
            context['formset'] = StockTransferItemFormSet()
        return context
    
    def form_valid(self, form):
        context = self.get_context_data()
        formset = context['formset']
        
        with transaction.atomic():
            # Nastavíme created_by
            form.instance.created_by = self.request.user
            self.object = form.save()
            
            if formset.is_valid():
                formset.instance = self.object
                
                # Pro každou položku nastavíme cenu ze zdrojového skladu
                for item_form in formset:
                    if item_form.cleaned_data and not item_form.cleaned_data.get('DELETE', False):
                        ingredient = item_form.cleaned_data.get('ingredient')
                        if ingredient:
                            try:
                                stock_item = StockItem.objects.get(
                                    ingredient=ingredient,
                                    warehouse=self.object.warehouse_from
                                )
                                item_form.instance.unit_price_with_vat = stock_item.price
                            except StockItem.DoesNotExist:
                                pass
                
                formset.save()
                messages.success(self.request, f'Převodka {self.object.transfer_number} byla vytvořena.')
                return redirect('inventory:stock_transfer_detail', pk=self.object.pk)
            else:
                return self.form_invalid(form)
        
        return super().form_valid(form)
    
    def get_success_url(self):
        return reverse('inventory:stock_transfer_detail', kwargs={'pk': self.object.pk})


class StockTransferDetailView(LoginRequiredMixin, DetailView):
    """Detail převodky."""
    model = StockTransfer
    template_name = 'inventory/stock_transfer_detail.html'
    context_object_name = 'transfer'
    
    def get_queryset(self):
        return StockTransfer.objects.select_related(
            'warehouse_from', 'warehouse_to',
            'warehouse_from__canteen', 'warehouse_to__canteen',
            'created_by'
        ).prefetch_related('items__ingredient')


@login_required
@require_POST
def stock_transfer_start(request, pk):
    """Zahájit převod - přesun do meziskladu."""
    transfer = get_object_or_404(StockTransfer, pk=pk)
    
    if not request.user.is_staff:
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
    
    if not request.user.is_staff:
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
    
    if not request.user.is_staff:
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
    
    if not request.user.is_staff:
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
    
    # Kontrola oprávnění
    if not request.user.is_staff:
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
        from weasyprint import HTML
        
        html = HTML(string=html_string, base_url=request.build_absolute_uri())
        response = HttpResponse(content_type='application/pdf')
        
        filename = f'prevodka_{transfer.transfer_number}.pdf'
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        
        html.write_pdf(response)
        
        return response
    except ImportError:
        messages.error(request, 'WeasyPrint není nainstalován. PDF export není dostupný.')
        return redirect('inventory:stock_transfer_detail', pk=pk)
    except Exception as e:
        logger.error(f'Error generating PDF for transfer {pk}: {e}', exc_info=True)
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
        formset = StockWriteOffItemFormSet(request.POST)
        
        # Debug: Zobrazit počet formulářů
        form_is_valid = form.is_valid()
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

