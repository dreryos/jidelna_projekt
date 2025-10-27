# Import CSV - Dokumentace

## Přehled funkcionality

Modul Import CSV umožňuje hromadné nahrání skladových položek z CSV souboru s inteligentním mapováním surovin.

## Workflow importu

### Krok 1: Nahrání souboru
- Uživatel vybere cílový sklad
- Nahraje CSV soubor (UTF-8 nebo Windows-1250)
- Systém parsuje soubor a detekuje strukturu

### Krok 2: Náhled a mapování
- Systém analyzuje každou položku
- **Existující suroviny**: Automaticky namapovány (zelená značka)
- **Nové suroviny**: Uživatel rozhodne pro každou položku:
  - ✅ **Vytvořit novou** - vytvoří novou surovinu s názvem z CSV
  - 🔗 **Namapovat** - přiřadí k existující surovině (s našeptávačem)
  - ⏭️ **Přeskočit** - tuto položku neimportuje

### Krok 3: Potvrzení
- Uživatel potvrdí import
- Systém v transakci:
  - Vytvoří nové suroviny (pokud bylo vybráno)
  - Vytvoří nebo aktualizuje skladové položky
  - U existujících položek přičte množství a aktualizuje cenu

## Formát CSV souboru

### Požadované sloupce

```csv
"Kód položky","Název položky","Šarže / Expirace","Množství (MJ)","Jednotka","Cena za MJ (Kč)","Celkem (Kč)"
```

### Příklad

```csv
"CHL001","Chléb konzumní bochník","14.07. / 17.07.2025",25,"ks",42,1050
"MLK003","Mléko polotučné trvanlivé","L24180A / 15.12.2025",60,"l",18.5,1110
"MAS012","Kuřecí prsa chlazená","20250714B / 19.07.2025",15,"kg",145,2175
```

### Normalizace jednotek

Systém automaticky normalizuje jednotky:

| Z CSV | Normalizováno |
|-------|---------------|
| `ks`, `kus`, `kusy` | `ks` |
| `kg`, `kilogram` | `kg` |
| `l`, `litr`, `litry`, `l (ks)` | `l` |
| `bal`, `balení`, `bal (1kg)` | `bal` |
| `plato`, `plato (30ks)` | `plato` |
| `bedna`, `bedna (15kg)` | `bedna` |

## Bezpečnostní prvky

1. **Validace dat**: 
   - Kontrola formátu čísel (množství, cena)
   - Ošetření neplatných řádků (přeskočí se)

2. **Transakční zpracování**:
   - Celý import proběhne v DB transakci
   - Při chybě se všechny změny vrátí zpět

3. **Preview před importem**:
   - Uživatel vidí všechny položky před potvrzením
   - Může rozhodnout o každé položce samostatně

4. **Intelligent matching**:
   - Systém nabízí podobné suroviny pro mapování
   - Case-insensitive porovnání názvů

## URL cesty

- `/inventory/import/` - Krok 1: Upload CSV
- `/inventory/import/confirm/` - Krok 2: Potvrzení a import

## Použití v kódu

### Parsování CSV

```python
from apps.inventory.views import parse_csv_file

with open('file.csv', 'r', encoding='utf-8') as f:
    content = f.read()

rows = parse_csv_file(content)
# rows = [{'name': '...', 'quantity': 10.0, 'unit': 'kg', 'price': 25.5, ...}, ...]
```

### Normalizace jednotky

```python
from apps.inventory.views import normalize_unit

unit = normalize_unit('l (ks)')  # -> 'l'
unit = normalize_unit('bal (1kg)')  # -> 'bal'
```

## Příklad použití

1. **Přístup**:
   ```
   http://127.0.0.1:8000/inventory/import/
   ```

2. **Vybrat sklad**: "Hlavní sklad (Testovací jídelna)"

3. **Nahrát soubor**: `mock_přijem1.csv`

4. **V náhledu**:
   - "Chléb konzumní" - ✅ Existuje → automaticky použije
   - "Mléko polotučné" - ✅ Existuje → automaticky použije
   - "Kuřecí prsa" - ⚠️ Nová → vybrat akci (vytvořit/mapovat/přeskočit)

5. **Potvrdit**: Import proběhne

6. **Výsledek**: 
   ```
   ✅ Import dokončen! 
   Importováno: 8 položek, vytvořeno nových surovin: 6.
   ```

## Chybové stavy

### Chyba při parsování
```
❌ CSV soubor neobsahuje žádná data nebo má nesprávný formát.
```
**Řešení**: Zkontrolujte strukturu CSV, správné hlavičky sloupců

### Chyba kódování
```
❌ Nepodařilo se načíst soubor. Zkontrolujte kódování.
```
**Řešení**: Soubor musí být v UTF-8 nebo Windows-1250

### Chybějící sklad
```
❌ Vybraný sklad neexistuje.
```
**Řešení**: Nejprve vytvořte sklad přes /inventory/warehouses/

### Session vypršela
```
❌ Import session vypršela. Začněte znovu.
```
**Řešení**: Znovu nahrajte CSV v kroku 1

## Limitace

- Maximální velikost CSV: 5 MB (nastavitelné)
- Session timeout: standardní Django session (defaultně 2 týdny)
- Transakční zpracování: celý import musí projít nebo se vše vrátí

## Budoucí vylepšení

- [ ] Export šablony CSV
- [ ] Batch import více souborů
- [ ] Import z Excel (.xlsx)
- [ ] Historie importů
- [ ] Asynchronní import pro velké soubory
- [ ] Automatické mapování pomocí fuzzy matching
- [ ] Podpora pro aktualizaci existujících položek (volba přepsat/přičíst)
