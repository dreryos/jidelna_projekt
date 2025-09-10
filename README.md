# Projekt Jídelna

Tento projekt je webová aplikace v Django pro správu provozu školní nebo firemní jídelny. Umožňuje efektivně spravovat skladové zásoby, receptury, výdej surovin a plánování objednávek.

## Popis

Cílem aplikace je digitalizovat a zjednodušit klíčové procesy v jídelně:

- **Evidence zásob:** Sledování aktuálního stavu surovin na skladě.
- **Správa receptů:** Vedení databáze receptů a norem pro vaření.
- **Odpis surovin:** Automatizovaný odpis surovin ze skladu na základě uvařených porcí.
- **Plánování:** Generování reportů pro objednání chybějících zásob podle plánovaného jídelníčku.
- **Kalkulace:** Výpočet ceny jednotlivých porcí na základě spotřebovaných surovin.

## Architektura

Aplikace je postavena na modulární architektuře, kde každá část systému je samostatná Django aplikace:

- `sklad`: Správa skladových zásob.
- `recepty`: Evidence receptů a norem porcí.
- `vydej`: Zpracování výdeje surovin z kuchyně.
- `objednavky`: Plánování a generování objednávek.
- `reporty`: Tvorba reportů a kalkulace cen.

## Technologie

- **Backend:** Python
- **Framework:** Django
- **Databáze:** SQLite3 (pro vývoj)

## Kroky pro zprovoznění

1. **Příprava prostředí:**
    Ujistěte se, že máte nainstalovaný Python. Vytvořte a aktivujte virtuální prostředí:

    ```bash
    # Vytvoření virtuálního prostředí
    python -m venv venv

    # Aktivace na Linux/macOS
    source venv/bin/activate

    # Aktivace na Windows
    .\\venv\\Scripts\\activate
    ```

2. **Instalace závislostí:**
    Nainstalujte všechny potřebné knihovny:

    ```bash
    pip install -r requirements.txt
    ```
    *(Poznámka: soubor `requirements.txt` je potřeba vytvořit, pokud neexistuje)*

3. **Aplikace databázových migrací:**
    Tento krok vytvoří potřebné databázové tabulky.

    ```bash
    python manage.py migrate
    ```

4. **Vytvoření superuživatele:**
    Vytvořte administrátorský účet pro přístup do administrace Django.

    ```bash
    python manage.py createsuperuser
    ```

5. **Spuštění vývojového serveru:**

    ```bash
    python manage.py runserver
    ```
    Aplikace bude dostupná na adrese [http://127.0.0.1:8000](http://127.0.0.1:8000). Administrace se nachází na [http://127.0.0.1:8000/admin](http://127.0.0.1:8000/admin).
