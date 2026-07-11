# 12. Řešení problémů

Katalog situací, hlášek a jejich řešení. Většina „chyb“ ve SPÍŽi jsou záměrné pojistky — systém brání operaci, která by poškodila data. Hláška vždy říká proč; tato kapitola dodává co dál.

## Katalog hlášek

### Sklad a doklady

| Hláška / situace | Příčina | Řešení |
|---|---|---|
| *„Sklad … je uzamčen (kvůli probíhající inventuře)“* | Na skladu běží inventura | Zjistit v **Sklady → Inventury**, kdo počítá; počkat, nebo inventuru dokončit/zrušit (kapitola [6](06-inventura.md)) |
| *„Nedostatečné množství … Dostupné: X, požadováno: Y“* | Převodka/výdej chce víc, než je **dostupné** (fyzicky − blokováno) | Zkontrolovat blokace (rozpracované výdejky), případně doplnit zboží příjemkou/převodkou |
| *„Příjem lze potvrdit pouze ve stavu Koncept“* | Doklad už je potvrzen (např. dvojklik) | Nic — doklad je v pořádku potvrzen jednou |
| *„Zdrojový a cílový sklad musí být různé“* / *„Nelze převádět z/do meziskladu“* | Špatně zvolené sklady převodky | Vybrat běžné sklady; mezisklad spravuje systém |
| Skladová karta v minusu | Výdej přes nulu (chybějící příjemka, špatná norma) | Doplnit chybějící doklad, ověřit převodní koeficient suroviny, případně srovnat inventurou (kapitola [8](08-vydejky.md)) |
| Zboží „zmizelo“ z dostupných zásob | Visící převodka V PŘEVOZU (zboží v meziskladu) nebo blokace výdejkou | Dokončit/zrušit převodku; zkontrolovat rozpracované výdejkové dokumenty |

### Suroviny a receptury

| Hláška / situace | Příčina | Řešení |
|---|---|---|
| *„Surovinu nelze deaktivovat: …“* | Surovina má zásobu nebo figuruje v otevřených dokladech | Splnit podmínku z hlášky: doprodat/odepsat zásobu, dokončit doklady (kapitola [3](03-suroviny-a-receptury.md)) |
| Surovina chybí v našeptávači | Je deaktivovaná | Správce ji může znovu aktivovat |
| Kalkulace porce vychází 0 nebo nesmyslně nízko | Suroviny bez skladové ceny (nikdy nenaskladněny) | Provést příjemku; do té doby kalkulaci nevěřit |
| Výdejka žádá 100× víc, než dává smysl | Špatný převodní koeficient suroviny (např. 1 místo 1000) | Opravit koeficient na kartě suroviny, přegenerovat výdejku |

### Uživatelé a oprávnění

| Hláška / situace | Příčina | Řešení |
|---|---|---|
| *„Nemáte přístup…“* / prázdné seznamy po přihlášení | Uživatel nemá profil nebo přiřazenou jídelnu | Správce doplní **User profile** se zaškrtnutou jídelnou (kapitola [11](11-sprava-systemu.md)) |
| Tlačítka pro vytváření chybí | Uživatel je **pouze pro čtení** | Záměr; případně správce příznak vypne |
| *„Zrušit inventuru může pouze ten, kdo ji zahájil“* | Pojistka proti zahození cizí práce | Požádat autora inventury, nebo správce |

### Importy

| Hláška / situace | Příčina | Řešení |
|---|---|---|
| *„XLSX neobsahuje očekávané sloupce: …“* (bufet) | Jiný export z FiskalPRO než „Položky dokladů – kumulované“ | Vyexportovat správný přehled (kapitola [9](09-odpisy-a-bufet.md)) |
| *„Soubor neobsahuje žádné prodané položky“* | Export bez prodejů, nebo vše vystornováno | Zkontrolovat období exportu na pokladně |
| *„Session vypršela. Začněte znovu.“* | Vícekrokový průvodce (bufet, importy) přerušen příliš dlouhou pauzou | Začít od kroku 1 — nic se nestalo, doklad vzniká až potvrzením |
| Import receptur XML spadne na duplicitním kódu | Dva recepty se stejným kódem v souboru | Opravit kódy v XML na unikátní |

## Zásady prevence chyb

1. **Doklad před zbožím.** Každý pohyb zboží zapište dokladem hned, ne „až večer“ — minusy a rozdíly v inventuře vznikají z odkladů.
2. **Kontrola před potvrzením.** Potvrzené doklady nejdou editovat. Součet příjemky vs. faktura, položky výdejky vs. plán — 30 sekund kontroly ušetří opravné doklady.
3. **Jednotky, jednotky, jednotky.** Nejdražší chyby jsou záměny kg/ks/balení při příjmu a špatné převodní koeficienty. Nové suroviny po založení zkontrolujte.
4. **Nemazat, stornovat.** Systém pro každou opravu nabízí bezpečnou cestu (zrušení převodky, vratka výdejky, smazání položky odpisu). Mazání přes admin je poslední možnost a jen pro návrhy.
5. **Nenechávat viset.** Rozpracované doklady (návrhy, V PŘEVOZU, PROBÍHÁ) pravidelně dokončovat či rušit — blokují zboží a matou přehledy.

## Kdy kontaktovat vývojáře a co poslat

Na vývojáře se obraťte, když: hláška vypadá jako technická chyba (*„Server Error (500)“*), data zjevně nesedí i po kontrole dokladů, nebo systém dělá něco jiného, než dokumentace popisuje.

Do hlášení uveďte:

1. **co jste dělali** (obrazovka, doklad, kroky),
2. **co se stalo** — přesné znění hlášky (screenshot),
3. **kdy** (čas — server má logy v adresáři `logs/`),
4. **kdo** (přihlášený uživatel).

⚠️ **Pozor:** Nikdy „nedolaďujte“ data přímo v databázi ani v Django adminu podle vlastního odhadu — z jedné nesrovnalosti se stanou tři. Nechte diagnózu na vývojáři s logy.

---

*Technická poznámka pro vývojáře: Hlášky vznikají převážně jako `ValidationError` v modelových metodách (`apps/inventory/models.py`, `apps/production/models.py`) a přes `messages` framework ve views. Server loguje do `logs/`; chyby 500 viz `server_error.log`. Diagnostický příkaz pro nesoulad blokací: `manage.py recalculate_blocked_quantities`.*
