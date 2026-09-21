# Převod na PostgreSQL — jak to nakonec proběhlo

> **Historický záznam, ne návod.** Převod proběhl 17.–21. 9. 2026 a už se
> opakovat nebude: zpátky na SQLite se nechystáme a další převod z PostgreSQL
> v plánu není. Smysl tohohle dokumentu je jediný — podchytit pasti, které
> plán nepředvídal, protože většina z nich není o SQLite. Jsou o tom, jak se
> chová Docker Compose, Django `loaddata` a PostgreSQL pod souběhem, a to
> platí dál.
>
> Souvislosti: [postgresql_pgvector_a_normalizace_nazvu.md](postgresql_pgvector_a_normalizace_nazvu.md)
> je analýza, ze které rozhodnutí vzešlo.

## Co se dělalo

SQLite → PostgreSQL 17 v Dockeru, k tomu nové zálohování (`pg_dump` ke stažení
a noční automat) a CI, která staví image. Změny jsou v PR #75 a #76.

Důvod nebyl výkon ani vektory, ale **správnost zamykání**: v kódu bylo dvanáct
volání `select_for_update()` a SQLite je tiše ignoruje. Pravidlo o zamykání
skladu bylo do té doby dekorace, která nespadla jen proto, že souběh nenastal.
Se druhou a třetí rekreačkou nastane.

## Osm věcí, které plán nepředvídal

### 1. Pořadí zámků nebyla dvě, ale čtyři

Plán počítal s tím, že stačí seřadit položky dokladu podle suroviny. Nestačí:
převodka pracuje se dvěma sklady a zdroj zamyká dřív než cíl, takže dvě
protisměrné převodky si vezmou zámky křížem. Odtud `StockItem.lock_existing()`,
které bere všechny zámky předem v pořadí podle `pk`.

Jenže po té opravě si každý další doklad bral zámky pořád po svém:

| Doklad | Pořadí zámků před opravou |
|---|---|
| převodka | podle `pk` |
| příjemka, inventura | podle `ingredient_id` |
| odpis | podle pořadí řádků ve formuláři |
| hromadné mazání položek výdejky | podle `PickingList.id` |

Dokud pořadí skladových karet podle `pk` odpovídá pořadí podle `ingredient_id`,
nic se nestane — ale to databáze nezaručuje. Stačí, aby karta pro druhou
surovinu vznikla dřív.

U odpisu je to nenápadné: `StockWriteOffItem.save()` si zamyká jednu kartu ve
vlastní transakci, jenže formset ukládá všechny položky uvnitř jedné vnější
`transaction.atomic()`. Vnitřní transakce se tam degraduje na savepoint
a zámky se hromadí až do konce té vnější.

**Poučení:** pravidlo zní „každá transakce, která může držet víc než jeden
zámek `StockItem`, si je musí vzít předem přes `lock_existing()`". Ne
„seřaď položky".

### 2. Mezi `migrate` a `loaddata` musí přijít `flush`

Plán tvrdil, že datové migrace nad prázdnou databází neudělají nic. To neplatí:
`inventory/0028_create_real_suppliers` založí dodavatele Zelináře a Pekárnu
a ti se pak srazí s týmiž dodavateli z fixture. Správné pořadí je
`migrate` → `flush --no-input` → `loaddata`.

### 3. Compose nezastaví službu, kterou nezná

Tohle málem stálo data. Na serveru běžel kontejner z ještě staršího nasazení,
kde se služba jmenovala `jidelna_projekt` (novější compose ji má jako `spiz`).
`docker compose stop` ho **nevypnul** — o službě, která v aktuálním souboru
není, compose neví. Hlásil ji jen jako `orphan container`.

Aplikace tedy celou dobu běžela dál a zapisovala do SQLite. Export byl
z okamžiku T, ale do SQLite se pak ještě vydávalo a maza­lo.

Chytilo to ověření (viz bod 8): PostgreSQL měla o 8 řádků výdejky **víc**,
u pěti položek `PENDING` tam, kde SQLite měla `COMPLETED`, a vyšší stavy
skladu. Všechno konzistentní s jedním vysvětlením — SQLite ujela dopředu.

**Poučení:** po `docker compose stop` vždycky `docker ps`, a hlavně
`docker ps -q --filter volume=<název_volume>`. Hlášku o orphan kontejnerech
nepřehlížet.

### 4. `docker compose run` ignoruje zadaný příkaz

`docker-entrypoint.sh` je ENTRYPOINT, který nepředává argumenty dál — spustí
migrace, mkdocs, collectstatic a gunicorn. Každý management příkaz proto
potřebuje `--entrypoint python`:

```bash
docker compose run --rm --entrypoint python spiz manage.py migrate
```

Bez toho se místo migrace nastartuje webserver a zadaný příkaz se zahodí.

### 5. Starý image byl mezitím smazaný z registru

Kvůli úniku (bod 7) šel celý Docker Hub repozitář pryč — a s ním jediná
vzdálená kopie image, na který se dalo couvnout. Zachránilo to, že image byl
pořád v lokální cache serveru.

**Poučení:** před převodem si odložit běžící image pod vlastním tagem, ať ho
nesmaže `docker prune`:

```bash
docker tag <image> jidelna-zaloha-pred-prevodem:1
```

### 6. Aplikace nenaběhla v čistém prostředí

`LOGGING` píše do `logs/audit.log`, ale `logs/` není v gitu. Chybějící adresář
shodí `dictConfig` rovnou při `django.setup()` hláškou
`Unable to configure handler 'file'` — z níž nejde poznat, že jde jen
o chybějící adresář.

Dosud to nebylo vidět, protože `logs/` se do image dostával omylem z pracovní
kopie. Po opravě `.dockerignore` by první CI stavěný image spadl hned po
startu. Našla to CI při prvním běhu nad čistým checkoutem.

### 7. Tajemství a zálohy v publikovaném image

`Dockerfile` dělá `COPY . /app/` a `.dockerignore` nevylučoval `.env` ani
`backups/`. Ve veřejném image na Docker Hubu tak ležel klíč k Mistral OCR
a **dvě kompletní kopie ostré databáze** včetně hashů hesel.

Vzor `db.sqlite3` je nepokryl, protože platí doslova, ne jako maska. Opraveno
na `**/*.sqlite3` a spol.; CI navíc staví z čistého `git clone`, kde takové
soubory vůbec nejsou.

Řešení incidentu: zneplatnit klíč, smazat repozitář z Docker Hubu, resetovat
hesla.

### 8. Ověření převodu muselo umět rozlišit ztrátu dat od jiné reprezentace

První verze `verify_migration.py` porovnávala součty. To nefunguje: SQLite typy
nevynucuje a v desetinných sloupcích drží delší ocas, než schéma povoluje,
takže PostgreSQL každou hodnotu zaokrouhlí a přes deset tisíc řádků se součty
rozejdou i u bezchybného převodu.

Po přepsání na porovnání řádek po řádku vyšly tři nálezy, všechny neškodné:

| Nález | Skutečnost |
|---|---|
| M2M `userprofile_canteens`, 30 rozdílů | množina vazeb identická; `loaddata` jen přiděluje jiná surogatní `id`, která nic nereferencuje |
| `annotation`, 61 rozdílů | po rozparsování shodné — SQLite drží JSON jako escapovaný text, PG jako `jsonb` s jiným pořadím klíčů |
| `pdf_file`, 15 rozdílů | 116 neprázdných na obou stranách, liší se jen `NULL` proti `''` |

Skript tyhle tři případy nově rozpozná sám.

**Poučení:** ověření, které křičí u každého rozdílu v reprezentaci, se přestane
číst. Ověření, které porovnává jen součty, přehlédne prohozený sloupec.

## Co odhalilo CI mimochodem

**49 testů se nikdy nespouštělo.** pytest sbírá jen `test_*.py`, ale Django
zakládá testy jako `tests.py`. Testy v `apps/core`, `apps/inventory`
a `apps/bufet` sadou tiše propadávaly — včetně nového souběhového testu na
zámky převodek, který by se tvářil, že hlídá, a nehlídal nic.

## Jak se ověřovalo, že opravy fungují

U obou souběhových testů jsem opravu dočasně vypnul a ověřil, že PostgreSQL
skutečně hlásí `deadlock detected`. Test na zamykání, u kterého nikdo nezkusil,
jestli umí spadnout, není test.

Totéž u obsahu image: místo domněnky se postavil pomocný image, který vypsal
skutečný obsah build kontextu (629 souborů před opravou, 411 po).

## Co po převodu zůstalo k úklidu

* `spiz_project/settings_sqlite_export.py` — dočasný settings modul pro čtení
  staré databáze.
* `test/verify_migration.py`, `test/verify_collation.py` — jednorázové
  ověřovací skripty.
* `db.sqlite3` a volume se starou databází — držet, dokud nová databáze
  nepřežije měsíc provozu.
