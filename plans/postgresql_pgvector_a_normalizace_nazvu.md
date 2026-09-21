# Analýza: PostgreSQL + pgvector a normalizace názvů z příjemek

> **Stav dokumentu:** analýza sepsaná **16. 9. 2026, před migrací**. Popisuje
> tehdejší nasazení (SQLite, `python:3.15-rc-alpine3.23`). Závěr bodu 1
> mezitím proběhl — aplikace běží na PostgreSQL 17 a base image je
> `python:3.14-slim`. Text se schválně nepřepisuje: je to záznam toho, **proč**
> se rozhodlo, jak se rozhodlo. Pro aktuální stav čtěte `CHANGELOG.md`
> a `docs/prirucka/13-pro-vyvojare.md`. Body 2 a 3 (pgvector, embedding)
> platí dál. Jak převod nakonec proběhl a na co se při něm narazilo:
> [prevod-na-postgresql-jak-probehl.md](prevod-na-postgresql-jak-probehl.md).

Předchůdce rozhodnutí z `plans/predikce_zasob_a_cen_plan.md`. Tři oddělené
otázky, které se míchají dohromady, ale mají různé odpovědi:

1. Přejít na PostgreSQL? → **Ano, ale ne kvůli predikci ani kvůli vektorům.**
2. Nasadit pgvector? → **Ne. Na 500–2 000 vektorů je to zbytečné.**
3. Použít embedovací model na názvy z příjemek? → **Ne jako první krok.
   Nejdřív změřit, pak slovník a rapidfuzz. Embedding až na zbytek, a pak
   nejspíš přes API, ne lokálně.**

Cílový stroj: Oracle Ampere A1, **1,5 OCPU / 5 GB RAM, aarch64**.

---

## 1. PostgreSQL

### 1.1 Skutečný důvod k přechodu: `select_for_update()` dnes nedělá nic

V kódu je **12 volání `select_for_update()`**:

```
apps/inventory/models.py:1172, 1239, 1282, 1592, 1651, 1708, 1777
apps/production/models.py:853, 881, 901, 919
apps/production/views.py:1039
```

**SQLite řádkové zámky nemá. `SELECT … FOR UPDATE` tiše ignoruje.** Celý
ochranný mechanismus okolo `StockItem`, který `CLAUDE.md` předepisuje jako
pravidlo („žádný zápis do `StockItem` mimo `transaction.atomic` se
`select_for_update()`"), je dnes dekorace. Nespadne to jen proto, že SQLite
serializuje zápisy zámkem přes celou databázi a deployment běží na málo
workerech — souběh prostě nenastane.

To je podstatnější argument než výkon. Predikce zásob bude číst a zapisovat
stavy skladu ve chvíli, kdy s aplikací pracuje víc jídelen. Na PostgreSQL ty
zámky začnou skutečně fungovat.

**Pozor — má to i odvrácenou stranu, viz 1.4:** jakmile zámky začnou platit,
začnou být možné i deadlocky, které dnes vzniknout nemůžou.

### 1.2 Co dalšího se přechodem získá

- `get_prices_bulk()` (`apps/inventory/models.py:512`) má v komentáři
  „z důvodu kompatibility se SQLite řadíme v Pythonu místo `DISTINCT ON`
  (PostgreSQL-only)". Na PG se z toho stane jeden efektivní dotaz.
- `JSONField` → skutečné `jsonb`. `MenuPlanForecast.stock_payload` z plánu
  predikce bude dotazovatelný a indexovatelný, na SQLite je to text.
- Řazení českých názvů podle `cs_CZ` collation místo podle kódových bodů.
- Odemkne Celery — ale ten podle měření pořád není potřeba, viz plán predikce.

### 1.3 Vejde se to na 1,5 OCPU / 5 GB?

Ano, s rezervou. Databáze má dnes **4,3 MB** v SQLite, po převodu odhadem
20–40 MB. **Vejde se celá do `shared_buffers`**, disk přestane hrát roli.

Rozpočet paměti:

| Složka | Odhad |
|---|---|
| OS + Docker | ~500 MB |
| PostgreSQL (`shared_buffers` 512 MB + 20 spojení) | ~900 MB |
| Gunicorn 2 workeři s WeasyPrint (Pango po pár PDF nabobtná) | ~700 MB |
| **Celkem** | **~2,1 GB z 5 GB** |

Doporučené nastavení pro tenhle stroj (ne defaulty — default
`max_connections = 100` na 5 GB RAM je nesmysl):

```
shared_buffers = 512MB
effective_cache_size = 1536MB
work_mem = 8MB
maintenance_work_mem = 128MB
max_connections = 20
random_page_cost = 1.1
wal_compression = on
```

V Djangu `CONN_MAX_AGE = 60` a `conn_health_checks = True` — jinak se na
každý request otevírá nové spojení a při 1,5 OCPU to je znát.

### 1.4 Co se při převodu rozbije (konkrétně v tomhle repu)

Tohle je seznam pro agenta, ne obecné poučky.

1. **Deadlocky na převodkách.** `StockTransfer` bere v jedné transakci zámek
   na zdrojový a pak na mezisklad (`models.py:1592, 1651, 1708, 1777`).
   Dvě souběžné převodky v opačném směru mezi týmiž sklady = klasický
   deadlock, který dnes nastat nemůže. **Totéž `GoodsReceipt.confirm()`
   a `InventoryVerification.complete()`, které iterují položky v libovolném
   pořadí a berou zámek na každý `StockItem`.**
   *Oprava:* před braním zámků řadit deterministicky podle `ingredient_id`
   (resp. `warehouse_id, ingredient_id`). Jednotné pořadí zámků deadlock
   vylučuje. Tohle udělat **jako součást převodu**, ne až potom.
2. **`__startswith` je na PG case-sensitive**, na SQLite ne.
   Výskyty: `apps/core/models.py:239`, `apps/inventory/models.py:1548`,
   `apps/inventory/views.py:2007`. Všechno jsou generované kódy dokladů
   s velkými písmeny, takže riziko je malé — ale projít a rozhodnout,
   ne přejít mlčky.
3. **Testy.** `pytest.ini` jede na SQLite. Když testy zůstanou na SQLite a
   provoz půjde na PG, budou se lišit přesně v tom nejnebezpečnějším místě —
   v zamykání. **Testy převést na PostgreSQL taky**, i za cenu pomalejšího CI.
4. **Řazení v testech.** Kde test spoléhá na pořadí českých názvů, může
   `cs_CZ` collation dát jiný (správnější) výsledek než SQLite.
5. **Zálohy.** Ověřit, co dělá XML zálohování v `apps/core` a co
   `backups/` — pokud kdekoli kopíruje soubor DB, přestane to platit.
   Nově `pg_dump` do stejného volume + do compose přidat službu/cron.
6. **`Decimal`.** PG má exaktní `numeric`, SQLite ukládá přes REAL/TEXT.
   Většinou se to zlepší; testy porovnávající částky na haléře můžou
   překvapit oběma směry.

### 1.5 Postup převodu

Na 4,3 MB dat není potřeba `pgloader`:

1. `manage.py dumpdata --natural-foreign --natural-primary --exclude contenttypes --exclude auth.Permission -o dump.json`
2. Prázdná PG databáze → `manage.py migrate`
3. `manage.py loaddata dump.json` (Django při tom resetuje sekvence)
4. **Ověřit počty řádků po tabulkách proti SQLite**, ne odhadem.
   Kontrolní čísla ze stavu 16. 9. 2026: 493 surovin, 124 receptů,
   1 072 skladových položek, 3 203 záznamů cenové historie, 648 příjemek,
   4 755 položek příjemek, 1 328 výrobních příkazů, 9 835 položek výdejek.
5. Teprve pak bod 1.4.1 (pořadí zámků) a znovu celý `pytest apps test`.

**Base image:** `Dockerfile` stojí na `python:3.15-rc-alpine3.23`. Dvě
poznámky mimo rozsah, ale patří sem: release candidate Pythonu v produkci je
odvážné, a Alpine (musl) je důvod, proč se v obrazu kompiluje přes
`build-base` — a taky důvod, proč tam nepůjde spustit lokální embedovací
model (viz 3.3).

**Pozor na `docker-compose.yml`:** `command:` přebíjí `docker-entrypoint.sh`,
což je v souboru i okomentované. Entrypoint spouští gunicorn s
`--workers 2 --timeout 120`, ale compose spouští holé
`gunicorn --bind 0.0.0.0:8000 spiz_project.wsgi:application`, tedy
**1 worker a výchozí timeout 30 s**. Pokud produkce jede přes compose, běží
na jednom workeru — jeden pomalý request (generování PDF, predikce sezóny
měřená na 1,05 s) blokuje všechny ostatní. Srovnat obě cesty na
`--workers 2 --timeout 120`; to je levnější zlepšení odezvy než cokoli
v tomhle dokumentu.

---

## 2. pgvector: ne

Rozsah úlohy:

- **493 surovin** (397 se objevilo na příjemkách),
- **12 dodavatelů**, 648 příjemek, 4 755 položek,
- unikátních dodavatelských názvů řádově stovky až nízké tisíce.

Vektorové vyhledávání nad ~2 000 vektory o 384 dimenzích je **12 MB v paměti
a jedno maticové násobení, tj. jednotky milisekund v NumPy**. HNSW index,
kvůli kterému pgvector existuje, se začne vyplácet o dva až tři řády výš
(10⁵–10⁶ vektorů).

Kdyby se embeddingy nakonec použily, patří do sloupce `BinaryField`
(float32 blob) nebo `JSONField` a hledá se brute force v Pythonu. Je to méně
kódu, míň závislostí a při téhle velikosti stejně rychlé.

pgvector tedy **není špatný, je zbytečný**. Hlavně ať není důvodem k přechodu
na PostgreSQL — ten důvod je oddíl 1.1.

---

## 3. Embedovací model na názvy z příjemek

### 3.1 Nejdřív zjistit, jestli je co zlepšovat

`apps/inventory/matching.py` už je propracovaný sedmivrstvý resolver:
naučené aliasy dodavatele (přesná shoda i „přihrádka" přes `core_key`),
globální aliasy, aliasy cizích dodavatelů, pravidla na nezbožní řádky
a teprve nakonec fuzzy. Vrstvy 1–4 mají 100% přesnost, protože je potvrdil
člověk. **Embedding tam nemá co zlepšit — může zasáhnout jen do vrstvy 6,
tedy do názvů, které systém vidí poprvé.**

Jak velká ta vrstva je, nikdo neví. A přitom je to měřitelné zadarmo:

> **`GoodsReceiptItem` má `source_name` (název z dokladu) i potvrzené
> `ingredient_id`. To je 4 755 řádků hotové trénovací a testovací sady
> označkované člověkem.**

**M0 — replay harness (první úkol, blokuje všechno ostatní).**
Management command `replay_matching`, který projde potvrzené položky
příjemek, pustí na `source_name` `IngredientResolver` (s aliasy ve stavu
*před* daným dokladem, ne po něm — jinak si to odpoví samo) a vydá tabulku:

- podíl položek podle vrstvy (`alias`, `alias_core`, …, `fuzzy`, `none`),
- přesnost fuzzy vrstvy: kolikrát trefila, kolikrát netrefila,
- kolik položek skončilo na `none`,
- census dat: počet aliasů celkem a na dodavatele, počet unikátních
  `source_name`, počet unikátních `raw_key` / `core_key`.
  *(Tenhle census se mi nepodařilo změřit — nástroj byl nedostupný.
  Harness ho stejně vyprodukuje jako vedlejší produkt.)*

Bez tohohle čísla je jakákoli debata o embedding modelu hádání. Pokud
vrstvy 1–5 pokrývají třeba 90 % položek a fuzzy má na zbytku slušnou
přesnost, je celá otázka bezpředmětná.

### 3.2 Levnější opravy, které přijdou na řadu dřív

**F1 — `rapidfuzz` místo `difflib`.** `calculate_similarity()`
(`matching.py:387`) používá `difflib.SequenceMatcher`, zatímco
**`rapidfuzz` už v `requirements.txt` je** a používá se v
`apps/production/xml_parser.py:11`. `rapidfuzz.fuzz.token_set_ratio` /
`WRatio` běží v C a na přeházených a částečných názvech je lepší.
Nulová nová závislost.

**F2 — překlepy z OCR propadají sítem.** `calculate_similarity()` vyžaduje
společný token delší než 2 znaky, jinak skóre zastropuje na
`FUZZY_THRESHOLD` a návrh se nenabídne. Vlastní docstring `naming.py`
uvádí jako příklad `Jabíko Pinova DE` — a právě ten případ propadne:
`jabiko` není `jablko`, společný token není žádný, návrh nevznikne.
*Oprava:* za společný token považovat i token s editační vzdáleností 1
u slov od 5 znaků. Přesně tahle jedna změna řeší dokumentovanou slabinu.

**F3 — slovník synonym (to, co jsi navrhoval).** České potravinářské
názvosloví je malý uzavřený slovník. Ručně udržovaný `dict` pro
„rajče / paradajka", „brambory / zemáky", značka → druh (`Hera` →
rostlinný tuk) porazí jakýkoli embedding model **v přesnosti**, běží
v nanosekundách a jde opravit tím, že se dopíše řádek. Pro 493 surovin
odhaduji 50–150 dvojic.
Umístit do `apps/inventory/naming.py` jako `SYNONYMS` vedle stávajících
`PACKAGING_WORDS` / `PROMO_WORDS` a aplikovat při stavbě `core_key` —
tam, kde už normalizace stejně probíhá.

F1–F3 jsou práce na pár hodin, bez nových závislostí a bez rizika.
Změřit znovu přes M0 a teprve pak řešit zbytek.

### 3.3 Když by na embedding přece jen došlo

**Lokální model v současném obrazu nejde spustit.** `Dockerfile` staví na
`python:3.15-rc-alpine3.23`, tedy **musl libc na aarch64**.
`onnxruntime` ani `torch` **musllinux wheels nevydávají** — jen manylinux.
Znamenalo by to buď kompilovat onnxruntime na ARM ze zdrojů (dny práce),
nebo přejít na `python:3.x-slim` (Debian/glibc). Ten přechod by sám o sobě
byl rozumný — na Alpine se dnes kvůli chybějícím wheels všechno kompiluje —
ale je to samostatný úkol, ne detail.

Pokud by se šlo lokální cestou, pak **ne multilingvální model, ale český**:
`Seznam/simcse-small-e-czech` nebo `Seznam/retromae-small-cs` (~50 M
parametrů). Jsou malé a na češtině lepší než `multilingual-e5-small`
(118 M), který češtinu umí jen okrajově. Kvantizovaně int8 přes ONNX
Runtime to je ~100 MB modelu a ~250 MB RSS — do rozpočtu z 1.3 se to vejde,
ale až po výměně base image.

**Lepší varianta při těchhle omezeních: `mistral-embed` přes API.**
Balík `mistralai` **už v projektu je** a OCR import **už teď na síti a na
Mistral API závisí** — embedding by běžel na přesně té samé cestě kódu,
kde ta závislost existuje. Žádný nový systémový balík, žádná RAM navíc,
žádné ARM/musl potíže. Doklad má 10–30 řádků, embedding stojí zlomek
haléře. 493 surovin se naembedduje jednou a uloží se do DB (viz oddíl 2 —
`BinaryField`, ne pgvector), přepočítá se při přidání nebo přejmenování
suroviny.

Podmínky, za kterých embedding vůbec nasadit:
- M0 ukázalo, že na vrstvu 6 spadá netriviální podíl položek **a** že fuzzy
  na nich chybuje i po F1–F3,
- embedding se měří **na téže sadě** proti stavu po F1–F3 — ne proti
  dnešnímu stavu, to by byl nepoctivý souboj,
- embedding zůstává **jen návrhem pro člověka** (nikdy v `AUTOMATIC_SOURCES`),
  se samostatným `source` v `MatchResult`, ať je v UI vidět, odkud návrh je,
- bez sítě nebo bez API klíče musí import fungovat dál přesně jako dnes —
  stejně jako u OCR.

---

## 4. Doporučené pořadí

| # | Krok | Proč teď |
|---|---|---|
| 1 | Srovnat gunicorn v compose a entrypointu (`--workers 2 --timeout 120`) | Jednořádková změna, největší okamžitý efekt na odezvu |
| 2 | M0 replay harness nad příjemkami | Bez čísel se o matchingu nedá rozhodovat |
| 3 | F1 rapidfuzz, F2 překlepy, F3 slovník synonym | Levné, bez závislostí, měřitelné přes M0 |
| 4 | Převod na PostgreSQL vč. pořadí zámků (1.4.1) a testů na PG | Než přibudou modely predikce |
| 5 | Fáze A–D z `predikce_zasob_a_cen_plan.md` | — |
| 6 | Embedding — **jen když M0 po kroku 3 ukáže, že je co zlepšovat** | Podmíněné |

Kroky 2–3 a 4 jsou nezávislé, dají se dělat souběžně různými agenty.

pgvector v seznamu není záměrně.
