"""Porovná české řazení v Pythonu a v PostgreSQL (ICU).

Jednorázový ověřovací skript k převodu na PostgreSQL, pytest ho nesbírá
(viz `--ignore` v `pytest.ini`).

Proč to vůbec porovnávat: do PostgreSQL jsme kolaci `czech` zavedli jako ICU
kolaci `cs-CZ` (migrace `core/0011_czech_collation`), zatímco do té doby řadil
názvy surovin ruční algoritmus v `apps/core/collation.py`. Oba znají „ch" jako
jedno písmeno mezi H a I, ale sekundární váhy (diakritika, velikost písmen)
se lišit mohou. Rozdíl znamená, že se uživateli po převodu přeházejí seznamy
surovin - což je drobnost, ale má se o ní vědět předem, ne ji objevit
v provozu.

Spuštění (potřebuje běžící PostgreSQL s načtenými daty):

    .venv/bin/python test/verify_collation.py
"""

import os
import sys
from pathlib import Path

import django

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'spiz_project.settings')
django.setup()

from django.db import connection  # noqa: E402

from apps.core.collation import czech_sort_key  # noqa: E402
from apps.core.models import Ingredient  # noqa: E402


def sorted_by_python(names):
    """Pořadí podle ruční implementace, která běžela nad SQLite."""
    return sorted(names, key=lambda name: (czech_sort_key(name), name))


def sorted_by_icu(names):
    """Pořadí podle ICU kolace `czech` přímo z PostgreSQL."""
    with connection.cursor() as cursor:
        cursor.execute(
            'SELECT name FROM unnest(%s::text[]) AS t(name) '
            'ORDER BY name COLLATE "czech"',
            [list(names)],
        )
        return [row[0] for row in cursor.fetchall()]


def main():
    if connection.vendor != 'postgresql':
        print('Skript má smysl jen nad PostgreSQL, aktuální backend: '
              f'{connection.vendor}')
        return 1

    names = list(Ingredient.objects.values_list('name', flat=True))
    if not names:
        print('V databázi nejsou žádné suroviny - není co porovnávat.')
        return 1

    by_python = sorted_by_python(names)
    by_icu = sorted_by_icu(names)

    if by_python == by_icu:
        print(f'Shoda: {len(names)} názvů, obě kolace řadí stejně.')
        return 0

    # Vypisujeme jen pozice, kde se pořadí rozchází - u pěti set názvů
    # je jinak výstup nečitelný.
    differences = [
        (index, python_name, icu_name)
        for index, (python_name, icu_name) in enumerate(zip(by_python, by_icu))
        if python_name != icu_name
    ]

    print(f'ROZDÍL: {len(differences)} pozic z {len(names)}.')
    print(f'{"poz.":>5}  {"Python (SQLite)":<40}  ICU (PostgreSQL)')
    for index, python_name, icu_name in differences[:50]:
        print(f'{index:>5}  {python_name:<40}  {icu_name}')
    if len(differences) > 50:
        print(f'... a dalších {len(differences) - 50}')

    return 2


if __name__ == '__main__':
    sys.exit(main())
