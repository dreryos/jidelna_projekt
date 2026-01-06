# Modul Analytika (Analytics)

Poskytuje finanční pohled na provoz jídelny. Umožňuje sledovat náklady na suroviny (Food Cost).

## Funkcionalita

### Analýza Jídelníčku (Menu Analytics)
*   Přehled nákladů pro celé jídelníčky.
*   Počítá:
    *   Celkové náklady na suroviny pro celý jídelníček.
    *   Průměrný náklad na jedno jídlo.
    *   Náklad na osobu (součet cen porcí).

### Detail Jídelníčku
*   Rozpad nákladů pro jednotlivá jídla v jídelníčku.
*   Zobrazuje přesnou kalkulaci ceny porce v den vaření (používá historické ceny surovin z `IngredientPriceHistory`).
*   Rozpis použitých surovin a jejich cen.

### Analýza Nákladů Receptů (Recipe Cost Analysis)
*   Umožňuje sledovat, jak se vyvíjí cena konkrétního receptu v čase.
*   Statistiky: Průměrná, minimální a maximální cena porce.
*   Graf historie použití a ceny.

## Technické detaily

*   **Výpočet ceny**: Metoda `Recipe.calculate_portion_price` je klíčová.
    *   Pokud je zadáno datum (`price_date`), hledá v `IngredientPriceHistory` cenu platnou k tomuto datu.
    *   Pokud datum není zadáno, bere aktuální cenu ze `StockItem`.
*   Ceny se průměrují přes všechny sklady jídelny (pokud má jídelna surovinu ve více skladech).

## Pro vývojáře
*   Analytika je náročná na databázové dotazy. Používá se `select_related` a `prefetch_related` pro optimalizaci (N+1 problém).
*   Výpočty probíhají v Pythonu s použitím `Decimal` pro zachování přesnosti měny.
