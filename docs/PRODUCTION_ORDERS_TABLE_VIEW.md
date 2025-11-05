# Přepracování zobrazení výrobních příkazů - Tabulkový formát

## Datum: 5. listopadu 2025

## Přehled změn

Výrobní příkazy byly přepracovány z **kartového zobrazení** na **tabulkový formát** seskupený podle jídelníčků a dní.

## Nová struktura

### Seskupení dat

**Výrobní příkazy jsou nyní seskupeny do 2 kategorií:**

1. **Příkazy s jídelníčkem** - seskupeny podle:
   - Jídelníčku (hlavní úroveň)
   - Dne (druhá úroveň)
   - Jídla (řádky v tabulce)

2. **Samostatné příkazy** - příkazy bez přiřazeného jídelníčku
   - Zobrazeny v samostatné tabulce

### Formát zobrazení

```
┌─ JÍDELNÍČEK ──────────────────────────────────────────┐
│ [Název] [Od - Do] [Jídelna]     [Statistiky] [Detail] │
├───────────────────────────────────────────────────────┤
│ Den      │ Jídlo │ Varianty │ Efektivně │ Akce        │
├──────────┼───────┼──────────┼───────────┼─────────────┤
│ 1.11.    │ Jídlo1│ 50×1.0   │ 50 porcí  │ 👁 ✏️ 🗑️    │
│ 2025     │ Jídlo2│ 30×0.75  │ 30 porcí  │ 👁 ✏️ 🗑️    │
│ Pondělí  │       │          │           │             │
├──────────┼───────┼──────────┼───────────┼─────────────┤
│ 2.11.    │ Jídlo3│ 40×1.0   │ 40 porcí  │ 👁 ✏️ 🗑️    │
│ 2025     │       │          │           │             │
│ Úterý    │       │          │           │             │
└──────────┴───────┴──────────┴───────────┴─────────────┘
```

## Změny v kódu

### 1. Backend (`apps/production/views.py`)

**Třída:** `ProductionOrderListView`

**Nová logika v `get_context_data()`:**

```python
# Seskupení příkazů podle jídelníčků a dní
grouped_data = {}
standalone_orders = []

for order in orders:
    if order.menu_plan:
        # Příkazy s jídelníčkem
        menu_key = order.menu_plan.id
        if menu_key not in grouped_data:
            grouped_data[menu_key] = {
                'menu': order.menu_plan,
                'days': {}
            }
        
        date_key = order.date
        if date_key not in grouped_data[menu_key]['days']:
            grouped_data[menu_key]['days'][date_key] = []
        
        grouped_data[menu_key]['days'][date_key].append(order)
    else:
        # Samostatné příkazy bez jídelníčku
        standalone_orders.append(order)

# Seřadíme dny a spočítáme statistiky
for menu_data in grouped_data.values():
    menu_data['days'] = dict(sorted(menu_data['days'].items()))
    total_meals = sum(len(orders) for orders in menu_data['days'].values())
    menu_data['total_meals'] = total_meals

context['grouped_menus'] = grouped_data
context['standalone_orders'] = standalone_orders
```

### 2. Frontend (`templates/production/order_list.html`)

**Struktura šablony:**

1. **Filtry** - aktualizované pro lepší použitelnost
   - Datum (date input)
   - Jídelna (select)
   - Recept (select)
   - Tlačítko "Zrušit všechny filtry"

2. **Tabulky jídelníčků**
   - Hlavička s názvem, datumem, jídelnou, statistikami
   - Tabulka s dny a jídly
   - Rowspan pro seskupení jídel pod jeden den
   - Barevné odlišení variant porcí

3. **Tabulka samostatných příkazů**
   - Podobná struktura, ale s datumem v každém řádku
   - Zobrazení jídelny pro každý příkaz

**CSS styly:**
```css
.table-hover tbody tr:hover {
  background-color: rgba(0, 123, 255, 0.05);
}

.menu-card:hover {
  box-shadow: 0 0.5rem 1rem rgba(0, 0, 0, 0.15) !important;
}
```

## Funkce

### Hlavička jídelníčku

```django
<div class="card-header bg-primary text-white">
  <h5>{{ menu_data.menu.name }}</h5>
  <small>{{ menu_data.menu.date_from }} - {{ menu_data.menu.date_to }} | {{ menu_data.menu.canteen.name }}</small>
  <span class="badge">{{ menu_data.days|length }} dní</span>
  <span class="badge">{{ menu_data.total_meals }} jídel</span>
  <a href="Detail jídelníčku">Zobrazit</a>
</div>
```

### Tabulka s dny

- **Rowspan** - den je zobrazen jen jednou pro všechna jídla v ten den
- **Formát dne**: "1.11.2025 Pondělí"
- **Vizuální oddělení** mezi dny pomocí prázdného řádku

### Zobrazení variant

```django
{% with variants=order.portion_variants.all %}
{% if variants %}
  {% for variant in variants %}
  <span class="badge bg-info">
    {{ variant.portions }}× {{ variant.coefficient }}
  </span>
  {% endfor %}
{% else %}
  <span class="badge bg-secondary">
    {{ order.total_portions }}× {{ order.portion_coefficient }}
  </span>
{% endif %}
{% endwith %}
```

### Tlačítka akcí

- 👁 **Detail** - zobrazení detailu příkazu
- ✏️ **Upravit** - editace příkazu
- 🗑️ **Smazat** - smazání příkazu

## Výhody nového formátu

✅ **Lepší přehlednost** - všechna jídla z jídelníčku na jednom místě
✅ **Seskupení podle dní** - snadná orientace v týdenním plánu
✅ **Kompaktní zobrazení** - více informací na obrazovce
✅ **Statistiky** - okamžitý přehled o počtu dní a jídel
✅ **Rychlý přístup** - odkaz na detail jídelníčku přímo z hlavičky
✅ **Responzivní** - funguje na různých velikostech obrazovek
✅ **Zpětná kompatibilita** - podporuje staré i nové příkazy

## Testování

### Scénáře k otestování:

- [ ] Zobrazení jídelníčku s více dny
- [ ] Zobrazení dne s více jídly
- [ ] Zobrazení variant porcí
- [ ] Zobrazení starých příkazů (bez variant)
- [ ] Zobrazení samostatných příkazů
- [ ] Filtrace podle data
- [ ] Filtrace podle jídelny
- [ ] Filtrace podle receptu
- [ ] Prázdný stav (žádné příkazy)
- [ ] Tlačítka akcí (detail, edit, delete)
- [ ] Odkaz na detail jídelníčku
- [ ] Responsivita na mobilu

## Příklad výstupu

### Jídelníček s více dny

```
┌─ Týdenní jídelníček (1.11. - 7.11.) - Testovací jídelna ─┐
│ Statistiky: 5 dní | 15 jídel                   [Detail]  │
├──────────────────────────────────────────────────────────┤
│ 1.11.2025 │ Svíčková         │ 50×1.0  │ 50 porcí │ 👁✏️🗑│
│ Pondělí   │ Knedlíky         │ 50×1.0  │ 50 porcí │ 👁✏️🗑│
│           │ Polévka          │ 50×1.0  │ 50 porcí │ 👁✏️🗑│
├──────────────────────────────────────────────────────────┤
│ 2.11.2025 │ Guláš            │ 40×1.0  │ 40 porcí │ 👁✏️🗑│
│ Úterý     │ Rýže             │ 40×0.75 │ 40 porcí │ 👁✏️🗑│
└──────────────────────────────────────────────────────────┘
```

## Migrace ze starého formátu

**Žádná migrace dat není potřeba!** 

- Stará data fungují automaticky díky fallback logice
- Nové příkazy používají varianty porcí
- Zobrazení je kompatibilní s oběma formáty

## Poznámky pro vývojáře

- Context data obsahují `grouped_menus` a `standalone_orders`
- Statistiky se počítají v `get_context_data()`
- Rowspan v HTML tabulce používá `forloop.first`
- CSS styly jsou definovány v `{% block extra_css %}`
