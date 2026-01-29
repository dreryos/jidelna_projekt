"""
Jednoduché view pro generování reportu pro objednávky.
- `order_report` zobrazí formulář pro výběr jídelny a období.
- Po odeslání bude v budoucnu implementována agregace plánovaných výrobních příkazů a porovnání s aktuálním stavem zásob.
"""

from django.shortcuts import render
from django import forms
from django.http import HttpResponse
from django.urls import reverse
from django.utils import timezone
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.core.exceptions import ObjectDoesNotExist
from decimal import Decimal

from apps.canteens.models import Canteen
from apps.production.models import ProductionOrder
from apps.core.models import Ingredient
from apps.inventory.models import StockItem

import io

try:
    import openpyxl
except Exception:
    openpyxl = None


class ReportForm(forms.Form):
    canteen = forms.ModelChoiceField(queryset=Canteen.objects.all())
    date_from = forms.DateField(widget=forms.DateInput(attrs={'type': 'date'}))
    date_to = forms.DateField(widget=forms.DateInput(attrs={'type': 'date'}))


@login_required
def order_report(request):
    user = request.user
    
    # Filtruj canteens na managed_canteens
    if user.is_superuser:
        canteen_queryset = Canteen.objects.all()
    else:
        try:
            user_canteens = user.profile.canteens.all()
            canteen_queryset = user_canteens
        except ObjectDoesNotExist:
            canteen_queryset = Canteen.objects.none()
    
    if request.method == 'POST':
        form = ReportForm(request.POST)
        form.fields['canteen'].queryset = canteen_queryset
        if form.is_valid():
            canteen = form.cleaned_data['canteen']
            
            # Kontrola přístupu
            if not user.is_superuser and canteen not in user_canteens:
                return HttpResponse('Access denied', status=403)
            
            date_from = form.cleaned_data['date_from']
            date_to = form.cleaned_data['date_to']
            report = generate_order_report(canteen, date_from, date_to)
            # links for exports (point to export endpoint)
            report['excel_url'] = reverse('reports:order_report_export') + f"?download=excel&canteen={canteen.pk}&from={date_from}&to={date_to}"
            report['pdf_url'] = reverse('reports:order_report_export') + f"?download=pdf&canteen={canteen.pk}&from={date_from}&to={date_to}"
            return render(request, 'reports/report_result.html', {'report': report})
    else:
        form = ReportForm()
        form.fields['canteen'].queryset = canteen_queryset
    
    return render(request, 'reports/report_form.html', {'form': form})


def generate_order_report(canteen, date_from, date_to):
    """Aggreguje potřebu surovin z plánovaných výrobních příkazů a porovná s aktuálními zásobami.

    Vrací dict s položkami: ingredient, unit, needed, stock, to_order
    
    Nová logika:
    - Používá ProductionOrderPortionVariant s koeficienty místo portions_adult/portions_child
    - Počítá pomocí RecipeIngredient.get_quantity_in_base_unit()
    """
    # Najdeme výrobní příkazy pro jídelnu v daném období
    # Filtrujeme podle jídelny - buď přímo nebo přes menu_plan
    orders = ProductionOrder.objects.filter(
        date__gte=date_from,
        date__lte=date_to
    ).filter(
        Q(canteen=canteen) | Q(menu_plan__canteen=canteen)
    ).select_related(
        'recipe',
        'menu_plan'
    ).prefetch_related(
        'portion_variants',
        'recipe__recipeingredient_set__ingredient'
    )

    needs = {}

    for order in orders:
        # Pro každý recept vezmeme normy
        for recipe_ingredient in order.recipe.recipeingredient_set.all():
            ing_id = recipe_ingredient.ingredient_id
            
            # Vypočítáme celkové množství ze všech variant porcí
            total_quantity = Decimal('0')
            for variant in order.portion_variants.all():
                quantity = recipe_ingredient.get_quantity_in_base_unit(
                    portions=variant.portions,
                    coefficient=variant.coefficient
                )
                total_quantity += quantity
            
            # Inicializujeme nebo aktualizujeme potřebu suroviny
            if ing_id not in needs:
                needs[ing_id] = {
                    'ingredient': recipe_ingredient.ingredient,
                    'unit': recipe_ingredient.ingredient.base_unit,
                    'needed': Decimal('0')
                }
            needs[ing_id]['needed'] += total_quantity

    # Porovnáme s aktuálním stavem ve skladech jídelny
    for data in needs.values():
        ing = data['ingredient']
        # Sečteme zásoby ze všech skladů jídelny
        stock_qs = StockItem.objects.filter(ingredient=ing, warehouse__canteen=canteen)
        total_stock = sum(s.quantity for s in stock_qs)
        data['stock'] = float(total_stock)
        data['needed'] = float(data['needed'])
        data['to_order'] = max(0, round(data['needed'] - data['stock'], 3))

    items = sorted(needs.values(), key=lambda x: x['ingredient'].name)

    # Count items with sufficient stock and items that need ordering
    sufficient_stock_count = sum(1 for item in items if item['stock'] >= item['needed'])
    to_order_count = sum(1 for item in items if item['to_order'] > 0)

    return {
        'canteen': canteen,
        'date_from': date_from,
        'date_to': date_to,
        'items': items,
        'sufficient_stock_count': sufficient_stock_count,
        'to_order_count': to_order_count,
    }


@login_required
def order_report_export(request):
    """Endpoint, který exportuje report jako Excel nebo PDF podle query parametru `download`."""
    user = request.user
    if user.is_superuser:
        canteen_queryset = Canteen.objects.all()
    else:
        try:
            canteen_queryset = user.profile.canteens.all()
        except ObjectDoesNotExist:
            return HttpResponse('Access denied', status=403)

    form = ReportForm(request.GET)
    form.fields['canteen'].queryset = canteen_queryset
    if not form.is_valid():
        return HttpResponse('Invalid parameters', status=400)

    canteen = form.cleaned_data['canteen']
    date_from = form.cleaned_data['date_from']
    date_to = form.cleaned_data['date_to']

    download = request.GET.get('download')

    report = generate_order_report(canteen, date_from, date_to)
    
    # Add metadata for PDF report
    report['generated_at'] = timezone.now()
    report['generated_by'] = request.user

    if download == 'excel':
        return generate_excel_response(report)
    elif download == 'pdf':
        return generate_pdf_response(report)
    else:
        return HttpResponse('Invalid download type', status=400)


def generate_excel_response(report):
    if openpyxl is None:
        return HttpResponse('openpyxl not installed', status=500)

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = 'Order report'

    ws.append(['Surovina', 'Jednotka', 'Potřeba', 'Sklad', 'K objednání', 'Poznámky'])
    for it in report['items']:
        ws.append([it['ingredient'].name, it['unit'], it['needed'], it['stock'], it['to_order'], ''])

    stream = io.BytesIO()
    wb.save(stream)
    stream.seek(0)

    resp = HttpResponse(stream.read(), content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    filename = f"order_report_{report['canteen'].name}_{report['date_from']}_{report['date_to']}.xlsx"
    resp['Content-Disposition'] = f'attachment; filename="{filename}"'
    return resp


def generate_pdf_response(report):
    """Generuje PDF report pomocí WeasyPrint s HTML templatem (konzistentní s ostatními PDF)."""
    from django.template.loader import render_to_string
    
    try:
        from weasyprint import HTML
    except ImportError:
        return HttpResponse('WeasyPrint není nainstalován. PDF export není dostupný.', status=500)
    except OSError as e:
        if "libgobject" in str(e) or "cannot load library" in str(e):
            return HttpResponse('Chyba: V systému chybí knihovny GTK3 potřebné pro generování PDF (WeasyPrint). Prosím nainstalujte GTK3 Runtime.', status=500)
        raise e
    
    # Připravíme kontext pro template
    context = {
        'report': report,
    }
    
    # Vyrenderujeme HTML
    html_string = render_to_string('reports/order_report_pdf.html', context)
    
    # Vygenerujeme PDF
    try:
        html = HTML(string=html_string)
        response = HttpResponse(content_type='application/pdf')
        
        filename = f"order_report_{report['canteen'].name}_{report['date_from']}_{report['date_to']}.pdf"
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        
        html.write_pdf(response)
        
        return response
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f'Error generating PDF for order report: {e}', exc_info=True)
        return HttpResponse(f'Chyba při generování PDF: {str(e)}', status=500)
