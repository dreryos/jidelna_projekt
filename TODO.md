# TODO Seznam pro SPÍŽ

Tento soubor sleduje hlavní úkoly, bugy a nápady pro projekt. Pro detailnější správu úkolů použijte Issues na GitHubu/GitLabu (pokud je máte).

---

## 🚀 Priorita / Urgentní
*Věci, které je třeba vyřešit co nejdříve (např. blokující chyby).*

- [x] Modul bufet a odpisy zbylých jídel
- [x] Kategorie při ručním odpisu přidat kategorie (Provozní - zaměstnanci, Výchovní zaměstnanci, Učitelky)

---

## 🐛 Bugy (Chyby)
*Nalezené chyby, které neblokují hlavní funkčnost, ale je třeba je opravit.*

- [x] Šablony k manuálnímu příjmu zboží - nereflektují nastavení v adminu, jací jsou dostupní dodavatelé a co dodávají.
- [x] V manuálním příjmu zboží dát DPH dříve než než ceny - upozornění že po změně DPH znovu zadat ceny.
- [ ] Při vytvoření nové suroviny se nezobrazuje v autocomplete dokud neobnovím stránku
- [ ] Po uložení jídelníčku se nezobrazí v tabulce - až po refresh
- [x] Skladové položky si nepamatují svoji sazbu DPH (resetují se na 21 %)
- [ ] Při ručním importu aby se suroviny řadili podle abecedy, ne podle ID

---

## ✨ Nové Funkce (Features)
*Nové části aplikace, které se mají implementovat.*

- [ ] "Předpověď ceny" jídelníčku na základě historických dat o cenách surovin.


---

## 🧹 Vylepšení / Refaktoring
*Úklid kódu, optimalizace, aktualizace závislostí nebo technický dluh.*

- [x] U reportů pro objednávky, přidat sloupce ruční úpravy množství.
- [x] Do reportu pro objednávky přidat i množství "s nulovým skladem".
- [x] Možnost editace receptů v jídelníčku bez nutnosti otevírat detail receptu, avšak pouze v tom jídelníčku

---

## 📚 Dokumentace
*Úkoly spojené s psaním nebo aktualizací dokumentace.*


---

## 💡 Nápady / Budoucnost (Backlog)
*Věci, které by bylo fajn mít, ale nespěchají. Slouží jako zásobník nápadů.*

- [x] Zvážit přidání tmavého režimu (dark mode).

---

## ✅ Hotovo

- [x] Mazání surovin - opraveno ošetření chyby 500 (23.1.2025)
  - Přidáno ošetření `ProtectedError` v `IngredientAdmin`
  - Uživatelsky přívětivé chybové hlášky v češtině
  - Testy pro ověření funkcionality
  - Dokumentace v `docs/fix_ingredient_deletion.md`
*Sem přesouvejte nedávno dokončené úkoly, abyste měli přehled o postupu.*

- [x] Nastavit základní strukturu projektu.
- [x] Inicializovat Git repozitář.
- [x] Zjednodušit formulář receptů (odstranit záksladní počet porcí).
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
- [x] Přejmenování projektu.
- [x] Správa uživatelů a oprávnění (přiřazení uživatele k jídelně, omezení přístupu k datům jídelny).
- [x] Vyřešit změnu ceny suroviny z nového příjmu - jak aktualizovat skladové ceny a historii cen.
- [x] Možnost uživatelsky příjemné editace šablony jídelníčku.
- [x] Příjem zboží, po získání XML souboru od dodavatele implementovat import.
- [x] Zpříjemnit práci s koeficienty porcí v jídelníčku (aktuálně se musí upravovat v detailu jídla).
- [x] DPH u příjmu zboží - zajistit správné zaokrouhlování a výpočet celkové ceny s DPH.
- [x] DPH u prodeje jídel - zajistit správné zaokrouhlování a výpočet celkové ceny s DPH.
- [x] Tmavý režim někde blbne (některé prvky zůstávají světlé).
- [x] Modul Inventura - možnost provádět inventury skladů, generovat inventurní soupisy, porovnávat s evidencí skladu, upozornění dlouho neinventurovaných skladů.
- [x] Předpřipravené jídelníčky na nejčastější akce (ŠVP, tábor - týden nebo 14 dní).
- [x] Připravit pro zelináře tabulku pro import (ať se nemusí vše zadávat ručně) - přidat dodavatele k surovinám.
- [x] Dát možnost upravit sklad a DPH v příjmu zboží pro všechny položky naráz
- [x] DPH receptů s jakým to prodáváme
- [x] Pokud odstraním všechny řádky v manuálním příjmu zboží nelze přidat žádný řádek zpět (chyba v JS).
- [x] Převodky, přesun surovin mezi sklady jídelen, přes mezisklad.
