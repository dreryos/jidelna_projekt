# Aktualizace modulu Production/Příkazy

## Datum: 5. listopadu 2025

## Provedené změny

### 1. Aktualizace zobrazení seznamu výrobních příkazů (`/production/prikazy/`)

**Soubor:** `templates/production/order_list.html`

**Změny:**
- ✅ Přidáno zobrazení **jídelníčku**, ke kterému příkaz patří
- ✅ Zobrazení **variant porcí** místo starých `portions_adult/child`
- ✅ Pro každou variantu se zobrazuje:
  - Počet porcí
  - Koeficient velikosti
  - Efektivní počet porcí (počet × koeficient)
- ✅ Fallback na starou strukturu pro příkazy bez variant
- ✅ Zobrazení celkového počtu porcí (`order.total_portions`)

**Příklad zobrazení:**
```
Jídelníček: Týdenní jídelníček (1.11. - 7.11.)

Varianty porcí:
┌─────────────────┐
│ 50× 1.0         │
│ = 50 porcí      │
└─────────────────┘

Celkem: 50 porcí
```

### 2. Aktualizace detailu výrobního příkazu (`/production/prikazy/<id>/`)

**Soubory:**
- `templates/production/order_detail.html`
- `apps/production/views.py` (funkce `production_order_detail`)

**Změny v šabloně:**
- ✅ Přidán odkaz na jídelníček v hlavičce
- ✅ Zobrazení informace o jídelníčku
- ✅ Přepracované zobrazení porcí:
  - Pokud existují varianty → zobrazí karty pro každou variantu
  - Pokud neexistují → fallback na starou strukturu
- ✅ Dynamické rozložení karet podle počtu variant

**Změny ve view:**
- ✅ Načítání výdejky pomocí `order.picking_list_items.all()`
- ✅ Výpočet celkové ceny na základě průměrných cen surovin ve skladech
- ✅ Předání `total_price` do kontextu
- ✅ Lepší error handling při výpočtu ceny

**Příklad zobrazení variant:**
```
┌──────────────┐ ┌──────────────┐ ┌──────────────┐
│ 30× (1.0)    │ │ 20× (0.75)   │ │              │
│ Varianta 1   │ │ Varianta 2   │ │ Celkem: 50   │
│ Ef: 30 porcí │ │ Ef: 20 porcí │ │    porcí     │
└──────────────┘ └──────────────┘ └──────────────┘
```

### 3. Zachování zpětné kompatibility

- ✅ Staré výrobní příkazy (bez variant) se stále zobrazují správně
- ✅ Fallback na `portions_adult + portions_child` pokud varianty neexistují
- ✅ Zobrazení `portion_coefficient` u starých příkazů

## Struktura dat

### Nový systém (s variantami):
```python
ProductionOrder
  ├── menu_plan (FK → MenuPlan)
  ├── recipe (FK → Recipe)
  ├── canteen (FK → Canteen)
  ├── date
  └── portion_variants (M2M)
      ├── ProductionOrderPortionVariant
      │   ├── portions (int)
      │   ├── coefficient (decimal)
      │   └── order (int)
```

### Starý systém (fallback):
```python
ProductionOrder
  ├── recipe (FK → Recipe)
  ├── canteen (FK → Canteen)
  ├── date
  ├── portions_adult (int)
  ├── portions_child (int)
  └── portion_coefficient (decimal)
```

## Testování

### Co otestovat:

1. **Seznam příkazů** (`/production/prikazy/`):
   - [ ] Zobrazení příkazů s variantami
   - [ ] Zobrazení příkazů bez variant (staré)
   - [ ] Zobrazení jídelníčku u příkazů z jídelníčku
   - [ ] Filtry fungují správně

2. **Detail příkazu** (`/production/prikazy/<id>/`):
   - [ ] Zobrazení variant porcí
   - [ ] Výpočet celkové ceny
   - [ ] Odkaz zpět na jídelníček
   - [ ] Výdejka se zobrazuje správně

3. **Zpětná kompatibilita**:
   - [ ] Staré příkazy se zobrazují bez chyb
   - [ ] Nové příkazy se zobrazují s variantami

## Poznámky

- Modul je nyní **kompatibilní** s novým systémem jídelníčků
- **Fallback** na starou strukturu zajišťuje, že staré příkazy fungují
- **Výdejka** se generuje automaticky při vytvoření příkazu
- **Cena** se počítá na základě průměrných cen surovin ve skladech jídelny

## Další vylepšení (TODO)

- [ ] Přidat možnost editace variant porcí přímo ze seznamu
- [ ] Exportovat výdejku do PDF/Excel
- [ ] Přidat statistiky spotřeby surovin
- [ ] Přidat možnost kopírování výrobního příkazu
