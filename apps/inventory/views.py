from django.urls import reverse_lazy, reverse
from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import ListView, CreateView, UpdateView, DeleteView, DetailView
from django.contrib import messages
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import JsonResponse
import csv
import io
from decimal import Decimal

from .models import StockItem, GoodsReceipt, GoodsReceiptItem
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


class StockCreateView(LoginRequiredMixin, CreateView):
    model = StockItem
    fields = ['ingredient', 'warehouse', 'quantity', 'price']
    template_name = 'inventory/stock_form.html'
    success_url = reverse_lazy('inventory:stock_list')
    
    def form_valid(self, form):
        messages.success(self.request, f'Skladová položka "{form.instance.ingredient.name}" byla úspěšně přidána.')
        return super().form_valid(form)


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


# Import CSV

def normalize_unit(unit_str):
    """Normalizuje jednotku z CSV na jednotný formát"""
    unit_str = unit_str.strip().lower()
    
    # Mapování běžných variant na standardní jednotky
    unit_mapping = {
        'ks': 'ks',
        'kus': 'ks',
        'kusy': 'ks',
        'kg': 'kg',
        'kilogram': 'kg',
        'l': 'l',
        'litr': 'l',
        'litry': 'l',
        'l (ks)': 'l',
        'bal': 'bal',
        'balení': 'bal',
        'bal (1kg)': 'bal',
        'plato': 'plato',
        'plato (30ks)': 'plato',
        'bedna': 'bedna',
        'bedna (15kg)': 'bedna',
    }
    
    return unit_mapping.get(unit_str, unit_str)


def parse_csv_file(file_content):
    """Parsuje CSV soubor a vrací seznam řádků"""
    reader = csv.DictReader(io.StringIO(file_content))
    rows = []
    
    for row in reader:
        try:
            # Parsování ceny (může obsahovat čárku nebo tečku)
            price_str = row.get('Cena za MJ (Kč)', '0').replace(',', '.').replace(' ', '')
            
            parsed_row = {
                'code': row.get('Kód položky', '').strip(),
                'name': row.get('Název položky', '').strip(),
                'batch': row.get('Šarže / Expirace', '').strip(),
                'quantity': float(row.get('Množství (MJ)', '0').replace(',', '.')),
                'unit': normalize_unit(row.get('Jednotka', '')),
                'price': float(price_str),
                'total': float(row.get('Celkem (Kč)', '0').replace(',', '.')),
            }
            rows.append(parsed_row)
        except (ValueError, KeyError) as e:
            # Přeskočíme chybné řádky
            continue
    
    return rows


@login_required
def import_csv_step1(request):
    """Krok 1: Nahrání CSV souboru a preview"""
    if request.method == 'POST':
        csv_file = request.FILES.get('csv_file')
        warehouse_id = request.POST.get('warehouse')
        
        if not csv_file or not warehouse_id:
            messages.error(request, 'Musíte vybrat soubor CSV a sklad.')
            return redirect('inventory:import_csv_step1')
        
        try:
            warehouse = Warehouse.objects.get(pk=warehouse_id)
        except Warehouse.DoesNotExist:
            messages.error(request, 'Vybraný sklad neexistuje.')
            return redirect('inventory:import_csv_step1')
        
        # Čtení CSV
        try:
            file_content = csv_file.read().decode('utf-8')
        except UnicodeDecodeError:
            try:
                file_content = csv_file.read().decode('windows-1250')
            except:
                messages.error(request, 'Nepodařilo se načíst soubor. Zkontrolujte kódování.')
                return redirect('inventory:import_csv_step1')
        
        # Parsování
        rows = parse_csv_file(file_content)
        
        if not rows:
            messages.error(request, 'CSV soubor neobsahuje žádná data nebo má nesprávný formát.')
            return redirect('inventory:import_csv_step1')
        
        # Analýza surovin - zjistíme, které existují a které ne
        import_data = []
        for row in rows:
            # Hledáme surovinu podle názvu (case insensitive)
            matching_ingredients = Ingredient.objects.filter(name__iexact=row['name'])
            
            row_data = {
                'csv_data': row,
                'ingredient_exists': matching_ingredients.exists(),
                'matching_ingredient': matching_ingredients.first() if matching_ingredients.exists() else None,
                'suggested_ingredients': list(Ingredient.objects.filter(
                    name__icontains=row['name'].split()[0]
                )[:5]) if not matching_ingredients.exists() else []
            }
            import_data.append(row_data)
        
        # Uložíme data do session pro další krok
        request.session['import_data'] = {
            'warehouse_id': warehouse_id,
            'rows': rows,
        }
        
        context = {
            'warehouse': warehouse,
            'import_data': import_data,
            'total_rows': len(rows),
            'existing_count': sum(1 for d in import_data if d['ingredient_exists']),
            'new_count': sum(1 for d in import_data if not d['ingredient_exists']),
        }
        
        return render(request, 'inventory/import_csv_step2.html', context)
    
    # GET - zobrazíme formulář pro upload
    warehouses = Warehouse.objects.select_related('canteen').all()
    return render(request, 'inventory/import_csv_step1.html', {'warehouses': warehouses})


@login_required
def import_csv_step2_confirm(request):
    """Krok 2: Potvrzení a mapování surovin"""
    if request.method != 'POST':
        return redirect('inventory:import_csv_step1')
    
    import_data = request.session.get('import_data')
    if not import_data:
        messages.error(request, 'Import session vypršela. Začněte znovu.')
        return redirect('inventory:import_csv_step1')
    
    warehouse = Warehouse.objects.get(pk=import_data['warehouse_id'])
    rows = import_data['rows']
    
    # Zpracování mapování z formuláře
    imported_count = 0
    created_ingredients = 0
    errors = []
    
    with transaction.atomic():
        for idx, row in enumerate(rows):
            action = request.POST.get(f'action_{idx}')
            
            if action == 'skip':
                continue
            
            ingredient = None
            
            if action == 'create':
                # Vytvořit novou surovinu
                ingredient, created = Ingredient.objects.get_or_create(
                    name=row['name'],
                    defaults={'unit': row['unit']}
                )
                if created:
                    created_ingredients += 1
            
            elif action == 'map':
                # Mapovat na existující surovinu
                ingredient_id = request.POST.get(f'ingredient_{idx}')
                if ingredient_id:
                    try:
                        ingredient = Ingredient.objects.get(pk=ingredient_id)
                    except Ingredient.DoesNotExist:
                        errors.append(f"Surovina ID {ingredient_id} pro '{row['name']}' neexistuje")
                        continue
            
            elif action == 'use_existing':
                # Použít existující surovinu se stejným názvem
                ingredient = Ingredient.objects.filter(name__iexact=row['name']).first()
            
            if ingredient:
                # Vytvoření nebo aktualizace skladové položky
                stock_item, created = StockItem.objects.get_or_create(
                    ingredient=ingredient,
                    warehouse=warehouse,
                    defaults={
                        'quantity': Decimal(str(row['quantity'])),
                        'price': Decimal(str(row['price']))
                    }
                )
                
                if not created:
                    # Aktualizace existující položky - přičteme množství
                    stock_item.quantity += Decimal(str(row['quantity']))
                    stock_item.price = Decimal(str(row['price']))  # Aktualizujeme cenu
                    stock_item.save()
                
                imported_count += 1
    
    # Vyčištění session
    if 'import_data' in request.session:
        del request.session['import_data']
    
    messages.success(
        request,
        f'Import dokončen! Importováno: {imported_count} položek, '
        f'vytvořeno nových surovin: {created_ingredients}.'
    )
    
    if errors:
        for error in errors:
            messages.warning(request, error)
    
    return redirect('inventory:stock_list')


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
    """Vytvoření nového příjmu zboží"""
    if request.method == 'POST':
        # Základní údaje příjmu
        warehouse_id = request.POST.get('warehouse')
        receipt_number = request.POST.get('receipt_number')
        receipt_date = request.POST.get('receipt_date')
        supplier = request.POST.get('supplier', '')
        notes = request.POST.get('notes', '')
        
        if not warehouse_id or not receipt_number or not receipt_date:
            messages.error(request, 'Vyplňte povinná pole: Sklad, Číslo dokladu a Datum příjmu.')
            return redirect('inventory:goods_receipt_create')
        
        try:
            warehouse = Warehouse.objects.get(pk=warehouse_id)
        except Warehouse.DoesNotExist:
            messages.error(request, 'Vybraný sklad neexistuje.')
            return redirect('inventory:goods_receipt_create')
        
        # Zpracování položek příjmu
        items_data = []
        item_count = int(request.POST.get('item_count', 0))
        
        for i in range(item_count):
            ingredient_id = request.POST.get(f'item_{i}_ingredient')
            quantity = request.POST.get(f'item_{i}_quantity')
            price = request.POST.get(f'item_{i}_price')
            item_notes = request.POST.get(f'item_{i}_notes', '')
            
            if ingredient_id and quantity and price:
                try:
                    items_data.append({
                        'ingredient_id': int(ingredient_id),
                        'quantity': Decimal(quantity.replace(',', '.')),
                        'price': Decimal(price.replace(',', '.')),
                        'notes': item_notes
                    })
                except (ValueError, Decimal.InvalidOperation):
                    messages.error(request, f'Neplatná hodnota v položce {i+1}.')
                    return redirect('inventory:goods_receipt_create')
        
        if not items_data:
            messages.error(request, 'Přidejte alespoň jednu položku příjmu.')
            return redirect('inventory:goods_receipt_create')
        
        # Vytvoření příjmu a položek v transakci
        try:
            with transaction.atomic():
                goods_receipt = GoodsReceipt.objects.create(
                    warehouse=warehouse,
                    receipt_number=receipt_number,
                    receipt_date=receipt_date,
                    supplier=supplier,
                    notes=notes,
                    created_by=request.user
                )
                
                for item_data in items_data:
                    ingredient = Ingredient.objects.get(pk=item_data['ingredient_id'])
                    GoodsReceiptItem.objects.create(
                        goods_receipt=goods_receipt,
                        ingredient=ingredient,
                        quantity=item_data['quantity'],
                        price=item_data['price'],
                        notes=item_data['notes']
                    )
                
                messages.success(request, f'Příjem zboží "{receipt_number}" byl úspěšně vytvořen.')
                return redirect('inventory:goods_receipt_detail', pk=goods_receipt.pk)
        
        except Exception as e:
            messages.error(request, f'Chyba při vytváření příjmu: {str(e)}')
            return redirect('inventory:goods_receipt_create')
    
    # GET - zobrazíme formulář
    warehouses = Warehouse.objects.select_related('canteen').all()
    ingredients = Ingredient.objects.all().order_by('name')
    
    context = {
        'warehouses': warehouses,
        'ingredients': ingredients,
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
