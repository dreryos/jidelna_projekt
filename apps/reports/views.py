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
            needed = (ri.quantity_adult * order.portions_adult) + (ri.quantity_child * order.portions_child)
            needs.setdefault(ing_id, {'ingredient': ri.ingredient, 'unit': ri.ingredient.unit, 'needed': 0})
            needs[ing_id]['needed'] += float(needed)

    # Porovnáme s aktuálním stavem ve skladech jídelny
    for data in needs.values():
        ing = data['ingredient']
        # simple sum across all warehouses of the canteen
        stock_qs = StockItem.objects.filter(ingredient=ing, warehouse__canteen=canteen)
        total_stock = sum(float(s.quantity) for s in stock_qs)
        data['stock'] = total_stock
        data['to_order'] = max(0, round(data['needed'] - total_stock, 3))

    items = sorted(needs.values(), key=lambda x: x['ingredient'].name)

    return {
        'canteen': canteen,
        'date_from': date_from,
        'date_to': date_to,
        'items': items,
    }


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
