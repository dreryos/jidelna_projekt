# Historie cen surovin - Dokumentace

## Přehled

Systém pro sledování historie cen surovin umožňuje přesné výpočty nákladů receptů v čase, i když se nákupní ceny surovin mění.

## Problém, který řeší

Dříve analytický modul počítal náklady receptů vždy s **aktuálními** cenami surovin. Když se změnila nákupní cena suroviny, všechny historické analýzy ukazovaly náklady s touto novou cenou, což neodpovídalo skutečnosti.

**Příklad:**
- Leden 2025: Mouka stojí 20 Kč/kg
- Únor 2025: Mouka stojí 25 Kč/kg
- Analýza receptu z ledna ukazovala náklady s cenou 25 Kč/kg místo 20 Kč/kg

## Řešení

Systém nyní automaticky zaznamenává každou změnu ceny do tabulky `IngredientPriceHistory` a analytické výpočty používají historické ceny podle data výrobního příkazu.

## Technické detaily

### Model `IngredientPriceHistory`

```python
class IngredientPriceHistory(models.Model):
    ingredient = models.ForeignKey(Ingredient, ...)
    warehouse = models.ForeignKey(Warehouse, ...)
    price = models.DecimalField(...)
    valid_from = models.DateTimeField(...)
    created_at = models.DateTimeField(...)
```

**Pole:**
- `ingredient`: Surovina
- `warehouse`: Sklad, kde platí tato cena
- `price`: Nákupní cena za jednotku
- `valid_from`: Od kdy platí tato cena
- `created_at`: Kdy byl záznam vytvořen

### Automatické zaznamenávání změn

Když se změní cena v `StockItem`, automaticky se vytvoří nový záznam v historii:

```python
# Při změně ceny
stock_item.price = Decimal('25.00')
stock_item.save()
# Automaticky se vytvoří IngredientPriceHistory záznam
```

### Použití historických cen

Metoda `Recipe.calculate_portion_price()` nyní přijímá parametr `price_date`:

```python
# Aktuální cena (bez price_date)
current_price = recipe.calculate_portion_price(canteen, portions=10)

# Historická cena (s price_date)
historical_price = recipe.calculate_portion_price(
    canteen, 
    portions=10,
    price_date=order.date  # Datum výrobního příkazu
)
```

### Funkce `get_price_at_date()`

Pro získání ceny platné k určitému datu:

```python
price = IngredientPriceHistory.get_price_at_date(
    ingredient=ingredient,
    warehouse=warehouse,
    date=datetime(2025, 1, 15)
)
```

Funkce:
1. Najde nejbližší starší záznam k zadanému datu
2. Pokud neexistuje historický záznam, použije aktuální cenu z `StockItem`
3. Pokud neexistuje ani `StockItem`, vrátí 0

## Použití v analytice

Všechny analytické pohledy nyní automaticky používají historické ceny:

### `menu_analytics_list`
Vypočítává průměrné náklady jídelníčků s cenami platnými k datu výrobních příkazů.

### `menu_detail_analytics`
Zobrazuje detailní náklady jídel včetně rozkladu surovin s historickými cenami.

### `recipe_cost_analysis`
Analýza nákladů receptů napříč časem s přesnými historickými cenami pro každé použití.

### `recipe_cost_detail`
Detailní historie použití receptu s náklady vypočítanými podle cen platných v době použití.

## Migrace existujících dat

Při nasazení systému se automaticky spustí datová migrace (`0004_populate_price_history`), která vytvoří historické záznamy pro všechny existující `StockItem` s aktuálním časovým razítkem.

## Správa v adminu

Model `IngredientPriceHistory` je dostupný v Django admin rozhraní:
- Zobrazení historie cen podle suroviny a skladu
- Filtrování podle skladu a data platnosti
- Vyhledávání podle názvu suroviny nebo skladu
- Hierarchie podle data (`date_hierarchy`)

## Výkon

Systém je optimalizován pro výkon:
- Index na `(ingredient, warehouse, -valid_from)` pro rychlé vyhledávání
- Průměrování cen přes sklady probíhá v Pythonu (typicky 1-3 sklady na jídelnu)
- Historické výpočty se provádějí pouze v analytických pohledech, ne v běžné práci

## Zpětná kompatibilita

Systém je plně zpětně kompatibilní:
- Pokud pro datum neexistuje historický záznam, použije se aktuální cena
- Stávající kód funguje beze změny (parametr `price_date` je volitelný)
- Migrace automaticky naplní historii pro existující data

## Testování

Systém je pokryt 11 testy, které ověřují:
- Automatické vytváření historie při změně ceny
- Správné vracení historických cen podle data
- Fungování v kombinaci s výpočty cen receptů
- Edge cases (chybějící data, staré datumy, atd.)

## Příklady použití

### Zobrazení historie cen suroviny

```python
history = IngredientPriceHistory.objects.filter(
    ingredient=ingredient,
    warehouse=warehouse
).order_by('-valid_from')

for record in history:
    print(f"{record.valid_from}: {record.price} Kč")
```

### Porovnání historické a aktuální ceny

```python
# Historická cena před 30 dny
old_date = timezone.now() - timedelta(days=30)
old_price = IngredientPriceHistory.get_price_at_date(
    ingredient, warehouse, old_date
)

# Aktuální cena
current_price = stock_item.price

difference = current_price - old_price
percentage = (difference / old_price * 100) if old_price > 0 else 0

print(f"Změna ceny: {difference} Kč ({percentage:.1f}%)")
```

### Analýza nákladů receptu v čase

```python
dates = [
    date(2025, 1, 1),
    date(2025, 2, 1),
    date(2025, 3, 1),
]

for analysis_date in dates:
    price_info = recipe.calculate_portion_price(
        canteen,
        portions=1,
        price_date=analysis_date
    )
    print(f"{analysis_date}: {price_info['per_portion']} Kč/porce")
```

## Omezení

1. **Přesnost časových razítek**: Historie zachycuje změny s přesností na sekundy. Pokud dojde k více změnám ve stejnou sekundu, může být pořadí neurčité.

2. **Historická data před nasazením**: Pro data před nasazením systému není historie dostupná (použije se aktuální cena jako fallback).

3. **Manuální změny v DB**: Přímé změny cen v databázi obcházející Django ORM nezaznamená automatický mechanismus.

## Budoucí vylepšení

Možná rozšíření v budoucnu:
- Grafické zobrazení vývoje cen v čase
- Predikce budoucích nákladů na základě trendu cen
- Upozornění na výrazné změny cen
- Export historie cen do Excel/CSV
- Hromadná úprava cen s automatickým záznamem do historie
