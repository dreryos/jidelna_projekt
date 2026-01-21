# Modul Sklad (Inventory)

Modul pro kompletní správu skladových zásob, cenotvorbu a příjem zboží.

## Modely a Datová struktura

### StockItem (Skladová položka)
Reprezentuje stav konkrétní suroviny v konkrétním skladu.
*   `quantity`: Aktuální množství fyzicky na skladě.
*   `quantity_blocked`: Množství rezervované pro naplánovanou výrobu (ale ještě nevydané).
*   `price`: Aktuální nákupní cena za jednotku.
*   `quantity_available`: Vypočítaná vlastnost (`quantity` - `quantity_blocked`).

### GoodsReceipt (Příjem zboží)
Doklad o naskladnění surovin.
*   Stavy: `DRAFT` (koncept), `CONFIRMED` (potvrzeno).
*   Až po potvrzení (`confirm()`) se navyšují stavy ve `StockItem`.

### IngredientPriceHistory (Historie cen)
Uchovává historii nákupních cen surovin v čase.
*   Klíčové pro zpětnou analytiku nákladů (kolik stálo jídlo uvařené před měsícem).
*   Záznam se vytváří automaticky při změně ceny v `StockItem`.

### StockTransfer (Převodka mezi sklady)
Doklad o převodu zboží mezi sklady s třístupňovým workflow.

**Stavy převodky:**
*   `DRAFT` (Návrh) - Převodka vytvořena, lze editovat
*   `IN_TRANSIT` (V převozu) - Zboží odečteno ze source, v meziskladu
*   `COMPLETED` (Dokončeno) - Zboží přijato v cílovém skladu
*   `CANCELLED` (Zrušeno) - Převod zrušen

**Workflow:**

```
DRAFT
  ├─> start_transfer() ──> IN_TRANSIT
  │                           │
  │                           ├─> complete_transfer() ──> COMPLETED
  │                           └─> cancel() ──> CANCELLED (vrací zboží zpět do source)
  │
  ├─> start_and_complete() ──> COMPLETED (okamžitý převod bez meziskladu)
  └─> cancel() ──> CANCELLED
```

**Mezisklad (Transit Warehouse):**
*   Každá jídelna má automaticky vytvořený mezisklad s názvem "{jídelna} - Převody"
*   Mezisklad je označen `is_transit_warehouse=True`
*   Slouží k evidenci zboží "na cestě" mezi sklady
*   Nelze ho použít jako zdrojový nebo cílový sklad při vytváření převodky
*   Ve výchozím zobrazení skladových položek je skryt (lze zobrazit zaškrtnutím filtru)

**Přenos ceny:**
*   Cena je automaticky převzata ze zdrojového skladu (`unit_price_with_vat`)
*   Při dokončení převodu se v cílovém skladu používá vážený průměr cen

## Procesy

1.  **Příjem zboží**:
    *   Vytvoří se `GoodsReceipt`.
    *   Přidají se položky (`GoodsReceiptItem`) s množstvím a cenou.
    *   Doklad se potvrdí -> aktualizuje se `StockItem` (množství += příjem, cena = nová cena).

2.  **Rezervace (Blokace)**:
    *   Vzniká automaticky z modulu Production (když se naplánuje vaření).
    *   Zvyšuje `quantity_blocked` na `StockItem`.

3.  **Výdej**:
    *   Realizován přes modul Production (`PickingList`).
    *   Snižuje `quantity` a `quantity_blocked`.

4.  **Oceňování**:
    *   Používá se metoda průměrných cen nebo aktuální ceny (dle implementace v analytice).
    *   Systém sleduje cenu za měrnou jednotku (např. Kč/kg).

5.  **Převod mezi sklady**:
    *   **Krok 1 - Vytvoření:** Vytvoří se `StockTransfer` ve stavu DRAFT s položkami
    *   **Krok 2a - Zahájení (s mezistavem):** `start_transfer()` - zboží se odečte ze source a přičte do meziskladu, status = IN_TRANSIT
    *   **Krok 2b - Rychlý převod:** `start_and_complete()` - zboží se přímo převede ze source do target bez meziskladu, status = COMPLETED
    *   **Krok 3 - Dokončení:** `complete_transfer()` - zboží se odečte z meziskladu a přičte do target, status = COMPLETED
    *   **Zrušení:** `cancel()` - možné ze stavu DRAFT nebo IN_TRANSIT (vrací zboží zpět do source)
    
    **Validace:**
    *   Kontrola zamčení skladů (probíhající inventura)
    *   Kontrola dostupného množství (`quantity_available`)
    *   Zdrojový ≠ cílový sklad
    *   Nelze použít mezisklad jako source nebo target
    
    **Oprávnění:**
    *   Vytváření a správa převodek: pouze staff uživatelé
    *   Zobrazení: všichni uživatelé s přístupem k dané jídelně
    
    **Export:**
    *   PDF průvodka s podpisovými poli pro předávajícího a přebírajícího
    *   QR kód s číslem převodky (plánováno)

## Pro vývojáře

*   Metody `block_quantity` a `unblock_quantity` na modelu `StockItem` jsou bezpečné pro souběžný přístup (používají `select_for_update` v volajícím kódu).
*   Cena se aktualizuje při každém příjmu. Historie se ukládá pro analytické účely.
*   Všechny workflow metody na `StockTransfer` používají `@transaction.atomic` pro zajištění konzistence dat.
*   Transit warehouse je automaticky vytvořen migrací `0005_create_transit_warehouses` v apps/canteens.
