# Changelog

Všechny významné změny v tomto projektu budou zdokumentovány v tomto souboru.

Formát je založen na [Keep a Changelog](https://keepachangelog.com/cs/1.0.0/),
a tento projekt dodržuje [Semantic Versioning](https://semver.org/lang/cs/).

## [0.9.1] - 2026-01-15

### Added
- **Vizuální editor šablon jídelníčků**: Nové drag-drop rozhraní pro úpravu šablon
  - Interaktivní editor s přetahováním jídel mezi dny (`menu_template_visual_edit.html`)
  - JavaScript modul s SortableJS a Select2 integrac (`menu_template_visual_edit.js`, 700+ řádků)
  - Helper metody v `MenuTemplate` modelu: `parse_schedule_to_dict()`, `update_schedule_from_dict()`, `get_stats()`
  - 5 AJAX endpointů pro operace: add-meal, remove-meal, reorder, copy-day, clear-day
  - Live statistiky (počet dnů, jídel, unikátních receptů)
  - Bulk operace: kopírování celého dne, vymazání dne
  - Autocomplete pro výběr receptů (Select2 4.1.0-rc.0)
  - Touch podpora pro tablety a mobily (SortableJS 1.15.0)
  - Confirm dialogy pro destruktivní akce
  - Toast notifikace pro zpětnou vazbu
  - Přepínač mezi vizuálním a XML režimem
  - Transparentní efekty v dark mode
  - Server-side validace s transaction atomicity
  - Dokumentace v `docs/visual_editor.md`
- **Import jídelníčku z XML šablony**: Trojkrokový proces importu jídelníčků
  - Krok 1: Výběr XML šablony pro import
  - Krok 2: Náhled importovaného menu s možností nastavení koeficientů pro jednotlivé varianty porcí
  - Krok 3: Potvrzení a finální import jídelníčku
  - Správa šablon: vytváření, editace, mazání a seznam šablon pro import jídelníčků
  - Notifikace a indikátory průběhu během celého importu
  - Podpora jmen pro varianty porcí a typu jídla (snídaně, svačina, oběd, večeře)
  - XML parser pro zpracování souborů jídelníčků (`apps/production/xml_parser.py`)
- **Import dodacího listu Bidfood z XML**: Nová funkce pro import skladových příjmů z XML souborů dodavatele Bidfood
  - Odstraněn zastaralý CSV import, nahrazen moderním XML importem
  - Parser pro XML dodací listy Bidfood (`apps/inventory/bidfood_parser.py`)
  - Dvoustupňový proces importu s náhledem a možností úprav před potvrzením
  - Šablony `bidfood_import_step1.html` a `bidfood_import_step2.html`
  - Automatické zpracování DPH s podporou různých sazeb (10%, 12%, 15%, 21%)
  - Migrace dat pro přidání polí DPH do existujících záznamů
  - Propojení skladových položek se sklady (`warehouse` pole v `GoodsReceiptItem`)
- **Inventarizace zásob**: Kompletní systém pro provádění inventur skladů
  - Seznam inventur s filtrováním podle skladu a stavu (`inventory_verification_list.html`)
  - Formulář pro vytvoření nové inventury (`inventory_verification_form.html`)
  - Potvrzovací stránka pro zahájení inventury (`inventory_verification_start_confirm.html`)
  - Rozhraní pro počítání zásob během inventury (`inventory_verification_count.html`)
  - Detail dokončené inventury s přehledem rozdílů (`inventory_verification_detail.html`)
  - Potvrzení dokončení inventury (`inventory_verification_complete_confirm.html`)
  - Potvrzení zrušení inventury (`inventory_verification_cancel_confirm.html`)
  - PDF export výsledků inventury (`verification_pdf.html`)
  - Modely `InventoryVerification` a `InventoryVerificationItem` pro správu inventur
  - Zamykání skladů během inventury (`is_locked`, `locked_by_inventory` pole v modelu `Warehouse`)
  - Automatické vytváření položek inventury ze stávajících skladových zásob
- **Jednotná stránka pro správu jídelen a skladů**: Nové rozhraní pro centralizovanou správu
  - Šablona `management.html` s modaly pro vytváření, editaci a mazání jídelen a skladů
  - AJAX operace pro všechny akce bez nutnosti reload stránky
  - JavaScript modul `management.js` (697 řádků) pro interaktivní správu
  - Zobrazení KPI statistik (počet jídelen, skladů, zamčených skladů, položek)
- **Analýza nákladů na osobu**: Nový pohled v analytice zobrazující průměrné náklady na jednoho strávníka
  - Výpočet cen na porci pro různé varianty porcí
  - Možnost filtrování podle jídelny a časového období
- **Dokumentace modulů**: Přidána kompletní dokumentace v adresáři `docs/`
  - `analytics.md` - popis modulu analytiky
  - `core_admin.md` - správa receptů a surovin
  - `inventory.md` - skladové hospodářství
  - `visual_editor.md` - vizuální editor šablon jídelníčků
  - `production.md` - výrobní plánování
  - `reports.md` - reporty
  - `overview.md` - celkový přehled projektu
  - `price_history.md` - historie cen
- **XML šablony pro jídelníčky**: Ukázkové šablony pro import
  - `static/sablona_14denni.xml` - šablona pro 14denní jídelníček
  - `static/sablona_4denni.xml` - šablona pro 4denní jídelníček
  - Ukázkové dokumenty v `docs/14denní.xml` a `docs/4denní švp.xml`
- **Upload XML souborů pro šablony jídelníčků**: Možnost nahrání XML souboru přímo z disku
  - Přidáno pole `xml_file` do formuláře `MenuTemplateForm` pro nahrání souboru
  - Uživatel může nahrát XML soubor místo kopírování jeho obsahu do textového pole
  - Automatická validace nahraného souboru s kontrolou kódování UTF-8
  - Informativní alert s odkazy na ukázkové šablony ke stažení
  - Vizuální oddělovač "NEBO" mezi nahráním souboru a textovým polem
  - Podpora formátů: `.xml`, `text/xml`, `application/xml`
- **Automatický tmavý režim**: Implementace dark mode podle systémových preferencí
  - Nový CSS soubor `static/css/dark-mode.css` s `@media (prefers-color-scheme: dark)` pravidly
  - Automatické přepínání mezi světlým a tmavým vzhledem podle nastavení operačního systému
  - Kompletní styly pro všechny komponenty: navbar, tabulky, formuláře, karty, dropdown menu, tlačítka, alerty, modal okna, pagination
  - Tmavé pozadí (#212529) se světlým textem (#f8f9fa) pro lepší čitelnost při nočním používání
  - Upravené barvy pro Bootstrap utility třídy (.bg-success, .bg-warning, .bg-danger, atd.) v tmavém režimu
  - Optimalizované pruhování tabulek s jemnými odstíny šedé místo černé a bílé
  - Podpora pro starší prohlížeče s fallback na světlý režim
  - Odstranění 111 výskytů hardcoded barev ze 16 template souborů
  - Nahrazení inline stylů Bootstrap utility třídami (.bg-light, .bg-*.bg-opacity-25, .text-muted)
  - Vyčištěné šablony: goods_receipt_detail.html, bidfood_import_step2.html, goods_receipt_form.html, stock_list.html, goods_receipt_list.html
  - CSS variables pro tabulky (--bs-table-bg, --bs-table-striped-bg, --bs-table-hover-bg)
  - Správné zobrazení .table-dark, .table-secondary, .table-light v obou režimech
- **DPH v modulu Analytika**: Počítání a zobrazování cen s DPH u jídelníčků a receptů
  - Nový soubor `apps/core/constants.py` s definicí `VAT_RATE_CHOICES` (21%, 12%, 0%)
  - Pole `selling_vat_rate` v modelu `Recipe` - výchozí DPH sazba 12% s možností volby
  - Pole `selling_vat_rate` v modelu `ProductionOrder` - DPH sazba pro každý výrobní příkaz
  - Signal `copy_vat_rate_from_recipe` v `apps/production/signals.py` - automatické kopírování DPH z receptu při vytváření nového příkazu
  - Rozšíření metody `Recipe.calculate_portion_price()` o parametr `vat_rate` a výpočet cen s DPH
    - Nový výstup: `{'total', 'per_portion', 'total_with_vat', 'per_portion_with_vat', 'vat_amount', 'vat_amount_per_portion', 'vat_rate'}`
    - Správné zaokrouhlování na 2 desetinná místa
  - Rozšíření admin rozhraní ProductionOrder o fieldset "Prodejní informace" s DPH sazbou
  - Aktualizace views `menu_detail_analytics` a `recipe_cost_detail` s výpočtem DPH
  - Rozšíření templates `menu_detail.html` a `recipe_cost_detail.html` o zobrazení cen s DPH
    - Zobrazení nákladové ceny bez DPH a prodejní ceny s DPH
    - Výpis výše DPH a DPH sazby
    - Celkové součty včetně DPH
  - Testovací skript `test_vat_implementation.py` pro ověření funkcionality
  - Migrace: `core/0005_recipe_selling_vat_rate.py`, `production/0015_productionorder_selling_vat_rate.py`

### Changed
- **Rebranding z "Jídelna" na "Spíž"**: Kompletní přejmenování projektu
  - Aktualizace všech odkazů v TODO.md a HTML šablonách
  - Přejmenování Django nastavení, URL a WSGI/ASGI konfigurací
  - Změna názvu služby v Docker Compose
  - Přejmenování adresáře `jidelna_project` na `spiz_project`
  - Aktualizace všech šablon (`base.html` a 40+ dalších)
  - Upgrade Django z verze 5.2.6 na 6.0.1
  - Aktualizace README.md s novým názvem projektu
- **Dockerfile optimalizace**: Přechod na Alpine Linux
  - Změna base image z `python:3.12-slim` na `python:3.15-rc-alpine3.23`
  - Přepis z `apt-get` na `apk` pro Alpine kompatibilitu
  - Přidání dodatečných závislostí pro Pillow (zlib-dev, jpeg-dev, libjpeg)
  - Bezpečnostní upgrade pro odstranění zranitelností (Snyk scan)
  - Přidán entrypoint skript `docker-entrypoint.sh` pro inicializaci
- **Vylepšení formuláře pro příjem zboží**: Rozšířené možnosti pro ruční vytváření příjmů
  - Přidání polí pro DPH (sazba, částka bez DPH, částka DPH)
  - Interaktivní výpočty DPH v JavaScriptu
  - Lepší validace a automatické výpočty cen
  - Vylepšené tlačítko pro mazání řádků s vizuální zpětnou vazbou
- **Admin rozhraní pro UserProfile**: Přidána správa uživatelských profilů
  - Možnost přiřazení jídelen k uživatelům
  - Lepší přehled oprávnění uživatelů
- **Vylepšení stránky detailu jídelníčku**: Interaktivnější UI
  - Aktualizované modaly pro přidávání jídel s podporou variant porcí
  - Vylepšený JavaScript pro dynamické přidávání variant
  - Template filtry v `production_filters.py` pro lepší formátování
- **Nastavení projektu**: Rozšířená konfigurace v `spiz_project/settings.py`
  - Přidány nové nastavení pro logování
  - Konfigurace pro podporu PDF generování
  - Nastavení pro správu souborů a médií
- **Formulář pro šablony jídelníčků**: Vylepšení UX při vytváření XML šablon
  - Přidána možnost nahrání XML souboru přímo z disku místo kopírování obsahu
  - Formulář `MenuTemplateForm` rozšířen o pole `xml_file` typu `FileField`
  - Pole `xml_content` je nepovinné při vytváření nové šablony (pokud se nahrává soubor)
  - Šablona `menu_template_form.html` s atributem `enctype="multipart/form-data"`
  - Informativní alert s odkazy na stažení ukázkových šablon
- **Aktualizace dependencies**: Upgrade všech balíčků na nejnovější stabilní verze
  - `django-bootstrap5`: 25.3 → 26.1
  - `pillow`: 12.0.0 → 12.1.0 (bezpečnostní oprava)
  - `fonttools`: 4.60.1 → 4.61.1
  - `reportlab`: 4.4.5 → 4.4.9
  - `sqlparse`: 0.5.3 → 0.5.5
  - `weasyprint`: 66.0 → 67.0
  - `pydyf`: 0.11.0 → 0.12.1
- **Čištění testů v production modulu**: Odstranění nepotřebných testů a zlepšení bezpečnosti
  - Odstraněny TODO testovací soubory bez skutečných testů (`test_import_views.py`, `test_xml_parser.py`)
  - Odstranění hardcoded hesel ze všech testů (bezpečnostní best practice)
  - Použití `force_login()` místo `login()` s heslem pro autentizaci v testech
  - Změna `create_user(username, password)` → `create_user(username)` bez hesla
  - Úpravy v souborech: `test_ajax_endpoints.py`, `test_archive.py`, `test_stock_blocking.py`
  - Celkem odstraněno 77 řádků, zachováno 35 funkčních testů

### Fixed
- **Přihlašovací stránka**: Opraveno zobrazování zavádějících validačních zaškrtávacích políček při chybě přihlášení
  - Validační checkmarky se nyní nezobrazují při neúspěšném přihlášení
- **Desetinná čísla v HTML5 vstupech**: Opraveno zobrazení desetinných čísel v polích pro množství surovin
  - HTML5 number inputy vyžadují tečku jako desetinný oddělovač
  - `DecimalInputWidget` byl chybně převáděl tečky na čárky, což způsobovalo odmítnutí hodnot jako "7,5"
  - Nyní widget správně zachovává tečku pro kompatibilitu s prohlížečem
- **Autocomplete dropdown v receptech**: Opravena viditelnost dropdown nabídky při výběru surovin
  - Dropdown byl oříznut kontejnerem `.table-responsive`
  - Přidány specifické CSS selektory pro správné zobrazení
  - Konsolidace CSS pravidel
- **Počítadlo položek v přehledu výrobních příkazů**: Opraveno zobrazení součtu místo konkatenace čísel
  - Výpočet počtu položek přesunut z šablony do view
  - Správné sčítání místo spojování textových řetězců
- **Ukládání receptů s novými surovinami**: Opravena chyba při vytváření nových surovin přímo z formuláře receptu
  - Odstraněna XSS zranitelnost při vytváření nových surovin
  - Odebrání zobrazení počtu porcí z formuláře receptu
  - Lepší zpracování dynamicky vytvořených surovin
- **Odstranění funkce pro přidání skladové položky**: Refaktoring views a šablon
  - Zjednodušení kódu pro správu skladových zásob
  - Odstranění duplicitní funkcionality

### Removed
- **CSV import**: Odstraněny zastaralé šablony a dokumentace pro CSV import
  - Smazány `import_csv_step1.html` a `import_csv_step2.html`
  - Odstraněna dokumentace `docs/IMPORT_CSV.md`
  - Odstraněn mock soubor `docs/mock_příjem1.csv`

### Security
- **Dockerfile security upgrade**: Oprava bezpečnostních zranitelností identifikovaných Snyk
  - SNYK-DEBIAN13-APT-5675173
  - SNYK-DEBIAN13-COREUTILS-10259260
  - SNYK-DEBIAN13-COREUTILS-5673914
  - SNYK-DEBIAN13-GLIBC-5680884
- **XSS prevence**: Opravena XSS zranitelnost při vytváření nových surovin v receptech

### Technical Details
- **Nové modely**:
  - `MenuTemplate` - šablony pro import jídelníčků
  - `InventoryVerification` - hlavní záznam inventury
  - `InventoryVerificationItem` - položky inventury
- **Nová pole**:
  - `ProductionOrder.meal_type` - typ jídla (snídaně, svačina, oběd, večeře)
  - `ProductionOrderPortionVariant.name` - název varianty porce
  - `GoodsReceiptItem.vat_rate`, `price_without_vat`, `vat_amount` - DPH pole
  - `GoodsReceiptItem.warehouse` - propojení se skladem
  - `Warehouse.is_locked`, `locked_by_inventory` - zamykání skladu
- **Migrace databáze**:
  - `production/0013_menutemplate_productionorder_meal_type.py`
  - `production/0014_productionorderportionvariant_name.py`
  - `inventory/0006_add_vat_to_goods_receipt.py`
  - `inventory/0007_populate_vat_fields.py`
  - `inventory/0008_add_warehouse_to_receipt_item.py`
  - `inventory/0009_inventoryverification_inventoryverificationitem.py`
  - `canteens/0002_warehouse_is_locked.py`
  - `canteens/0003_warehouse_locked_by_inventory.py`
- **Nové views**:
  - `apps/production/template_views.py` - 481 řádků pro správu šablon a import
  - Inventory verification views - seznam, vytvoření, zahájení, počítání, dokončení, zrušení, PDF
  - AJAX views pro správu jídelen a skladů v `management.html`
- **Nové parsery**:
  - `apps/production/xml_parser.py` - 245 řádků pro parsing XML jídelníčků
  - `apps/inventory/bidfood_parser.py` - 141 řádků pro parsing Bidfood XML
- **Nové testy**:
  - `apps/production/tests/test_import_views.py`
  - `apps/production/tests/test_xml_parser.py`

## [0.9.0] - 2025-11-25

### Added
- **Analytika a statistiky**: Přidána nová sekce na hlavní stránku (dashboard)
  - Karta "Analytika a statistiky" mezi sklady a výrobou
  - Odkazy na přehled nákladů jídelníčků a vývoj cen receptů
- **Favicon**: Přidána ikona aplikace (`favicon.png`)
  - Vytvořena struktura pro statické obrázky (`static/img`)
  - Implementováno v `base.html` pro zobrazení na všech stránkách
- **Automatické vytváření surovin ve skladu**: Při vytvoření výrobního příkazu s receptem obsahujícím novou surovinu
  - Surovina je automaticky vytvořena ve skladu s množstvím 0 ks, pokud ve skladu jídelny ještě neexistuje
  - Cena je nastavena na 0 (není známa)
  - Surovina je vytvořena v prvním skladu jídelny
  - Prevence vytváření záznamů se zápornými hodnotami
  - Zajištění, že všechny potřebné suroviny jsou viditelné v inventáři
- **Tabulka vygenerovaných výdejek**: Přidána tabulka na stránku `production/vydejky/` pro trvalý přístup k vygenerovaným výdejkám
  - Umožňuje snadnější editaci reálně vydaných položek
  - Zachování historie vygenerovaných výdejek pro budoucí reference
  - Rychlý přehled všech výdejek v systému
- **Template filtr `get_item`**: Nový filtr pro získání hodnoty ze slovníku v Django šablonách
  - Umístění: `apps/core/templatetags/core_filters.py`
  - Použití: `{{ dictionary|get_item:key }}`
  - Vrací prázdný list pokud klíč neexistuje nebo slovník je None
- **Select2 autocomplete pro výběr receptů**: Implementace vyhledávacího pole s našeptávačem v modulu tvorby jídelníčku
  - Integrace knihovny Select2 4.1.0 s Bootstrap 5 témem
  - Česká lokalizace vyhledávacího pole
  - Výrazně zlepšená použitelnost při práci s velkým množstvím receptů (171+)
  - Okamžité vyhledávání podle názvu receptu
  - Klávesová navigace a podpora mobilních zařízení
- **Rozšiřitelnost base šablony**: Přidány bloky `extra_css` a `extra_js` do `base.html`
  - Umožňuje snadné přidání dalších CSS a JavaScript knihoven do jednotlivých šablon
  - Bloky vloženy za Bootstrap CSS a JavaScript pro správné pořadí načítání
- **Uživatelské profily s přiřazením jídelen**: Nový model `UserProfile` pro správu oprávnění uživatelů
  - Model `UserProfile` propojuje uživatele s jídelnami, které smí spravovat
  - Automatické vytváření profilu při registraci uživatele pomocí Django signálů
  - Many-to-Many vztah mezi uživateli a jídelnami
- **Autorizační systém pro jídelny**: Kompletní systém kontroly přístupu k datům podle přiřazených jídelen
  - `CanteenOwnerMixin` - mixin pro class-based views s automatickou filtrací podle jídelen
  - `user_can_access_canteen_object()` - dekorátor pro function-based views
  - Superuživatelé mají přístup ke všem jídelnám
  - Běžní uživatelé vidí pouze data z přiřazených jídelen
- **Strukturované logování**: Implementace loggeru pro sledování chyb a bezpečnostních událostí
  - Logování autorizačních selhání
  - Logování chyb v AJAX endpointech
  - Detailní záznamy s traceback pro debugging

### Changed
- **Zjednodušení formuláře receptů**: Odstraněno pole "Základní počet porcí"
  - Recepty se nyní vždy počítají na 1 porci (databázově default=10, ale v UI skryto)
  - Upraven layout formuláře pro lepší využití prostoru (název a kategorie vedle sebe)
- **Konfigurace statických souborů**: Aktualizováno nastavení `STATICFILES_DIRS` v `settings.py` pro správnou podporu vlastních statických souborů (obrázků)
- **PDF výdejky optimalizované pro černobílý tisk**: Upraveno generování PDF dokumentů výdejek
  - Veškeré prvky generovány pouze v černobílých barvách
  - Zajištění dobré čitelnosti i na černobílých tiskárnách
  - Optimalizace kontrastu a čitelnosti textu pro ČB tisk
- **Vylepšená čitelnost sekce "Skutečně vydáno"**: Změněn vzhled PDF výdejek
  - Odstraněno pruhované pozadí v sekci "Skutečně vydáno" pro lepší čitelnost
  - Jednodušší a přehlednější layout pro vyplňování skutečně vydaných množství
- **Filtrování položek podle skladu jídelny**: Při generování PDF výdejky se nyní filtrují položky
  - Blokují se pouze položky ze skladu přidruženého k dané jídelně
  - Ostatní sklady se při generování výdejky neberou v úvahu
  - Přesnější řízení zásob podle jednotlivých jídelen
- **Redesign stránky editace jídelníčku**: Předělání z kartové struktury na tabulkovou
  - Stránka `/production/jidelnicky/<id>/` nyní používá tabulkový layout konzistentní se seznamem výrobních příkazů
  - **MenuPlanDetailView** (`apps/production/views.py`):
    - Přidána logika pro seskupení výrobních příkazů podle data
    - Nový context `orders_by_date` - slovník ve formátu `{datum: [seznam příkazů]}`
    - Optimalizace dotazů pomocí `select_related('recipe', 'menu_plan')` a `prefetch_related('portion_variants')`
  - **Šablona `menu_detail.html`**:
    - Změna z karet na tabulku s 5 sloupci: Den (rowspan), Jídlo, Varianty porcí, Efektivně, Akce
    - Zjednodušené CSS - odstraněny styly specifické pro karty
    - Prázdné dny se zobrazují s tlačítkem "Přidat" napříč celým řádkem
    - Vizuální oddělovače mezi dny
    - Zachování všech JavaScript handlerů s původními CSS třídami
- **Přidávání jídel do jídelníčku**: Při přidávání nového jídla do jídelníčku lze nyní rovnou definovat více variant porcí (např. malé a velké porce)
  - Nový modal `addMealModal` s podporou dynamického přidávání variant
  - Upravený view `add_meal_to_menu` podporuje pole variant místo jednoho koeficientu
  - Automatické vytvoření všech variant `ProductionOrderPortionVariant` při přidání jídla
- **Generování výdejky dne**: Aktualizováno pro práci s novým systémem variant porcí
  - View `daily_picking_list` počítá množství surovin ze všech variant porcí každého výrobního příkazu
  - Šablony `daily_picking_list.html` a `daily_picking_list_pdf.html` zobrazují varianty porcí místo `portions_adult` a `portions_child`
  - Celkový počet porcí je nyní součet efektivních porcí ze všech variant
  - Detail použití suroviny zobrazuje varianty ve formátu "30×1.0 + 20×0.75"
- **Všechny views modulu production**: Přepracovány pro podporu víceuživatelského prostředí
  - `MenuPlanListView`, `MenuPlanCreateView`, `MenuPlanDetailView`, `MenuPlanDeleteView` - použití `CanteenOwnerMixin`
  - `ProductionOrderListView`, `ProductionOrderCreateView`, `ProductionOrderUpdateView`, `ProductionOrderDeleteView` - použití `CanteenOwnerMixin`
  - AJAX views - použití `@user_can_access_canteen_object` dekorátoru
  - Filtrace jídelen v seznamech podle uživatelských oprávnění
  - Předávání uživatele do formulářů pro validaci přístupu
- **RecipeIngredient model**: Přidán explicitní `related_name="recipeingredient_set"`
  - Umožňuje přímý přístup k normám receptu: `recipe.recipeingredient_set.all()`
  - Zlepšuje čitelnost a kompatibilitu kódu
- **Transakční bezpečnost**: Přidány `@transaction.atomic` dekorátory pro všechny operace měnící data
  - Zajišťuje konzistenci dat při selhání části operace
  - Ochrana před částečnými změnami v databázi
- **Zpracování chyb v AJAX views**: Přepracováno pro lepší robustnost
  - Explicitní validace HTTP metod
  - Specifické zachytávání výjimek místo obecného `Exception`
  - Strukturované error handling s logging
  - Konzistentní JSON error responses

### Fixed
- **Ošetření nedostupných položek na skladě**: Implementováno řešení pro případ, kdy položky na blokaci nejsou na skladě
  - Systém korektně zpracovává situace s nedostatečnými zásobami
  - Upozornění nebo alternativní handling při nedostupnosti surovin
  - Prevence chyb při generování výdejek s chybějícími položkami
- **Zobrazení efektivních porcí**: Opraveno zobrazení počtu efektivních porcí v tabulce jídelníčku
  - Přidána `@property total_effective_portions` do modelu `ProductionOrder` (dříve jen metoda `get_total_effective_portions()`)
  - Aktualizovány šablony `daily_picking_list.html` a `daily_picking_list_pdf.html` na použití property místo metody
  - Nyní se správně zobrazuje číslo, ne jen text "porcí"
- **Tlačítko pro přidání jídla k dni**: Opravena CSS třída v JavaScript handleru
  - Handler hledal `.open-add-meal-modal`, ale HTML používalo `.add-meal-to-day-btn`
  - Změna selektoru v `menu_detail.html` na řádku ~412
  - Odstraněno nefunkční tlačítko `bulkAddMealBtn` z hlavičky (funkce duplikována tlačítky u jednotlivých dnů)
- **Formuláře pro jídelníčky a výrobní příkazy**: Opravena chyba při vytváření nového jídelníčku
  - Formuláře `MenuPlanForm`, `ProductionOrderForm` a `ProductionOrderFormAdvanced` nyní správně přijímají argument `user`
  - Implementována filtrace jídelen podle uživatelských oprávnění přímo ve formulářích
  - Uživatelé vidí v select boxech pouze jídelny, ke kterým mají přístup

### Removed
- **Rychlé stažení výdejky ze seznamu jídelníčků**: Odstraněna sekce pro stažení výdejky na konkrétní den
  - Odstraněn formulář s výběrem data a jídelny z `menu_list.html`
  - Odstraněna JavaScript funkce `setToday()`
  - Funkce je stále dostupná v jiných částech aplikace

### Security
- **Kontrola přístupu k jídelnám**: Implementována granulární kontrola přístupu na úrovni objektů
  - Uživatelé nemohou zobrazit ani upravovat data z jiných jídelen
  - Ochrana na úrovni views i querysetů
  - Validace oprávnění před každou operací
- **AJAX endpoint security**: Všechny AJAX endpointy chráněny autorizací
  - Validace přístupu k menu plánům a výrobním příkazům
  - HTTP 403 response při pokusu o neoprávněný přístup
  - Logging bezpečnostních událostí

### Technical Details
- **Type hints**: Přidány type hints pro lepší type safety
  - Použití `TYPE_CHECKING` pro import typů
  - Anotace návratových typů metod
  - Cast operace pro Django User objekt
- **Migrace databáze**:
  - `0003_alter_recipeingredient_recipe_userprofile.py` - vytvoření UserProfile modelu a úprava RecipeIngredient
  - `0008_migrate_orders_to_menu_plans.py` - migrace na menu-first architekturu
    - Automatická migrace všech `ProductionOrder` bez `menu_plan` do nově vytvořených jídelníčků
    - Seskupení výrobních příkazů podle kombinace (jídelna, datum)
    - Validace existence `canteen` u všech migrovaných záznamů
    - Management command `check_orphan_orders` pro kontrolu dat před migrací
    - Podpora rollback s automatickým vymazáním vytvořených jídelníčků
    - Detailní dokumentace v `apps/production/migrations/MIGRATION_0008_README.md`

## [0.3.0] - 2025-10-27

### Added
- **Systém kategorií receptů**: Nový model `Category` pro organizaci receptů podle kategorií z receptáře (P1, P2, HJ, PO atd.)
- **Konverze jednotek**: Automatický převod mezi receptovými (g, ml) a skladovými (kg, l) jednotkami
  - Nová pole v modelu `Ingredient`: `base_unit`, `recipe_unit`, `conversion_factor`
  - Metody `convert_to_base_unit()` a `convert_to_recipe_unit()`
- **Management command `import_recipes_xml`**: Import receptů z XML souboru
  - Automatické vytváření chybějících surovin s detekcí správných jednotek
  - Import 171 receptů a ~150 surovin z `docs/recipebook.xml`
  - Parametry: `--clear` (vymazat existující), `--update` (aktualizovat)
- **Koeficient velikosti porce**: Flexibilní úprava velikosti porcí (např. 0.5 pro poloviční, 1.5 pro větší)
  - Nové pole `portion_coefficient` v modelu `ProductionOrder`
- **Kódy receptů**: Pole `code` v modelu `Recipe` pro identifikaci receptů z XML
- **Referenční počet porcí**: Pole `base_portions` v modelu `Recipe` (obvykle 10)
- **České formátování čísel**: Kompletní lokalizace pro desetinná čísla
  - Custom widget `DecimalInputWidget` s podporou čárky jako oddělovače
  - Template filtry `format_decimal` a `format_price`
  - Automatické odstranění zbytečných koncových nul
  - Podpora až 3 desetinných míst
- **CRUD pro sklady**: Kompletní správa skladů
  - Nové views: `WarehouseListView`, `WarehouseCreateView`, `WarehouseUpdateView`, `WarehouseDeleteView`
  - URL cesty: `/inventory/warehouses/`, `/inventory/warehouses/add/`, apod.
  - Šablony s Bootstrap 5 designem
- **Filtrování skladových položek**: Možnost filtrovat zásoby podle jednoho nebo více skladů najednou
- **Lokalizační soubory**: `locale/cs/formats.py` pro české formáty data a čísel

### Changed
- **Zjednodušení modelu `RecipeIngredient`**: 
  - Odstraněna pole `quantity_adult` a `quantity_child`
  - Přidáno jediné pole `quantity_per_portion` (množství na 1 porci)
  - Přidáno pole `notes` pro poznámky k surovině
- **Aktualizace výpočtu ceny**: `Recipe.calculate_portion_price()` nyní podporuje koeficient porce
  - Nová signatura: `calculate_portion_price(canteen, portions=1, portion_coefficient=1.0)`
  - Návratová hodnota: `{'total': ..., 'per_portion': ...}`
- **Optimalizace databázových dotazů**: 
  - Použití `select_related()` pro snížení počtu SQL dotazů ve views
  - Prefetch pro agregované hodnoty (počty položek ve skladech)
- **Aktualizace formulářů**: Všechny views nyní používají vlastní form classes s custom widgety
  - `RecipeForm`, `RecipeIngredientForm`, `IngredientForm` v `apps/core/forms.py`
- **Vylepšení admin rozhraní**: 
  - Přidán `CategoryAdmin` pro správu kategorií
  - Aktualizace `RecipeAdmin`, `IngredientAdmin`, `ProductionOrderAdmin` pro nová pole
  - Inline editace `RecipeIngredientInline` s novými poli

### Fixed
- **Exponenciální zápis čísel**: Opraveno zobrazování větších celých čísel (100, 1000) - místo exponenciálního zápisu (1E+2) se zobrazí normálně (100)
- **Formátování desetinných čísel**: Odstranění zbytečných koncových nul při zachování přesnosti

### Technical Details
- **Migrace databáze**:
  - `core/0002_category_...`: Vytvoření Category, rozšíření Ingredient a Recipe, změna RecipeIngredient
  - `production/0004_productionorder_portion_coefficient_...`: Přidání portion_coefficient
- **Nové moduly**:
  - `apps/core/widgets.py`: Custom widgety pro formuláře
  - `apps/core/forms.py`: Formulářové třídy
  - `apps/core/templatetags/core_filters.py`: Template filtry pro formátování
  - `apps/core/management/commands/import_recipes_xml.py`: Import z XML
- **Aktualizované šablony**:
  - `templates/core/recipe_form.html`: Nová struktura formuláře s novými poli
  - `templates/production/order_detail.html`: Použití custom filtrů
  - `templates/production/daily_picking_list.html`: České formátování čísel
  - `templates/inventory/stock_list.html`: Filtrování a české formátování
  - `templates/inventory/warehouse_*.html`: Nové šablony pro správu skladů

## [0.2.0] - 2025-10-XX

### Added
- Modul `production` pro plánování výroby
- Modul `reports` pro reporty
- MenuPlan model pro plánování jídelníčků
- PickingList model pro výdejky surovin

### Changed
- Aktualizace Django na verzi 4.2.25
- Přechod na Bootstrap 5

## [0.1.0] - 2025-10-XX

### Added
- Základní struktura Django projektu
- Modul `core` pro recepty a suroviny
- Modul `inventory` pro skladové hospodářství
- Modul `canteens` pro správu jídelen
- Admin rozhraní pro všechny moduly
- Přihlašování uživatelů

[Unreleased]: https://github.com/dreryos/spiz/compare/v0.9.0...HEAD
[0.9.0]: https://github.com/dreryos/spiz/compare/v0.3.0...v0.9.0
[0.3.0]: https://github.com/dreryos/spiz/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/dreryos/spiz/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/dreryos/spiz/releases/tag/v0.1.0
