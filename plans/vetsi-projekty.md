# Větší projekty (backlog)

Zapsáno 5. 10. 2026, aktualizováno 12. 10. 2026 (projekt 3 hotový, projekt 2 rozpracovaný,
projekt 1 čeká na seznam od kolegů). U každého projektu je, co v kódu
a v datech už existuje, co se z nich dá říct a co zbývá rozhodnout. Čísla jsou
z kopie produkční databáze z 5. 10. 2026 a ověřují se znovu před zahájením.

| # | Projekt | Velikost | Blokováno čím |
|---|---|---|---|
| 1 | Suroviny odepisované nárazově (koření, základní suroviny) | střední | seznamem od kolegů |
| 2 | Překladová vrstva názvů surovin z příjemek | střední, po etapách | **rozpracováno**: M0, čištění, kód hotové; zbývá dodavatel + správa aliasů |
| 3 | Šablona jídelníčku z ručně zapsaného jídelníčku | malá | **hotovo** (PR #83) |

Doporučené pořadí: **3** (levné, nezávislé), **2** začít měřením, **1** až budou kolegové
mít seznam. Projekt 1 navazuje na krok 2.6 v `plans/vydejky-nezapisovana-data.md`
a nesmí se dělat dvakrát.

---

## 1. Suroviny odepisované nárazově

### Cíl

Mít **seznam surovin, které se na jídlo nevažují**: rozdělá se balení a používá se, dokud
je (koření, sůl, olej a podobně). Pro takové suroviny se:

* **nepočítá spotřeba po jídlech** a nevznikají pro ně řádky ve výdejce,
* v **odhadu nákupu** objevují jen jako **odhad**, výslovně označený, ne jako přesné číslo.

Seznam se připraví **postupně s kolegy** — rozhodují o něm lidé z kuchyně, ne data.

### Co už je

Krok **2.6** v plánu k výdejkám popisuje příznak na `Ingredient` a tabulku kódových
cest, kterých se musí dotknout (generátor řádků, blokace v `PickingList.save()`, ruční
přidání řádku, `calculate_cost()`, `generate_order_report()`) a novou kategorii odpisu.
**Zásadní z toho:** příznak se nesmí promítnout do `get_required_ingredients()`, protože ho
používá i cena jídla — pepř by z ní zmizel.

### Co data říkají

* Nula ve výdejce znamená „nevážilo se": pepř 87 % nul, kmín 86 %, olej 54 %, sůl 43 %.
  Tyhle čtyři tvoří zhruba 12 % dokončených řádků od 23. 7.
* **Spotřeba těchhle surovin v systému prakticky neexistuje.** Odpisy (`StockWriteOff`) jsou
  řídké a v kategoriích, které neodpovídají kuchyni: olej 9 odpisů (Ubytovací akce, Ostatní),
  sůl 3 (Personál RS, Ubytovací akce), **pepř a kmín žádný**. Rozdíly se srovnávaly inventurou
  (drobné: pepř −0,20, kmín −0,24 ks).
* To neodpovídá popisu, že se „jednou za čas odepsal celý balík". **Jak se to skutečně dělalo,
  z dat nevidíme — ověřit s kolegy**, než se navrhne cokoli, co na tom stojí.
* **Jediný signál, který existuje, jsou nákupy** (potvrzené příjemky): pepř 6 příjemek,
  kmín 5, olej 11 (průměr 162 l), sůl 21 (průměr 13,5 kg).

### Návrh

1. **Seznam.** Kandidáty vytáhnout z dat (vysoký podíl nul při dostatku výskytů: pepř, kmín,
   olej, česnek mražený, marmeláda, sůl, Rama) a nechat vedoucí kuchyně **potvrdit, doplnit
   a vyškrtnout**. Česnek, marmeláda a Rama jsou nejasné — nejsou to koření a nuly u nich
   mohou znamenat skutečně nevydáno.
2. **Příznak a cesty v kódu** podle 2.6 (včetně nové kategorie odpisu a migrace).
3. **Odhad nákupu pro označené suroviny** — **ne** z jídelníčku, ale z historie nákupů:
   typické množství a interval nákupů na jídelnu, přepočtené na délku plánovaného období.
   V reportu samostatná sekce **„Odhad (nepřesný)"**, aby se nepletla s přesným výpočtem
   z jídelníčku.

### Otevřené otázky

* Jak se spotřeba těchhle surovin skutečně evidovala (viz výš)?
* Odhad po jídelně, nebo společný? Ostrovec je sezónní a má jedno léto, takže z jeho
  historie nákupů se interval nedá spolehlivě odvodit.
* Má se označená surovina smět ručně přidat do výdejky? (2.6 to nechává otevřené.)
* Poslední příjemka a stav na skladě — brát v odhadu v úvahu? Odhad „zbývá na tři týdny" je
  užitečnější než „obvykle se koupí 1 ks".

### Rizika

* Odhad z řídkých nákupů je hrubý. Pepř má 6 nákupů za osm měsíců — to není statistika.
  Proto musí být v UI viditelně označený jako odhad a nic nesmí vypadat přesněji, než je.
* Změna se dotkne ceny jídla, pokud se příznak omylem promítne do
  `get_required_ingredients()`. Hlídat testem.

---

## 2. Překladová vrstva názvů surovin

### Cíl

Dodavatelé pojmenovávají totéž jinak, než jsme zvyklí my. Cíl je **lepší shoda při
příjemkách**: aby se řádek z dokladu spároval se správnou surovinou bez ručního zásahu a
aby se po jednom ručním potvrzení naučil.

### Co už je

* `apps/inventory/matching.py` — `IngredientResolver`, sedmivrstvý: naučené aliasy
  dodavatele, globální aliasy, aliasy cizích dodavatelů, pravidla na nezbožní řádky, teprve
  nakonec fuzzy (`difflib`). Aliasy (`SupplierItemAlias`) vznikají samy při potvrzení importu
  a **spravují se jen v administraci**.
* Dřívější analýza: `plans/postgresql_pgvector_a_normalizace_nazvu.md`, oddíl 3. Závěr:
  embedding ne jako první krok; nejdřív změřit, pak levné opravy (F1 `rapidfuzz`, F2 překlepy,
  F3 slovník synonymů).

### Co data říkají

Census, který se tehdy nepodařilo změřit:

* aliasů je **171**: Bolero 53, Makro 45, Bidfood 40, DK OPEN 18, Zelenina 15;
* položek příjemek **4 790**, ale `source_name` (název z dokladu) má **jen 323**, unikátních
  názvů 200. Zbytek se zadával ručně;
* z těch 323 se jen **15 (5 %)** shoduje s názvem naší suroviny, takže 95 % je skutečný překlad;
* **Oprava dřívější analýzy:** tvrdila, že „4 755 řádků příjemek je hotová označkovaná sada".
  Není — označkovaných (se `source_name`) je 323. Vzorek pro měření je řádově menší.
* **Názvy dodavatelů se v příjemkách liší:** `Makro Cash & Carry` / `makro Cash & Carry`,
  `DK OPEN, spol. s r.o.` / `DK OPEN, spol., s r.o.`, `BOLERO` / `Bolero`. Pole `supplier` je
  volný text, což alias podle dodavatele rozbíjí.
* **Kódy dodavatele existují, ale zahazují se.** V OCR anotacích má vyplněný kód (`kod`)
  **40 % položek (118 z 298)**, jenže v `SupplierItemAlias` ani `GoodsReceiptItem` pro něj
  není sloupec. Kód je u dodavatele stabilnější než název.

### Stav k 12. 10. 2026

| Krok | Stav | PR |
|---|---|---|
| M0 měření (`manage.py replay_matching`) | hotovo | #84 |
| Čištění názvů + `SYNONYMS` (část F3) | hotovo | #85 |
| Kód dodavatele u aliasu (vrstva `alias_code`) | hotovo, přínos zatím neměřitelný | #86 |
| F1 `rapidfuzz` místo `difflib` | nezačato | |
| F2 překlepy z OCR | **změřeno, zamítnuto** (viz níže) | |
| Normalizace názvu dodavatele | nezačato | |
| Správa aliasů mimo administraci | nezačato | |

**Měření M0** (323 položek na 57 dokladech, 200 názvů; aliasy ve stavu před dokladem):

| | základ | po čištění a synonymech |
|---|---|---|
| nepoznáno | 25 % | 15 % |
| automaticky předvyplněno | 37 % (97 % správně) | 39 % (97 % správně) |
| fuzzy návrh správně | 90 % | 89 % |

* **Fuzzy je lepší, než se čekalo** (86–94 % ve všech pásmech jistoty od 40 %), takže
  embedding teď nic podstatného nevyřeší. Chybí hlavně pokrytí, ne přesnost odhadu.
* **Zbylých 15 % nepoznaných** jsou značky a sémantika (`ARO RAJČAT. PYŘE` → protlak,
  `Pinova` → červené jablko), ne překlepy. Opraví je aliasy po prvním potvrzení.
* **F2 zamítnuto.** Tolerance jednoho znaku u slov od 5 znaků změnila po zpřísnění jen 2
  položky (jedna správně, jedna špatně). Širší varianta zachytila i skloňování
  (`okurky`/`okurka`) a z nově navržených řádků bylo 5 špatně a 4 správně, tedy hůř než
  stávající pásma. Nevyplatí se; vracet se k tomu jen s větším vzorkem.
* **Zkratka země jen na konci názvu** (zamítnuto): fuzzy 89 → 86 %, nepoznáno 49 → 52.
* **Pozor na přeladění:** `SYNONYMS` je vyladěný na stejném vzorku, na kterém se měří.
* **Dva dosud neověřené předpoklady:** přínos kódu dodavatele (historické doklady kód
  nemají) a reprezentativnost vzorku (323 položek jen z OCR importu, ručně zadané
  příjemky `source_name` nemají).

### Návrh (po etapách, pořadí je podstatné)

1. **M0 — změřit.** Replay harness nad 323 položkami: podíl podle vrstvy resolveru, přesnost
   fuzzy vrstvy, kolik skončí bez návrhu. Bez toho je každá další úvaha hádání. Vzorek je
   malý, takže výsledek je orientační — říct to v jeho výstupu.
2. **Levné opravy z dřívější analýzy (viz stav výše):** F1 `rapidfuzz` (už v `requirements.txt`), F2 překlepy
   z OCR, F3 slovník synonymů `SYNONYMS` v `apps/inventory/naming.py`.
3. **Nové oproti dřívější analýze: kód dodavatele.** Ukládat ho k aliasu a párovat podle něj
   jako první. Dřív ověřit, jak často kód skutečně chybí (40 % je u OCR; u Bidfood XML bude
   jiné číslo).
4. **Normalizace názvu dodavatele** (jedna kanonická podoba, vazba na `supplier_obj`).
5. **Správa aliasů mimo administraci** — vidět, upravit, sloučit špatně naučený alias.
6. Embedding **jen když** M0 a kroky 2–4 ukážou, že zbývá netriviální podíl nespárovaných
   řádků. Podmínky a omezení (musl/Alpine už neplatí, base image je `python:3.14-slim`) jsou
   v dřívější analýze, 3.3.

### Otevřené otázky

* **Kde to bolí?** Které toky (OCR z fotky, Bidfood XML, ruční příjemka) mají nejvíc
  nespárovaných řádků. Ruční příjemky `source_name` nezaznamenávají, takže se z nich
  nic nenaučí — ověřit, zda to tak je.
* Jak poznat úspěch: podíl řádků spárovaných bez ruční úpravy?
* Přejmenovat si suroviny u nás, nebo je nechat a překládat? (Cíl říká druhé.)

---

## 3. Šablona jídelníčku z ručně zapsaného jídelníčku

### Cíl

Jídelníček vytvořený **bez šablony** (ručně) jde jedním tlačítkem **uložit jako šablonu**
a příště znovu použít.

### Co už je

* `MenuTemplate` ukládá **XML** (`xml_content`) s harmonogramem: posun dne (`date_offset`),
  `recipe_code`, `meal_type`, `note`, `portion_count`. Má vizuální editor, duplikování a
  zpětný převod harmonogramu na slovník (`parse_schedule_to_dict`,
  `update_schedule_from_dict`).
* **Aplikuje se přes průvodce Import jídelníčku** (`menu_import_step1`–`3` v
  `template_views.py`), který z šablony vytvoří `MenuPlan` (s výchozími 50 dospělými a 0 dětskými porcemi),
  jeho `MenuPlanCoefficient` a `ProductionOrder`y; datum jídla je začátek jídelníčku + `date_offset`.
* **Kódy receptů jsou neměnné a globálně unikátní** (`KATEGORIE-NNN`), takže na ně
  šablona může spolehlivě odkazovat.
* V datech je 6 šablon a 39 jídelníčků ve 3 jídelnách. Podle názvů se část opakuje
  (Adapťáky — I./II./III. týden, víkendovky) — **dojem z názvů, ne měření**.

### Návrh

Na detailu jídelníčku akce **Uložit jako šablonu**:

* pro každý `ProductionOrder` jídelníčku: `date_offset = order.date − plan.date_from`,
  `recipe.code`, `meal_type`, případně počet porcí;
* **XML se nesklá ručně**, ale přes stávající převod ze slovníku a výsledek se ověří stejným
  parserem, kterým šablonu čte import (`parse_menu_template_xml`);
* **kulatý test:** jídelníček → šablona → import → jídelníček musí dát stejnou strukturu
  (recepty, dny, typy jídel). Bez toho nikdo nepozná, že se při převodu něco ztratilo.

### Otevřené otázky (rozhodnout před implementací)

* **Co se přenáší.** Šablona nezná úpravy surovin (`ProductionOrderIngredientOverride`,
  `RecipeOverride`), koeficienty variant porcí ani záměny jídel. Navrhuju je **nepřenášet**
  a říct to uživateli v potvrzení — ale je to rozhodnutí.
* **Záměna jídla** (`replacement_of`): uložit původní, nebo skutečně uvařené? Pro opakované
  použití dává smysl to, co se skutečně vařilo — rozhodnout s kuchyní.
* **Polévka a druhá večeře** vznikají lazy a mají vlastní typy jídel; ověřit, že je šablona
  a import umějí.
* **Jídelníček s mezerami** (dny bez jídel) a jídelníček přes víc než týden.
* **Název a popis šablony**: předvyplnit z názvu jídelníčku; hlídat duplicitní název
  (`template_check_name_ajax` už existuje).

### Odhad a rizika

Malé — hodiny až den dva, protože převod sestavuje existující kód. Jediné skutečné riziko je
**tichá ztráta dat při převodu**, proto je kulatý test povinný.
