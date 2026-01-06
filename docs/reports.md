# Modul Sestavy (Reports)

Modul pro generování tiskových sestav a exportů dat.

## Funkcionalita

### Order Report (Podklady pro objednávku)
Tento report pomáhá vedoucímu jídelny určit, co je potřeba objednat.

**Logika výpočtu:**
1.  Uživatel vybere jídelnu a období (datum od-do).
2.  Systém najde všechny `ProductionOrder` v tomto období.
3.  Pro každou objednávku sečte potřebu surovin (zohledňuje všechny varianty porcí a jejich koeficienty).
4.  Sečtená potřeba se porovná s aktuálním stavem na všech skladech dané jídelny (`StockItem`).
5.  Výsledek:
    *   **Needed**: Kolik je potřeba na vaření.
    *   **Stock**: Kolik je aktuálně na skladě.
    *   **To Order**: `max(0, Needed - Stock)` - kolik chybí a je třeba objednat.

### Exporty
*   **PDF**: Generováno pomocí knihovny ReportLab. Obsahuje přehlednou tabulku s diakritikou (používá font DejaVuSans, pokud je dostupný).
*   **Excel**: Generováno pomocí knihovny openpyxl. Vhodné pro další zpracování dat.

## Pro vývojáře

*   Logika je implementována ve funkci `generate_order_report` v `apps/reports/views.py`.
*   Pro PDF generování se dynamicky hledají fonty v systému, aby se správně zobrazovala čeština.
