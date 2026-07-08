# Plán oprav modulu Převodky (StockTransfer)

> **Stav (8. 7. 2026): všechny 4 fáze hotové.** A1–A4, B1–B3, C1–C7 opraveny,
> pokryto testy `test/test_stock_transfer_create.py` a `test/test_stock_transfer_workflow.py`.
> Sirotčí DRAFT převodky (5 ks z 3. 7.) ponechány v DB na žádost uživatele.
> Zuzce přiřazena jídelna Černá Hora. Nová migrace: inventory 0023.

Kontext: Uživatelka Zuzka hlásí, že formulář nové převodky (Růžená → Černá hora) se cyklí v chybách a nezapisuje data. Zároveň v seznamu surovin nelze najít všechny položky ze zvoleného skladu (Růžená).

Dotčené soubory:
- `apps/inventory/views.py` (StockTransferCreateView, detail, akce, PDF, API)
- `apps/inventory/forms.py` (StockTransferForm, StockTransferItemForm, formset)
- `apps/inventory/models.py` (StockTransfer, StockTransferItem)
- `templates/inventory/stock_transfer_form.html` (JS formsetu)

---

## A. Kritické — příčiny „cyklení a nezapisování dat"

### A1. Hlavička převodky se ukládá i při nevalidním formsetu (sirotčí převodky)
`views.py` – `StockTransferCreateView.form_valid`: hlavička se uloží (`form.save()`) PŘED validací formsetu. Když je formset nevalidní, metoda vrací `self.form_invalid(form)` zevnitř `transaction.atomic()` — návrat bez výjimky transakci **commitne**. Každý neúspěšný pokus tedy vytvoří prázdnou DRAFT převodku bez položek a spotřebuje `transfer_number`. Uživatel vidí chyby a „nic se neuloží", ale DB se plní sirotky.

**Oprava:** Validovat formset před uložením hlavičky. Sestavit formset z `request.POST` s `instance=form.instance` (neuloženou) a `form_kwargs={'warehouse_from': form.cleaned_data.get('warehouse_from')}`; teprve když je vše validní, uložit hlavičku i položky v jedné transakci. Alternativně `transaction.set_rollback(True)` před `form_invalid`.

**Úklid dat:** Smazat existující sirotčí DRAFT převodky bez položek (po potvrzení).

### A2. Povinné readonly pole `unit_price_with_vat` — neopravitelná chyba = smyčka
`forms.py` – `StockTransferItemForm`: pole je povinné (model bez `blank=True`) a widget má `readonly`. Cenu vyplňuje jen JS přes AJAX. Když AJAX cenu nevyplní (surovina není na skladu, chyba sítě, JS selže), server vrátí „Toto pole je povinné" a uživatel to kvůli readonly **nemůže opravit** → nekonečná smyčka chyb. Server-side autofill v `clean()` nefunguje: required chyba vznikne na úrovni pole dřív a zápis do `cleaned_data` ji neodstraní.

**Oprava:** Ve formu nastavit `unit_price_with_vat` jako `required=False`; cenu vždy autoritativně doplnit na serveru ze `StockItem` ve `warehouse_from` (v `clean()` formu / ve view). Klientská hodnota jen informativní.

### A3. Formset se re-renderuje bez `warehouse_from` — nekonzistentní validace
`views.py` – `get_context_data` vytváří formset bez `form_kwargs={'warehouse_from': ...}` a bez instance, zatímco `form_valid` s nimi. Při chybě se tak uživateli zobrazí jiná sada chyb, než která ukládání skutečně zablokovala (chybí kontrola dostupnosti, autofill ceny, `available_quantity`).

**Oprava:** Jediné místo konstrukce formsetu (helper metoda), vždy s `warehouse_from` odvozeným z POST/instance. V `get_context_data` nepřevalidovávat znovu.

### A4. JS mazání řádku rozbíjí indexy formsetu — tichá ztráta položek
`stock_transfer_form.html` – při odstranění neuloženého řádku JS dělá `row.remove(); formIndex--; TOTAL_FORMS--`. Když uživatel smaže **prostřední** řádek, vznikne mezera v indexech (`items-0`, `items-2`) a snížený `TOTAL_FORMS` způsobí, že Django poslední řádek ignoruje, případně formset spadne na ManagementForm. Položky se tiše ztratí → „nezapisuje data".

**Oprava:** Nikdy nedekrementovat `TOTAL_FORMS` při mazání z prostředka — buď řádky po smazání přeindexovat, nebo řádek jen skrýt a nechat prázdný (formset prázdné formy přeskočí).

---

## B. „Nelze najít všechny položky ze skladu Růžená"

### B1. Dropdown surovin není vázaný na sklad
`forms.py` – `StockTransferItemForm.__init__`: `ingredient.queryset = Ingredient.objects.filter(is_active=True)` — nabízí všechny aktivní suroviny bez ohledu na sklad. Důsledky:
- Suroviny s `is_active=False`, které fyzicky **jsou** na skladě Růžená, se v seznamu vůbec nenabídnou → přesně hlášený problém.
- Naopak seznam obsahuje stovky surovin, které na skladě nejsou → po výběru chyba „není na skladu".

**Oprava:** Nabízet suroviny podle `StockItem` ve zvoleném `warehouse_from` (quantity > 0), bez filtru `is_active` (na skladě už jsou). Dynamicky: nový AJAX endpoint `api/warehouse-ingredients/?warehouse=ID`, JS při změně „Ze skladu" přenačte options všech řádků (Select2). Server-side queryset ve formu ponechat široký (validace řeší dostupnost), nebo zúžit dle POSTnutého warehouse.

### B2. Dostupnost počítá s blokovaným množstvím bez vysvětlení
`quantity_available = quantity − quantity_blocked`. Uživatel vidí ve skladu plné množství, ale převodka hlásí nedostatek, protože část je blokovaná (výdejky/plány). Zobrazit v UI i blokované množství („Dostupné: X (blokováno: Y)") a v chybové hlášce.

### B3. Sklady filtrované podle jídelen uživatele
`StockTransferForm.__init__`: neadmin vidí jen sklady svých jídelen. Pokud Zuzka nemá přiřazenou jídelnu Černé hory, cílový sklad se jí nenabídne. Ověřit přiřazení profilu; případně rozlišit: zdrojový sklad = jen vlastní jídelny, cílový = všechny (převzetí potvrzuje cílová strana). Rozhodnout se zadavatelem.

---

## C. Další nalezené chyby

### C1. Race condition při generování `transfer_number`
`models.py` – `StockTransfer.save`: stejný vzor, který byl u receptů opraven commitem 3904d7f. Souběžné vytvoření dvou převodek ve stejný den → duplicitní číslo → `IntegrityError` (500). Navíc `order_by('-transfer_number')` řadí stringově (`-999` > `-1000`). **Oprava:** převzít robustní generátor z opravy receptů (retry na IntegrityError, číselné řazení / `Max` přes délku+hodnotu).

### C2. Chybějící kontrola oprávnění na detailu převodky
`StockTransferDetailView` má jen `LoginRequiredMixin` — kterýkoli přihlášený uživatel zobrazí detail cizí převodky (list i PDF filtrují, detail ne). **Oprava:** omezit `get_queryset` na jídelny uživatele (stejná logika jako v ListView).

### C3. `stock_transfer_complete` ověřuje jen zdrojovou jídelnu
Dokončení zapisuje do `warehouse_to`, ale oprávnění se kontroluje na `warehouse_from.canteen`. Uživatel bez přístupu k cílové jídelně může naskladnit do jejího skladu. **Oprava:** u `complete` kontrolovat cílovou jídelnu (u `start`/`cancel` zdrojovou; u `start_and_complete` obě).

### C4. `cancel()` může nafouknout/podtéct zásoby
- Když transit `StockItem` neexistuje, zaloguje se warning, ale zboží se **stejně přičte** zpět do zdroje → duplikace zásob.
- `transit_stock.quantity -= item.quantity` bez kontroly → transit může jít do minusu.
- `vat_rate` hardcode `Decimal('12')` při obnově položky.
**Oprava:** vracet jen to, co v transitu reálně je; DPH převzít z položky transitu/zdroje.

### C5. Množství bez server-side validace
`StockTransferItem.quantity` nemá `MinValueValidator`; `min="0"` je jen v HTML. Záporné množství projde a provede inverzní převod; nula vytvoří prázdnou položku. **Oprava:** `MinValueValidator(Decimal('0.001'))` na modelu + validace ve formu.

### C6. Možná ZeroDivisionError ve váženém průměru
`complete_transfer`/`start_and_complete`: `total_value / target_stock.quantity` — pokud má cílová položka záporný zůstatek (možné kvůli C4/C5) a součet vyjde 0, spadne dělení nulou. **Oprava:** guard na `quantity <= 0` (převzít cenu položky).

### C7. Kosmetické
- PDF filename `odepsani_{pk}_...` — copy-paste z odpisů, má být `prevodka_...` (`stock_transfer_pdf`).
- Model `clean()`: při nevyplněných skladech `None == None` vyhodí matoucí „Zdrojový a cílový sklad musí být různé" navíc k required chybám — porovnávat jen když jsou obě FK vyplněné.
- JS klon řádku kopíruje chybové divy (`.text-danger`) z posledního řádku do nového.

---

## Pořadí realizace

1. **Fáze 1 – odblokovat Zuzku (A1–A4):** přepsat `form_valid`/konstrukci formsetu, `unit_price_with_vat` `required=False` + server autofill, oprava JS indexování. Úklid sirotčích DRAFT převodek.
2. **Fáze 2 – položky skladu (B1, B2):** AJAX endpoint na suroviny dle skladu, dynamický dropdown, zobrazení blokovaného množství. Ověřit Zuzčin profil (B3).
3. **Fáze 3 – integrita a bezpečnost (C1–C6):** generátor čísla, oprávnění detail/complete, cancel, validátory množství, guard dělení.
4. **Fáze 4 – kosmetika (C7).**
5. **Testy:** pytest — create view (nevalidní formset nesmí nic uložit), formset s mezerou v indexech, readonly cena prázdná, dostupnost s blokovaným množstvím, cancel bez transit stocku, souběžné generování čísla, oprávnění detail/complete.
