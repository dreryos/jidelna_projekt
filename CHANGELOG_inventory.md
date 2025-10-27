# Changelog - Modul Sklady (Inventory)

## [2025-10-27] - Vylepšení modulu skladů

### Přidáno ✨

#### CRUD pro sklady (Warehouse)
- **Nové views:**
  - `WarehouseListView` - seznam všech skladů s informací o počtu položek
  - `WarehouseCreateView` - vytvoření nového skladu
  - `WarehouseUpdateView` - úprava existujícího skladu
  - `WarehouseDeleteView` - smazání skladu (s varováním při existujících položkách)

- **Nové URL cesty:**
  - `/inventory/warehouses/` - seznam skladů
  - `/inventory/warehouses/add/` - přidat nový sklad
  - `/inventory/warehouses/edit/<id>/` - upravit sklad
  - `/inventory/warehouses/delete/<id>/` - smazat sklad

- **Nové šablony:**
  - `templates/inventory/warehouse_list.html` - seznam skladů se statistikami
  - `templates/inventory/warehouse_form.html` - formulář pro vytvoření/úpravu skladu
  - `templates/inventory/warehouse_confirm_delete.html` - potvrzení smazání s varováním

#### Filtrování skladových položek
- **Vylepšený `StockListView`:**
  - Možnost filtrovat podle jednoho nebo více skladů najednou
  - Checkboxy pro výběr skladů
  - Tlačítko "Všechny sklady" pro rychlé zobrazení všech zásob
  - Query parametry: `?warehouse=1&warehouse=2` pro filtrování

- **Vylepšená šablona `stock_list.html`:**
  - Filtrovací panel s checkboxy pro jednotlivé sklady
  - JavaScript pro ovládání "Všechny sklady" checkbox
  - Tlačítko "Spravovat sklady" pro rychlý přístup ke správě skladů
  - Zachování vybraných filtrů v UI

### Změněno 🔄

- **Homepage (`templates/home.html`):**
  - Přidán odkaz "Spravovat sklady" do sekce "Sklady a zásoby"

- **Inventory views (`apps/inventory/views.py`):**
  - Přidán `select_related` pro optimalizaci databázových dotazů
  - Přidány success messages pro všechny CRUD operace
  - Context název změněn z `object_list` na `stock_items` pro lepší čitelnost

### Technické detaily 🔧

- **Optimalizace:**
  - `select_related('ingredient', 'warehouse', 'warehouse__canteen')` pro snížení počtu SQL dotazů
  - Prefetch pro stock_items.count() ve warehouse listu

- **Validace:**
  - Django unique_together constraint zajišťuje unikátnost (name, canteen) pro sklady
  - Varování při mazání skladu s existujícími položkami

### Jak používat 📖

1. **Přidání skladu:**
   - Navigujte na `/inventory/warehouses/`
   - Klikněte na "Přidat sklad"
   - Vyplňte název a vyberte jídelnu
   - Uložte

2. **Filtrování zásob podle skladu:**
   - Navigujte na `/inventory/`
   - V horním panelu zaškrtněte sklady, které chcete zobrazit
   - Klikněte "Filtrovat"
   - Pro zobrazení všech skladů zaškrtněte "Všechny sklady"

3. **Správa skladů:**
   - Z homepage: Sklady a zásoby → Spravovat sklady
   - Nebo přímo: `/inventory/warehouses/`

### Příklady použití 💡

**Filtrování podle konkrétního skladu:**
```
GET /inventory/?warehouse=1
```

**Filtrování podle více skladů:**
```
GET /inventory/?warehouse=1&warehouse=3
```

**Zobrazení všech skladů:**
```
GET /inventory/
```

### TODO (budoucí vylepšení) 📝

- [ ] Export seznamu skladů do Excel/PDF
- [ ] Přehled zásob v jednotlivých skladech (agregace)
- [ ] Grafy a statistiky pro sklady
- [ ] Historie pohybů na skladě
- [ ] Upozornění na nízké stavy v konkrétním skladu
