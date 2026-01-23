# Oprava chyby 500 při mazání surovin

## Problém
Při pokusu o smazání suroviny, která je použita v receptech, jídelníčcích nebo výdejkách, server vracel chybu 500 místo čitelné chybové hlášky. Chyba se vyskytovala jak v Django admin rozhraní, tak v custom view pro mazání surovin.

## Příčina
Django vyvolává `ProtectedError` výjimku, když se pokusíme smazat objekt, na který odkazují jiné objekty s `on_delete=models.PROTECT`. Pokud tato výjimka není správně zachycena a ošetřena, zobrazí se uživateli chyba 500.

## Řešení

### 1. Django Admin ([apps/core/admin.py](apps/core/admin.py))
Implementována vlastní logika mazání v `IngredientAdmin` třídě:

#### Metoda `delete_model`
Ošetřuje mazání jednotlivé suroviny:
- Zachytí `ProtectedError` výjimku
- Analyzuje, které objekty brání smazání
- Zobrazí uživatelsky přívětivou chybovou hlášku v češtině

#### Metoda `delete_queryset`
Ošetřuje hromadné mazání surovin:
- Pokusí se smazat každou surovinu zvlášť
- Sleduje úspěšná a neúspěšná smazání
- Zobrazí souhrnné zprávy o výsledcích

### 2. Custom View ([apps/core/views.py](apps/core/views.py))
Přepsána metoda `post()` v `IngredientDeleteView`:
- Zachytí `ProtectedError` při pokusu o smazání
- Vytvoří uživatelsky přívětivou chybovou hlášku
- Přesměruje uživatele zpět na seznam surovin
- Zobrazí error message s detaily o blokujících záznamech

## Typy vztahů
Surovina (`Ingredient`) má následující vztahy:

**CASCADE (automaticky se smaže):**
- `RecipeIngredient` - normy v receptech
- `StockItem` - skladové zásoby
- `SupplierIngredientTemplate` - šablony dodavatelů
- `IngredientPriceHistory` - historie cen

**PROTECT (zabrání smazání):**
- `PickingList` - výdejky
- `GoodsReceiptItem` - položky příjmu zboží
- `InventoryVerificationItem` - položky inventury
- `StockTransferItem` - položky převodek
- `ProductionOrderIngredientOverride` - úpravy surovin ve výrobních příkazech

## Testování
Vytvořeny testy v [test/test_ingredient_deletion.py](test/test_ingredient_deletion.py):
- ✅ Test mazání nepoužité suroviny
- ✅ Test mazání suroviny se vztahy CASCADE
- ✅ Test blokování mazání při výdejkách (PROTECT)
- ✅ Test blokování mazání při příjmech zboží (PROTECT)
- ✅ Test správného ošetření v custom view

Spuštění testů:
```bash
python manage.py test test.test_ingredient_deletion
```

Všech 5 testů úspěšně prošlo ✅

## Výsledek
Nyní při pokusu o smazání používané suroviny:
1. ❌ Neobjeví se chyba 500
2. ✅ Zobrazí se čitelná chybová hláška v češtině
3. ✅ Uživatel vidí, které záznamy brání smazání (např. "3× výdejky, 2× položky příjmu zboží")
4. ✅ Uživatel ví, co musí udělat (smazat nebo upravit blokující záznamy)
5. ✅ Funguje jak v Django admin, tak v custom view
