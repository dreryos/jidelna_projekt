from django.urls import reverse_lazy, reverse
from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import ListView, CreateView, UpdateView, DeleteView, DetailView
from django.contrib import messages
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.db import transaction
from decimal import Decimal, InvalidOperation

from .models import StockItem, GoodsReceipt, GoodsReceiptItem
from .forms import GoodsReceiptForm, GoodsReceiptItemFormSet
from apps.canteens.models import Warehouse, Canteen
from apps.core.models import Ingredient


class StockListView(LoginRequiredMixin, ListView):
    model = StockItem
    template_name = 'inventory/stock_list.html'
    context_object_name = 'stock_items'
    
    def get_queryset(self):
        queryset = StockItem.objects.select_related('ingredient', 'warehouse', 'warehouse__canteen').all()
        
        # Filtrování podle skladu/skladů
        warehouse_ids = self.request.GET.getlist('warehouse')
        if warehouse_ids:
            queryset = queryset.filter(warehouse_id__in=warehouse_ids)
        
        # Řazení podle názvu suroviny
        queryset = queryset.order_by('ingredient__name')
        
        return queryset
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['warehouses'] = Warehouse.objects.select_related('canteen').all()
        context['selected_warehouses'] = self.request.GET.getlist('warehouse')
        
        # Přidáme statistiky
        stock_items = context['stock_items']
        context['stats'] = {
            'available_count': sum(1 for item in stock_items if item.quantity_available > 0),
            'blocked_count': sum(1 for item in stock_items if item.quantity_blocked > 0),
            'low_stock_count': sum(1 for item in stock_items if item.quantity_available <= 10),
        }
        
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

class WarehouseListView(LoginRequiredMixin, ListView):
    model = Warehouse
    template_name = 'inventory/warehouse_list.html'
    context_object_name = 'warehouses'
    
    def get_queryset(self):
        return Warehouse.objects.select_related('canteen').order_by('canteen__name', 'name')


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


# CRUD pro příjem zboží (GoodsReceipt)

class GoodsReceiptListView(LoginRequiredMixin, ListView):
    model = GoodsReceipt
    template_name = 'inventory/goods_receipt_list.html'
    context_object_name = 'goods_receipts'
    paginate_by = 20
    
    def get_queryset(self):
        queryset = GoodsReceipt.objects.select_related('warehouse', 'warehouse__canteen', 'created_by').all()
        
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
        context['warehouses'] = Warehouse.objects.select_related('canteen').all()
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
        
        if form.is_valid() and formset.is_valid():
            try:
                with transaction.atomic():
                    # Uložit hlavní příjem
                    goods_receipt = form.save(commit=False)
                    # Nastavit warehouse z default_warehouse
                    goods_receipt.warehouse = form.cleaned_data['default_warehouse']
                    goods_receipt.created_by = request.user
                    goods_receipt.save()
                    
                    # Uložit položky
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
    
    context = {
        'form': form,
        'formset': formset,
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
            # Vytvoření nové suroviny
            ingredient = Ingredient.objects.create(
                name=item['item_name'],
                unit=unit,
                code=item['item_id'],
                allergens=''
            )
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

