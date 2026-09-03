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

import pytest

# Hlídají se atributy, jejichž obsah se posílá na server – tam lokalizované
# ID znamená přijatá data mimo. `id=` a `data-*` mají stejnou vadu (rozbitý
# JS selektor), ale zbytek aplikace je zatím nemá pročištěný, takže by test
# jen šuměl; importní kroky a výdejky pročištěné jsou.
ATTR = re.compile(r'\b(?:name|value)="([^"]*)"')
VAR = re.compile(r'\{\{ *([^}]+?) *\}\}')
# Výrazy, jejichž hodnota je celé číslo (ID nebo index cyklu).
RISKY = re.compile(r'(\.(id|pk)|_id|forloop\.(parentloop\.)?counter0?)$')

ROOTS = [Path('templates'), Path('apps')]


def rizikove_vyrazy():
    for root in ROOTS:
        for path in sorted(root.rglob('*.html')):
            for cislo, radek in enumerate(path.read_text().splitlines(), 1):
                for hodnota in ATTR.findall(radek):
                    for vyraz in VAR.findall(hodnota):
                        holy = vyraz.split('|')[0].strip()
                        if RISKY.search(holy) and 'unlocalize' not in vyraz:
                            yield f'{path}:{cislo}: {{{{ {vyraz} }}}}'


def test_id_v_atributech_maji_unlocalize():
    nalezy = list(rizikove_vyrazy())
    assert not nalezy, (
        'ID/index v HTML atributu bez |unlocalize – při ID nad 999 se '
        'vykreslí s mezerou a formulář se rozbije:\n  ' + '\n  '.join(nalezy)
    )
