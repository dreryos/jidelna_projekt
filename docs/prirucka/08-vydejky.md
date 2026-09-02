# 8. Výdejky

Výdejka je doklad o výdeji surovin ze skladu do kuchyně na konkrétní vaření. Vzniká automaticky z jídelníčku — systém spočte potřebu podle normy receptu, variant porcí a případných úprav ingrediencí.

## Kde výdejky najdete

* **Výdejka dne** (`/production/vydejka-dne/`) — agregovaný pohled na dnešní potřebu surovin ze všech jídel.
* **Generátor výdejek** (`/production/vydejky/`, menu Reporty → Výdejky) — sestavení výdejkového **dokumentu** za den či rozsah dní, jeho editace, PDF a archivace.

![Výdejka dne](img/08-vydejka-dne.png)
![Generátor výdejek](img/08-vydejky-generator.png)

## Životní cyklus položky výdejky

```text
vygenerováno (ČEKÁ / PENDING)
      │  zařazení do výdejkového dokumentu
      ▼
BLOKOVÁNO na skladě (plánované množství)
      │  výdej — zapsání skutečného množství
      ▼
DOKONČENO (COMPLETED): blokace uvolněna, sklad snížen o skutečné množství
      │  (omylem? lze vrátit)
      ▼
vratka: sklad vrácen, položka znovu ČEKÁ s blokací
```

### 1. Generování

Každé jídlo v jídelníčku má vygenerované položky výdejky: surovina, **plánované množství** (norma × efektivní porce, převedeno na skladové jednotky) a sklad, ze kterého se bude vydávat (systém předvyplní sklad jídelny, kde surovina je).

### 2. Blokace

Zařazením položek do výdejkového dokumentu se plánované množství **zablokuje** na skladové kartě. Zboží je stále fyzicky na skladě, ale jiná výdejka ani převodka ho už „nevidí“ jako dostupné.

💡 **Proč blokace, a ne rovnou odečtení:** Výdejka se připravuje dopředu (třeba v pátek na pondělí), ale zboží fyzicky opustí sklad až při vaření. Kdyby se sklad odečetl hned, inventura přes víkend by nevyšla; kdyby se neblokovalo nic, dvě výdejky by si mohly slíbit totéž kilo masa. Blokace odděluje **rezervováno** od **vydáno**.

### 3. Dokončení (výdej)

V editaci výdejky (`picking_list_edit`) má každá surovina pole **Skutečně vydáno**. Pole je vždy prázdné, placeholder jen ukazuje plán (nebo už vydané množství). Po uložení:

* **vyplněné** pole = vydat — řádek se dokončí a skutečné množství se rovnou odečte ze skladu,
* **prázdné** pole = beze změny — položka zůstává ČEKÁ, blokace na skladu drží dál.

Desetinná čísla lze psát s čárkou i tečkou.

💡 **Proč se pole nepředvyplňuje plánem:** V praxi se stejně skoro každé číslo přepisuje podle skutečně navážené suroviny. Předvyplněný plán svádí k omylu — kuchař ho nechá být a systém pak tiše vydá plán místo skutečnosti.

### Odebrání nepoužité suroviny

Surovinu, kterou nakonec nepoužijete, odeberete z výdejky **košem** u řádku (jen dokud není vydaná). Blokace na skladu se tím uvolní, jako by položka ve výdejce nikdy nebyla.

### Oprava omylem vydaného množství

Už vydanou (dokončenou) položku nejde přepsat přímo — pole je needitovatelné. Opravu řešíte tlačítkem **Zrušit výdej** u daného řádku:

1. Systém vrátí skutečné množství zpět na sklad a řádek přepne zpátky na ČEKÁ se zablokovaným plánovaným množstvím.
2. Zadáte správné množství znovu a uložíte.

Platí to stejně pro položky u jídel i pro položky vydané mimo plánovaná jídla.

## Záměna jídla

Když se plánované jídlo nakonec vaří jinak (chybí surovina, změna na poslední chvíli), lze ho v editaci výdejky **zaměnit** za jiný recept tlačítkem **Zaměnit jídlo**: vyberete náhradní recept a systém přepočte suroviny podle jeho normy na stejný počet porcí. Původní jídlo zůstane u dokumentu vidět (přeškrtnuté, s odkazem „zaměněno za…“), jeho odběr surovin je nulový. Záměnu lze tlačítkem **Zrušit záměnu** vrátit zpět.

💡 **Proč se původní jídlo neschovává:** V jídelníčku i na PDF pro kuchyni musí zůstat dohledatelné, co se mělo vařit a co se vařilo skutečně — kvůli alergenům, evidenci a případné reklamaci.

## Druhá večeře a polévka

Kromě jídel z jídelníčku obsahuje výdejka dne u každého dne navíc dvě volitelné karty, které se v jídelníčku vůbec neplánují:

* **Druhá večeře** — pro strávníky s režimem druhé večeře,
* **Polévka** — prázdná karta zařazená před obědem, pro polévku, kterou kuchař uvaří „navíc“.

Obě karty jsou zpočátku prázdné a objeví se, až do nich přidáte první surovinu (tlačítko **Přidat surovinu do tohoto jídla**). Nepoužitá prázdná karta se z dokumentu při dalším otevření/generování ztratí sama — nezůstávají po ní žádné nulové položky. Na papírovou PDF výdejku se polévka netiskne (jde o pracovní pomůcku pro kuchyni, ne o položku jídelníčku); druhá večeře se tiskne jako běžné jídlo.

## Záporný sklad

Pokud při dokončení není na skladě dost zboží, systém výdej **nezablokuje** — provede ho a skladová karta jde do minusu. Záporné stavy jsou zvýrazněny v přehledech i na PDF výdejky.

💡 **Proč je minus dovolen:** Kuchyně musí uvařit — realita má přednost před evidencí. Zákaz by vedl jen k obcházení systému („vydáme bokem a doklad uděláme potom“, tedy nikdy). Minus je signál, že evidence neodpovídá: buď chybí příjemka/převodka, nebo je špatně norma. Řešte ho co nejdřív — doplněním chybějícího dokladu nebo inventurou.

⚠️ **Pozor:** Opakované minusy u stejné suroviny = systémový problém (špatný převodní koeficient, zapomenutý závoz). Nenechávejte je „vyhnít“ — pokřivují kalkulace cen.

## Výdejkové dokumenty a PDF

Výdejky se seskupují do **dokumentů** (den nebo více dní), které lze:

* **editovat** — upravit plánovaná množství, doplnit skutečná, dokončovat položky,
* **exportovat do PDF** — optimalizováno pro černobílý tisk do kuchyně; u vícedenních dokumentů se generuje po dnech,
* **archivovat** — dokument, jehož všechny položky jsou dokončené, lze archivovat; zmizí z aktivních přehledů, ale zůstává dohledatelný (včetně PDF).

U dokumentu se eviduje i **kuchař** — kdo vaření zajišťoval (využívá analytika kuchařů, kapitola [10](10-analytika-a-reporty.md)).

💡 **Proč se velká PDF generují „po dnech“:** Vícedenní dokument s desítkami jídel by se renderoval celý naráz a spotřeboval příliš mnoho paměti serveru. Nad ~60 jídel proto systém vykreslí každý den zvlášť a stránky spojí — výsledek je stejný, jen se nezahltí server.

## Časté situace

| Situace | Co se děje | Řešení |
|---|---|---|
| *Sklad je uzamčen inventurou* při výdeji | Na skladu běží inventura | Počkat na dokončení / kontaktovat toho, kdo počítá (kapitola [6](06-inventura.md)) |
| Položka jde vydat jen částečně | Skutečné množství < plán | Zapsat skutečnost; zbytek blokace se uvolní dokončením |
| Vydáno z nesprávného skladu | — | Vratka → změna skladu → znovu dokončit |
| Karta suroviny v minusu | Výdej přes nulu | Dohledat chybějící příjemku/převodku, případně srovnat inventurou |
| Nelze archivovat dokument | Některá položka není dokončená | Dokončit či odebrat zbývající položky |
| Vydáno špatné množství | Překlep, špatná surovina | **Zrušit výdej** u řádku → zadat znovu |
| Surovina se nakonec nepoužila | Plán se nenaplnil | Odebrat řádek **košem** (jen dokud není vydaný) |
| Jídlo se vařilo jinak, než plánoval jídelníček | Chybějící surovina, změna na poslední chvíli | **Zaměnit jídlo** — vybrat náhradní recept |

---

*Technická poznámka pro vývojáře: `PickingList.save()` (`apps/production/models.py`) řídí blokace: přiřazení k dokumentu → `block_quantity(quantity_planned)`; přechod na COMPLETED → `unblock` + odečet `quantity_actual`; revert (`unissue_item_<id>` handler v `picking_list_edit`, běží před quantity-loopem) vrací zásobu a znovu blokuje. Dokument: `PickingListDocument` (`can_be_archived()` vyžaduje vše COMPLETED). Záměna jídla: `ProductionOrder.replacement_of`, normy se přepočtou na recept náhrady při stejném počtu porcí. Druhá večeře / polévka: `MealType.DINNER_SECOND` / `MealType.SOUP`, recept „Výdej“ (code=VYDEJ) resp. lazy příkaz „Polévka“ vzniká až prvním přidáním suroviny (`_store_added_ingredient()`); prázdné příkazy se uklízí při smazání výdejky, jinak by je generátor zabalil do příští výdejky s nulovými množstvími. `MEAL_TYPE_ORDER` v `apps/production/utils.py` řadí SOUP před LUNCH a `generate_picking_list_pdf_file` položky typu SOUP z PDF vynechává. PDF: `PDF_CHUNK_MEAL_THRESHOLD = 60`, spojování stránek přes pypdf. Validace ve `clean()`: sklad patří jídelně, není zamčen, `quantity_actual` povinné pro COMPLETED.*
