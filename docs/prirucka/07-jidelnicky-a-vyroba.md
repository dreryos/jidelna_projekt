# 7. Jídelníčky a výroba

Jídelníček je plán vaření: která jídla, ve kterých dnech, pro kolik strávníků. Z jídelníčku systém automaticky spočítá potřebu surovin (výdejky, kapitola [8](08-vydejky.md)) i náklady (kapitola [10](10-analytika-a-reporty.md)).

## Jídelní plán

**Jídelníčky → Jídelníčky** (`/production/jidelnicky/`).

![Seznam jídelníčků](img/07-jidelnicky-seznam.png)

Plán má název, jídelnu a rozsah dat (typicky týden). Do každého dne přidáváte **výrobní příkazy** — jedno jídlo = jeden příkaz (recept + typ jídla: snídaně, přesnídávka, oběd, svačina, večeře).

![Detail jídelníčku](img/07-jidelnicek-detail.png)

## Varianty porcí a koeficienty

Jedno jídlo se často vaří pro více kategorií strávníků s různě velkou porcí. To řeší **varianty porcí** u každého výrobního příkazu:

| Varianta | Koeficient | Porcí | Efektivní porce |
|---|---|---|---|
| Dospělí | 1,00 | 120 | 120 |
| Děti | 0,75 | 80 | 60 |
| **Celkem k vaření** | | 200 | **180** |

Potřeba surovin se počítá z **efektivních porcí** (porce × koeficient): norma 150 g brambor na porci × 180 efektivních porcí = 27 kg. Vaří se tedy „180 dospělých porcí“ rozdělených na 200 talířů.

💡 **Proč koeficienty místo dvou receptů:** Dětská porce je totéž jídlo, jen menší. Kdyby existoval zvláštní recept „guláš dětský“, každá úprava receptury by se dělala dvakrát a dřív nebo později by se verze rozešly. Koeficient škáluje jeden recept — a nastavuje se na úrovni jídelníčku (výchozí varianty), takže je u všech jídel konzistentní.

Výchozí varianty (názvy, koeficienty, počty porcí) nastavíte u jídelního plánu; každé jídlo je zdědí a lze je u něj individuálně upravit (např. bufet vaří jen pro dospělé).

## Šablony jídelníčků

Opakující se cykly (14denní jídelníček ŠVP…) uložte jako **šablonu** — **Jídelníčky → Šablony** (`/production/sablony/`).

![Seznam šablon](img/07-sablony-seznam.png)

Šablonu lze editovat dvěma způsoby:

* **Vizuální editor** — přetahování jídel mezi dny (drag & drop), přidávání přes našeptávač receptů, kopírování celých dnů. Změny se ukládají automaticky.
* **XML editor** — přímá úprava XML pro hromadné zásahy.

![Vizuální editor šablony](img/07-vizualni-editor.png)

💡 **Proč šablony odkazují na kódy receptů:** Šablona uchovává kódy (`PO-012`), ne názvy. Recept můžete přejmenovat a šablona dál funguje — proto je kód receptu neměnný (kapitola [3](03-suroviny-a-receptury.md)).

### Uložení jídelníčku jako šablony

Jídelník, který vznikl ručně (bez šablony), nebo už byl uvařený, jde uložit jako šablonu: na detailu jídelníčku tlačítko **Uložit jako šablonu**. Před uložením stránka ukáže, kolik jídel a dnů se přenese a co se vynechá.

Do šablony se přenáší **rozvržení**: den (posun od začátku jídelníčku), recept a typ jídla. **Nepřenáší se:**

* **počty porcí a koeficienty variant** — patří ke konkrétní skupině; nastavíte je při použití šablony v průvodci (viz níž),
* **úpravy surovin** u jednotlivých jídel a prodejní DPH,
* **polévka a druhá večeře** — jsou to technické karty, do kterých se suroviny doplňují ad hoc, ne plánovaná jídla.

U **zaměněného jídla** (záměna za jiný recept) jde do šablony **náhrada**, tedy to, co se skutečně vařilo; původní jídlo se vynechá. Právě to dává smysl pro opětovné použití.

Šablona se jmenuje podle jídelníčku, název můžete změnit; duplicitní název (bez ohledu na velikost písmen) systém odmítne. Jídelníček bez jediného přenositelného jídla uložit nejde. Uloženou šablonu pak najdete v **Jídelníčky → Šablony** a použijete ji stejně jako každou jinou.

### Tvorba jídelníčku ze šablony

**Jídelníčky → Tvorba ze šablony** (`/production/import-jidelnicku/`) — třífázový průvodce:

1. **Výběr šablony** a data začátku. Datum smí ležet i **v minulosti** — viz níže.
2. **Náhled** — vidíte, která jídla na které dny vzniknou, a nastavíte počty porcí variant.
3. **Potvrzení** — vytvoří se jídelní plán se všemi výrobními příkazy a variantami.

![Import jídelníčku ze šablony](img/07-import-jidelnicku.png)

⚠️ **Pozor:** Pokud šablona odkazuje na recept, který mezitím někdo smazal, náhled na to upozorní — jídlo přeskočte nebo recept obnovte. Proto recepty raději needitujte „mazáním a zakládáním znovu“ — nový recept dostane nový kód a vazba ze šablon se ztratí.

#### Jídelníček zpětně

Datum začátku není omezené na dnešek a dál — jídelníček lze založit i na dny, které už proběhly.

💡 **Proč to jde:** Když se na akci zapomene jídelníček založit předem a akce už mezitím začala (typicky o den dřív), nemá provoz jak vykázat, co se vařilo. Zákaz zpětného data by v takové situaci vedl jen k tomu, že by se jídelníček založil na špatný den — a evidence by seděla ještě míň. Doplnit ho zpětně je tedy legitimní postup, ne obcházení systému.

⚠️ **Pozor:** Zpětně založený jídelníček **nepřepíše, co se už stalo se skladem.** Vygenerovaná výdejka bude vycházet z norem, ne ze skutečnosti, a suroviny se odečtou až v okamžiku výdeje. Když už se zboží vydalo mimo systém, srovnejte rozdíl odpisem nebo inventurou (kapitoly [9](09-odpisy-a-bufet.md) a [6](06-inventura.md)) — jinak zůstane sklad v minusu.

## Úpravy ingrediencí na den (overrides)

Občas je třeba jedno konkrétní vaření upravit: dnes místo čerstvé papriky mražená, bez ořechů kvůli alergikovi, dvojnásobek koření. K tomu slouží **úprava ingrediencí výrobního příkazu** (v detailu jídelníčku u jídla):

* **změna množství** — jiná norma jen pro tento den,
* **odebrání suroviny** — dnes se nepoužije,
* **přidání suroviny** — dnes navíc.

Upravené jídlo je v jídelníčku označené; úpravy lze zkopírovat na jiné dny nebo hromadně vrátit na původní recepturu.

💡 **Proč overrides místo úpravy receptu:** Receptura je trvalá norma — kdyby kuchařka kvůli jednomu dni změnila recept, změna by se propsala do všech budoucích jídelníčků i kalkulací. Override platí jen pro jeden výrobní příkaz; recept zůstává netknutý. Výdejka se generuje už s ohledem na úpravy.

⚠️ **Pozor:** Úpravy dělejte **před** vygenerováním a výdejem výdejky. Změna ingrediencí po výdeji výdejku nepřepočítá zpětně — rozdíl byste museli řešit ručně (doodepsat/vrátit).

---

*Technická poznámka pro vývojáře: Modely v `apps/production/models.py`: `MenuPlan` + `MenuPlanCoefficient` (výchozí varianty), `ProductionOrder` + `ProductionOrderPortionVariant` (`effective_portions = portions × coefficient`), `ProductionOrderIngredientOverride` (`is_added`/`is_removed`/změněná `quantity_per_portion`), `MenuTemplate` (`parse_schedule_to_dict()` ↔ vizuální editor, autosave AJAX). Generování výdejky: `ProductionOrder.generate_picking_list()` respektuje varianty i overrides.*
