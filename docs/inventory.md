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

## Pro vývojáře

*   Metody `block_quantity` a `unblock_quantity` na modelu `StockItem` jsou bezpečné pro souběžný přístup (používají `select_for_update` v volajícím kódu).
*   Cena se aktualizuje při každém příjmu. Historie se ukládá pro analytické účely.
