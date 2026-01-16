# Vizuální Editor Šablon Jídelníčků

## Přehled

Vizuální editor umožňuje upravovat šablony jídelníčků pomocí intuitivního drag-drop rozhraní namísto přímé editace XML kódu.

## Funkcionalita

### Základní operace

#### Přidání jídla do dne
1. Klikněte na tlačítko "Přidat jídlo" u požadovaného dne
2. Vyberte recept z nabídky (s vyhledáváním)
3. Zvolte typ jídla (snídaně, oběd, svačina, večeře)
4. Volitelně zadejte počet porcí a poznámku
5. Klikněte na "Přidat"

#### Odstranění jídla
- Klikněte na ikonu "×" u jídla které chcete odstranit
- Potvrďte odstranění

#### Přeuspořádání jídel
- **V rámci jednoho dne**: Přetáhněte jídlo na novou pozici
- **Mezi dny**: Přetáhněte jídlo z jednoho dne do druhého

#### Kopírování celého dne
1. Klikněte na ikonu "kopírovat" (📋) u dne
2. Vyberte cílový den
3. Potvrďte kopírování
4. ⚠️ Varování: Existující jídla v cílovém dni budou přepsána

#### Vymazání celého dne
1. Klikněte na ikonu "koš" (🗑️) u dne
2. Potvrďte vymazání všech jídel

#### Přidání nového dne
- Klikněte na tlačítko "Přidat den" na konci seznamu
- Otevře se formulář pro první jídlo v novém dni

### Režimy editace

#### Vizuální režim (doporučený)
- Drag-drop rozhraní
- Autocomplete pro recepty
- Live statistiky
- Okamžitá validace
- Přístupný na: `/production/sablony/<id>/vizualni-editor/`

#### XML režim (pokročilý)
- Přímá editace XML kódu
- Pro hromadné úpravy
- Přístupný na: `/production/sablony/<id>/upravit/`

### Přepínání mezi režimy

V pravém horním rohu editoru:
- **"Vizuální editor"** - přepne do drag-drop režimu
- **"XML režim"** - přepne do textového editoru

Změny jsou automaticky synchronizovány mezi oběma režimy.

## Technické detaily

### Live statistiky

Panel vpravo zobrazuje:
- **Počet dnů**: Kolik dnů má šablona naplánováno
- **Celkem jídel**: Celkový počet jídel v šabloně
- **Unikátní recepty**: Počet různých receptů použitých v šabloně

Statistiky se aktualizují při každé změně.

### Typy jídel

- **BREAKFAST** (Snídaně)
- **SNACK_MORNING** (Svačina dopolední)
- **LUNCH** (Oběd/Polévka)
- **SNACK_AFTERNOON** (Svačina odpolední)
- **DINNER** (Večeře)

### Validace

- Každé jídlo musí mít platný kód receptu
- Kód receptu musí existovat v databázi receptů
- XML struktura je automaticky validována při uložení
- Neplatné změny jsou zamítnuty s chybovou hláškou

### Automatické ukládání

Všechny změny jsou ukládány **okamžitě** při:
- Přidání jídla
- Odstranění jídla
- Přeuspořádání jídel
- Kopírování/vymazání dne

Není třeba klikat na "Uložit" - změny jsou persistentní ihned.

## API Endpointy

Pro pokročilé použití nebo vlastní integraci:

### POST `/production/template/<id>/add-meal/`
Přidá jídlo do dne.

**Request body:**
```json
{
  "day_index": 0,
  "recipe_code": "HL-001",
  "meal_type": "LUNCH",
  "note": "Poznámka",
  "portion_count": 50
}
```

**Response:**
```json
{
  "success": true,
  "meal": {
    "recipe_code": "HL-001",
    "meal_type": "LUNCH",
    "note": "Poznámka",
    "unique_id": "uuid-string",
    "portion_count": 50
  },
  "stats": {
    "days": 5,
    "meals": 23,
    "unique_recipes": 18
  }
}
```

### POST `/production/template/<id>/remove-meal/`
Odstraní jídlo z dne.

**Request body:**
```json
{
  "day_index": 0,
  "meal_index": 2
}
```

### POST `/production/template/<id>/reorder/`
Přeuspořádá jídla v rámci dne.

**Request body:**
```json
{
  "day_index": 0,
  "meal_indices": [2, 0, 1, 3]
}
```

### POST `/production/template/<id>/copy-day/`
Zkopíruje jídla z jednoho dne do druhého.

**Request body:**
```json
{
  "source_day": 0,
  "target_day": 3
}
```

### POST `/production/template/<id>/clear-day/`
Vymaže všechna jídla z dne.

**Request body:**
```json
{
  "day_index": 2
}
```

## Řešení problémů

### Jídlo se nezobrazuje po přidání
- Zkontrolujte konzoli prohlížeče (F12) na chyby
- Ověřte, že kód receptu existuje v databázi
- Zkuste obnovit stránku (Ctrl+R)

### Drag-drop nefunguje
- Ujistěte se, že JavaScript je povolen
- Zkuste vypnout rozšíření prohlížeče
- Použijte moderní prohlížeč (Chrome, Firefox, Safari)

### Změny se neuloží
- Zkontrolujte síťové připojení
- Ověřte, že jste přihlášeni jako staff uživatel
- Zkontrolujte chybové hlášky v notifikacích (pravý dolní roh)

### Chyba "Den neexistuje"
- Den byl pravděpodobně vymazán jiným uživatelem
- Obnovte stránku pro aktuální data

## Podporované funkce

- ✅ Drag-drop mezi dny
- ✅ Touch podpora (tablety, mobily)
- ✅ Autocomplete pro recepty (Select2)
- ✅ Live statistiky
- ✅ Bulk operace (kopírování, mazání dne)
- ✅ Confirm dialogy pro destruktivní akce
- ✅ Toast notifikace
- ✅ Validace na straně serveru i klienta
- ✅ Transparentní efekty v dark mode
- ✅ Responsive design

## Technický stack

- **Frontend**: Vanilla JavaScript (ES6+)
- **Drag-drop**: SortableJS 1.15.0
- **Autocomplete**: Select2 4.1.0-rc.0
- **Backend**: Django 6.0.1
- **AJAX**: Fetch API
- **UI**: Bootstrap 5 + custom CSS

## Výkon

- Optimalizováno pro šablony do 30 dnů
- Podporuje stovky jídel bez zpomalení
- Lazy loading pro recepty
- Minimální znovuvykreslování DOM

## Bezpečnost

- CSRF ochrana na všech AJAX endpointech
- Kontrola staff oprávnění
- Server-side validace všech vstupů
- Transaction atomicity pro konzistenci dat
- XSS prevence (escapování HTML)
