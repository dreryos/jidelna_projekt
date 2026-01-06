# Modul Receptury a Výroba (Production)

Tento modul je srdcem aplikace. Zajišťuje evidenci receptů, plánování jídelníčku a řízení procesu vaření.

## Modely a Datová struktura

### MenuPlan (Jídelníček)
Reprezentuje plán stravování na určité období (od-do).
*   Vazba na `Canteen` (Jídelna).
*   Obsahuje výchozí koeficienty pro porce (např. "Dospělá", "Dětská").

### ProductionOrder (Výrobní příkaz)
Konkrétní instrukce k vaření jednoho jídla v daný den.
*   Spojuje `MenuPlan`, `Recipe` a datum.
*   Počítá celkový počet porcí a "efektivních porcí" (přepočteno koeficienty).
*   **Klíčová funkcionalita**: Metoda `generate_picking_list()` automaticky vypočítá potřebné suroviny na základě norem a vytvoří položky výdejky.

### ProductionOrderPortionVariant
Umožňuje definovat více variant porcí pro jeden výrobní příkaz.
*   Například: 100x Normální porce (koef. 1.0) + 50x Malá porce (koef. 0.75).
*   Systém automaticky sčítá nároky na suroviny ze všech variant.

### PickingList (Položka výdejky)
Požadavek na vydání konkrétní suroviny ze skladu pro daný výrobní příkaz.
*   Obsahuje `quantity_planned` (vypočteno z normy) a `quantity_actual` (skutečně vydáno).
*   Stavy: `PENDING` (čeká), `COMPLETED` (vydáno).
*   Při vytvoření/aktualizaci blokuje množství na skladě (`StockItem.quantity_blocked`).
*   Při dokončení (`COMPLETED`) odečítá množství ze skladu a uvolňuje blokaci.

### PickingListDocument (Dokument výdejky)
Seskupuje položky výdejky do jednoho dokladu (pro tisk, podpis).

## Procesy

1.  **Tvorba jídelníčku**: Uživatel vytvoří `MenuPlan` a přidá do něj `ProductionOrder`s (jídla na dny).
2.  **Kalkulace surovin**: Při uložení `ProductionOrder` systém automaticky vytvoří `PickingList` položky. Pokud surovina ve skladu není, vytvoří se s nulovým množstvím (upozornění).
3.  **Výdej**: Skladník vidí seznam surovin k výdeji. Může upravit skutečně vydané množství. Po potvrzení výdeje se aktualizuje stav skladu.

## Pro vývojáře

*   Logika výpočtu množství surovin je v `RecipeIngredient.get_quantity_in_base_unit`.
*   Transakce jsou použity při práci se skladem (`StockItem`) pro zajištění konzistence dat (blokace, odpis).
*   Validace zajišťuje, že nelze vydat ze skladu jiné jídelny.
