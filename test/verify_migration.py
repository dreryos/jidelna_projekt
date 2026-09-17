"""Porovná obsah původní SQLite databáze s novou PostgreSQL.

Jednorázový ověřovací skript k převodu, pytest ho nesbírá (viz `--ignore`
v `pytest.ini`) - připojuje se k ostrým databázím a s testovacími fixturami
nemá co dělat.

Převod `dumpdata` → `loaddata` umí selhat tiše: chybějící tabulka se přeskočí,
`NULL` se doplní defaultem, sekvence zůstane na jedničce a první nový doklad
pak spadne na duplicitní klíč. Proto se nekontroluje „naběhlo to", ale čísla.

Spuštění po `loaddata`, s běžícím PostgreSQL:

    .venv/bin/python test/verify_migration.py
    .venv/bin/python test/verify_migration.py --sqlite /cesta/db.sqlite3

Návratový kód 0 = shoda, 2 = rozdíl. **Rozdíl kdekoli znamená převod zahodit
a zopakovat**, ne dohledávat, jestli zrovna tenhle nevadí.
"""

import argparse
import os
import sqlite3
import sys
from decimal import Decimal
from pathlib import Path

import django

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'spiz_project.settings')
django.setup()

from django.apps import apps  # noqa: E402
from django.db import connection  # noqa: E402

# Tabulky, které se schválně nepřevádějí (`dumpdata --exclude`) - vytvoří je
# `migrate` nebo vzniknou samy za provozu, takže rozdíl v nich je v pořádku.
SKIPPED_TABLES = {
    'django_content_type',
    'auth_permission',
    'django_session',
    'django_admin_log',
    'django_migrations',
}

# Číselné sloupce, které se porovnávají hodnotu po hodnotě - pouhý `count(*)`
# by nechytil posunutou desetinnou čárku ani prohozené sloupce.
CHECKSUMS = [
    ('inventory_stockitem', 'quantity'),
    ('inventory_stockitem', 'quantity_blocked'),
    ('inventory_stockitem', 'price'),
    ('inventory_goodsreceiptitem', 'quantity'),
    ('inventory_goodsreceiptitem', 'price'),
    ('inventory_ingredientpricehistory', 'price'),
    ('production_pickinglist', 'quantity_planned'),
    ('production_pickinglist', 'quantity_actual'),
]


def sqlite_tables(cursor):
    cursor.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' "
        "AND name NOT LIKE 'sqlite_%' ORDER BY name"
    )
    return [row[0] for row in cursor.fetchall()]


def compare_counts(sqlite_cursor, pg_cursor, tables):
    """Vrátí seznam hlášek o rozdílech v počtu řádků."""
    problems = []
    for table in tables:
        if table in SKIPPED_TABLES:
            continue

        sqlite_cursor.execute(f'SELECT count(*) FROM "{table}"')
        sqlite_count = sqlite_cursor.fetchone()[0]

        try:
            pg_cursor.execute(f'SELECT count(*) FROM "{table}"')
        except Exception as error:  # tabulka v PG chybí úplně
            connection.connection.rollback()
            problems.append(f'{table}: v PostgreSQL nelze číst ({error})')
            continue

        pg_count = pg_cursor.fetchone()[0]
        if sqlite_count != pg_count:
            problems.append(
                f'{table}: SQLite {sqlite_count} × PostgreSQL {pg_count} řádků'
            )
    return problems


def compare_values(sqlite_cursor, pg_cursor):
    """Porovná číselné sloupce **řádek po řádku**, ne součtem.

    Součty tu nefungují a je důležité vědět proč: SQLite typy nevynucuje
    a v desetinných sloupcích má hodnoty s delším ocasem, než kolik povoluje
    schéma (`0.03574407244132015` ve sloupci se třemi desetinnými místy).
    PostgreSQL je `numeric(10,3)`, takže každou hodnotu při načtení zaokrouhlí.
    Přes deset tisíc řádků se z těch zaokrouhlení nasčítají desetiny a součty
    se rozejdou, i když je každý jednotlivý řádek v pořádku. Navíc by se
    v součtu vyrušily dvě opačné chyby.

    Proto se porovnává každý řádek zvlášť a tolerance je půl posledního
    povoleného desetinného místa - přesně to, co může udělat zaokrouhlení.
    Cokoli většího je skutečná ztráta dat.
    """
    problems = []
    for table, column in CHECKSUMS:
        sqlite_cursor.execute(f'SELECT id, "{column}" FROM "{table}"')
        sqlite_rows = {
            row[0]: (Decimal(str(row[1])) if row[1] is not None else None)
            for row in sqlite_cursor.fetchall()
        }

        try:
            pg_cursor.execute(
                'SELECT numeric_scale FROM information_schema.columns '
                'WHERE table_name = %s AND column_name = %s',
                [table, column],
            )
            scale_row = pg_cursor.fetchone()
            scale = scale_row[0] if scale_row and scale_row[0] is not None else 3

            pg_cursor.execute(f'SELECT id, "{column}" FROM "{table}"')
            pg_rows = {row[0]: row[1] for row in pg_cursor.fetchall()}
        except Exception as error:
            connection.connection.rollback()
            problems.append(f'{table}.{column}: v PostgreSQL nelze číst ({error})')
            continue

        tolerance = Decimal(1).scaleb(-scale) / 2

        missing = set(sqlite_rows) - set(pg_rows)
        if missing:
            problems.append(
                f'{table}.{column}: v PostgreSQL chybí {len(missing)} řádků '
                f'(např. id {sorted(missing)[:5]})'
            )

        differing = []
        for row_id, sqlite_value in sqlite_rows.items():
            if row_id not in pg_rows:
                continue
            pg_value = pg_rows[row_id]

            if (sqlite_value is None) != (pg_value is None):
                differing.append((row_id, sqlite_value, pg_value))
            elif sqlite_value is not None and abs(sqlite_value - pg_value) > tolerance:
                differing.append((row_id, sqlite_value, pg_value))

        if differing:
            examples = ', '.join(
                f'id {row_id}: {old} × {new}' for row_id, old, new in differing[:5]
            )
            problems.append(
                f'{table}.{column}: {len(differing)} řádků se liší víc než '
                f'o zaokrouhlení ({examples})'
            )

    return problems


def compare_sequences(pg_cursor):
    """Ověří, že sekvence jsou nad MAX(id).

    Tohle je nejčastější tichá chyba po `loaddata`: data se načtou i se svými
    ID, ale sekvence zůstane na začátku a první nový záznam spadne na
    duplicitní primární klíč - klidně až za týden.
    """
    problems = []
    for model in apps.get_models():
        table = model._meta.db_table
        pk_column = model._meta.pk.column

        pg_cursor.execute(
            'SELECT pg_get_serial_sequence(%s, %s)', [table, pk_column]
        )
        sequence = pg_cursor.fetchone()[0]
        if sequence is None:  # není autoincrement (M2M přes through apod.)
            continue

        pg_cursor.execute(f'SELECT coalesce(max("{pk_column}"), 0) FROM "{table}"')
        max_id = pg_cursor.fetchone()[0]

        pg_cursor.execute('SELECT last_value, is_called FROM ' + sequence)
        last_value, is_called = pg_cursor.fetchone()
        next_value = last_value + 1 if is_called else last_value

        if next_value <= max_id:
            problems.append(
                f'{table}: sekvence vydá {next_value}, ale MAX({pk_column}) '
                f'je {max_id} - první nový záznam spadne na duplicitní klíč'
            )
    return problems


def compare_users(sqlite_cursor, pg_cursor):
    """Uživatelé zvlášť - ztráta příznaku is_superuser nebo hesla by znamenala,
    že se do aplikace po převodu nikdo nedostane."""
    query = (
        'SELECT username, is_superuser, is_active, password '
        'FROM auth_user ORDER BY username'
    )
    sqlite_cursor.execute(query)
    sqlite_users = sqlite_cursor.fetchall()

    pg_cursor.execute(query)
    pg_users = pg_cursor.fetchall()

    if sqlite_users == pg_users:
        return []

    problems = []
    sqlite_by_name = {row[0]: row for row in sqlite_users}
    pg_by_name = {row[0]: row for row in pg_users}

    for username in sorted(set(sqlite_by_name) | set(pg_by_name)):
        if username not in pg_by_name:
            problems.append(f'uživatel {username}: v PostgreSQL chybí')
        elif username not in sqlite_by_name:
            problems.append(f'uživatel {username}: v PostgreSQL přebývá')
        elif sqlite_by_name[username] != pg_by_name[username]:
            problems.append(
                f'uživatel {username}: liší se příznaky nebo hash hesla'
            )
    return problems


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '--sqlite',
        default=str(BASE_DIR / 'db.sqlite3'),
        help='Cesta k původní SQLite databázi (výchozí db.sqlite3 v kořeni)',
    )
    args = parser.parse_args()

    sqlite_path = Path(args.sqlite)
    if not sqlite_path.is_file():
        print(f'SQLite databáze {sqlite_path} neexistuje.')
        return 1

    if connection.vendor != 'postgresql':
        print(f'Cílová databáze musí být PostgreSQL, je {connection.vendor}.')
        return 1

    sqlite_connection = sqlite3.connect(f'file:{sqlite_path}?mode=ro', uri=True)
    try:
        sqlite_cursor = sqlite_connection.cursor()
        with connection.cursor() as pg_cursor:
            tables = sqlite_tables(sqlite_cursor)

            problems = (
                compare_counts(sqlite_cursor, pg_cursor, tables)
                + compare_values(sqlite_cursor, pg_cursor)
                + compare_sequences(pg_cursor)
                + compare_users(sqlite_cursor, pg_cursor)
            )
    finally:
        sqlite_connection.close()

    if not problems:
        print(
            f'Shoda: {len(tables) - len(SKIPPED_TABLES & set(tables))} tabulek, '
            'kontrolní součty, sekvence i uživatelé sedí.'
        )
        return 0

    print(f'ROZDÍL: {len(problems)} nálezů. Převod zopakovat.')
    for problem in problems:
        print(f'  - {problem}')
    return 2


if __name__ == '__main__':
    sys.exit(main())
