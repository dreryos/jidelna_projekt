# Projekt Jídelna

Webová aplikace v Django pro komplexní správu provozu školní nebo firemní jídelny. Umožňuje efektivně spravovat skladové zásoby, receptury, výdej surovin, plánování výroby a kalkulaci cen.

[![Django](https://img.shields.io/badge/Django-4.2.25-green.svg)](https://www.djangoproject.com/)
[![Python](https://img.shields.io/badge/Python-3.13-blue.svg)](https://www.python.org/)
[![Bootstrap](https://img.shields.io/badge/Bootstrap-5-purple.svg)](https://getbootstrap.com/)

## 📋 Funkce

### Správa receptů
- **Databáze receptů** s kategorizací (přílohy, hlavní jídla, polévky, atd.)
- **Import receptů z XML** s automatickým vytvářením surovin
- **Jednotková norma na porci** s flexibilním koeficientem velikosti
- **Kalkulace ceny** na základě aktuálních skladových cen

### Skladové hospodářství
- **Více skladů** pro každou jídelnu
- **Sledování zásob** s filtracím podle skladů
- **Automatická konverze jednotek** (g→kg, ml→l)
- **Výdejky surovin** pro výrobní příkazy

### Plánování výroby
- **Výrobní příkazy** s nastavitelným koeficientem porce
- **Denní výdejka** agregovaná ze všech výrobních příkazů
- **PDF export** výdejek pro tisk
- **Sledování stavu** výdeje surovin

### Reporty
- **Přehled potřebných surovin** pro daný den/období
- **Kontrola dostupnosti** surovin na skladě
- **Návrh objednávky** chybějících surovin

## 🏗️ Architektura

Aplikace je postavena na modulární architektuře, kde každá část systému je samostatná Django aplikace:

```
jidelna_projekt/
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
   git clone https://github.com/dreryos/jidelna_projekt.git
   cd jidelna_projekt
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

- **CHANGELOG.md** - Historie všech změn v projektu
- **docs/IMPORT_CSV.md** - Průvodce importem dat z CSV
- **component_dia.plantuml** - Diagram komponent

## 🔧 Technologie

- **Backend:** Python 3.13.7
- **Framework:** Django 4.2.25
- **Frontend:** Bootstrap 5, FontAwesome
- **Databáze:** SQLite3 (vývoj), PostgreSQL/MySQL (produkce)
- **Template Engine:** Django Templates
- **Forms:** django-bootstrap-v5

## 📊 Hlavní modely

### Core (Recepty)
- **Category** - Kategorie receptů (P1, P2, HJ, PO, atd.)
- **Ingredient** - Suroviny s podporou konverze jednotek
- **Recipe** - Recepty s kódy a kategorizací
- **RecipeIngredient** - Normy surovin v receptech

### Inventory (Sklad)
- **Canteen** - Jídelny
- **Warehouse** - Sklady přiřazené k jídelnám
- **Stock** - Skladové zásoby

### Production (Výroba)
- **MenuPlan** - Plány jídelníčků
- **ProductionOrder** - Výrobní příkazy
- **PickingList** - Výdejky surovin

## 🎯 Klíčové vlastnosti

### Konverze jednotek
Systém automaticky převádí mezi receptovými a skladovými jednotkami:
- Recepty používají **gramy (g)** a **mililitry (ml)**
- Sklady používají **kilogramy (kg)** a **litry (l)**
- Konverze probíhá automaticky pomocí `conversion_factor`

### Koeficient porce
Flexibilní úprava velikosti porcí:
- `1.0` = normální porce
- `0.5` = poloviční porce (např. děti)
- `1.5` = větší porce

### České formátování
- Desetinná čárka místo tečky (2,5 místo 2.5)
- Automatické odstranění zbytečných nul
- Podpora až 3 desetinných míst

## 📝 Licence

Tento projekt je uvolněn jako volné dílo (Public Domain) pod licencí Unlicense - viz LICENSE soubor pro detaily.

## 👥 Autoři

- **Marek** - Hlavní vývojář

## 🙏 Poděkování

- Django komunita za skvělý framework
- Bootstrap team za responzivní CSS framework
- Všem přispěvatelům open source projektů
