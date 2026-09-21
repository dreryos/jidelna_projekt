# Plán: predikce potřebných zásob a budoucích cen jídel

> **Pozor na zastaralý předpoklad:** plán vznikl **16. 9. 2026, před migrací
> na PostgreSQL**, a rozhodnutí proti Celery v něm stojí mimo jiné na tom, že
> aplikace běží na SQLite (`database is locked` při zápisu z workeru mimo
> gunicorn). **Tenhle argument už neplatí** — od 17. 9. 2026 běží PostgreSQL
> a řádkové zámky fungují. Ostatní důvody proti Celery (tři procesy navíc
> na 1,5 OCPU) platí dál, ale před implementací je potřeba rozhodnutí
> přehodnotit, ne ho převzít.

Kontext: Aplikace má umět pro zadaný jídelníček na konkrétní jídelně předpovědět
(a) kolik surovin bude potřeba nakoupit a (b) jakou cenu budou ta jídla mít
v době vaření. Podklad pro plán: kopie produkční DB (`db.sqlite3`, stav
16. 9. 2026) a měření na ní.

Práci provedou agenti na Sonnetu/Haiku. Každá fáze je samostatně
dokončitelná, testovatelná a commitovatelná.

---

## 0. Co už v aplikaci je (nestavět znovu)

Před psaním kódu si přečti tyto tři místa — většina „predikce zásob" tam už
v základní podobě existuje:

- **`apps/reports/views.py:82` `generate_order_report()`** — agreguje potřebu
  surovin z `ProductionOrder.get_required_ingredients()` za jídelnu a období,
  odečte dostupné zásoby, vrátí `to_order`. Správně řeší dvojí započtení:
  `COMPLETED` položky výdejky přeskočí, u `PENDING` s dokumentem odečte
  blokované množství. **Tohle je jádro predikce zásob — rozšiřuje se, nepíše se znovu.**
- **`apps/inventory/models.py:479` `IngredientPriceHistory`** — historie
  nákupních cen per (surovina, sklad), s `get_price_at_date()` a
  `get_prices_bulk()`. Zapisuje se automaticky v `StockItem.save()` při změně ceny.
- **`apps/core/models.py:245` `Recipe.calculate_portion_price()`** — cena porce
  k danému datu, s `price_date` a breakdownem.

Rovněž si přečti `docs/prirucka/13-pro-vyvojare.md` (návrhová rozhodnutí).

---

## 1. Rozhodnutí: Celery, nebo současný synchronní režim?

**Závěr: Celery nezavádět. Zůstat u synchronního výpočtu + uložený snapshot
+ management command pro dávky.** Důvody jsou měřené, ne dojmové.

### Naměřené časy (produkční DB, `.venv`, M-series)

| Operace | Čas | Dotazů |
|---|---|---|
| `generate_order_report()` Varvažov, 2 měsíce, 55 surovin | 0,03 s | 62 |
| `generate_order_report()` Růžená, 2 měsíce, 86 surovin | 0,06 s | 198 |
| Náklady celého jídelníčku (23 výrobních příkazů) | 0,07 s | 676 |
| Náklady 300 výrobních příkazů (≈ čtvrt sezóny) | 1,05 s | 9000 |

Nic se nepřibližuje timeoutu requestu. Predikce nad jedním jídelníčkem bude
řádově stejná — přibude jen násobení korekčními koeficienty a jeden dotaz
do historie cen.

### Proti Celery v tomto nasazení

1. **Nasazení je jeden kontejner nad SQLite na volume** (`docker-compose.yml`,
   `SQLITE_DB_PATH=/app/data/db.sqlite3`, gunicorn). Celery znamená přidat
   broker (Redis), worker a beat — tři další procesy a tři další věci,
   které v provozu padají.
2. **SQLite + zapisující worker mimo gunicorn = `database is locked`.**
   Zápisy se v SQLite serializují přes celou databázi. Dnes všechny zápisy
   chodí z jednoho procesu; worker to rozbije přesně ve chvíli, kdy někdo
   ukládá výdejku. Celery má smysl až po přechodu na PostgreSQL.
3. **Skutečné úzké hrdlo není synchronnost, ale N+1.** 676 dotazů na 23 jídel,
   protože `ProductionOrder.calculate_cost()` (`apps/production/models.py:582`)
   dělá `StockItem.objects.aggregate(Avg('price'))` zvlášť pro každou surovinu
   každého jídla. Přepis na `IngredientPriceHistory.get_prices_bulk()` srazí
   dotazy o řád a je levnější než jakákoli fronta.
4. **Vzorec pro běh na pozadí už v repu je a funguje** — `_start_picking_pdf_generation()`
   (`apps/production/views.py:2075`): démonské vlákno + polling přes
   `picking_list_pdf_status` + fallback „vygeneruj on-demand při stažení,
   pokud vlákno selhalo". Pro predikci stačí ten samý vzorec, pokud by se
   výpočet někdy protáhl.

### Co se místo Celery udělá

- Výpočet **synchronně v requestu**, spouštěný explicitním tlačítkem
  „Přepočítat predikci", ne automaticky při každé změně vstupu.
  Automatický přepočet při každé editaci porcí by na jídelníčku o 23 jídlech
  znamenal desítky přepočtů za minutu bez užitku.
- Výsledek se **uloží do snapshotu** (`MenuPlanForecast`, fáze 3), takže
  opakované zobrazení stránky nic nepočítá a je z čeho dělat zpětné
  vyhodnocení „predikce vs. skutečnost".
- Dávkové a dlouhé úlohy (přefit cenového modelu, přepočet korekčních
  koeficientů, backfill sezóny) jako **management commandy** spouštěné cronem
  v kontejneru — `python manage.py refresh_consumption_factors` apod.
  To je jeden řádek v crontabu proti třem službám v compose.

### Kdy se k Celery vrátit (napsat do CHANGELOGu jako podmínku, ne tabu)

Až platí **všechny tři** body zároveň:
1. databáze je PostgreSQL (ne SQLite),
2. predikce jednoho jídelníčku trvá přes ~5 s, nebo je potřeba pravidelný
   běh častěji než denně,
3. na aplikaci pracuje souběžně víc jídelen tak, že se requesty blokují.

Do té doby je Celery čistá provozní režie.

---

## 2. Fáze A — příprava dat a výkon (bez nových funkcí)

Cíl: aby predikce stavěla na rychlém a správném základu. Agent: **Sonnet**.

### A1. Odstranit N+1 ve výpočtu nákladů
`apps/production/models.py:582` `ProductionOrder.calculate_cost()` volá
`StockItem.objects.filter(...).aggregate(Avg('price'))` v cyklu přes suroviny.
Navíc používá **průměr cen napříč sklady jídelny**, zatímco zbytek aplikace
čte cenu přes `IngredientPriceHistory`.

**Oprava:** jedno bulk načtení cen přes
`IngredientPriceHistory.get_prices_bulk(ingredient_ids, warehouse_ids, date)`,
datum = `self.date` (ne „teď"). Zachovat zpětnou kompatibilitu návratového
dictu (`total`, `per_portion`). Přidat volitelný parametr `prices` pro
předané ceny, aby volající mohl načíst ceny pro celý jídelníček jednou.

**Test:** `apps/production/tests/test_order_cost.py` — cena jídla v minulosti
odpovídá historické ceně, ne dnešní; počet dotazů na jídelníček o 20 jídlech
pod 30 (`assertNumQueries`).

### A2. Vytáhnout `generate_order_report()` z views do služby
Přesunout do `apps/reports/services.py` (nový soubor) bez změny chování.
View jen volá. Důvod: predikce ji bude volat taky a z `views.py` se importovat
napříč aplikacemi nemá.

**Test:** stávající testy reportu musí projít beze změny očekávání.

### A3. Index na `production_pickinglist`
Predikce bude opakovaně číst `(production_order, ingredient, status)` a
`(ingredient, status)` nad 9 835 řádky. Přidat index, vygenerovat migraci.

---

## 3. Fáze B — predikce potřebných zásob

Cíl: pro `MenuPlan` + jídelnu vrátit nákupní seznam, který je **přesnější než
prostý součet norem receptů**. Agent: **Sonnet** (B1–B3), **Haiku** (B4 šablona).

### B1. Model `ConsumptionFactor` — korekce plán vs. skutečnost

Data v produkční DB tuhle korekci ospravedlňují (měřeno na 5 615 dokončených
položkách výdejek):

- medián `quantity_actual / quantity_planned` = **0,943** → normy receptů
  systematicky **nadhodnocují spotřebu o ~6 %**,
- přesnou shodu plánu a skutečnosti má jen **17,6 %** položek,
- 50,2 % položek se vydá méně než 0,95× plán, 27 % více než 1,05× plán,
- **100 surovin ze 180** má ≥ 10 dokončených pozorování, 42 surovin má ≥ 30.

Prostý součet norem tedy pro polovinu surovin míří vedle. Korekce je hlavní
přidaná hodnota proti dnešnímu reportu.

**Model** (`apps/analytics/models.py`, dosud bez modelů):

```
ConsumptionFactor
  ingredient  FK, canteen FK (null = globální fallback)
  factor      Decimal(6,4)     # medián actual/planned
  sample_size PositiveInteger
  mad         Decimal(6,4)     # median absolute deviation, míra spolehlivosti
  computed_at DateTimeField
  unique_together (ingredient, canteen)
```

**Výpočet** (`apps/analytics/services/consumption.py`):
- zdroj: `PickingList` se `status=COMPLETED`, `quantity_actual__isnull=False`,
  `quantity_planned__gt=0`, přes `production_order__canteen`,
- poměry ořezat na rozsah ⟨0,2; 3,0⟩ (nad 3,0 je to překlep, ne spotřeba),
- **medián**, ne průměr — průměr 1,02 vs. medián 0,943 ukazuje, jak moc
  ho několik odlehlých hodnot táhne,
- práh: **min. 8 pozorování** pro faktor na úrovni (surovina, jídelna),
  jinak fallback na (surovina, globálně), jinak faktor 1,0,
- MAD uložit — v UI se podle ní odliší „spolehlivá korekce" od „odhad".

**Management command** `refresh_consumption_factors` (`apps/analytics/management/commands/`),
volitelný `--canteen`. Určený pro cron (stačí týdně).

**Test** `apps/analytics/tests/test_consumption_factors.py`: syntetická data
s jasným mediánem, ověřit ořez odlehlých hodnot, fallback ladder, práh vzorku.

### B2. Služba `forecast_stock_needs(menu_plan, canteen=None)`

`apps/analytics/services/stock_forecast.py`. Staví na `generate_order_report()`
z A2 (období = `menu_plan.date_from`–`date_to`, jídelna = `menu_plan.canteen`)
a přidává:

1. **Korekce spotřeby** — `needed_corrected = needed * factor` z `ConsumptionFactor`.
   Vedle sebe vykázat `needed_raw` (norma) i `needed_corrected`, ať je vidět rozdíl.
2. **Přirážka na odpisy** — z `StockWriteOff` (325 dokladů v DB) spočítat
   podíl odepsaného množství na vydaném za posledních 180 dní per surovina;
   při podílu > 2 % připočíst. Pod 2 % ignorovat jako šum.
3. **Očekávané příjmy** — odečíst položky `GoodsReceipt` ve stavu `DRAFT`
   (7 dokladů v DB) a `StockTransfer` v rozpracovaném stavu směřující do
   skladů jídelny. Dnes se ignorují a report nakupuje podruhé, co je na cestě.
4. **Rozpad na sklady** — zásoby brát z `StockItem.quantity_available`
   (tj. mínus `quantity_blocked`) po skladech jídelny.
   **Zamčený sklad** (`Warehouse.is_locked` při inventuře) do disponibilní
   zásoby nepočítat a označit v výstupu — jinak predikce slíbí zboží,
   které se nedá vydat. **Mezisklad** (`is_transit_warehouse=True`) počítat
   zvlášť jako „na cestě".
5. **Zaokrouhlení na balení** — pole pro velikost balení na `Ingredient`
   neexistuje. Odvodit modus `quantity` z `GoodsReceiptItem` za posledních
   12 měsíců (175 surovin má ≥ 8 pozorování); pokud modus pokrývá ≥ 60 %
   příjmů, nabídnout zaokrouhlení nahoru na jeho násobek jako
   `suggested_order_qty` **vedle** přesného `to_order`, ne místo něj.

Výstup: seznam dictů `{ingredient, unit, needed_raw, needed_corrected,
waste_allowance, stock_available, incoming, to_order, suggested_order_qty,
confidence}`, kde `confidence` ∈ {vysoká, střední, nízká} podle `sample_size`/MAD.

**Test** `apps/analytics/tests/test_stock_forecast.py`: zamčený sklad se
nezapočítá; DRAFT příjemka sníží `to_order`; korekce se aplikuje; surovina bez
faktoru dostane 1,0; výdejka `COMPLETED` potřebu nezdvojí (regrese na logiku,
kterou `generate_order_report()` už řeší).

### B3. Rozšířit objednávkový report o jídelníček
`apps/reports/views.py:37` `order_report` — přidat volbu „podle jídelníčku"
vedle stávajícího rozsahu dat. Vybere se `MenuPlan`, období a jídelna se
doplní z něj. Výstup z `forecast_stock_needs()`. Export do XLSX/PDF
(`generate_excel_response`, `generate_pdf_response`) rozšířit o nové sloupce.

### B4. Šablona — Haiku
`templates/reports/order_report.html`: sloupce „norma", „korigováno",
„na cestě", „k objednání", „doporučené balení", odznak spolehlivosti.
Pozor na pasti z `CLAUDE.md`: ID ve formulářových atributech přes
`|unlocalize`, desetinná čárka, víceřádkové komentáře přes `{% comment %}`.

---

## 4. Fáze C — predikce budoucí ceny jídel

### C0. Realita dat — čti dřív, než navrhneš metodu

> **Opraveno 21. 9. 2026.** První verze měřila řady **po surovině se slitými
> sklady**, jenže C1 predikuje po dvojici **(surovina, sklad)** — to je první
> příčka fallback ladderu. Na správné jednotce jsou data podstatně řidší
> a divočejší, než plán původně tvrdil. Čísla níž jsou obě, protože obě
> příčky ladderu se používají.

Změřeno na `inventory_ingredientpricehistory` (3 203 záznamů,
rozsah **15. 1. – 16. 9. 2026, tj. 243 dní**):

| | po dvojici (surovina, sklad) | po surovině (sklady slité) |
|---|---|---|
| počet řad | **1 085** | 402 |
| z toho ≥ 6 cenových bodů | **128 (12 %)** | 192 (48 %) |
| medián absolutní relativní změny | **13,5 %** | 9,1 % |
| podíl nulových změn | 0,3 % | 18,2 % |
| p90 absolutní změny | **99,4 %** | — |

Levý sloupec je to, s čím C1 počítá na první příčce. Pravý platí pro
druhou příčku (fallback na jídelnu/globál).

Dvě pozorování, která se dají snadno přehlédnout:

- **Těch 18,2 % nulových změn v pravém sloupci je artefakt slévání skladů** —
  vznikne prokládáním dvou skladů se shodnou cenou. Na skutečné řadě jsou
  nulové změny 0,3 %, což odpovídá tomu, že se historie zapisuje jen při
  změně ceny. Data nejsou klidnější, než vypadají; vypadala klidnější, než
  jsou.
- **p90 změny je 99,4 %** — cena se u desetiny změn zhruba zdvojnásobí.
  Rozdělení má těžký ocas, takže pásma p10/p90 budou u části surovin široká.
  Je to poctivé, ale UI na to musí být připravené.

`StockItem.price` je **poslední nákupní cena**, ne vážený průměr
(`GoodsReceipt.confirm()`, `apps/inventory/models.py:761`) — řada je tedy
čistá posloupnost skutečně zaplacených cen, ale skáče s dodavatelem a balením.

**Důsledky, které jsou závazné:**

1. **Žádná sezonnost se z těchto dat naučit nedá.** Není ani jeden celý rok,
   takže „brambory v březnu zdraží" model nemá z čeho vzít. Kdo to zkusí
   modelovat, nafituje šum.
2. **Zákaz ARIMA / Prophet / ML / regrese s mnoha parametry.** Na 6–20 bodech
   na sérii s 13% šumem přefitují. Do `requirements.txt` nepřibude žádná
   knihovna pro time series.
3. **Predikce musí vracet interval, ne číslo.** Při 13,5% mediánovém rozptylu
   a p90 kolem 100 % je bodová cena „14,37 Kč" falešná přesnost.
4. **Trend dostane jen zhruba osminu řad.** Při prahu ≥ 6 bodů na dvojici
   (surovina, sklad) jde o 128 z 1 085. Zbylých 88 % skončí na plochém
   odhadu nebo na fallbacku — tedy velmi blízko naivní baseline. Počítejte
   s tím, že **brána v C2 může C1 zamítnout**, a berte to jako regulérní
   výsledek, ne jako selhání.

**Před spuštěním C1 měření zopakovat nad ostrými daty.** Čísla výš jsou
z kopie k 16. 9. 2026 a každý další měsíc provozu je posune. Od nich se
odvíjejí všechny prahy v C1, takže se neopisují, ale přeměřují.

### C1. Estimátor ceny — `apps/analytics/services/price_forecast.py`

`forecast_ingredient_price(ingredient, warehouse, target_date)`:

1. **Základ:** medián posledních N = 5 cen z `IngredientPriceHistory`
   za posledních 180 dní (winsorizace na 10./90. percentil série).
   Medián, ne poslední cena — poslední cena chytí jednu akční nákupku.
2. **Trend:** lineární regrese přes body posledních 180 dní, **jen pokud je
   bodů ≥ 6**. Sklon **tlumit koeficientem 0,5** a extrapolaci omezit na
   **±15 % základu** bez ohledu na to, co regrese říká. Při < 6 bodech trend 0.

   Ten práh splňuje **128 z 1 085 řad (12 %)** — viz C0. U zbytku je odhad
   plochý, tedy prakticky naivní baseline. Strop ±15 % je zhruba **jeden
   typický cenový pohyb** (medián změny 13,5 %); není odvozený z ničeho
   jemnějšího a není důvod ho dolaďovat dřív, než ho změří C2.
3. **Horizont:** nad **90 dní** dopředu se trend přestane aplikovat úplně
   (plochá extrapolace) a interval se rozšíří. Delší horizont data neunesou.
4. **Pásmo p10/p50/p90:** z **empirických reziduí** vlastní série
   (rozptyl historických relativních změn), ne z normálního rozdělení.
   Rozdělení má těžký ocas (p90 změny 99,4 %), takže u části surovin vyjde
   pásmo velmi široké. To je správný výstup, ne chyba — široké pásmo je
   informace, že se ta cena nedá předpovědět. Nezužovat ho kosmeticky.
5. **Fallback ladder** při nedostatku dat:
   (surovina, sklad) → (surovina, jídelna) → (surovina, globálně) →
   `SupplierIngredientTemplate.default_price_without_vat` →
   aktuální `StockItem.price`. Použitou úroveň vrátit ve výstupu jako `source`,
   aby UI mohlo říct „odhad z jediné ceny".

Návrat: `{p10, p50, p90, source, sample_size, horizon_days}`.

### C2. Backtest — tohle je akceptační brána, ne volitelný doplněk

`apps/analytics/services/price_backtest.py` + management command
`backtest_price_forecast`.

Walk-forward přes 8 měsíců dat: pro každou surovinu s ≥ 8 body vezmi řez
k datu T, predikuj na T+14 / T+30 / T+60 dní, porovnej se skutečností.
Metrika: **MAPE** a podíl skutečných cen uvnitř pásma p10–p90 (cíl ≈ 80 %).

**Baseline: „poslední známá cena" (naivní).**

> **Pokud estimátor z C1 neporazí naivní baseline na MAPE alespoň o 10 %
> relativně, C1 se zahodí a nasadí se naivní baseline s intervalem z C2.**
> Uživateli je lepší poctivé „cena bude jako posledně ± 12 %" než domýšlivý
> model, který se mýlí stejně a tváří se chytře. Výsledek backtestu zapiš
> do `docs/analytics_price_forecast.md` včetně tabulky MAPE.

### C3. Predikce ceny jídelníčku

`forecast_menu_plan_cost(menu_plan)` v `apps/analytics/services/menu_forecast.py`:

- pro každý `ProductionOrder` vezmi `get_required_ingredients()`
  (respektuje varianty porcí i overrides),
- ceny přes C1 k datu `order.date` — načíst **bulk pro celý jídelníček
  najednou**, ne per jídlo (viz A1),
- sečti p10/p50/p90 zvlášť → cena za jídlo, za den, za celý jídelníček,
  cena na porci; DPH přes `ProductionOrder.selling_vat_rate`,
- označ jídla, kde > 30 % nákladů stojí na surovinách se `source` na
  posledních příčkách fallback ladderu — u těch je odhad slabý.

Součet p10 a p90 přes suroviny je **konzervativní** (předpokládá plnou
korelaci cen). Je to vědomé zjednodušení a patří do dokumentace — poctivější
by byl rozklad na korelované/nekorelované složky, což tahle data neunesou.

---

## 5. Fáze D — snapshot, UI, zpětné vyhodnocení

### D1. Model `MenuPlanForecast`
`apps/analytics/models.py`:

```
MenuPlanForecast
  menu_plan     FK MenuPlan
  canteen       FK Canteen
  computed_at   DateTimeField
  computed_by   FK User, null
  stock_payload JSONField     # výstup forecast_stock_needs()
  cost_payload  JSONField     # výstup forecast_menu_plan_cost()
  cost_p50      Decimal       # denormalizováno pro řazení v seznamu
  is_stale      BooleanField  # nastaví signál při změně jídelníčku
```

Snapshot je důvod, proč není potřeba Celery: počítá se na tlačítko, čte se
z DB. Signál na `ProductionOrder` / `ProductionOrderPortionVariant` /
`ProductionOrderIngredientOverride` jen nastaví `is_stale=True` —
**nepřepočítává**. UI zobrazí „jídelníček se změnil, predikce je zastaralá,
přepočítat?".

### D2. View a šablony — Haiku
- `analytics:menu_forecast` (detail jídelníčku: potřeba surovin + cena),
- tlačítko „Přepočítat predikci" (POST, respektovat `ReadOnlyUserMiddleware`),
- odkaz z detailu jídelníčku v `apps/production` a ze seznamu v
  `analytics:menu_analytics_list`,
- **scoping na jídelnu přes `UserProfile.canteens`** v každém querysetu,
  superuser vidí vše — povinné, viz `CLAUDE.md`.

### D3. Zpětné vyhodnocení predikce
`analytics:forecast_accuracy`: u jídelníčků, které už proběhly, porovnat
uložený snapshot se skutečností (`PickingList.quantity_actual`, skutečné
příjemky). Tohle je zároveň zpětná vazba pro `ConsumptionFactor` — a jediný
způsob, jak po sezóně poznat, jestli predikce vůbec k něčemu je.

---

## 6. Pořadí a přidělení agentům

| # | Fáze | Model | Závisí na |
|---|---|---|---|
| 1 | A1 N+1 v `calculate_cost` | Sonnet | — |
| 2 | A2 služba z `generate_order_report` | Sonnet | — |
| 3 | A3 index na PickingList | Haiku | — |
| 4 | B1 `ConsumptionFactor` + command | Sonnet | A2 |
| 5 | B2 `forecast_stock_needs` | Sonnet | A2, B1 |
| 6 | C1 estimátor ceny | Sonnet | A1 |
| 7 | C2 backtest + brána | Sonnet | C1 |
| 8 | C3 cena jídelníčku | Sonnet | C1, C2 |
| 9 | D1 `MenuPlanForecast` + signály | Sonnet | B2, C3 |
| 10 | B3 + D2 views a šablony | Haiku | D1 |
| 11 | D3 zpětné vyhodnocení | Sonnet | D1 |

Body 1–3 běží paralelně. 4 a 6 také.

### Pravidla pro každého agenta (vlož do zadání)

- Číst `CLAUDE.md` **před** prvním zápisem do repa.
- Vše česky: UI, hlášky, komentáře, commit messages, CHANGELOG.
- Před commitem: `.venv/bin/python -m pytest apps test` a
  `.venv/bin/python manage.py check`.
- Migrace vygenerovat a přiložit ke commitu, který mění model.
- Stavové přechody na model, ne do view. Žádný zápis do `StockItem` mimo
  `transaction.atomic` + `select_for_update()`.
- Záznam do `CHANGELOG.md` do `[Unreleased]`.
- Conventional Commits, scope `analytics` / `reports` / `production` /
  `inventory`, tělo vysvětluje **proč**.
- Nepřidávat závislost do `requirements.txt` bez schválení — pro predikci
  žádná nová není potřeba (viz C0).

---

## 7. Rizika

1. **Osmiměsíční historie cen svádí k přeslibování.** Proti tomu stojí brána
   v C2 a povinný interval místo bodové ceny. Pokud backtest vyjde špatně,
   je správný výsledek nasadit naivní baseline, ne model doladit do vítězství
   na trénovacích datech.
2. **Korekční faktor může zakonzervovat špatnou praxi.** Pokud kuchař
   soustavně vydává méně, než recept říká, faktor to zabuduje do normy.
   Proto se v UI ukazuje `needed_raw` i `needed_corrected` vedle sebe —
   rozdíl je informace pro vedoucího, ne věc k zamlčení.
3. **Jídelny Chorvatsko a Španělsko nemají výrobní příkazy** (ty má jen
   Varvažov 459, Růžená 634, Ostrovec 235). Predikce na nich vrátí prázdno —
   ošetřit hláškou, ne dělením nulou.
4. **`quantity_actual` je vyplněná jen u `COMPLETED` položek** (5 794 z 9 835).
   Vzorek pro faktory tedy poroste v čase; práh 8 pozorování hlídá, aby se
   nepočítalo z ničeho.
