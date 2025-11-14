# Migration Log - Menu-First Refactoring

## Datum: 14. listopadu 2025
## Branch: Výrobní-příkaz

---

## ✅ Fáze 1: Příprava (DOKONČENO)

### Změny v modelu ProductionOrder:
- ✅ Změněno pole `canteen` na `null=True, blank=True`
- ✅ Přidána metoda `get_canteen()` která vrací canteen z FK nebo z menu_plan
- ✅ Aktualizována `save()` metoda aby automaticky nastavila canteen z menu_plan
- ✅ Aktualizován `__str__()` aby používal `get_canteen()`
- ✅ Aktualizována `generate_picking_list()` aby používala `get_canteen()`
- ✅ Aktualizována `PickingList.clean()` aby používala `get_canteen()`

### Změny ve views:
- ✅ Odstraněno explicitní nastavení `canteen=menu_plan.canteen` při vytváření order
- ✅ Aktualizováno použití `order.canteen` na `order.get_canteen()`

### Migrace:
- ✅ `0007_make_canteen_nullable.py` - nastavení canteen na nullable

### Testy:
- ✅ Opraven test `test_picking.py` aby používal nový formát RecipeIngredient
- ✅ Všechny testy prošly

---

## ✅ Fáze 2: Migrace dat (DOKONČENO)

### Migrace:
- ✅ `0008_migrate_orders_to_menu_plans.py` - data migration
  - Našla všechny ProductionOrder bez menu_plan
  - Vytvořila jednorázové jídelníčky seskupené podle jídelny a data
  - Přiřadila všechny orphan příkazy k těmto jídelníčkům
  
- ✅ `0009_make_menu_plan_required.py` - schema migration
  - Nastaveno `menu_plan` jako NOT NULL (povinné pole)
  - ProductionOrder nyní MUSÍ být součástí jídelníčku

---

## ✅ Fáze 3: Odstranění legacy kódu (DOKONČENO)

### Odstraněné views:
- ✅ `ProductionOrderListView` (samostatný seznam)
- ✅ `ProductionOrderCreateView` (standalone vytváření)
- ✅ `ProductionOrderUpdateView` (standalone editace)
- ✅ `ProductionOrderDeleteView` (standalone mazání)

### Odstraněné URL patterns:
- ✅ `/prikazy/` - seznam výrobních příkazů
- ✅ `/prikazy/novy/` - vytvoření příkazu
- ✅ `/prikazy/<pk>/upravit/` - editace příkazu
- ✅ `/prikazy/<pk>/smazat/` - smazání příkazu

### Zachované:
- ✅ `/jidlo/<pk>/` - detail výrobního příkazu (read-only)
- ✅ `/jidlo/<pk>/vydejka/` - tisk výdejky

### Odstraněné šablony:
- ✅ `order_form.html`
- ✅ `order_confirm_delete.html`
- ✅ `order_list.html`

### Odstraněné importy:
- ✅ `ProductionOrderForm` (z views)
- ✅ `ProductionOrderFormAdvanced` (z views)

---

## ✅ Fáze 4: Simplifikace modelu (DOKONČENO)

### Odstraněné deprecated pole:
- ✅ `portions_adult` - nahrazeno ProductionOrderPortionVariant
- ✅ `portions_child` - nahrazeno ProductionOrderPortionVariant
- ✅ `portion_coefficient` - nahrazeno ProductionOrderPortionVariant

### Aktualizované metody:
- ✅ `generate_picking_list()` - používá pouze varianty
- ✅ `get_required_ingredients()` - používá pouze varianty
- ✅ `total_portions` property - počítá ze všech variant
- ✅ `total_effective_portions` property - počítá ze všech variant

### Odstraněné formuláře:
- ✅ `ProductionOrderForm` (unused)
- ✅ `ProductionOrderFormAdvanced` (unused)
- ✅ `ProductionOrderFormSet` (replaced by AJAX)
- ✅ `MenuPlanFormBasic` (zbytečný)

### Aktualizovaný admin:
- ✅ Odstraněno `portion_coefficient` z list_display
- ✅ Odstraněn fieldset pro deprecated pole
- ✅ Aktualizována `price_per_portion()` - počítá průměr
- ✅ Aktualizována `total_price()` - používá `total_effective_portions`

### Migrace:
- ✅ `0010_remove_deprecated_fields.py` - odstranění 3 polí

### Testy:
- ✅ Opraven `test_picking.py` aby používal MenuPlan a ProductionOrderPortionVariant
- ✅ Všechny testy prošly

---

## ⏳ Fáze 5: Dokumentace (V PŘÍPRAVĚ)

### Plánované změny:
- 🔲 Aktualizace hlavního menu (odstranění odkazu na samostatné výrobní příkazy)
- 🔲 Přejmenování navigace ("Jídelníčky" místo "Výroba")
- 🔲 Aktualizace breadcrumbs
- 🔲 Kontrola všech odkazů v šablonách

---

## 📊 Statistika změn

- **Změněné soubory:** 10 (models, views, admin, forms, urls, tests, migrations)
- **Nové migrace:** 4 (0007, 0008, 0009, 0010)
- **Odstraněné soubory:** 3 (šablony)
- **Odstraněná pole:** 3 (portions_adult, portions_child, portion_coefficient)
- **Odstraněné formuláře:** 4 (ProductionOrderForm, ProductionOrderFormAdvanced, MenuPlanFormBasic, ProductionOrderFormSet)
- **Nové metody:** 1 (get_canteen)
- **Odstraněné views:** 4
- **Odstraněné URL patterns:** 4

---

## 🎯 Výsledek

✅ **Aplikace je nyní plně menu-first:**

- Všechny výrobní příkazy MUSÍ být součástí jídelníčku
- Canteen se nastavuje automaticky z jídelníčku
- ProductionOrderPortionVariant místo deprecated polí
- Odstranění duplicitního systému pro standalone příkazy
- Odstranění všech unused formulářů a views
- Zachována zpětná kompatibilita pro čtení (detail, výdejky)
- Všechny testy prošly
- Žádné breaking changes pro koncové uživatele
- Model je nyní jednodušší a konzistentní

---

## 🔜 Další kroky

1. ✅ ~~Odstranit deprecated pole~~ - HOTOVO
2. ✅ ~~Odstranit unused formuláře~~ - HOTOVO
3. ✅ ~~Aktualizovat testy~~ - HOTOVO
4. ⏳ Otestovat v produkci s reálnými daty
5. ⏳ Aktualizovat dokumentaci pro uživatele
6. ⏳ Dokončit UI cleanup (navigace, breadcrumbs)
