# TODO Seznam pro Projekt Jídelna

Tento soubor sleduje hlavní úkoly, bugy a nápady pro projekt. Pro detailnější správu úkolů použijte Issues na GitHubu/GitLabu (pokud je máte).

---

## 🚀 Priorita / Urgentní
*Věci, které je třeba vyřešit co nejdříve (např. blokující chyby).*

- [ ] Příjem zboží, po získání XML souboru od dodavatele implementovat import.
- [ ] Připravit pro zelináře tabulku pro import (ať se nemusí vše zadávat ručně) - přidat dodavatele k surovinám.
- [ ] Vyřešit změnu ceny suroviny z nového příjmu - jak aktualizovat skladové ceny a historii cen.


---

## 🐛 Bugy (Chyby)
*Nalezené chyby, které neblokují hlavní funkčnost, ale je třeba je opravit.*

- [ ] Zpříjemnit práci s koeficienty porcí v jídelníčku (aktuálně se musí upravovat v detailu jídla).
- [ ] DPH u příjmu zboží - zajistit správné zaokrouhlování a výpočet celkové ceny s DPH.
- [ ] DPH u prodeje jídel - zajistit správné zaokrouhlování a výpočet celkové ceny s DPH.

---

## ✨ Nové Funkce (Features)
*Nové části aplikace, které se mají implementovat.*

- [ ] Předpřipravené jídelníčky na nejčastější akce (ŠVP, tábor - týden nebo 14 dní).
- [ ] Převodky, přesun surovin mezi sklady jídelen, přes mezisklad.
- [ ] "Předpověď ceny" jídelníčku na základě historických dat o cenách surovin.
- [ ] Modul Inventura - možnost provádět inventury skladů, generovat inventurní soupisy, porovnávat s evidencí skladu, upozornění dlouho neinventurovaných skladů.

---

## 🧹 Vylepšení / Refaktoring
*Úklid kódu, optimalizace, aktualizace závislostí nebo technický dluh.*

- [ ] U reportů pro objednávky, přidat sloupce ruční úpravy množství.
- [ ] Do reportu pro objednávky přidat i množství "s nulovým skladem".

---

## 📚 Dokumentace
*Úkoly spojené s psaním nebo aktualizací dokumentace.*


---

## 💡 Nápady / Budoucnost (Backlog)
*Věci, které by bylo fajn mít, ale nespěchají. Slouží jako zásobník nápadů.*

- [ ] Zvážit přidání tmavého režimu (dark mode).

---

## ✅ Hotovo
*Sem přesouvejte nedávno dokončené úkoly, abyste měli přehled o postupu.*

- [x] Nastavit základní strukturu projektu.
- [x] Inicializovat Git repozitář.
- [x] Zjednodušit formulář receptů (odstranit základní počet porcí).
- [x] Odstranit, předělat modul výrobní příkazy pro lepší integraci s plánováním výroby.
- [x] Reporty upravit aby byly v souladu s novou strukturou plánování jídelníčku.
- [x] Předělat tvorbu výrobních příkazů podle nové logiky plánování jídelníčku.
- [x] Výrobní příkaz by měl mít na začátku seznam jídel z jídelníčku na daný den. A dále pokračovat seznamem surovin, které je potřeba vykladnit, vedle toho by kuchař napsal kolik doopravdy spotřeboval.
- [x] Při editaci jídelníčku možnost upravit koeficient porce přímo v řádku.
- [x] Po uložení jídelníčku rezervovat skladové suroviny, pokud není dostatek, zobrazit upozornění na objednávku.
- [x] Umožnit generovat výdejky na suroviny, asi nový modul "výdejky", zde se nastaví čas a sklad, a vygenerují se výdejky na všechny suroviny potřebné pro jídelníčky v daném časovém rozmezí a danou jídelnu. Vydané suroviny "rezervovat" ve skladu, po uvaření odečíst skutečnou spotřebu.
- [x] Opravit přidávání jídla do jídelníčku, nelze přidat.
- [x] Dashboard pro statistiky jídelny (denní přehled, nejčastěji vařená jídla, spotřeba surovin).
- [x] Přidat favicon aplikace.