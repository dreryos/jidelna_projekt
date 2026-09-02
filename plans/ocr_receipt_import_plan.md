# Plán: Import příjemek z fotky (Mistral OCR)

## Cíl

Vyfotit dodací list / prodejku / fakturu telefonem, nechat Mistral OCR vytáhnout
strukturovaná data a napojit je na stávající třístupňový import příjemek.
Podporovaní dodavatelé: BOLERO Fruit (ovoce/zelenina), Bidfood, Makro, pekárna
a libovolný další — bez psaní parseru na každý layout.

## Klíčové rozhodnutí

**Jedno JSON schéma pro všechny dodavatele.** Mistral `document_annotation_format`
dostane pydantic model a vrátí data podle něj bez ohledu na vzhled dokladu.
Rozdíly mezi dodavateli se neřeší parserem, ale:

1. **schématem, které je nadmnožinou** všech dokladů (volitelná pole: kód
   položky/EAN, počet balení, sleva, číslo objednávky),
2. **příznakem `ceny_jsou_s_dph`**, který OCR odvodí z hlaviček sloupců —
   Bolero uvádí ceny bez DPH, Makro prodejky často s DPH,
3. **quirks vrstvou** po parsování (nezbožní řádky, jednotky, násobky balení).

Stávající `bidfood_parser.py` (XML) a `supplier_csv_parser.py` (CSV) zůstávají —
jsou přesnější než OCR. Foto je cesta pro doklady, které přijdou jen na papíře.

## Architektura

```
foto → ocr/client.py     → syrový annotation JSON (+ markdown, uloženo pro audit)
     → ocr/schema.py     → pydantic validace
     → ocr/normalize.py  → kanonický receipt_data dict
     → ocr/quirks.py     → odfiltrování nezbožních řádků, per-supplier úpravy
     → resolver          → mapování názvů na Ingredient (alias tabulka)
     → step2 template    → uživatel potvrdí/opraví
     → step3             → GoodsReceipt + GoodsReceiptItem
```

### Kanonický `receipt_data`

Nadmnožina toho, co dnes vrací `parse_supplier_csv` a `parse_bidfood_xml`, aby
šly všechny tři zdroje sloučit do jednoho step2/step3:

```python
{
  'source': 'ocr' | 'csv' | 'xml',
  'receipt_number': str,
  'receipt_date': date,
  'doc_type': 'faktura' | 'prodejka' | 'dodaci_list' | 'jine',
  'supplier': str,          # název tak, jak stojí na dokladu
  'supplier_ico': str,
  'supplier_id': int | None,  # rozpoznaný Supplier.pk
  'totals': {'base': Decimal, 'vat': Decimal, 'total': Decimal},
  'items': [{
      'item_id', 'item_name', 'quantity', 'unit', 'unit_mapped',
      'price_per_unit_net', 'price_per_unit_gross',
      'vat_rate', 'vat_amount', 'total_price',
      'is_ignored', 'ignore_reason',
  }],
  'warnings': [str],
}
```

## Fáze

### Fáze 1 — OCR jádro (hotovo)
- [x] `apps/inventory/ocr/schema.py` — pydantic anotační schéma
- [x] `apps/inventory/ocr/client.py` — volání Mistralu + replay fixtur bez API
- [x] `apps/inventory/ocr/normalize.py` — annotation → `receipt_data`
- [x] `apps/inventory/ocr/quirks.py` — nezbožní řádky, mapování jednotek
- [x] settings: `MISTRAL_API_KEY`, `MEDIA_ROOT`, `MEDIA_URL`
- [x] management command `ocr_replay` pro vývoj nad `backups/bolero`
- [x] testy nad uloženými fixturami (bez síťových volání) — `test/test_ocr_receipt_normalize.py`
- [x] HEIC z iPhonu — `pillow-heif`, každý rastr se překóduje na JPEG
- [x] načítání `.env` — `python-dotenv`, proměnné prostředí mají přednost
- [x] `apps/inventory/ocr/storage.py` — dočasné úložiště skenů se lhůtou
- [x] `manage.py purge_receipt_scans` + úklid při startu kontejneru
- [x] `media_volume` v `docker-compose.yml`, `.env.example`

Ověřeno proti SDK `mistralai==2.9.4`: klient je v podbalíčku `mistralai.client`,
`ocr.process` bere `document_annotation_format` i `document_annotation_prompt`
a `document_annotation` vrací jako JSON řetězec.

### Fáze 2 — datový model mapování (hotovo)
- [x] `apps/inventory/naming.py` — `raw_key` a `core_key` z názvu položky
- [x] `Supplier.ico` (rozpoznání dodavatele podle IČO, ne podle názvu)
- [x] `SupplierItemAlias` — učící se tabulka dodavatelský název → `Ingredient`
- [x] `GoodsReceiptScan` — foto + syrový JSON u příjemky kvůli auditu
- [x] migrace `0024_supplier_ico_goodsreceiptscan_supplieritemalias`
- [x] admin pro revizi aliasů a skenů
- [x] testy — `test/test_ocr_naming.py`, `test/test_supplier_item_alias.py`

Poznámky k modelu:

- IČO se ukládá jako `NULL`, ne prázdný řetězec – prázdné řetězce by si
  kolidovaly v unikátním indexu. `Supplier.find_by_ico()` si poradí i se
  zápisem „IČ: 685 243 58", jak ho vrací OCR.
- Alias má dva unikátní klíče: `(supplier, raw_key)` pro dodavatelské aliasy
  a částečný index na `raw_key` pro globální (bez dodavatele). Bez toho druhého
  by šlo založit libovolně mnoho globálních aliasů téhož názvu, protože
  SQL považuje `NULL` hodnoty za navzájem různé.
- Alias bez suroviny a s `is_ignored` znamená „tenhle řádek na sklad nepatří".
  Takhle se doučí obalový materiál a služby, které obecné pravidlo v
  `ocr.quirks` schválně nechytá.
- `core_key` slévá zápisy téže položky: `Cibule cal.70/90 25kg NL`,
  `Cibule cal 70/90 10kg AT/NL` i `Cibule cal.70/90 25kg CZ` dají `cibule`.
  Odrůdu ale nechává být, takže `Jablko Gala` a `Jablko Golden` zůstanou
  oddělené.

### Fáze 3 — resolver názvů (hotovo)
- [x] `apps/inventory/matching.py`: `IngredientResolver` se šesti vrstvami
- [x] `find_supplier()` — rozpoznání dodavatele podle IČO, pak podle názvu
- [x] zápis aliasu při dokončení importu (samoučení)
- [x] refaktor `supplier_csv_import_step2` / `bidfood_xml_import_step2` na resolver
- [x] odstraněny překonané `_normalize_ingredient_name`
      a `_calculate_ingredient_similarity` z `views.py`
- [x] testy — `test/test_ingredient_resolver.py`

Vrstvy hledání, od nejjistější:

| # | vrstva | jistota | předvyplní se |
|---|---|---|---|
| 1 | alias dodavatele na přesný název | 100 | ano |
| 2 | alias dodavatele na přihrádku názvu | 95 | ano |
| 3 | globální alias na přesný název | 90 | ano |
| 4 | globální alias na přihrádku názvu | 85 | ano |
| 5 | alias jiného dodavatele | 70 | ne, jen návrh |
| 6 | obecné pravidlo na nezbožní řádek | 100 | ano |
| 7 | fuzzy podobnost s názvy surovin | podle skóre | ne, jen návrh |

Pořadí není libovolné:

- Aliasy jdou **před** obecným pravidlem z `ocr.quirks`. Co uživatel potvrdil,
  je silnější než to, co jsme uhádli – dodavatel může „Dopravu" prodávat
  jako zboží.
- Globální alias (bez dodavatele) platí pro všechny, takže **nevzniká sám**.
  Když se doklad nepodaří přiřadit ke konkrétnímu dodavateli, resolver si
  nic neuloží; jinak by jeden špatně pojmenovaný řádek z Makra přebil
  mapování u všech ostatních. Založit ho jde jen s `allow_global_learning`.
- Z aliasů cizích dodavatelů vyhrává nejpoužívanější – ten je nejspíš správně.

Resolver načte aliasy i suroviny jednou v konstruktoru a samotné hledání
už do databáze nechodí. Doklad má běžně deset až třicet řádků; ověřeno
testem s `django_assert_num_queries(0)`.

### Fáze 4 — UI (hotovo)
- [x] `photo_import_step1` — upload/fotoaparát, výběr skladu, volání OCR
- [x] `photo_import_step2` — náhled skenu vedle tabulky, odškrtávání řádků
- [x] `photo_import_step3` — vytvoření příjemky, samoučení včetně odmítnutých řádků
- [x] `photo_import_scan` — náhled skenu přes view s kontrolou oprávnění
- [x] smazání fotky při potvrzení příjemky (`goods_receipt_confirm`)
- [x] odkaz v nabídce „Nový příjem zboží"
- [x] testy — `test/test_photo_import_views.py`

Poznámky:

- Skeny se **neservírují z `MEDIA_URL`**. Jsou to dodavatelské doklady s cenami,
  takže jdou přes `photo_import_scan`, který ověří, že je uživatel nahrál nebo
  má přístup k jídelně příslušné příjemky.
- Krok 3 nejdřív ověří všechny řádky a teprve pak zapisuje. `transaction.atomic`
  roluje zpět výjimku, ne `return redirect()` – při dřívějším pořadí by
  po chybě uživatele zůstala v databázi rozdělaná příjemka. Stejná chyba byla
  v `supplier_csv_import_step3`, tam je opravená přes `transaction.set_rollback`.
- Odškrtnutý řádek se ukládá jako nezbožní alias, takže se systém doučí obalový
  materiál a služby, které obecné pravidlo v `ocr.quirks` schválně nechytá.
- Nová surovina se zakládá bez kategorie (`Ingredient.category` je nullable).
  Starší importy tam dosazují natvrdo `category_id=1`, což spadne, pokud
  kategorie s tím ID neexistuje.

### Fáze 5 — kontroly a audit (hotovo)
- [x] součtová kontrola položek vs. základ daně z dokladu (`ocr.normalize`)
- [x] `apps/inventory/units.py` — přepočet měrných jednotek
- [x] `apps/inventory/receipt_checks.py` — duplicita, odchylka a přesnost ceny
- [x] blokace potvrzení příjemky s nesrovnanými jednotkami
- [x] `goods_receipt_resolve_units` — obrazovka pro doplnění přepočtu
- [x] admin pro revizi aliasů (fáze 2)
- [x] testy — `test_unit_conversion.py`, `test_receipt_checks.py`,
      `test_unit_conflict_guard.py`

#### Měrné jednotky

`GoodsReceiptItem.quantity` se při potvrzení přičítá rovnou do `StockItem`,
takže musí být ve skladové jednotce suroviny. **Do fáze 5 to nekontroloval
nikdo** – ani import z CSV, ani z XML. Když dodavatel fakturoval v kusech
a sklad vedl kilogramy, naskladnilo se množství beze změny a přišlo se na to
až na inventuře.

Rozlišují se dva případy:

- **jednoznačný převod** (kg ↔ g, l ↔ ml) – poměr je daný, udělá se sám,
- **nejednoznačný** (ks → kg, bal → ks) – kolik váží jeden kus ví jen člověk.

**Kontrola sedí v `GoodsReceipt.confirm()`, ne v importech.** Potvrzení je
jediné místo, kde se mění stav skladu, takže je to jediné místo, které nejde
obejít – ani ručním založením položky, ani importem, který někdo přidá
později. Import, který přepočet nezná, položku založí s poměrem 1 a příjemka
zůstane v konceptu, dokud poměr někdo nedoplní. Spoléhat na upozornění, které
jde přehlédnout, tady nestačí – chyba se projeví až na inventuře.

Položka si pamatuje, z čeho vznikla: `source_name`, `source_unit`,
`source_quantity` a `unit_factor`. Jde tak zpětně říct „na dokladu byly
3 kartony, na skladě je 36 kusů", a `apply_unit_factor()` počítá vždy
z původního množství, takže oprava překlepu nenásobí už jednou přepočtené
číslo.

Cesta pro uživatele: potvrzení příjemky s nesrovnanými jednotkami přesměruje
na `goods_receipt_resolve_units`, kde se poměr doplní s náhledem výsledku.
Zadaná hodnota se uloží k položce **i do aliasu dodavatele**, takže se na totéž
zboží podruhé neptáme.

Při převodu se množství násobí a jednotková cena dělí, takže **celková cena
řádku zůstává stejná** – jinak by příjemka přestala sedět s dokladem.

Naučený poměr z aliasu platí jen pro jednotku, ve které se učil. Dodavatel
může přejít z kartonů na kusy a starý poměr by naskladnil dvanáctinásobek.

#### Přesnost ceny

Cenová pole měla dvě desetinná místa. U suroviny vedené v gramech vyšlo
54,90 Kč/kg jako 0,0549 Kč/g a uložilo se 0,05 – ocenění skladu o 9 % vedle.
Nezpůsobil to přepočet jednotek, jen ho zviditelnil: stejnou nepřesnost mělo
i ruční zadání ceny za gram.

Devět peněžních polí je proto rozšířeno na `max_digits=12, decimal_places=6`.
Relativní chyba zaokrouhlení je `0,5 · 10⁻ᴺ / cena`, takže:

| Kč/kg | Kč/g | N=2 | N=4 | N=6 |
|---:|---:|---:|---:|---:|
| 5 | 0,005 | >100 % | 1 % | 0,01 % |
| 20 | 0,02 | 25 % | 0,25 % | 0,002 % |
| 55 | 0,055 | 9,1 % | 0,091 % | 0,001 % |

Čtyři místa by na levné sypké zboží (mouka, brambory kolem 5–10 Kč/kg)
nestačila, šest má řádovou rezervu. `max_digits` muselo nahoru zároveň –
s `10,6` by strop spadl na 9 999,99 a nejdražší položka ve skladu stojí
3 140 Kč.

Rozšiřují se jen **jednotkové** ceny. Součty (`get_total_value`,
`total_price`) jsou počítané properties, nikde se neukládají, takže změna
nezkresluje žádnou uloženou agregaci a nepotřebuje přepočet historie.

Uživateli se dál ukazují dvě desetinná místa – 53 míst v šablonách už
používalo `floatformat:2` a existující filtr `format_price`. Skutečná past
nebyla ve zobrazení, ale ve **formulářích**: kdyby edit formulář ukázal
zaokrouhlenou cenu, stačilo by příjemku otevřít a uložit beze změny
a přesnost by byla pryč. Widget `PriceInput` proto zobrazuje plnou hodnotu
s useknutými koncovými nulami (`0,0549`, ne `0,054900`) a má `step="any"`,
protože pevný krok 0,01 by prohlížeč u takové hodnoty odmítl.

#### Pojistky v kroku 2

- **Duplicitní doklad** – stejné číslo od stejného dodavatele. Doklad koluje
  mezi lidmi a druhý ho pořídí, aniž by věděl o prvním.
- **Odchylka ceny** nad 50 % proti poslední známé (`IngredientPriceHistory`,
  jinak aktuální skladová cena). Chytá hlavně chybu čtení: „54,90" přečtené
  jako „5490" projde všemi ostatními kontrolami, protože doklad si sedí sám
  se sebou. Práh je schválně vysoký – sezónní zelenina skáče o desítky procent.

Tyhle dvě neblokují, jen upozorňují. Obě mají legitimní výjimku: dodavatel
opravdu zdražil, doklad se opravdu importuje znovu po smazání. Měrné jednotky
naopak blokují, protože tam žádná legitimní výjimka není – množství v cizí
jednotce je vždycky chyba.

#### Hygiena dat v ostré DB

Mezi skladovými jednotkami jsou i `bochník`, `balení` a `Ks` s velkým K.
Velikost písmen převod řeší, ale `bochník` a `balení` nejsou jednotky, které
by šlo na cokoli převést – u dokladů v kusech nebo kilech tyhle suroviny
skončí na obrazovce pro doplnění přepočtu.


## Otevřené body

- **Synchronní volání.** Projekt nemá Celery ani jinou frontu. OCR jednoho
  dokladu trvá jednotky sekund, což ve step1 se spinnerem projde. Dávkový import
  více fotek najednou by frontu potřeboval.
- **Náklady.** Mistral OCR se účtuje po stránkách; jeden doklad = jedna stránka.
- **Oprávnění.** Špatně potvrzený alias se tiše propíše do všech dalších dodáků.
  Zápis aliasu omezit na roli skladníka a výš, mít v adminu seznam k revizi.
- **Kontrola součtu.** Porovnává se základ daně, ne částka s DPH. Doklady počítají
  DPH ze součtu základů, takže součet řádkových cen s DPH se běžně liší o koruny
  i u správně přečteného dokladu. Na osmi skenech z `backups/bolero` projde
  kontrola základu na všech, u jednoho dokladu přitom sedí základ přesně,
  zatímco součet cen s DPH se liší o 6,54 Kč.

## Životnost skenů

Fotka dokladu je pracovní materiál, ne archiv – slouží jen ke kontrole položek
proti originálu. Na datech se nic netrénuje, takže je není proč držet.

- Po potvrzení příjemky se sken maže hned (`storage.delete_scan`, napojit ve fázi 4).
- Rozdělaný import vyprší po `OCR_SCAN_RETENTION_DAYS` (výchozí 7 dní).
- Úklid běží ze tří míst: `manage.py purge_receipt_scans` z cronu, při startu
  kontejneru, a `storage.maybe_purge()` při nahrání dalšího dokladu (nejvýš
  jednou denně). Projekt nemá plánovač, takže poslední jmenované je pojistka
  pro nasazení bez cronu.
- Rozpoznaná anotace zůstává v databázi. Je malá, čitelná a na rozdíl od fotky
  z ní jde zpětně zjistit, co systém z dokladu přečetl.

## Ověření proti živému API

Syntetický dodací list pekárny (layout nepodobný Boleru) prošel celou cestou
foto → OCR → `receipt_data` bez jediného varování: číslo dokladu, IČO, datum,
pět řádků, jednotky `ks` i rozpad DPH 12/21 %. Součet položek bez DPH sedl
na haléř proti základu daně na dokladu.

Přitom vyšla najevo chyba schématu: pole zapsaná jako `Field(None, ...)` mají
v JSON schématu `default: null`, model je pak smí vynechat a anotace se vrátí
prakticky prázdná, i když OCR dokument přečetlo celý. Řešením je `Field(...)` –
pole povinné, hodnota smí být `null`.

## Poznámky k datům z `backups/bolero`

Osm skenů od BOLERO Fruit ukazuje, co musí normalizace zvládnout:

- Každý doklad má řádek `Zaokrouhlení` (i záporný) — není to zboží.
- Názvy nesou zemi původu (`Jablko Gala IT`), gramáž (`Cibule cal.70/90 25kg NL`),
  obal (`Mrkev 5kg igelit NL`) a promo (`Banán ECU "akce"`).
- OCR překlepy: `Jabíko` místo `Jablko`, `Melloun` místo `Meloun`, `igelít`.
- Název dodavatele kolísá: `BOLERO Fruit, Aleš Bolek`, `BOLERO Fruit`,
  u jednoho skenu jen razítko `OPOČE ZELENINA` bez IČO a bez čísla dokladu.
- Jednotky jsou skoro vždy `kg`, výjimka `Salát ledový CZ | 6 ks`.
