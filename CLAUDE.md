# CLAUDE.md

Pokyny pro Claude Code při práci v tomto repozitáři.

## Co to je

**SPÍŽ** — Django aplikace pro provoz školní/firemní jídelny: sklad, receptury, jídelníčky, výdejky, příjemky (včetně importu z fotky dokladu přes Mistral OCR), inventury, analytika.

Django 6 / Python 3.14, SQLite, Bootstrap 5, WeasyPrint (PDF), MkDocs (nápověda v aplikaci).

## Jazyk

Celý projekt je česky — UI, hlášky, dokumentace, commit messages, komentáře v kódu, záznamy v CHANGELOG.md. **Piš česky.** Jen názvy proměnných, funkcí a tříd jsou anglicky.

## Příkazy

Vždy přes `.venv` — systémový Python nemá závislosti:

```bash
.venv/bin/python -m pytest apps test    # všechny testy (335+)
.venv/bin/python -m pytest test/test_ocr_client.py -k nazev
.venv/bin/python manage.py check
.venv/bin/python manage.py migrate
.venv/bin/python manage.py runserver
mkdocs build                            # nápověda → staticdocs/
```

- `pytest.ini` má `testpaths = test`, takže holý `pytest` **nespustí** testy v `apps/*/tests/` — proto vždy `pytest apps test`.
- `manage.py test` v tomto projektu nefunguje (kolize `apps/production/tests` adresář vs. soubor). Používej pytest.
- Starší skripty v `test/` (`test_form_readonly.py`, `test_ingredient_deletion.py`, `test_ingredient_soft_delete.py`, `test_vat_implementation.py`, `test_visual_editor.py`) zapisují při importu do ostré DB — jsou proto v `addopts` ignorované. Nesbírej je zpět.
- Testy OCR běží nad uloženými anotacemi v `test/fixtures/ocr/` — nikdy nesahej na skutečné (placené) Mistral API. Bez `MISTRAL_API_KEY` běží zbytek aplikace i testy normálně.

## Struktura

```
apps/core/        suroviny, receptury, kategorie, uživatelské profily, zálohy XML
apps/canteens/    jídelny, sklady (mezisklad, zámek při inventuře)
apps/inventory/   skladové karty, příjemky, dodavatelé, převodky, inventury, odpisy, cenová historie
apps/inventory/ocr/  rozpoznání dokladu z fotky (client, normalize, quirks, schema, storage)
apps/production/  jídelníčky, šablony, výrobní příkazy, varianty porcí, výdejky, PDF
apps/bufet/       import prodejů z pokladny FiskalPRO
apps/analytics/   náklady, vývoj cen, analýzy odpisů a kuchařů
apps/reports/     objednávkový report
spiz_project/     settings, urls
templates/        šablony po modulech
docs/prirucka/    zdroje uživatelské příručky (MkDocs → staticdocs/ → /napoveda/)
```

## Pravidla pro změny

- **Stavové přechody patří na model**, ne do views (`confirm()`, `start_transfer()`, `complete()`, …). Views jen volají metodu a překládají `ValidationError` na hlášku přes `messages`.
- **Žádný zápis do `StockItem` mimo `transaction.atomic` se `select_for_update()`** a žádná změna množství mimo dokladové metody.
- **Doklad = hlavička se stavem + položky** s `unique_together` (doklad, surovina). Nový typ dokladu modeluj podle `StockWriteOff`.
- **Ceny nepočítej znovu ve view** — čti přes `calculate_portion_price()`, `get_prices_bulk()`.
- **Data jsou scoped na jídelnu.** Každý queryset musí respektovat jídelny uživatele (`UserProfile.canteens`); superuser vidí vše. `ReadOnlyUserMiddleware` blokuje zápis uživatelům s `is_readonly`.
- **Migrace** vždy vygeneruj a přilož ke commitu, který mění model.

## Šablonové pasti (opakovaně kousaly)

- ID v atributech formulářů lokalizuj filtrem `|unlocalize` — jinak Django vloží u čísel nad 999 mezeru jako oddělovač tisíců a párování polí se rozbije. Hlídá `test/test_template_id_localization.py`.
- Víceřádkový `{# … #}` komentář Django neodstraní a text unikne do stránky — na víc řádků použij `{% comment %} … {% endcomment %}`.
- `format_html()` bez formátovacího argumentu je od Djanga 5.0 tvrdý `TypeError`, ne warning.
- České desetinné číslo se píše čárkou (`USE_THOUSAND_SEPARATOR = True`, `DECIMAL_SEPARATOR = ','`); formuláře musí brát čárku i tečku.
- PDF výdejky je A5 portrait pro černobílý tisk — po zásahu do PDF zkontroluj výstup okem.

## Git

- Conventional Commits s českým popisem: `fix(inventory): zopakovat OCR volání po přechodné chybě API`. Scope = název aplikace (`core`, `inventory`, `production`, `analytics`, `templates`, `docs`).
- Tělo commitu vysvětluje **proč** a co by se bez opravy stalo — to je v tomhle repu zavedený zvyk, drž ho.
- Větve: `feat/…`, `fix/…`, `docs/…` s českým kebab-case popisem. Práce jde na main přes PR.
- Nezapomeň `Co-Authored-By:` u commitů, na kterých jsi dělal.

## Před commitem

1. `.venv/bin/python -m pytest apps test`
2. `.venv/bin/python manage.py check`
3. Záznam do `CHANGELOG.md` do sekce `[Unreleased]` — česky, s datem, ve stylu okolních položek (co se změnilo a proč, ne výčet souborů).
4. Dotkl ses chování popsaného v příručce? Aktualizuj `docs/prirucka/`.

## Kam se podívat dál

- `docs/prirucka/13-pro-vyvojare.md` — datový model, **návrhová rozhodnutí a jejich důvody**, známé zvláštnosti. Čti před většími zásahy.
- `docs/overview.md`, `docs/inventory.md`, `docs/production.md`, `docs/price_history.md` — vývojářské poznámky k modulům.
- `README.md` — instalace, proměnné prostředí, přehled modelů.
- `CHANGELOG.md` — historie změn včetně důvodů.
