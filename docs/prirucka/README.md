# Příručka systému SPÍŽ

Kompletní dokumentace systému **SPÍŽ** (Systém Pro Inventuru Žvance) — webové aplikace pro správu provozu školní nebo firemní jídelny.

Příručka je určena třem skupinám čtenářů. Každá kapitola začíná praktickým návodem pro uživatele, rámečky **Proč to tak je** vysvětlují návrhová rozhodnutí a technické poznámky na konci kapitol slouží vývojářům.

## Kudy začít podle role

| Role | Doporučené kapitoly |
|---|---|
| **Kuchař / skladník** | 01, 03, 04, 05, 06, 08, 12 |
| **Vedoucí jídelny** | 01–12 (vše kromě 13) |
| **Správce systému** | 01, 02, 11, 12 |
| **Vývojář / nástupce** | 01, 13 + technické poznámky v kapitolách |

## Obsah

1. [Úvod a pojmy](01-uvod-a-pojmy.md) — co je SPÍŽ, slovník pojmů, mapa modulů, role
2. [Začínáme](02-zaciname.md) — přihlášení, nastavení jídelny, skladů a uživatelů
3. [Suroviny a receptury](03-suroviny-a-receptury.md) — karty surovin, jednotky, normy, kalkulace cen
4. [Příjem zboží](04-prijem-zbozi.md) — příjemky, dodavatelé, DPH, importy
5. [Sklady a převodky](05-sklady-a-prevodky.md) — skladové karty, převody mezi sklady, mezisklad
6. [Inventura](06-inventura.md) — fyzické počítání zásob, zamykání skladu
7. [Jídelníčky a výroba](07-jidelnicky-a-vyroba.md) — plánování, šablony, varianty porcí
8. [Výdejky](08-vydejky.md) — výdej surovin do kuchyně, blokace, PDF
9. [Odpisy a bufet](09-odpisy-a-bufet.md) — odpisy mimo recepty, import prodejů z FiskalPRO
10. [Analytika a reporty](10-analytika-a-reporty.md) — náklady, vývoj cen, objednávkový report
11. [Správa systému](11-sprava-systemu.md) — uživatelé, oprávnění, zálohy, údržba
12. [Řešení problémů](12-reseni-problemu.md) — chybové hlášky, FAQ, prevence chyb
13. [Pro vývojáře](13-pro-vyvojare.md) — architektura, datový model, návrhová rozhodnutí

## Konvence v textu

* **Tučně** názvy obrazovek, tlačítek a datových modelů (**Příjemka**, **StockItem**).
* `Kódem` názvy polí a technické identifikátory (`quantity_blocked`).
* KAPITÁLKAMI stavy dokladů (DRAFT, IN_TRANSIT, COMPLETED).
* Rámečky:
  * 💡 **Proč to tak je** — zdůvodnění návrhu.
  * ⚠️ **Pozor** — časté chyby a jak se jim vyhnout.
