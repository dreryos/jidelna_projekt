# Plán: nezapisované výdejky na Varvažově a Ostrovci

Měřeno 22. 9. 2026 nad produkční kopií.

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

Nezávislá na zbytku, dá se udělat hned.

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
| 2.1 | tlačítko „vydat vše podle plánu" | půl dne | hned, možná stačí |
| 2.2 | QR do tištěné výdejky | půl dne | hned, nezávisle |
| 2.3 | OCR jednoho papíru | dny | až po 2.5 |
| 2.4 | dávkový sken štosu | dny | až po 2.3 |
| 2.5 | brána proveditelnosti | hodiny | **před 2.3** |

**2.1 a 2.2 se dělají hned a nezávisle na sobě.** U 2.2 platí, že funguje jen
na papírech vytištěných po té změně, takže každý týden odkladu je další štos
bez kódu — a to i v případě, že se k OCR nikdy nedojde.

### 2.1 Tlačítko „vydat vše podle plánu" (levná varianta)

Na výdejce jedno tlačítko, které vyplní všem nevydaným řádkům plán, a kuchař
opraví jen to, co sedělo jinak. Jednotka akce je celý dokument — přesně ta,
na které se to dnes láme.

Podle dat sedí plán přesně jen u 14–26 % řádků, takže úspora není zázračná.
Ale je to **jedna akce místo padesáti políček**, a oprava několika řádků je
proti opsání celého papíru nesrovnatelná.

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

---

## Co tenhle plán vědomě neřeší

**Proč se na dvou jídelnách nezapisuje, když na třetí ano.** Růžená to zvládá
ve stejné aplikaci. Je možné, že rozdíl není v nástroji, ale v tom, kdo a kdy
to má v popisu práce — a pak žádná funkce nepomůže. Stojí za to se zeptat
dřív, než se postaví OCR.

---

## Dopad na plán predikce

`plans/predikce_zasob_a_cen_plan.md` staví fázi B na historii spotřeby.
Ta historie od července existuje **pro jednu jídelnu ze tří**. Dokud se to
nezmění, má predikce smysl jen pro Růženou — a ta funguje i bez ní.
Tohle je tedy předpoklad fáze B, ne paralelní úkol.
