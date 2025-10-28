# Changelog

Všechny významné změny v tomto projektu budou zdokumentovány v tomto souboru.

Formát je založen na [Keep a Changelog](https://keepachangelog.com/cs/1.0.0/),
a tento projekt dodržuje [Semantic Versioning](https://semver.org/lang/cs/).

## [Unreleased]

### Added
- **Select2 autocomplete pro výběr receptů**: Implementace vyhledávacího pole s našeptávačem v modulu tvorby jídelníčku
  - Integrace knihovny Select2 4.1.0 s Bootstrap 5 témem
  - Česká lokalizace vyhledávacího pole
  - Výrazně zlepšená použitelnost při práci s velkým množstvím receptů (171+)
  - Okamžité vyhledávání podle názvu receptu
  - Klávesová navigace a podpora mobilních zařízení
- **Rozšiřitelnost base šablony**: Přidány bloky `extra_css` a `extra_js` do `base.html`
  - Umožňuje snadné přidání dalších CSS a JavaScript knihoven do jednotlivých šablon
  - Bloky vloženy za Bootstrap CSS a JavaScript pro správné pořadí načítání

### Fixed
- **Formuláře pro jídelníčky a výrobní příkazy**: Opravena chyba při vytváření nového jídelníčku
  - Formuláře `MenuPlanForm`, `ProductionOrderForm` a `ProductionOrderFormAdvanced` nyní správně přijímají argument `user`
  - Implementována filtrace jídelen podle uživatelských oprávnění přímo ve formulářích
  - Uživatelé vidí v select boxech pouze jídelny, ke kterým mají přístup

### Added
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

## [1.2.0] - 2025-10-27

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

## [1.1.0] - 2025-10-XX

### Added
- Modul `production` pro plánování výroby
- Modul `reports` pro reporty
- MenuPlan model pro plánování jídelníčků
- PickingList model pro výdejky surovin

### Changed
- Aktualizace Django na verzi 4.2.25
- Přechod na Bootstrap 5

## [1.0.0] - 2025-10-XX

### Added
- Základní struktura Django projektu
- Modul `core` pro recepty a suroviny
- Modul `inventory` pro skladové hospodářství
- Modul `canteens` pro správu jídelen
- Admin rozhraní pro všechny moduly
- Přihlašování uživatelů

[Unreleased]: https://github.com/dreryos/jidelna_projekt/compare/v1.2.0...HEAD
[1.2.0]: https://github.com/dreryos/jidelna_projekt/compare/v1.1.0...v1.2.0
[1.1.0]: https://github.com/dreryos/jidelna_projekt/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/dreryos/jidelna_projekt/releases/tag/v1.0.0
