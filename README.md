# SPÍŽ

**SPÍŽ** = **S**ystém **P**ro **I**nventuru **Ž**vance

Webová aplikace v Django pro komplexní správu provozu školní nebo firemní jídelny. Umožňuje efektivně spravovat skladové zásoby, receptury, výdej surovin, plánování výroby a kalkulaci cen.

[![Django](https://img.shields.io/badge/Django-6.0.1-green.svg)](https://www.djangoproject.com/)
[![Python](https://img.shields.io/badge/Python-3.14-blue.svg)](https://www.python.org/)
[![Bootstrap](https://img.shields.io/badge/Bootstrap-5-purple.svg)](https://getbootstrap.com/)

## 📋 Funkce

### 📊 Analytika a Dashboard
- **Přehledový dashboard** s rychlým přístupem k funkcím
- **Statistiky nákladů** jídelníčků
- **Vývoj cen** receptů v čase

### 🍳 Správa receptů
- **Databáze receptů** s kategorizací a vyhledáváním (našeptávač)
- **Import receptů z XML** s automatickým vytvářením surovin
- **Jednotková norma na porci** (vždy kalkulováno na 1 porci)
- **Kalkulace ceny** na základě aktuálních skladových cen

### 📦 Skladové hospodářství
- **Více skladů** pro každou jídelnu
- **Automatické zakládání karet** surovin při prvním použití
- **Sledování zásob** s filtrací podle skladů
- **Automatická konverze jednotek** (g→kg, ml→l)
- **Převodky mezi sklady** přes mezisklad („zboží na cestě")
- **Inventura** se zamčením skladu, včetně hromadného vynulování skladu
- **Odpisy mimo recepty** a import prodejů z pokladny FiskalPRO

### 🧾 Příjem zboží a dodavatelé
- **Dvoufázová příjemka** (koncept → potvrzení), potvrzením se propíší ceny a DPH do skladu
- **Import příjemky z fotky dokladu** přes Mistral OCR — vyfoťte dodací list, systém navrhne položky a vy je jen zkontrolujete
- **Učení dodavatelských názvů**: potvrzené mapování názvu na surovinu se uloží a příště se předvyplní samo
- **Hlídání měrných jednotek**: doklad v balení vs. sklad v kilogramech se nepotvrdí, dokud nedoplníte přepočet
- **Importy dodacích listů** z Bidfood XML a dodavatelského CSV
- **Šablony položek dodavatelů** pro rychlé zadání opakovaných závozů
- **Cenová historie** každé změny skladové ceny pro zpětné kalkulace

### 📅 Plánování výroby a Jídelníčky
- **Tabulkový plánovač** jídelníčků s podporou variant porcí
- **Varianty porcí** (např. dospělá, dětská) v rámci jednoho jídla
- **Denní výdejka** agregovaná ze všech příkazů a variant
- **Záměna jídla** za jiný recept s přepočtem surovin na stejný počet porcí
- **Druhá večeře a polévka** jako karty mimo jídelníček
- **Zrušení výdeje** u chybně vydané položky (vrátí zboží na sklad)
- **PDF export** optimalizovaný pro černobílý tisk
- **Historie výdejek** s možností zpětné editace

### 👥 Uživatelé a Oprávnění
- **Granulární řízení přístupu** k datům jednotlivých jídelen
- **Uživatelské profily** s přiřazením k jídelnám
- **Bezpečné oddělení dat** mezi provozy

### 📈 Reporty
- **Přehled potřebných surovin** pro daný den/období
- **Kontrola dostupnosti** surovin na skladě
- **Návrh objednávky** chybějících surovin

### 📖 Nápověda v aplikaci
- **Kompletní česká příručka** (13 kapitol) dostupná na `/napoveda/` za přihlášením
- Generuje ji MkDocs ze zdrojů v `docs/prirucka/`

## 🏗️ Architektura

Aplikace je postavena na modulární architektuře, kde každá část systému je samostatná Django aplikace:

```
spiz/
├── apps/
│   ├── core/          # Recepty, suroviny, uživatelské profily, zálohy XML
│   ├── canteens/      # Jídelny a sklady (včetně meziskladu a zámku)
│   ├── inventory/     # Skladové hospodářství, příjemky, dodavatelé, inventury
│   │   └── ocr/       # Rozpoznávání dokladů z fotky (Mistral OCR)
│   ├── production/    # Plánování výroby a výdejky
│   ├── bufet/         # Import prodejů z pokladny FiskalPRO
│   ├── analytics/     # Náklady, vývoj cen, analýzy odpisů a kuchařů
│   └── reports/       # Reporty a analýzy
├── templates/         # HTML šablony
├── docs/              # Dokumentace a XML soubory
│   └── prirucka/      # Zdroje uživatelské příručky pro MkDocs
├── staticdocs/        # Sestavená nápověda (generuje `mkdocs build`)
└── manage.py          # Django management skript
```

## 🚀 Rychlý start

### Předpoklady
- Python 3.14 nebo novější
- pip (správce balíčků)

### Instalace

1. **Klonování repositáře:**
   ```bash
   git clone https://github.com/dreryos/spiz.git
   cd spiz
   ```

2. **Vytvoření virtuálního prostředí:**
   ```bash
   python -m venv .venv
   
   # Aktivace na Windows (PowerShell)
   .\.venv\Scripts\Activate.ps1
   
   # Aktivace na Linux/macOS
   source .venv/bin/activate
   ```

3. **Instalace závislostí:**
   ```bash
   pip install -r requirements.txt
   ```

4. **Aplikace migrací databáze:**
   ```bash
   python manage.py migrate
   ```

5. **Vytvoření superuživatele:**
   ```bash
   python manage.py createsuperuser
   ```

6. **Import ukázkových receptů (volitelné):**
   ```bash
   python manage.py import_recipes_xml docs/recipebook.xml
   ```

7. **Sestavení nápovědy (volitelné):**
   ```bash
   mkdocs build
   ```

8. **Spuštění vývojového serveru:**
   ```bash
   python manage.py runserver
   ```

Aplikace bude dostupná na adrese [http://127.0.0.1:8000](http://127.0.0.1:8000)

### Konfigurace přes proměnné prostředí

Všechny mají rozumnou výchozí hodnotu, takže pro vývoj není potřeba nastavovat nic.

| Proměnná | Výchozí | K čemu je |
|---|---|---|
| `SECRET_KEY` | vývojový klíč | Podpisový klíč Djanga — v produkci nastavte vlastní |
| `DEBUG` | `True` | V produkci `False` |
| `DJANGO_ALLOWED_HOSTS` | `localhost,127.0.0.1,testserver` | Povolené domény |
| `CSRF_TRUSTED_ORIGINS` | `http://localhost,http://127.0.0.1` | Důvěryhodné originy pro CSRF |
| `SQLITE_DB_PATH` | `db.sqlite3` v kořeni | Umístění databáze |
| `MEDIA_ROOT` | `media/` | Úložiště nahraných souborů (skeny dokladů) |
| `MISTRAL_API_KEY` | prázdný | Klíč pro rozpoznávání dokladů z fotky. Bez něj je import z fotky vypnutý, zbytek aplikace běží dál |
| `MISTRAL_OCR_MODEL` | `mistral-ocr-latest` | Model OCR |
| `OCR_SCAN_RETENTION_DAYS` | `7` | Za jak dlouho se smažou nedokončené skeny dokladů |

## 📚 Dokumentace

- **[docs/prirucka/](docs/prirucka/README.md)** - Kompletní příručka (uživatelé, správci, vývojáři)
- **[docs/overview.md](docs/overview.md)** - Přehled modulů a vývojářská dokumentace
- **CHANGELOG.md** - Historie všech změn v projektu

Příručka je v aplikaci dostupná jako **Nápověda** (`/napoveda/`, za přihlášením). Web nápovědy generuje MkDocs:

```bash
mkdocs build    # jednorázové sestavení do staticdocs/
mkdocs serve    # živý náhled při psaní dokumentace (http://127.0.0.1:8000)
```

## 🔧 Technologie

- **Backend:** Python 3.14
- **Framework:** Django 6.0.1
- **Frontend:** Bootstrap 5, FontAwesome, Select2
- **Databáze:** SQLite3 (vývoj), PostgreSQL/MySQL (produkce)
- **Template Engine:** Django Templates
- **Forms:** django-bootstrap-v5
- **PDF:** WeasyPrint (výdejky, převodky, odpisy, reporty)
- **XLSX:** openpyxl (import prodejů z FiskalPRO)
- **OCR:** Mistral OCR (rozpoznávání dokladů z fotky), Pillow + pillow-heif pro zpracování fotek
- **Dokumentace:** MkDocs s tématem Material
- **Testy:** pytest (`pytest.ini`)

## 📊 Hlavní modely

### Core (Recepty)
- **Category** - Kategorie receptů (P1, P2, HJ, PO, atd.)
- **Ingredient** - Suroviny s podporou konverze jednotek
- **Recipe** - Recepty s kódy a kategorizací
- **RecipeIngredient** - Normy surovin v receptech
- **UserProfile** - Rozšířený profil uživatele s vazbou na jídelny

### Canteens (Jídelny)
- **Canteen** - Jídelny
- **Warehouse** - Sklady přiřazené k jídelnám (včetně meziskladu a zámku při inventuře)

### Inventory (Sklad)
- **StockItem** - Skladová karta suroviny (množství, blokace, cena, DPH)
- **IngredientPriceHistory** - Historie skladových cen pro zpětné kalkulace
- **GoodsReceipt** / **GoodsReceiptItem** - Příjemky a jejich položky
- **GoodsReceiptScan** - Sken dokladu, ze kterého příjemka vznikla (fotka se po potvrzení maže, anotace zůstává)
- **Supplier** / **SupplierIngredientTemplate** - Dodavatelé a šablony jejich položek
- **SupplierItemAlias** - Naučené mapování dodavatelského názvu na surovinu včetně přepočtu jednotek
- **StockTransfer** / **StockTransferItem** - Převodky mezi sklady
- **InventoryVerification** / **InventoryVerificationItem** - Inventury
- **StockWriteOff** / **StockWriteOffItem** - Odpisy mimo recepty

### Production (Výroba)
- **MenuTemplate** - Šablony opakujících se jídelníčků
- **MenuPlan** - Plány jídelníčků
- **ProductionOrder** - Výrobní příkazy (vazba na jídelníček)
- **ProductionOrderPortionVariant** - Varianty porcí pro výrobní příkaz
- **ProductionOrderIngredientOverride** - Ruční úpravy surovin u konkrétního jídla
- **PickingListDocument** / **PickingList** - Výdejkové dokumenty a položky výdejek

### Bufet
- **BufetImport** / **BufetImportItem** - Importy prodejů z pokladny FiskalPRO a jejich párování na suroviny

## 🎯 Klíčové vlastnosti

### 🔐 Bezpečnost a Oprávnění
- **Izolace dat**: Uživatelé vidí pouze data jídelen, ke kterým mají přístup
- **Role**: Superuživatelé (přístup ke všemu) vs. Běžní uživatelé (omezený přístup)
- **Audit**: Logování bezpečnostních událostí a chyb

### 🔄 Konverze jednotek
Systém automaticky převádí mezi receptovými a skladovými jednotkami:
- Recepty používají **gramy (g)** a **mililitry (ml)**
- Sklady používají **kilogramy (kg)** a **litry (l)**
- Konverze probíhá automaticky pomocí `conversion_factor`

### ⚖️ Varianty a Koeficienty
Flexibilní úprava velikosti porcí:
- **Varianty**: Možnost definovat více variant porcí pro jedno jídlo (např. 100x dospělá, 50x dětská)
- **Koeficienty**: Přepočet norem podle velikosti porce (např. 0.7 pro dětskou porci)

### 🇨🇿 České prostředí
- Desetinná čárka místo tečky (2,5 místo 2.5)
- Automatické odstranění zbytečných nul
- Podpora až 3 desetinných míst
- Lokalizované formáty data a času

## 📝 Licence

Tento projekt je uvolněn jako volné dílo (Public Domain) pod licencí Unlicense - viz LICENSE soubor pro detaily.

## 👥 Autoři

- **Marek** - Hlavní vývojář

## 🙏 Poděkování

- Django komunita za skvělý framework
- Bootstrap team za responzivní CSS framework
- Všem přispěvatelům open source projektů
