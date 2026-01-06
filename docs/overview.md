# Přehled projektu Jídelna

Tento projekt slouží jako komplexní systém pro správu jídelny (školní, firemní, atd.). Pokrývá celý proces od evidence receptur, přes plánování jídelníčku, správu skladu až po výdej surovin a analytiku nákladů.

## Hlavní moduly

Systém je rozdělen do několika logických modulů:

1.  **Administrace a Jádro (Core & Canteens)**
    *   Správa základních číselníků (suroviny, kategorie).
    *   Definice jídelen a jejich skladů.
    *   Správa uživatelů a jejich oprávnění k jídelnám.

2.  **Receptury a Výroba (Production)**
    *   Evidence receptů a norem.
    *   Tvorba jídelníčků (plánování).
    *   Výrobní příkazy (co se vaří, kolik porcí).
    *   Generování výdejek (Picking List) - seznam surovin k vydání ze skladu.

3.  **Sklad (Inventory)**
    *   Evidence zásob na skladech (množství, cena).
    *   Příjem zboží (Goods Receipt).
    *   Historie cen surovin.
    *   Blokace surovin pro plánovanou výrobu.

4.  **Sestavy (Reports)**
    *   Tvorba podkladů pro objednávání zboží (Order List).
    *   Exporty do PDF a Excelu.

5.  **Analytika (Analytics)**
    *   Výpočet nákladů na jídelníček a jednotlivá jídla.
    *   Sledování vývoje cen receptů v čase.
    *   Kalkulace "food cost".

## Klíčové koncepty

*   **Jídelna a Sklad**: Každá jídelna může mít více skladů (např. hlavní sklad, příruční sklad). Zásoby jsou vázány na konkrétní sklad.
*   **Recept a Norma**: Recept definuje postup a seznam surovin. Norma určuje množství suroviny na jednu porci v receptových jednotkách (g, ml).
*   **Výrobní příkaz**: Spojuje recept s konkrétním dnem a jídelnou. Určuje, kolik porcí se má uvařit.
*   **Koeficienty porcí**: Systém podporuje různé velikosti porcí (např. dětská 0.7, dospělá 1.0) v rámci jednoho vaření.
*   **Výdejka (Picking List)**: Dokument, který vzniká z výrobního příkazu a říká skladníkovi, co má vydat. Po dokončení výdeje se suroviny odečtou ze skladu.

## Technické detaily

Projekt je postaven na frameworku **Django**.
*   Databáze: SQLite (výchozí), PostgreSQL (doporučeno pro produkci).
*   Front-end: Django Templates + Bootstrap (pravděpodobně, dle standardů).
*   Generování PDF: ReportLab.
*   Generování Excel: OpenPyXL.

Dokumentace k jednotlivým modulům naleznete v samostatných souborech v této složce.
