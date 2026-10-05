# Plán: nezapisované výdejky na Varvažově a Ostrovci

Měřeno 22. 9. 2026 nad produkční kopií, **aktualizováno 5. 10. 2026** nad novou
kopií po zpětném doplnění výdejek kolegou. Původní text níž popisuje stav
k 22. 9.; co se od té doby změnilo, je hned tady.

## Aktualizace 5. 10. 2026

**Kolega doplnil 3 742 položek ručně.** Nezavřené položky na Varvažově
2 277 → 0, na Ostrovci 1 444 → 0; `quantity_blocked` na Varvažově
44 997 → 403, na Ostrovci 13 067 → 0. Hodnoty nejsou slepě opsaný plán
(shoda přesně s plánem 1 %). Tím se potvrdilo, že úkon je proveditelný;
problém není schopnost, ale **včasnost** — trvalo to dva a půl měsíce.

**Ostrovec je sezónní** (léto), jinak se chodí na jídlo do Varvažova. Chybějící
doklady a příjemky po srpnu nejsou výpadek zápisu.

**Koření se na jídlo nevážilo.** Pepř, kmín, sůl a olej se odepisovaly jednou za
čas po celém balení. Nula u nich ve výdejce proto znamená „nevážilo se", ne
„nevydalo se" (pepř 87 % nul, kmín 86 %, olej 54 %, sůl 43 %).

**Dvě různé populace dat.** Řádky doplněné zpětně z papíru (3 619) a řádky
zadané průběžně v systému (7 336) se chovají zásadně jinak:

| | zpětně z papíru | zadáno průběžně |
|---|---|---|
| nula | 38 % | 20 % |
| nenulové přesně = plán | **1 %** | **41 %** |
| nenulové do ±5 % plánu | 11 % | 47 % |
| nenulové > 10× plán | **7,1 %** | 2,4 % |

Čtení (hypotéza, ne měření): u průběžného zadání se plán často **opisuje** —
41 % hodnot je přesně rovných plánu —, kdežto hodnoty z papíru jsou skutečné
a od plánu se liší skoro vždy. Papírové hodnoty jsou tedy pravděpodobně
věrnější, ale mají víc chyb jednotek (7,1 % vs 2,4 %). Řádky nejsou
v databázi označené, odkud pocházejí, takže je nejde zpětně spolehlivě oddělit.

**Sklad po odepsání spadl do mínusu.** Karet v mínusu: Varvažov 5 → 56
(Σ −2 348), Ostrovec 0 → 40 (Σ −1 211), Růžená 57 → 62 (Σ −8 067). Příčin je víc
(viz „Chyby jednotek" níž), skutečný stav srovná jedině inventura.

**Zadané množství mnohonásobně přesahuje plán.** U 299 dokončených položek
(3,7 % nenulových) je zadáno víc než 10× plán. Poměr k plánu ale **nerozliší
několik různých věcí**:

* **celá balení** — plán je zlomek, odebírá se celé balení (droždí 1 kg,
  kanystr oleje, 10 kg soli); většina z pásma 10–50×. Totéž je chléb níž,
* **chybný převodní faktor** — loupáček: plán 0,16 ks, zadáno 200. Surovina
  má `ks → ks`, ale `conversion_factor` 1000, takže se plán dělí tisícem
  (viz „Past s výchozím faktorem 1000" níž). Kuchaři zadávají správně;
  špatný je plán,
* **granularita celých balení u chleba** — plán je zlomek bochníku
  (plátky na porci), ale odebírá se celý bochník (nejčastěji zadáno 1).
  **Není to chyba**: sklad chleba sedí (příjemky 890 bochníků, odepsáno
  ~779, zůstatky +17 / 0,5 / −2),
* **skutečné překlepy jednotek** — máslo: plán 0,67 kg, zadáno 375; petrželka
  mražená: plán 0,027, zadáno 150.

Kolik řádků je skutečný překlep, z poměru určit nejde. Dřívější odhad „70 %
záporných stavů Varvažova jsou chyby jednotek" se **nedrží**: počítal se
všemi řádky > 10×, tedy i celými baleními. Největší mínusy Varvažova (jogurt
−621 ks, mléko −511 l, brambory −276 kg) vypadají spíš na chybějící příjemky.

**Důsledky pro tento plán:** fáze 1 se nerealizuje; tlačítko „vydat podle
plánu" **se nestaví** (viz 2.1); přibývá evidence koření souhrnně (2.6)
a **kontrola nesmyslného množství (2.7) se musí navrhnout jinak, než
se původně počítalo**. QR a brána OCR zůstávají.

## Co se děje

| jídelna | 05 | 06 | 07 | 08 | 09 |
|---|---|---|---|---|---|
| Růžená | 100 % | 100 % | 95 % | 100 % | 65 % |
| Varvažov | 100 % | 100 % | **7 %** | **0 %** | **0 %** |
| Ostrovec | — | — | **22 %** | **0 %** | — |

Podíl dokončených položek výdejek. Růžená po změně UI z 22. 7. zapisuje dál,
takže **příčina není v aplikaci**. Je to lidský proces na dvou jídelnách:
papír existuje, do systému se nepřepisuje.

Rozpad dokumentů na Varvažově je binární:

```
98 dokumentů:  66 netknutých   0 částečně vyplněných   32 hotových
```

**Nula částečně vyplněných.** Kdyby vadila zdlouhavost po řádcích, byly by
vidět rozdělané dokumenty. Jednotkou selhání je celý denní papír, ne řádek —
proto nula a koš (obojí řeší řádek) nemohly pomoct.

Nedokončené položky nejsou balast: 115 různých surovin, polovinu nesou
suroviny typu sůl, olej, rohlík, cibule, mouka. Legitimní řádky, které
nikdo nepřepsal.

## Škoda, která už vznikla

```
Varvažov   2 277 nezavřených položek   blokuje 44 594 jednotek na 116 kartách
Ostrovec   1 444                       blokuje 13 067 na 103 kartách
Růžená       287                       blokuje  2 735 na  80 kartách
```

Objednávkový report odečítá blokace od dostupné zásoby, takže těm dvěma
jídelnám tvrdí, že mají míň, než mají. **Modul „nefunguje" kvůli datům,
ne kvůli kódu** — jeho testy procházejí (15/15).

> **Pozor na to, co úklid nedokáže.** Jídlo se uvařilo a suroviny se
> spotřebovaly, jen to nikdo nezapsal. Ať se s těmi položkami udělá cokoli,
> skutečný stav skladu na Varvažově a Ostrovci se z databáze zrekonstruovat
> nedá. Srovná ho **jedině fyzická inventura.** Úklid níž zařídí, aby
> přestaly lhát blokace — víc ne, a nemá se to tak prodávat.

---

## Fáze 1 — úklid zaseknutých blokací

> **Nerealizovat. Překonáno 5. 10. 2026** — kolega zaseknuté položky doplnil
> ručně se skutečnými hodnotami, což je lepší než cokoli, co by doplnil
> automat. Text níž zůstává jako **záloha pro případ, že se to příští sezónu
> znovu nakupí**. Jediné, co se dělá už teď, je **1.3** (varování), protože to
> zabrání opakování.

### 1.1 Příznak `auto_closed` na `PickingList`

Jedno boolean pole + migrace. Důvod: uzavření dávkou vyrobí `quantity_actual`,
které nikdo neviděl. Bez příznaku by se ta čísla později míchala do statistik
spotřeby (fáze B plánu predikce) a tvářila se jako pozorování.

### 1.2 Management command `close_stale_picking_documents`

```
--canteen <název>     povinné, ať se nezavře omylem všechno
--before <datum>      jen dokumenty starší
--dry-run             výchozí chování, zápis až s --commit
```

Pro položky `PENDING` v dotčených dokumentech nastaví
`quantity_actual = quantity_planned`, `status = COMPLETED`, `auto_closed = True`.

**Proč plán a ne nula:** jídlo se uvařilo. Nula by uvolnila blokaci, ale sklad
by zůstal nadhodnocený o všechno, co se od července spotřebovalo — tedy dál
špatně, jen jinak. Plán je nejbližší dostupný odhad skutečnosti.

Výstup dry-runu: počet dokumentů a položek, součet uvolněné blokace a součet
odepsaného množství, po jídelnách. Tohle číslo chce vidět vedoucí jídelny
**před** spuštěním, ne po něm.

### 1.3 Aby to znovu nenarostlo

Nejlevnější varianta: na přehledu výdejek ukázat počet nezavřených položek
starších než 14 dní jako varování. Žádný automat, který zavírá sám —
při 0% zápisu by tiše vyráběl fikci.

---

## Fáze 2 — zlevnit zápis

Pořadí je podstatné a není to pořadí podle zajímavosti:

| # | Krok | Náklad | Kdy |
|---|---|---|---|
| 2.1 | ~~tlačítko „vydat vše podle plánu"~~ | — | **nestavět** |
| 2.2 | QR do tištěné výdejky | půl dne | hned, nezávisle |
| 2.3 | OCR jednoho papíru | dny | až po 2.5 |
| 2.4 | dávkový sken štosu | dny | až po 2.3 |
| 2.5 | brána proveditelnosti | hodiny | **před 2.3** |
| 2.6 | koření a základní suroviny souhrnně | půl dne | po rozhodnutí, které suroviny |
| 2.7 | kontrola nesmyslného množství při zadání | hodiny | **přepracovat** (poměr k plánu nestačí) |

**2.1 a 2.2 se dělají hned a nezávisle na sobě.** U 2.2 platí, že funguje jen
na papírech vytištěných po té změně, takže každý týden odkladu je další štos
bez kódu — a to i v případě, že se k OCR nikdy nedojde.

### 2.1 Tlačítko „vydat vše podle plánu" (levná varianta)

Na výdejce jedno tlačítko, které vyplní všem nevydaným řádkům plán, a kuchař
opraví jen to, co sedělo jinak. Jednotka akce je celý dokument — přesně ta,
na které se to dnes láme.

> **Nestavět. Přeměřeno 5. 10. 2026.** Právě u zpětně doplňovaných řádků, tedy
> u toho, k čemu tlačítko mělo sloužit, je plán správně (do ±5 %) jen u **7 %**
> všech řádků, 34–38 % je nula a zbytek jsou jiné hodnoty. Předvyplnění by
> uživatele nutilo opravovat devět řádků z deseti — a hlavně by **institucionalizovalo
> opisování plánu**, což je přesně to, co u průběžně zadaných dat vidíme
> (41 % nenulových hodnot přesně rovných plánu). Dostali bychom víc dat,
> ale horších.
>
> Původní odhad „14–26 % shoda" byl špatná míra a hodnoty z různých
> populací se nedají míchat. Text níž zůstává jen jako záznam úvahy.

Odhad: půl dne. Dokud tohle nevyzkoušíte v provozu, nemá smysl stavět OCR —
možná je celý problém tady.

### 2.2 QR kód do tištěné výdejky

Samostatně užitečné, nezávislé na zbytku — a dělá se **dřív než OCR**, protože
funguje jen na papírech vytištěných po té změně. Každý týden odkladu je další
štos papírů bez kódu.

Papír se totiž musí umět spárovat se svou výdejkou. Jde to i bez kódu —
tištěné názvy surovin a plánovaná množství jsou pro každý dokument prakticky
otisk prstu — ale **nemá smysl řešit rozpoznávací úlohu, když si ten papír
tiskneme sami.** Kód dělá z pravděpodobnostního párování jistotu.

**Bez nové závislosti:** `reportlab` (už v `requirements.txt`, verze 4.5.0)
má `reportlab.graphics.barcode.qr` i `code128`. QR se vyrenderuje do SVG
nebo PNG a vloží do šablony `templates/production/picking_list_pdf.html`
jako `data:` URI — WeasyPrint si s tím poradí.

**Co kódovat.** Výchozí volba je **URL na editaci té výdejky**
(`https://<doména>/production/vydejky/<id>/edit/`), protože to zvládne
telefon fotoaparátem bez jakékoli aplikace: kuchař namíří a otevře se mu
přímo ten dokument. Přihlášení aplikace vyžaduje dál, kód sám o sobě nic
neodemyká. Alternativa je holé ID dokumentu — nic neprozrazuje o adrese
serveru, ale pak je potřeba čtečka uvnitř aplikace.

**Proč QR a ne čárový kód:** fotka nebo sken papíru bývá pootočený a QR to
snese, kdežto Code128 chce vodorovně a v rozumném rozlišení. Kdyby se někdy
kupovala ruční čtečka, `code128` je v téže knihovně a dá se přidat vedle.

**Umístění:** hlavička PDF u data a názvu jídelny, malý (cca 15 × 15 mm).
Výdejka je A5 na černobílý tisk — po zásahu do PDF **zkontrolovat výstup
okem a jeden kus vytisknout a zkusit načíst**, ne se spolehnout na náhled.

K čemu se to hodí mimo OCR: spárovat archivovaný papír s dokumentem
v systému, a otevřít výdejku na telefonu bez proklikávání.

### 2.3 OCR papírové výdejky

Až kdyby 2.1 nestačilo.

**Co se znovu nepíše** (`apps/inventory/ocr/`):

| existující | použití |
|---|---|
| `client.run_ocr()` | volání Mistralu, retry na přechodné chyby, rozbalení odpovědi |
| `client.prepare_image()` | zmenšení, HEIC, rotace z EXIF |
| `client.combine_images_to_pdf()` | víc fotek jednoho papíru |
| `storage.save_scan()` / `purge_expired_scans()` | dočasné uložení fotky a její automatické mazání |
| `matching.IngredientResolver` | párování rozpoznaných názvů na suroviny |

**Co je nové:** schéma pro výdejkový papír v `apps/production/ocr_schema.py` —
seznam `{nazev, mnozstvi, jednotka}`. Nic víc; hlavička (datum, jídelna) se
nečte, ta je známá z dokumentu, do kterého se importuje.

**Papír je vytištěný formulář, ne volný list.** `picking_list_pdf.html` tiskne
tabulku `№ | Surovina | Plánováno | Jednotka | Skutečně vydáno`, kde poslední
sloupec je prázdný na ruční zápis. Čtyři z pěti sloupců jsou tedy tištěné
a rukou přibude **jedno číslo na řádek**. To je podstatně snazší úloha, než
jsem původně odhadoval:

* identita řádku je tištěná — nemusí se z ruky rozpoznávat „Hladká mouka",
  stačí číslo řádku a pořadí je známé z dokumentu,
* rozpoznává se **jen číslice**,
* u každého řádku je vytištěný plán, takže **kontrola je zadarmo**: přečte-li
  OCR u řádku s plánem 2,50 hodnotu 25, je to skoro jistě špatně přečtená
  desetinná čárka a systém to označí sám.

**Klíčové zjednodušení oproti příjemkám:** u dodacího listu je seznam položek
otevřený a může přijít cokoli. U výdejky **už víme, co na papíře má být** —
je to ta samá výdejka, kterou aplikace vygenerovala. Z toho:

* do promptu se posílá očekávaný seznam surovin daného dokumentu,
* rozpoznaný název se páruje **jen proti řádkům té výdejky**, ne proti celému
  katalogu surovin,
* název, který v dokumentu není, je **signál chyby rozpoznání**, ne nová
  surovina. Nikdy nezakládat řádek, jen upozornit.

**Tok:** na editaci výdejky tlačítko „Načíst z fotky" → fotka → rozpoznání →
**předvyplnění polí skutečného množství** → člověk zkontroluje a uloží
stávající cestou. OCR nikdy nezapisuje do skladu přímo; stejné pravidlo jako
u příjemek, kde rozpoznání dělá jen koncept.

### 2.4 Dávkový režim — tohle je vlastní odpověď na kupení

Selhání se nekupí po řádcích, ale po dnech: jeden zapomenutý papír, pak druhý,
a kolega to přestane stíhat. Nástroj, který zpracuje **jeden dokument**, tomu
odpovídá jen zpola — pořád je to 66 samostatných úkonů.

Tok pro štos:

1. kolega **naskenuje štos** kancelářskou multifunkcí do jednoho PDF
   (lepší než fotky — rovné, konstantní osvětlení, jedna operace),
2. nahraje ten soubor,
3. systém rozdělí na stránky, z QR určí dokument a přečte sloupec čísel,
4. vznikne **fronta ke schválení**: jeden dokument = jedna obrazovka,
   předvyplněná, s označenými podezřelými hodnotami,
5. kolega odklikává, sporné opraví.

Podstatné: **kontrola nezmizí, jen se dá dělat po kouscích.** Fronta, ze které
se ukrajuje mezi jinou prací, je proti 66 samostatným výdejkám úplně jiná věc.
To je ta vlastnost, kvůli které se dávka staví.

`combine_images_to_pdf()` už v `ocr/client.py` existuje pro víc fotek jednoho
dokladu — pro opačný směr (rozdělit vícestránkové PDF na stránky) stačí
`pypdf`, také už v závislostech.

### 2.5 Brána proveditelnosti — dřív než jakékoli UI

Ručně psané číslice ve formuláři jsou snazší než volné písmo, ale **pořád není
ověřeno, že to Mistral OCR na těchhle papírech zvládne.** Zvlášť ne škrtance,
opravy přes původní číslo a desetinnou čárku.

Postup: vyžádat si **5–10 skutečných vyplněných papírů** z Varvažova, prohnat
je `run_ocr()` skriptem a změřit podíl správně přečtených čísel — zvlášť
u řádků, které se od plánu liší, protože tam je informace.

> **Když správně přečtených čísel není aspoň 90 %, fáze 2.3 se nestaví.**
> Práh je vyšší než u příjemek schválně: tady se čte jen číslice ve formuláři,
> takže horší výsledek znamená, že to ta metoda neumí. A oprava každého
> desátého čísla je horší než opsání papíru — člověk musí zkontrolovat
> všechno stejně, ale navíc nevěří tomu, co vidí. V tom případě zůstat
> u 2.1 a 2.2.

Anotace z těch papírů uložit do `test/fixtures/ocr/` jako testovací data;
testy pak běží nad nimi, nikdy proti placenému API.

### 2.6 Koření a základní suroviny souhrnně

Pepř, kmín, sůl a olej se na jídlo nevažují; dřív se odepsal celý balík jednou
za čas. Řádek ve výdejce u nich nese nulu nebo vymyšlené číslo a **zavádí
statistiku** (nula = „nevážilo se", ne „nevydalo se").

Návrh: příznak na `Ingredient` (např. `evidovat_souhrnne`), který takovou
surovinu **nezařadí do řádků výdejky** ani do blokací. Spotřeba se dál
odepisuje tak, jak dosud — odpisem celého balení.

**Rozsah, který data dokládají:** čtyři nejzřetelnější suroviny (pepř, kmín,
sůl, olej) tvoří zhruba 12 % dokončených řádků od 23. 7. (659 z 5 516).
Ostatní suroviny s vysokým podílem nul (česnek mražený 52 %, marmeláda
44 %, Rama 36 %) nejsou koření a mohou být skutečně nevydané. **Které suroviny
příznak dostanou, určí vedoucí kuchyně, ne data.**

Odhad: půl dne. Dělat až po tom, co někdo seznam potvrdí.

### 2.7 Kontrola nesmyslného množství při zadání

> **Původní návrh se nestaví.** Chtěl upozornit při zadání > 10× plán.
> Ověření na datech (5. 10.) ukázalo, že to **nefunguje**: pásmo 10–50× tvoří
> z velké části celá balení (bochník, droždí, olej, sůl), takže by se kuchaři
> ptali na legitimní věci a upozornění by přestali číst.

Co data skutečně říkají, rozpad řádků nad plán:

| poměr | řádků | co v tom je |
|---|---|---|
| 10–20× | 118 | kg 60, bochník 29, l 18, ks 11 — převážně celá balení |
| 20–50× | 79 | kg 31, bochník 30, ks 11, l 7 |
| 50–100× | 39 | bochník 29 (celé bochníky při malém plánu) |
| > 100× | 63 | bochník 30, ks 16, kg 15, l 2 |

Dvě konkrétní zjištění a obě **jsou jiná, než jsem původně psal**:

1. **Chléb (22 plátků) není chyba.** Plán je zlomek bochníku, protože porce
   počítá plátky (`conversion_factor` 22), ale vydává se celý bochník — zadané
   hodnoty jsou celá čísla (nejčastěji 1, pak 3, 2, 4). Sklad sedí. Proto
   poměr zadáno/plán u chleba (medián 18,9) **nic neříká o chybě**, je to
   zrnitost balení. Totéž platí pro jakoukoli surovinu, která se odebírá
   po celých kusech.
2. **Loupáček je skutečná chyba v datech** — viz další odstavec.

### Past s výchozím faktorem 1000

`Ingredient.conversion_factor` má **výchozí hodnotu 1000**
(`apps/core/models.py:54`; stejnou výchozí hodnotu má AJAX přidání suroviny
v `apps/core/views.py`) a `convert_to_base_unit()` jím vždy dělí. Výchozí
hodnota je správná pro `kg ← g`, ale pro surovinu s **toutéž** základní
a receptovou jednotkou je špatná. Loupáček (`ks → ks`, faktor 1000) má proto
plán 1000× menší (medián zadáno/plán 1 047). Důsledek není jen statistický:
**objednávkový report by loupáčky nikdy nenavrhl k objednání** a blokace na
skladu je 1000× podhodnocená.

Podle dat je 13 surovin s toutéž základní a receptovou jednotkou a faktorem
≠ 1. Skutečně rozbitý je z nich **jen Loupáček**, u dalších to z dat nejde
posoudit:

| surovina | jednotka | faktor | výdejek | poznámka |
|---|---|---|---|---|
| Loupáček | ks | 1000 | 6 | **rozbité** (medián 1 047) — opravit faktor na 1 |
| Tortilla | ks | 16 | 6 | medián 4,9, nejasné; ověřit |
| Dobrá voda Yess | ks | 8 | 0 | zatím nepoužito |
| Fruit&go kapsičky | ks | 1000 | 0 | zatím nepoužito, pravděpodobně chybné |
| CLIN okena | l | 1000 | 0 | zatím nepoužito, pravděpodobně chybné |
| Chléb, Vánočka (22 plátků), Toastový chléb (20) | bochník / balení | 22 / 20 | 209 / 17 / 5 | **záměrné** — faktor převádí plátky na kus |
| Cuketa, rajčata, masové kuličky | kg / g | 1000 | 1–4 | vzorek moc malý na závěr |

Návrh opravy: jednorázově opravit **Loupáček** v administraci (faktor 1)
a projít Tortillu. Případně změnit výchozí hodnotu faktoru tak, aby se při
shodných jednotkách nastavila na 1 — ale pozor, chléb a vánočka tu shodu
jednotek (`bochník → bochník`) používají záměrně s faktorem 22, takže
automatická validace „shodné jednotky ⇒ faktor 1" by je rozbila. Jednotku
u nich popisuje `recipe_unit = 'bochník'`, přestože normy v receptech jsou
v plátcích; správně by měla být `plátek`. Nechávám na rozhodnutí.

Skutečné překlepy (máslo 375 kg, petrželka 150) jsou řádově desítky.
Případná kontrola má smysl až **vůči vlastní historii suroviny**
(např. > 20× horní decil dosavadních hodnot *téže suroviny*), ne vůči plánu.
To je složitější, než jak to bylo původně nakreslené, a přínos je zatím
neprokázaný. **Nejdřív opravit loupáček a zkontrolovat zbylé suroviny z tabulky
výš a přeměřit**, teprve pak rozhodnout, zda kontrola vůbec zbyde.

---

## Co tenhle plán vědomě neřeší

**Proč se na dvou jídelnách nezapisovalo, když na třetí ano.** Aktualizace
5. 10.: kolega zaseknuté položky doplnil, takže schopnost tu je; nezapisovalo
se včas. Příčinou nejspíš není nástroj, ale kdo a kdy to má v popisu práce —
a pak žádná funkce nepomůže. Papír → systém je ruční přepis a ten se odkládá.
Proto má smysl hlavně to, co zkracuje cestu nebo zviditelňuje skluz (1.3, 2.2,
2.4), ne další pohodlí při zadávání jednotlivých polí.

**Skutečný stav skladu.** Žádný krok tohoto plánu ho nesrovnává. Záporné stavy
(Varvažov 56 karet, Ostrovec 40) srovná jedině fyzická inventura. Pro sezónní
provoz je přirozené místo **konec sezóny**; do té doby je záporný stav
viditelný signál, ne chyba k opravě.

---

## Dopad na plán predikce

`plans/predikce_zasob_a_cen_plan.md` staví fázi B na historii spotřeby.
**Aktualizace 5. 10.:** spotřeba teď existuje pro všechny tři jídelny, takže
původní předpoklad „jen Růžená" padl. Ale:

* **koření je v datech zkreslené** (nula = nevážilo se) a musí se z modelu
  „vydá se / nevydá se" vyřadit — viz 2.6;
* **zrnitost celých balení** (chléb se odebírá po bochnících, plán je zlomek)
  znamená, že poměr zadáno/plán **na úrovni jednoho jídla nemá smysl**.
  Spotřeba takových surovin se musí agregovat na úrovni dokumentu nebo dne;
  jinak by faktor "naučil", že chléb se spotřebuje 19× víc, než plán;
* **chybný převodní faktor** (loupáček) a překlepy (máslo 375 kg) je potřeba
  z dat vyčistit nebo ořezat dřív, než se počítá jakýkoli faktor — viz 2.7.
  Poměr k plánu jako filtr nestačí;
* **Varvažov a Ostrovec mají jednu sezónu**, takže sezónnost se nedá naučit;
* **hodnoty zadané průběžně jsou z 41 % přesně rovné plánu** (u zpětně
  z papíru 1 %). Takové řádky o odchylce od plánu nic nevypovídají. Pro
  faktory spotřeby se proto řádky **přesně rovné plánu nesmí počítat jako
  pozorování** — medián poměru skutečnost/plán vychází 1,000 právě kvůli té
  bodové mase, ne proto, že by normy seděly.
