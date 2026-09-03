"""
Pojistka proti lokalizaci ID v HTML atributech.

Projekt má `USE_THOUSAND_SEPARATOR = True` a české locale, takže Django
v šabloně vykreslí celé číslo 4598 jako „4 598" (s nedělitelnou mezerou).
U textu je to správně, u `name="factor_{{ item.pk }}"` nebo
`value="{{ ingredient.id }}"` to rozbije formulář: prohlížeč pošle jiný klíč
či hodnotu, než jakou view hledá, a uživatel dostane nesrozumitelnou chybu
(např. „zadejte přepočet jako číslo" i po zadání jedničky).

Bomba je časovaná – projeví se až ID překročí 999, tedy typicky na produkci
a dávno po napsání šablony. Proto statická kontrola místo čekání na průšvih.
"""
import re
from pathlib import Path

# Hlídají se atributy, jejichž obsah se posílá na server – tam lokalizované
# ID znamená přijatá data mimo. `id=` a `data-*` mají stejnou vadu (rozbitý
# JS selektor), ale zbytek aplikace je zatím nemá pročištěný, takže by test
# jen šuměl; importní kroky a výdejky pročištěné jsou.
# Obě uvozovky a hodnota přes víc řádků – pojistka nesmí mlčet jen proto,
# že šablona atribut zapsala jinak, než se čekalo.
ATTR = re.compile(r'\b(?:name|value)=(?P<q>["\'])(?P<val>(?:(?!(?P=q)).)*)(?P=q)', re.S)
VAR = re.compile(r'\{\{ *([^}]+?) *\}\}')
# Výrazy, jejichž hodnota je celé číslo (ID nebo index cyklu).
RISKY = re.compile(r'(\.(id|pk)|_id|forloop\.(parentloop\.)?counter0?)$')

ROOTS = [Path('templates'), Path('apps')]


def rizikove_vyrazy():
    for root in ROOTS:
        for path in sorted(root.rglob('*.html')):
            obsah = path.read_text()
            for atribut in ATTR.finditer(obsah):
                for promenna in VAR.finditer(atribut.group('val')):
                    vyraz = promenna.group(1)
                    holy = vyraz.split('|')[0].strip()
                    if not RISKY.search(holy) or 'unlocalize' in vyraz:
                        continue
                    # Pozice proměnné v souboru, ne v atributu – u atributu
                    # přes víc řádků by jinak číslo ukazovalo na jeho začátek.
                    pozice = atribut.start('val') + promenna.start()
                    cislo = obsah.count('\n', 0, pozice) + 1
                    yield f'{path}:{cislo}: {{{{ {vyraz} }}}}'


def test_id_v_atributech_maji_unlocalize():
    nalezy = list(rizikove_vyrazy())
    assert not nalezy, (
        'ID/index v HTML atributu bez |unlocalize – při ID nad 999 se '
        'vykreslí s mezerou a formulář se rozbije:\n  ' + '\n  '.join(nalezy)
    )
