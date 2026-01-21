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
*   **PDF**: Generováno pomocí knihovny WeasyPrint (od verze 1.x - sloučený vizuál s ostatními PDF reporty). Obsahuje:
    *   Přehlednou hlavičku s informacemi o jídelně a období
    *   Sumární statistiky (celkem surovin, dostačující zásoby, k objednání)
    *   Tabulku se sloupci: Surovina, Jednotka, Potřeba, Na skladě, K objednání, **Poznámky**
    *   Sloupec Poznámky je prázdný pro ruční vyplnění (dodavatel, termín, apod.)
    *   Zvýraznění položek k objednání tučným levým okrajem
    *   Vysvětlivky a legendu
*   **Excel**: Generováno pomocí knihovny openpyxl. Obsahuje stejné sloupce včetně prázdného sloupce Poznámky. Vhodné pro další zpracování dat.

## Pro vývojáře

*   Logika je implementována ve funkci `generate_order_report` v `apps/reports/views.py`.
*   PDF používá HTML template `apps/reports/templates/reports/order_report_pdf.html` renderovaný přes WeasyPrint (konzistentní s výdejkami a převodkami).
*   Webové zobrazení v `report_result.html` také obsahuje sloupec Poznámky pro konzistenci.
