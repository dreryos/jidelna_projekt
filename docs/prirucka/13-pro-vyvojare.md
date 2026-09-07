# 13. Pro vývojáře

Kapitola pro nástupce: architektura, datový model a hlavně **proč** jsou věci navrženy tak, jak jsou. Doplňuje technické poznámky na konci předchozích kapitol a vývojářské dokumenty v `docs/` (inventory.md, production.md, price_history.md, visual_editor.md).

## Technologie a struktura

* **Django 6** / Python 3.14, šablony + Bootstrap 5, minimum JS (AJAX tam, kde to UX vyžaduje — vizuální editor se SortableJS, správa skladů).
* **SQLite** (cesta přes env `SQLITE_DB_PATH`), **WeasyPrint** pro PDF, **openpyxl** pro XLSX.
* Testy: `pytest` (`.venv/bin/python -m pytest apps test`), konfigurace `pytest.ini`.

```text
apps/
  core/        suroviny, receptury, kategorie, uživatelské profily, zálohy XML
  canteens/    jídelny, sklady (vč. meziskladu a zámku)
  inventory/   skladové karty, příjemky, dodavatelé, převodky, inventury, odpisy, cenová historie
    ocr/         import příjemky z fotky dokladu (OCR přes Mistral, normalizace, rozpoznání nezbožních řádků)
  production/  jídelníčky, šablony, výrobní příkazy, varianty porcí, overrides, výdejky, PDF
  bufet/       import prodejů z FiskalPRO
  analytics/   náklady, vývoj cen, analýzy odpisů a kuchařů
  reports/     objednávkový report
spiz_project/  settings, urls
templates/     šablony po modulech
docs/          dokumentace (tato příručka v docs/prirucka/)
```

## Datový model — jádro vztahů

```text
Canteen ─┬─< Warehouse (is_locked, is_transit_warehouse — právě 1 transit/jídelnu)
         └─< MenuPlan ─< ProductionOrder ─< PortionVariant
                              │  └─< IngredientOverride
                              └─< PickingList >─ PickingListDocument
Ingredient ─< RecipeIngredient >─ Recipe >─ Category
Ingredient ×  Warehouse → StockItem (unique together; quantity, quantity_blocked, price)
                              └─< IngredientPriceHistory (ingredient, warehouse, -valid_from)
GoodsReceipt ─< GoodsReceiptItem          Supplier ─< SupplierIngredientTemplate
GoodsReceipt ─1 GoodsReceiptScan          Supplier ─< SupplierItemAlias
StockTransfer ─< StockTransferItem        StockWriteOff ─< StockWriteOffItem
InventoryVerification ─< InventoryVerificationItem
BufetImport ─< BufetImportItem (→ StockWriteOff přes write_off_id)
UserProfile (user 1:1, canteens M2M, is_readonly)
```

Konvence: doklad = hlavička se stavem + položky s `unique_together` (doklad, surovina). Stavové přechody jsou **metody modelu** (`confirm()`, `start_transfer()`, `complete()`, …), ne logika ve views — views jen volají a překládají `ValidationError` na hlášky.

## Klíčová návrhová rozhodnutí

| Rozhodnutí | Proč | Kde |
|---|---|---|
| **Mezisklad** pro převodky | Stav „zboží na cestě“ musí být explicitní — jinak dvojí započtení nebo výdej již odeslaného zboží | `StockTransfer.start/complete_transfer()`, `Canteen.get_or_create_transit_warehouse()` |
| **Blokace** (`quantity_blocked`) místo okamžitého odečtu | Výdejka se chystá dopředu; odděluje rezervováno od vydáno, inventura sedí | `StockItem.block/unblock_quantity()`, `PickingList.save()` |
| **Vážený průměr** ceny při převodu, **poslední cena** při příjmu | Příjem = nová tržní cena; převod jen slévá zásobu a nesmí změnit její hodnotu | `_add_to_stock_with_average_price()` vs. `GoodsReceipt.confirm()` |
| **Soft delete** surovin (`is_active`) | Historické doklady musí dál odkazovat na surovinu; mazání by rozbilo audit | `Ingredient.can_be_deactivated()` — 5 podmínek |
| **Neměnný, globálně unikátní kód receptu** | Kódy žijí v XML šablonách; přejmenování/přesun kategorie nesmí rozbít odkazy | `Recipe.save()` — generování `KATEGORIE-NNN` |
| **Číslování dokladů parsováním čísel**, ne řazením stringů | `'999' > '1000'` ve stringu; kolizi řeší unique constraint, ne tichý duplikát | `StockTransfer._generate_transfer_number()` |
| **Záporný sklad dovolen** u výdeje | Provoz nesmí stát na evidenci; minus je viditelný signál k opravě | `PickingList.save()`, `StockWriteOffItem.save()` |
| **Zámek skladu** entitou inventury | Zámek má vlastníka a životní cyklus; nejde „zapomenout“ bez viditelné příčiny | `Warehouse.is_locked` + `locked_by_inventory` |
| **PDF po dnech nad 60 jídel** | WeasyPrint drží celý layout v paměti; chunking + spojení stránek drží špičku nízko | `apps/production/utils.py`, `PDF_CHUNK_MEAL_THRESHOLD` |
| **Bufet agreguje podle názvu**, ne artiklu | FiskalPRO přiděluje jeden artikl více produktům; název je jediný stabilní klíč | `apps/bufet/fiskalpro_parser.py` |
| **Cenová historie** jako append-only log | Zpětné kalkulace k datu; index `(ingredient, warehouse, -valid_from)` | signál v `StockItem.save()`, `get_prices_bulk()` |
| **OCR vytváří jen koncept příjemky** | Rozpoznaná data jsou návrh; potvrzení musí projít lidskou kontrolou, protože se jím ceny propíšou do skladu i do kalkulací | `photo_import_step3` |
| **Učení aliasů** místo fuzzy odhadu pokaždé znovu | Samotné porovnání názvů se nic nenaučí — pátý dodák od stejného dodavatele by dopadl stejně špatně jako první; potvrzené mapování se předvyplní jako hotová věc | `matching.py` (`IngredientResolver.remember()`), `SupplierItemAlias` |
| **Nesrovnaná měrná jednotka blokuje potvrzení** | Kolik kilo je jedno balení ví jen člověk; naskladnit „10“ místo „50 kg“ se pozná až na inventuře, kdy už to nikdo nedohledá | `GoodsReceiptItem.has_unit_conflict`, `goods_receipt_resolve_units` |
| **Fotka se maže, anotace zůstává** | Fotka je pracovní materiál ke kontrole při zadávání; anotace je malá a čitelná, a když se za měsíc nesejde sklad, jde z ní zjistit, co systém přečetl | `GoodsReceiptScan.delete_file()`, `ocr/storage.py` |
| **Ceny na šest desetinných míst** | Cena za skladovou jednotku vzniká dělením ceny za balení; při dvou desetinných místech se drobné položky zaokrouhlily na nulu | `GoodsReceiptItem`, `StockItem` |

## Souběh a transakce

Všechny vícekrokové skladové operace běží v `transaction.atomic` a berou skladové karty přes `select_for_update()` (převodky, inventura, potvrzení příjemky). Při rozšiřování dodržujte: **žádný zápis do `StockItem` mimo transakci s řádkovým zámkem** a žádná změna množství mimo dokladové metody.

## Jak spustit vývoj

```bash
python -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python manage.py migrate
.venv/bin/python manage.py createsuperuser
.venv/bin/python manage.py import_recipes_xml docs/recipebook.xml   # volitelně data
.venv/bin/python manage.py runserver
.venv/bin/python -m pytest        # testy
```

Alternativně `docker-compose up` (viz `Dockerfile`, `docker-entrypoint.sh`).

Import příjemky z fotky potřebuje `MISTRAL_API_KEY` (a volitelně `MISTRAL_OCR_MODEL`, `OCR_SCAN_RETENTION_DAYS` — výchozí `mistral-ocr-latest` a `7`, viz `spiz_project/settings.py`). Bez klíče je import z fotky v aplikaci vypnutý, ale zbytek vývoje i testy běží dál — testy OCR jedou nad uloženými anotacemi ve `test/fixtures/ocr/`, ne nad skutečným API.

## Kam sáhnout při rozšíření

* **Nový typ dokladu** → vzor `StockWriteOff`: hlavička + položky, stavové metody na modelu, `ValidationError` pro pravidla, atomicita.
* **Nový import** → vzor `apps/bufet/fiskalpro_parser.py`: čistý parser (bez DB) + vícekrokový průvodce se session + potvrzení tvoří doklad; testy parseru nad syntetickým souborem (`apps/bufet/tests.py`). Stejný vzor v `photo_import_step1..3`: `apps/inventory/ocr/` (parser/normalizace bez DB) + krokový průvodce se session (`photo_import_step1/2`) + potvrzení vytvoří `GoodsReceipt` (`photo_import_step3`). Test bez placeného API jde postavit nad uloženými anotacemi ve `test/fixtures/ocr/` (viz `ocr_replay`).
* **Nová analytika** → čtěte přes existující kalkulační metody (`calculate_portion_price`, `get_prices_bulk`), nepočítejte ceny znovu ve view.
* **Změna skladové logiky** → nejdřív testy: `test/test_stock_transfer_workflow.py`, `test/test_vat_implementation.py` ukazují očekávané invarianty.
* Před commitem: `pytest`, u PDF změn ruční kontrola výstupu (černobílý tisk!), CHANGELOG.md záznam česky.

## Nápověda v aplikaci (tato příručka)

Příručka z `docs/prirucka/` se builduje MkDocs (`mkdocs.yml` v kořeni, theme Material) do `staticdocs/` a servíruje se na `/napoveda/` za přihlášením (`help_index`/`help_page` v `apps/core/views.py` — záměrně mimo whitenoise, který je veřejný). Build spouští `docker-entrypoint.sh`; při vývoji `mkdocs build`, živý náhled `mkdocs serve`. Nová kapitola = nový `.md` soubor + řádek v `nav:` v `mkdocs.yml`; obrázky do `docs/prirucka/img/`.

## Známé zvláštnosti

* `GoodsReceipt.supplier` (text) vedle `supplier_obj` (FK) — postupná migrace na dodavatele s šablonami; při čtení preferujte FK s fallbackem na text.
* `MenuPlan.default_portions_adult/child` jsou legacy — varianty řeší `MenuPlanCoefficient`.
* `manage.py test` selhává na kolizi modulu `tests` (adresář `apps/production/tests` vs. soubor) — používejte `pytest`.
* Import receptur vyžaduje globálně unikátní kódy v XML (kontrola existence je per kategorie, ale DB constraint globální).
* V šablonách se ID nesmí lokalizovat v atributech formulářů (Django by u čísla nad 999 vložilo mezeru jako oddělovač tisíců) — použijte filtr `|unlocalize`; hlídá `test_template_id_localization.py`.
* Víceřádkový komentář `{# … #}` Django šablonový engine neodstraní (funguje jen na jednom řádku) a text unikne do vykreslené stránky — na víc řádků použijte `{% comment %} … {% endcomment %}`.
