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

### 📅 Plánování výroby a Jídelníčky
- **Tabulkový plánovač** jídelníčků s podporou variant porcí
- **Varianty porcí** (např. dospělá, dětská) v rámci jednoho jídla
- **Denní výdejka** agregovaná ze všech příkazů a variant
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

## 🏗️ Architektura

Aplikace je postavena na modulární architektuře, kde každá část systému je samostatná Django aplikace:

```
spiz/
├── apps/
│   ├── core/          # Recepty a suroviny
│   ├── inventory/     # Skladové hospodářství
│   ├── production/    # Plánování výroby a výdejky
│   ├── canteens/      # Správa jídelen
│   └── reports/       # Reporty a analýzy
├── templates/         # HTML šablony
├── docs/             # Dokumentace a XML soubory
└── manage.py         # Django management skript
```

## 🚀 Rychlý start

### Předpoklady
- Python 3.13 nebo novější
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

7. **Spuštění vývojového serveru:**
   ```bash
   python manage.py runserver
   ```

Aplikace bude dostupná na adrese [http://127.0.0.1:8000](http://127.0.0.1:8000)

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

## 📊 Hlavní modely

### Core (Recepty)
- **Category** - Kategorie receptů (P1, P2, HJ, PO, atd.)
- **Ingredient** - Suroviny s podporou konverze jednotek
- **Recipe** - Recepty s kódy a kategorizací
- **RecipeIngredient** - Normy surovin v receptech
- **UserProfile** - Rozšířený profil uživatele s vazbou na jídelny

### Inventory (Sklad)
- **Canteen** - Jídelny
- **Warehouse** - Sklady přiřazené k jídelnám
- **Stock** - Skladové zásoby

### Production (Výroba)
- **MenuPlan** - Plány jídelníčků
- **ProductionOrder** - Výrobní příkazy (vazba na jídelníček)
- **ProductionOrderPortionVariant** - Varianty porcí pro výrobní příkaz
- **PickingList** - Výdejky surovin

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
