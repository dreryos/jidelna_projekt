# TODO Seznam pro Projekt Jídelna

Tento soubor sleduje hlavní úkoly, bugy a nápady pro projekt. Pro detailnější správu úkolů použijte Issues na GitHubu/GitLabu (pokud je máte).

---

## 🚀 Priorita / Urgentní
*Věci, které je třeba vyřešit co nejdříve (např. blokující chyby).*

- [ ] Předělat tvorbu výrobních příkazů podle nové logiky plánování jídelníčku.
- [ ] Výrobní příkaz by měl mít na začátku seznam jídel z jídelníčku na daný den. A dále pokračovat seznamem surovin, které je potřeba vykladnit, vedle toho by kuchař napsal kolik doopravdy spotřeboval.
- [x] Při editaci jídelníčku možnost upravit koeficient porce přímo v řádku.
- [ ] Po uložení jídelníčku rezervovat skladové suroviny, pokud není dostatek, zobrazit upozornění na objednávku.
- [ ] Umožnit generovat výdejky na suroviny, asi nový modul "výdejky", zde se nastaví čas a sklad, a vygenerují se výdejky na všechny suroviny potřebné pro jídelníčky v daném časovém rozmezí a danou jídelnu. Vydané suroviny "rezervovat" ve skladu, po uvaření odečíst skutečnou spotřebu.

---

## 🐛 Bugy (Chyby)
*Nalezené chyby, které neblokují hlavní funkčnost, ale je třeba je opravit.*

- [x] Opravit přidávání jídla do jídelníčku, nelze přidat.

---

## ✨ Nové Funkce (Features)
*Nové části aplikace, které se mají implementovat.*

- [ ] Dashboard pro statistiky jídelny (denní přehled, nejčastěji vařená jídla, spotřeba surovin).

---

## 🧹 Vylepšení / Refaktoring
*Úklid kódu, optimalizace, aktualizace závislostí nebo technický dluh.*

- [ ] Odstranit, předělat modul výrobní příkazy pro lepší integraci s plánováním výroby.
- [ ] Reporty upravit aby byly v souladu s novou strukturou plánování jídelníčku.

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