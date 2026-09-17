# 11. Správa systému

Kapitola pro správce: uživatelé a oprávnění, zálohy, údržba a hranice mezi aplikací a Django adminem.

## Django admin: co v něm řešit a co ne

**Administrace → Django Admin** (`/admin/`) je nízkoúrovňové rozhraní nad databází.

![Django admin](img/11-admin.png)

**Patří sem:**

* zakládání a správa **uživatelů** a jejich profilů,
* správa **dodavatelů** a jejich šablon položek,
* **aliasy položek dodavatelů** (`SupplierItemAlias`) — oprava špatně naučeného párování dodavatelského názvu na surovinu nebo špatného přepočtu jednotek (souvisí s importem příjemky z fotky, viz níže),
* výjimečné zásahy pod dohledem (smazání omylem založeného prázdného dokladu ve stavu návrhu).

![Naučené aliasy položek dodavatelů v adminu](img/11-admin-aliasy.png)

Seznam se řadí podle četnosti použití, takže nahoře jsou aliasy, na kterých nejvíc záleží. Kurzívou *nezbožní řádek* jsou označené naučené výjimky (doprava, obaly, zaokrouhlení), které se do příjemky nikdy nedostanou.

💡 **Proč je mazání aliasu bezpečná oprava:** Smazání aliasu jen zapomene naučené pravidlo — na už zapsané doklady nesahá. Příště se dodavatelský název namapuje znovu, uživatel jen vybere správnou surovinu (nebo přepočet) ručně a systém se přeučí. Na rozdíl od mazání dokladů tu tedy nehrozí poškození skladu ani historie.

**Nepatří sem** (admin obchází aplikační logiku — nevrací zásoby, nepřepočítává blokace, nepíše historii):

* mazání potvrzených příjemek, dokončených převodek, odpisů a výdejek,
* ruční přepínání zámku skladu (`is_locked`) — viz kapitola [6](06-inventura.md),
* úprava skladových množství — používejte inventuru/odpis/příjemku.

⚠️ **Pozor:** Zlaté pravidlo: **doklad, který už pohnul skladem, se v adminu nemaže.** Bezpečně lze mazat jen návrhy (DRAFT), které se skladu nedotkly.

## Správa uživatelů krok za krokem

1. **Admin → Users → Add user**: uživatelské jméno + heslo (dvakrát).
2. Ve druhém kroku vyplňte jméno, příjmení, e-mail. **Nezaškrtávejte** *staff* ani *superuser* běžným uživatelům.
3. **Admin → User profiles → Add**: vyberte uživatele a zaškrtejte **jídelny**, ke kterým smí. Bez profilu uživatel neuvidí žádná data!
4. Volitelně **pouze pro čtení** (`is_readonly`) — pro kontrolní role (ekonomka, vedení).

Role shrnuje kapitola [1](01-uvod-a-pojmy.md). Superusera zakládejte jen správcům — vidí a smí vše, včetně admin rozhraní.

💡 **Proč jsou oprávnění per jídelna, a ne per obrazovka:** Provozy sdílejí jednu instalaci systému, ale data si nesmí vidět navzájem. Uživatel proto dostává **jídelny**, ne funkce — v rámci své jídelny smí všechno (kromě readonly), cizí jídelna pro něj neexistuje. Je to jednodušší na správu a bezpečnější než matice desítek dílčích práv.

## Rozpoznávání dokladů (OCR)

Systém umí založit příjemku z **fotky dodacího listu** — nahranou fotku přečte přes Mistral OCR a předvyplní jí formulář (kapitola [4](04-prijem-zbozi.md)). Je to volitelná funkce: bez nastaveného klíče systém funguje úplně normálně dál, doklady se jen zadávají ručně nebo importují z XML/CSV.

Nastavuje se proměnnými prostředí:

| Proměnná | Výchozí hodnota | Význam |
|---|---|---|
| `MISTRAL_API_KEY` | prázdné | Přístupový klíč k Mistral OCR. Bez něj je nahrávání fotky zablokované. |
| `MISTRAL_OCR_MODEL` | `mistral-ocr-latest` | Který OCR model se volá. |
| `OCR_SCAN_RETENTION_DAYS` | `7` | Za kolik dní vyprší nedokončený import (fotka nahraná, ale příjemka nikdy nevznikla/nepotvrzena). |

V Dockeru se klíč předává přes `docker-compose.yml` (`MISTRAL_API_KEY=${MISTRAL_API_KEY:-}`) — stačí ho mít v prostředí nebo v `.env`, nic dalšího se neupravuje. Bez klíče se formulář pro nahrání fotky zobrazí zablokovaný s hláškou „Rozpoznávání dokladů není nastavené." a odkazem na ruční zadání příjemky.

Nahraná fotka se ukládá zmenšená pod `MEDIA_ROOT`. Po **potvrzení** příjemky se soubor smaže — dál už neslouží k ničemu. Fotka k importu, který nikdo nedokončil (koncept se nikdy nepotvrdil, nebo uživatel průvodce opustil), vyprší po `OCR_SCAN_RETENTION_DAYS` dnech. Rozpoznaná anotace (přepis dokladu tak, jak ho OCR přečetlo) zůstává natrvalo, i po smazání fotky.

💡 **Proč se fotka maže, ale anotace zůstává:** Fotka je pracovní materiál — slouží ke kontrole položek proti originálu při zadávání a zabírá místo, které se s dalšími doklady jen kupí. Anotace je oproti tomu malá a čitelná: když se za měsíc nesejde sklad, jde z ní zjistit, co systém z dokladu přečetl, aniž by bylo potřeba fotku znovu vyhledávat nebo ji vůbec mít.

Úklid nedokončených importů nemá vlastní plánovač — veze se na dalším nahrání fotky (proběhne nejvýš jednou denně, aby nezdržoval každý upload). Pro ruční nebo pravidelný úklid (např. z cronu) slouží `manage.py purge_receipt_scans`.

⚠️ **Pozor:** Fotky dodacích listů jsou provozní doklady s obchodními údaji (ceny, dodavatel, sortiment). Lhůtu v `OCR_SCAN_RETENTION_DAYS` nenastavujte zbytečně dlouhou a zálohy adresáře `media/` řešte stejně opatrně jako databázi.

## Zálohy a obnova

**Administrace → Zálohy** (`/backup/`, pouze superuser).

![Zálohy](img/11-zalohy.png)

Stránka nabízí dvě různé věci a je důležité je neplést:

| | Záloha databáze (dump) | XML export |
|---|---|---|
| Co obsahuje | **všechno** | vybrané entity |
| K čemu je | obnova po havárii | přenos dat mezi instalacemi |
| Obnova | přepíše celou databázi | slučuje s existujícími daty |

### Záloha databáze

Kompletní obraz databáze ve formátu `pg_dump`. Tohle je **ta záloha** — cokoli dalšího na stránce zálohu nenahrazuje.

Dělá se dvěma způsoby:

* **Automaticky každou noc** ve 3:17. Zálohy leží v `/app/data/backups/` a drží se **7 dní**; starší se samy mažou. Na stránce vidíte čas a velikost té poslední — když je datum staré, něco se pokazilo a patří to prověřit.
* **Na klik** tlačítkem *Stáhnout zálohu databáze*. Soubor se streamuje přímo z databáze, na serveru po něm nic nezůstane.

⚠️ **Stažený soubor obsahuje úplně všechno:** hesla všech uživatelů (zahashovaná, ale útočník je může zkoušet lámat offline), e-maily a data **všech jídelen** bez ohledu na to, ke kterým máte přístup. Kdo ten soubor má, má celou aplikaci. Stahujte ho jen přes HTTPS, ukládejte na šifrovaný disk a neposílejte e-mailem. Každé stažení se zapisuje do logu (kdo, odkud, kdy).

Stahování jde na serveru úplně vypnout proměnnou `DB_DUMP_DOWNLOAD_ENABLED=False` — bez nasazení nové verze. Noční automat běží dál.

#### Ruční vytvoření zálohy

Kromě tlačítka a nočního automatu jde záloha udělat i z příkazové řádky — hodí se před rizikovou operací:

```bash
docker compose exec -T db pg_dump -Fc --no-owner --no-privileges \
    -U spiz -d spiz > zaloha.dump
```

Přepínač `-T` u `docker compose exec` je **povinný**. Bez něj Docker přimíchá do výstupu řídicí znaky a výsledný soubor je nepoužitelný — což se pozná až při pokusu o obnovu.

Co znamenají ostatní přepínače:

* **`-Fc`** — *custom* formát: komprimovaný, binární, a hlavně dovolí při obnově vybrat jen některé tabulky. Bez `-F` vznikne čitelné SQL, jenže to už pak jde obnovit jen celé.
* **`--no-owner --no-privileges`** — v záloze nebudou příkazy nastavující vlastníka objektů. Bez nich zálohu nenasadíte pod jiným databázovým uživatelem, než pod kterým vznikla.

Verze `pg_dump` musí být **stejná nebo vyšší** než verze serveru. Proto je v aplikačním obrazu `postgresql-client-17` shodně s `postgres:17`.

#### Co je v záloze a jak se do ní podívat

Záloha je binární soubor, `cat` ani textový editor nepomůžou. Nejdřív ji dostaňte do kontejneru s databází:

```bash
docker compose cp zaloha.dump db:/tmp/z.dump
```

**Obsah zálohy** — první kontrola, jestli soubor není useknutý:

```bash
docker compose exec -T db pg_restore -l /tmp/z.dump
```

```text
;     dbname: spiz
;     TOC Entries: 412
;     Compression: gzip
;     Format: CUSTOM
```

⚠️ Tenhle výpis jako jediný **nefunguje z roury**. `docker compose exec -T db pg_restore -l /dev/stdin < zaloha.dump` skončí hláškou `did not find magic string in file header`, protože `pg_restore` potřebuje v souboru skákat. Odtud to kopírování o odstavec výš.

**Převod na čitelné SQL:**

```bash
docker compose exec -T db pg_restore -f - /tmp/z.dump | less
docker compose exec -T db pg_restore -f - -t core_ingredient /tmp/z.dump
```

**Jen data jedné tabulky** (`-a`), když v záloze hledáte konkrétní záznam:

```bash
docker compose exec -T db pg_restore -a -t core_ingredient -f - /tmp/z.dump | grep "Hladká mouka"
```

#### Obnova zálohy

Obnova se dělá z příkazové řádky serveru, ne z aplikace. Scénáře jsou tři.

**1. Do nové prázdné databáze** — tohle chcete skoro vždycky. Nic nepřepíše, takže si zálohu můžete prohlédnout dřív, než se rozhodnete:

```bash
docker compose exec -T db psql -U spiz -d postgres -c "CREATE DATABASE nahled OWNER spiz;"
docker compose exec -T db pg_restore --no-owner --no-privileges -U spiz -d nahled /tmp/z.dump
docker compose exec -T db psql -U spiz -d nahled -c "SELECT count(*) FROM core_ingredient;"
```

Až skončíte: `docker compose exec -T db psql -U spiz -d postgres -c "DROP DATABASE nahled;"`

**2. Jen jedna tabulka** — třeba když někdo omylem smazal číselník:

```bash
docker compose exec -T db pg_restore --no-owner -U spiz -d nahled -t core_ingredient /tmp/z.dump
```

**3. Přepis ostré databáze** — po havárii. Tohle je ta nevratná varianta:

```bash
# 1. zastavit aplikaci, ať do databáze nikdo nezapisuje
docker compose stop spiz

# 2. nahrát zálohu zpět
docker compose exec -T db pg_restore \
    --clean --if-exists --no-owner --no-privileges \
    -U spiz -d spiz < spiz_2026-09-16_0317.dump

# 3. spustit aplikaci
docker compose start spiz
```

`--clean --if-exists` znamená, že se stávající obsah databáze **zahodí** a nahradí zálohou. Není to doplnění, je to přepis.

#### Na co si dát pozor

* **Aplikaci zastavte před obnovou.** Zapisuje-li do databáze někdo ve chvíli, kdy pod ním měníte tabulky, skončíte s poloviční obnovou a nepoznáte to.
* **Záloha ve formátu `-Fc` neobsahuje `CREATE DATABASE`.** Cílová databáze musí existovat předem — proto to `CREATE DATABASE` ve scénáři 1.
* **Nikdy nespouštějte `docker compose down -v`.** Přepínač `-v` maže volumy, tedy i celou databázi.
* Soubor se zálohou obsahuje hesla i data všech jídelen — platí pro něj totéž, co je napsané o stahování výš.

⚠️ **Zálohu, kterou jste nikdy nezkusili obnovit, nepovažujte za zálohu.** Vyzkoušejte scénář 1 aspoň jednou — až v ostrém výpadku na to není čas.

### XML export a import (Pokročilé)

Na stránce je sbalený pod *Pokročilé — přenos dat mezi instalacemi*. **Není to záloha.**

Zaškrtáváte, které entity zahrnout:

suroviny · kategorie · recepty · jídelny · sklady · dodavatelé · stav skladů · šablony jídelníčků · jídelníčky · výrobní příkazy · příjemky · převodky · inventury · odpisy · výdejky · historie cen · uživatelé

Systém hlídá **závislosti**: vyberete-li recepty, přibalí suroviny a kategorie; vyberete-li stav skladů, přibalí sklady a jídelny atd. Nemůže tak vzniknout export, který by při importu odkazoval do prázdna.

⚠️ **Co XML nepokrývá ani po zaškrtnutí všeho:**

* **naučené mapování dodavatelských názvů** (`SupplierItemAlias`) — tedy všechno, co se systém naučil při importech dokladů z fotky; po obnově z XML by se to muselo naučit znovu,
* **modul bufetu** (prodeje z pokladny FiskalPRO).

Právě proto XML jako záloha nikdy nestačilo a ustoupilo dumpu.

Import téhož XML na stejné stránce se chová **doplňkově**: existující záznamy (podle názvu/kódu) ponechá a doplní chybějící údaje, nové vytvoří. To dump neumí — ten přepíše celou databázi. Když tedy zakládáte další rekreačku a chcete do ní dostat suroviny a receptury z té stávající, je XML správný nástroj.

Přepínač *Dry-run* import jen zkontroluje a nic nezapíše. Před importem do ostré instalace ho použijte vždy.

## Údržba a doporučený režim

* **Denně**: noční `pg_dump` běží sám, stačí ho kontrolovat — na `/backup/` musí být datum poslední zálohy z dnešního rána.
* **Týdně**: stáhnout dump z `/backup/` a uložit **mimo server** (šifrovaný disk). Noční zálohy leží na tomtéž stroji jako databáze; při jeho ztrátě zmizí s ní.
* **Jednou za čas**: zkusit obnovu do prázdné databáze (postup výše).
* **Průběžně**: sledovat záporné skladové karty (kapitola [8](08-vydejky.md)) a „visící“ doklady — převodky V PŘEVOZU a inventury PROBÍHÁ starší než pár dní, rozpracované importy z fotky (koncepty příjemek, které nikdo nepotvrdil) a příjemky čekající na srovnání měrných jednotek.
* **Po aktualizaci systému**: projít CHANGELOG a ověřit kritické workflow (příjemka → výdejka) na zkušebním dokladu.

## Bezpečnost dat

* Oddělení jídelen je vynuceno na úrovni aplikace — každý pohled filtruje data podle profilu uživatele; přímý přístup na cizí URL končí chybou oprávnění.
* Readonly uživatelé nemohou vytvářet ani měnit žádné doklady.
* Auditní stopy: doklady nesou autora a časy, ceny mají historii, inventury evidují kdo zahájil/dokončil/zrušil, deaktivace surovin kdo a kdy.
* Hesla spravuje Django (bezpečné hashování); heslo resetuje správce v adminu na kartě uživatele.

---

*Technická poznámka pro vývojáře: Záloha databáze: `apps/core/db_backup.py` (`stream_pg_dump()`, `write_dump_to_file()`, `latest_dump_info()`), view `backup_download_dump_view` (jen POST, jen superuser, zápis do logu), noční běh `manage.py dump_database --keep 7` z hostitelského cronu, adresář přes `DB_BACKUP_DIR`, vypínač `DB_DUMP_DOWNLOAD_ENABLED`. XML: `apps/core/backup.py` — `ALL_ENTITIES`, `ENTITY_DEPENDENCIES`, `get_required_entities()`; UI `apps/core/views.py` (`backup_page`, export/import view), CLI ekvivalenty `manage.py export_backup_xml` / `import_backup_xml`. Oprávnění: `UserProfile` + `user_can_access_canteen()`; DB: PostgreSQL 17, připojení přes env `POSTGRES_DB` / `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_HOST`. OCR: `MISTRAL_API_KEY` / `MISTRAL_OCR_MODEL` / `OCR_SCAN_RETENTION_DAYS` v `spiz_project/settings.py`, mazání souboru `GoodsReceiptScan.delete_file()`, úklid `apps/inventory/ocr/storage.py` (`maybe_purge`), příkazy `manage.py purge_receipt_scans` a `manage.py ocr_replay`, naučené mapování `SupplierItemAlias` (`apps/inventory/models.py`).*
