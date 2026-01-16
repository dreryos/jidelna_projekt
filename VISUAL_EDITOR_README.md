# Vizuální Editor Šablon - Rychlý Start

## Co bylo implementováno

Kompletní vizuální editor pro úpravu šablon jídelníčků s drag-drop rozhraním jako náhrada za manuální editaci XML.

## Nové soubory

### Backend
- `apps/production/models.py` - přidány helper metody do `MenuTemplate`:
  - `parse_schedule_to_dict()` - konverze XML → Python dict
  - `update_schedule_from_dict()` - konverze Python dict → XML
  - `get_stats()` - živé statistiky šablony

- `apps/production/template_views.py` - 5 nových AJAX endpointů:
  - `template_add_meal_ajax()` - přidání jídla
  - `template_remove_meal_ajax()` - odstranění jídla
  - `template_reorder_ajax()` - přeuspořádání jídel
  - `template_copy_day_ajax()` - zkopírování celého dne
  - `template_clear_day_ajax()` - vymazání celého dne
  - `MenuTemplateVisualEditView` - view pro vizuální editor

- `apps/production/urls.py` - aktualizované URL routy

### Frontend
- `templates/production/menu_template_visual_edit.html` - hlavní UI šablona
  - Day containery s SortableJS
  - Meal cards s drag-drop
  - Select2 autocomplete pro recepty
  - Modaly pro bulk operace
  - Live statistiky

- `static/js/menu_template_visual_edit.js` - JavaScript logika (700+ řádků)
  - SortableJS inicializace s touch podporou
  - Select2 konfigurace
  - AJAX callbacky
  - Error handling
  - Toast notifikace

### Dokumentace
- `docs/visual_editor.md` - uživatelská dokumentace
- `test_visual_editor.py` - testovací skript

### Aktualizované soubory
- `templates/production/menu_template_form.html` - přidán přepínač režimů
- `templates/production/menu_template_list.html` - odkazy na vizuální editor
- `CHANGELOG.md` - dokumentace změn

## Jak používat

### 1. Přístup k editoru

Existují 3 způsoby:

**A) Ze seznamu šablon:**
```
http://localhost:8000/production/sablony/
→ Klikněte na ikonu "✏️" u šablony
```

**B) Z XML režimu:**
```
Při editaci šablony klikněte na "Vizuální editor" v pravém horním rohu
```

**C) Přímý odkaz:**
```
http://localhost:8000/production/sablony/<id>/vizualni-editor/
```

### 2. Základní operace

#### Přidat jídlo:
1. Klikněte "Přidat jídlo" u dne
2. Vyberte recept (začněte psát pro vyhledávání)
3. Zvolte typ (snídaně/oběd/večeře/svačina)
4. Volitelně: počet porcí, poznámka
5. Klikněte "Přidat"

#### Přeuspořádat:
- Přetáhněte jídlo myší nebo prstem
- Funguje i mezi různými dny

#### Zkopírovat den:
1. Klikněte ikonu 📋 u dne
2. Vyberte cílový den
3. Potvrďte

#### Smazat jídlo/den:
- Jídlo: ikona ×
- Celý den: ikona 🗑️

### 3. Testování

Spusťte testovací skript:
```bash
python test_visual_editor.py
```

Očekávaný výstup:
```
============================================================
TEST: Helper metody MenuTemplate
============================================================
✓ Testujeme šablonu: 4denní pro ŠVP
  ID: 1

1. Test parse_schedule_to_dict()
   ✓ Parsování úspěšné
   Počet dnů: 5
   Den 0: 4 jídel
   ...

2. Test get_stats()
   ✓ Statistiky získány
   Dny: 5
   Jídla: 23
   Unikátní recepty: 18

3. Test update_schedule_from_dict() - round-trip
   ✓ Round-trip úspěšný

ZÁVĚR: Všechny testy proběhly úspěšně ✓
============================================================
```

## Funkce

✅ **Implementováno:**
- Drag-drop jídel mezi dny
- Touch podpora (tablety/mobily)
- Autocomplete pro recepty (Select2)
- Live statistiky (dny, jídla, unikátní recepty)
- Bulk operace (kopírování/mazání dne)
- Confirm dialogy pro destruktivní akce
- Toast notifikace
- Validace (server + klient)
- Transparentní efekty v dark mode
- Responsive design
- Automatické ukládání
- Přepínač XML ↔ Vizuální režim

## Technologie

- **Frontend**: Vanilla JavaScript ES6+
- **Drag-drop**: SortableJS 1.15.0
- **Autocomplete**: Select2 4.1.0-rc.0
- **Backend**: Django 6.0.1
- **UI**: Bootstrap 5
- **AJAX**: Fetch API

## Struktura dat

### Python → JavaScript
```python
schedule_dict = {
    0: [  # Den 0
        {
            'recipe_code': 'HL-001',
            'meal_type': 'LUNCH',
            'note': 'Poznámka',
            'unique_id': 'uuid-string',
            'portion_count': 50
        }
    ]
}
```

### JavaScript → Server
```javascript
{
    day_index: 0,
    recipe_code: 'HL-001',
    meal_type: 'LUNCH',
    note: 'Poznámka',
    portion_count: 50
}
```

### Server → XML
```xml
<MenuSchedule>
  <Day name="Den 1" dateOffset="0">
    <Meal recipeCode="HL-001" type="obed" note="Poznámka" portionCount="50"/>
  </Day>
</MenuSchedule>
```

## Bezpečnost

- ✅ CSRF ochrana na všech endpointech
- ✅ Staff oprávnění kontrola
- ✅ Server-side validace
- ✅ Transaction atomicity
- ✅ XSS prevence (HTML escaping)
- ✅ Input sanitizace

## Výkon

- Optimalizováno pro 30 dnů
- Stovky jídel bez zpomalení
- Lazy loading receptů
- Minimální re-renders
- Debounced updates

## Řešení problémů

### JavaScript chyby
```bash
# Zkontrolujte konzoli (F12):
# - Načetly se SortableJS a Select2?
# - Je templateData definováno?
# - Jsou AJAX requesty úspěšné?
```

### Django chyby
```bash
# Zkontrolujte Django konzoli:
python manage.py check
python manage.py collectstatic --noinput
```

### URL chyby
```python
# Ověřte, že URLs jsou správně namapovány:
python manage.py show_urls | grep template
```

## Další kroky

1. **Testování v provozu:**
   - Vytvořte novou šablonu
   - Upravte existující šablonu
   - Zkuste všechny operace

2. **Školení uživatelů:**
   - Ukažte drag-drop rozhraní
   - Vysvětlete rozdíl mezi XML a vizuálním režimem
   - Zdůrazněte automatické ukládání

3. **Monitoring:**
   - Sledujte AJAX error rate
   - Kontrolujte validační chyby
   - Sbírejte feedback od uživatelů

## Podpora

Pro otázky nebo problémy:
1. Zkontrolujte `docs/visual_editor.md`
2. Spusťte `test_visual_editor.py`
3. Zkontrolujte browser console (F12)
4. Zkontrolujte Django logs

## Changelog

Viz `CHANGELOG.md` - sekce [0.9.1] - 2026-01-15
