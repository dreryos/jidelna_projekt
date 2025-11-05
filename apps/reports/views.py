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

from apps.canteens.models import Canteen
from apps.production.models import ProductionOrder
from apps.core.models import Ingredient
from apps.inventory.models import StockItem

import io

try:
    import openpyxl
except Exception:
    openpyxl = None

try:
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    import os
except Exception:
    SimpleDocTemplate = None
    Table = None


class ReportForm(forms.Form):
    canteen = forms.ModelChoiceField(queryset=Canteen.objects.all())
    date_from = forms.DateField(widget=forms.DateInput(attrs={'type': 'date'}))
    date_to = forms.DateField(widget=forms.DateInput(attrs={'type': 'date'}))


@login_required
def order_report(request):
    if request.method == 'POST':
        form = ReportForm(request.POST)
        if form.is_valid():
            canteen = form.cleaned_data['canteen']
            date_from = form.cleaned_data['date_from']
            date_to = form.cleaned_data['date_to']
            report = generate_order_report(canteen, date_from, date_to)
            # links for exports (point to download endpoint)
            report['excel_url'] = reverse('reports:order_report_download') + f"?download=excel&canteen={canteen.pk}&from={date_from}&to={date_to}"
            report['pdf_url'] = reverse('reports:order_report_download') + f"?download=pdf&canteen={canteen.pk}&from={date_from}&to={date_to}"
            return render(request, 'reports/report_result.html', {'report': report})
    else:
        form = ReportForm()
    return render(request, 'reports/report_form.html', {'form': form})


def generate_order_report(canteen, date_from, date_to):
    """Aggreguje potřebu surovin z plánovaných výrobních příkazů a porovná s aktuálními zásobami.

    Vrací dict s položkami: ingredient, unit, needed, stock, to_order
    """
    # Najdeme výrobní příkazy pro jídelnu v daném období
    orders = ProductionOrder.objects.filter(canteen=canteen, date__gte=date_from, date__lte=date_to)

    needs = {}

    for order in orders:
        # Pro každý recept vezmeme normy
        for ri in order.recipe.recipeingredient_set.all():
            ing_id = ri.ingredient_id
            
            # Vypočítáme celkové množství ze všech variant porcí
            total_quantity = 0
            variants = order.portion_variants.all()
            
            if variants.exists():
                # Pokud existují varianty, použijeme je
                for variant in variants:
                    quantity = ri.get_quantity_in_base_unit(
                        portions=variant.portions,
                        coefficient=float(variant.coefficient)
                    )
                    total_quantity += float(quantity)
            else:
                # Fallback - pokud neexistují varianty, použijeme staré pole portions_adult/child
                # s výchozím koeficientem
                total_portions = order.portions_adult + order.portions_child
                if total_portions > 0:
                    quantity = ri.get_quantity_in_base_unit(
                        portions=total_portions,
                        coefficient=float(order.portion_coefficient)
                    )
                    total_quantity = float(quantity)
            
            needs.setdefault(ing_id, {'ingredient': ri.ingredient, 'unit': ri.ingredient.base_unit, 'needed': 0})
            needs[ing_id]['needed'] += total_quantity

    # Porovnáme s aktuálním stavem ve skladech jídelny
    for data in needs.values():
        ing = data['ingredient']
        # simple sum across all warehouses of the canteen
        stock_qs = StockItem.objects.filter(ingredient=ing, warehouse__canteen=canteen)
        total_stock = sum(float(s.quantity) for s in stock_qs)
        
        # Zaokrouhlíme všechny hodnoty na 2 desetinná místa pro lepší čitelnost
        data['needed'] = round(data['needed'], 2)
        data['stock'] = round(total_stock, 2)
        data['to_order'] = max(0, round(data['needed'] - total_stock, 2))

    items = sorted(needs.values(), key=lambda x: x['ingredient'].name)

    # Spočítáme statistiky
    total_items = len(items)
    items_in_stock = sum(1 for item in items if item['stock'] >= item['needed'])
    items_to_order = sum(1 for item in items if item['to_order'] > 0)

    return {
        'canteen': canteen,
        'date_from': date_from,
        'date_to': date_to,
        'items': items,
        'total_items': total_items,
        'items_in_stock': items_in_stock,
        'items_to_order': items_to_order,
    }


@login_required
def order_report_download(request):
    """Endpoint, který stáhne report jako Excel nebo PDF podle query parametru `download`."""
    download = request.GET.get('download')
    canteen_id = request.GET.get('canteen')
    date_from = request.GET.get('from')
    date_to = request.GET.get('to')

    try:
        canteen = Canteen.objects.get(pk=canteen_id)
    except Exception:
        return HttpResponse('Invalid canteen', status=400)

    report = generate_order_report(canteen, date_from, date_to)

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

    ws.append(['Surovina', 'Jednotka', 'Potřeba', 'Sklad', 'K objednání'])
    for it in report['items']:
        ws.append([it['ingredient'].name, it['unit'], it['needed'], it['stock'], it['to_order']])

    stream = io.BytesIO()
    wb.save(stream)
    stream.seek(0)

    resp = HttpResponse(stream.read(), content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    filename = f"order_report_{report['canteen'].name}_{report['date_from']}_{report['date_to']}.xlsx"
    resp['Content-Disposition'] = f'attachment; filename="{filename}"'
    return resp


def generate_pdf_response(report):
    if SimpleDocTemplate is None:
        return HttpResponse('reportlab not installed', status=500)

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4)

    # Register a TTF font that supports Czech diacritics if available (DejaVu Sans)
    font_name = 'Helvetica'
    try:
        # prefer project-local font (static files)
        proj_local = os.path.join(os.path.dirname(__file__), 'static', 'fonts', 'DejaVuSans.ttf')
        possible_paths = [
            proj_local,
            '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
            '/usr/local/share/fonts/DejaVuSans.ttf',
            '/Library/Fonts/DejaVuSans.ttf',
            '/System/Library/Fonts/Arial Unicode.ttf',
        ]
        for p in possible_paths:
            if p and os.path.exists(p):
                pdfmetrics.registerFont(TTFont('DejaVuSans', p))
                font_name = 'DejaVuSans'
                break
    except Exception:
        # If registration fails, fallback to default
        font_name = 'Helvetica'

    styles = getSampleStyleSheet()
    # ensure styles use the registered font
    for s in styles.byName.values():
        try:
            s.fontName = font_name
        except Exception:
            pass

    elems = []

    title = Paragraph(f"Report objednávek - {report['canteen'].name}", styles['Heading2'])
    elems.extend([title, Spacer(1, 12)])

    data = [['Surovina', 'Jednotka', 'Potřeba', 'Sklad', 'K objednání']]
    data.extend([[it['ingredient'].name, it['unit'], str(it['needed']), str(it['stock']), str(it['to_order'])] for it in report['items']])

    table = Table(data, hAlign='LEFT')
    table.setStyle(TableStyle([
        ('FONT', (0, 0), (-1, -1), font_name),
        ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.black),
    ]))
    elems.append(table)

    doc.build(elems)
    pdf = buffer.getvalue()
    buffer.close()

    resp = HttpResponse(pdf, content_type='application/pdf')
    filename = f"order_report_{report['canteen'].name}_{report['date_from']}_{report['date_to']}.pdf"
    resp['Content-Disposition'] = f'attachment; filename="{filename}"'
    return resp
