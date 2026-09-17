"""Záloha databáze přes ``pg_dump``.

Dvě cesty, jedno jádro:

* **Stažení na klik** (``stream_pg_dump``) - dump teče rovnou do odpovědi,
  na disku serveru nevzniká žádný soubor. Kdyby vznikal, ležel by tam
  kompletní obsah databáze a čekal, až ho někdo zapomene smazat.
* **Noční automat** (``write_dump_to_file``) - zapíše soubor do datového
  adresáře a smaže starší než ``keep`` dní.

Co dump obsahuje, je potřeba mít napsané nahlas: **hashe hesel všech
uživatelů, e-maily a kompletní data všech jídelen bez ohledu na
``UserProfile.canteens``.** Kdo soubor má, má celou aplikaci. Patří proto
jen na šifrovaný disk a stahuje se výhradně přes HTTPS.

Heslo k databázi se předává **jen přes ``PGPASSWORD`` v prostředí
podprocesu**, nikdy jako argument - argumenty jsou vidět v ``ps`` každému
uživateli na stroji.
"""

import logging
import os
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

from django.conf import settings

logger = logging.getLogger('apps.core')

# Velikost bloku při streamování. 64 kB je kompromis mezi počtem iterací
# a pamětí drženou na jeden běžící download.
CHUNK_SIZE = 64 * 1024

DUMP_FILENAME_PREFIX = 'spiz_'
DUMP_FILENAME_SUFFIX = '.dump'


def get_backup_dir():
    """Adresář s automatickými zálohami. Musí být mimo MEDIA_ROOT
    i STATIC_ROOT, aby zálohu nikdy neposlala statika."""
    return Path(getattr(settings, 'DB_BACKUP_DIR', settings.BASE_DIR / 'data' / 'backups'))


def dump_filename(moment=None):
    """Název souboru zálohy. Bez sekund - dvě zálohy ve stejné minutě
    nedávají smysl a kratší název se líp čte."""
    moment = moment or datetime.now()
    return f"{DUMP_FILENAME_PREFIX}{moment.strftime('%Y-%m-%d_%H%M')}{DUMP_FILENAME_SUFFIX}"


def build_pg_dump_command(database=None):
    """Sestaví argumenty ``pg_dump`` z konfigurace databáze.

    ``-Fc`` (custom formát) kvůli tomu, že ``pg_restore`` z něj umí obnovit
    i jednotlivé tabulky a rovnou komprimuje. ``--no-owner`` a
    ``--no-privileges`` proto, aby šla záloha nasadit i pod jiným
    databázovým uživatelem, než pod kterým vznikla.
    """
    database = database or settings.DATABASES['default']

    command = [
        'pg_dump',
        '--format=custom',
        '--no-owner',
        '--no-privileges',
        '--host', str(database.get('HOST') or 'localhost'),
        '--port', str(database.get('PORT') or '5432'),
        '--username', str(database.get('USER') or ''),
        str(database.get('NAME') or ''),
    ]
    return command


def build_pg_dump_env(database=None):
    """Prostředí pro podproces. Heslo jen tudy, nikdy v argumentech."""
    database = database or settings.DATABASES['default']

    env = os.environ.copy()
    password = database.get('PASSWORD')
    if password:
        env['PGPASSWORD'] = str(password)
    return env


def _spawn_pg_dump(stdout):
    return subprocess.Popen(
        build_pg_dump_command(),
        stdout=stdout,
        stderr=subprocess.PIPE,
        env=build_pg_dump_env(),
    )


def stream_pg_dump():
    """Generátor bloků dumpu pro ``StreamingHttpResponse``.

    Nevzniká dočasný soubor. Nenulový návratový kód ``pg_dump`` skončí
    výjimkou - jinak by si uživatel stáhl neúplný soubor a považoval ho
    za zálohu. Pozor: hlavičky odpovědi už jsou v tu chvíli odeslané,
    takže se chyba projeví přerušeným stahováním, ne stránkou s chybou.
    Proto je důležité zálohu po stažení vyzkoušet obnovit.
    """
    process = _spawn_pg_dump(subprocess.PIPE)

    try:
        while True:
            chunk = process.stdout.read(CHUNK_SIZE)
            if not chunk:
                break
            yield chunk
    finally:
        if process.stdout:
            process.stdout.close()
        stderr = process.stderr.read() if process.stderr else b''
        if process.stderr:
            process.stderr.close()
        returncode = process.wait()

    if returncode != 0:
        message = stderr.decode('utf-8', errors='replace').strip()
        raise RuntimeError(f"pg_dump skončil s kódem {returncode}: {message}")


def write_dump_to_file(directory=None, keep=7):
    """Zapíše zálohu do souboru a smaže zálohy starší než ``keep`` dní.

    Vrací cestu k vytvořenému souboru. Při chybě ``pg_dump`` se rozdělaný
    soubor maže - nedopsaný dump vypadá jako záloha, ale není.
    """
    directory = Path(directory) if directory else get_backup_dir()
    directory.mkdir(parents=True, exist_ok=True)

    target = directory / dump_filename()

    with open(target, 'wb') as handle:
        process = _spawn_pg_dump(handle)
        stderr = process.stderr.read() if process.stderr else b''
        if process.stderr:
            process.stderr.close()
        returncode = process.wait()

    if returncode != 0:
        target.unlink(missing_ok=True)
        message = stderr.decode('utf-8', errors='replace').strip()
        raise RuntimeError(f"pg_dump skončil s kódem {returncode}: {message}")

    prune_old_dumps(directory, keep)
    return target


def prune_old_dumps(directory=None, keep=7):
    """Smaže zálohy starší než ``keep`` dní. Vrací seznam smazaných cest."""
    directory = Path(directory) if directory else get_backup_dir()
    if not directory.exists():
        return []

    # keep=0 by znamenalo smazat i zálohu, která právě vznikla.
    if keep <= 0:
        return []

    threshold = datetime.now() - timedelta(days=keep)
    removed = []

    for path in directory.glob(f'{DUMP_FILENAME_PREFIX}*{DUMP_FILENAME_SUFFIX}'):
        if datetime.fromtimestamp(path.stat().st_mtime) < threshold:
            path.unlink()
            removed.append(path)
            logger.info(f"Smazána stará záloha databáze: {path.name}")

    return removed


def latest_dump_info(directory=None):
    """Údaje o poslední automatické záloze pro stránku /backup/.

    Vrací ``None``, když žádná není - typicky než poprvé proběhne noční
    cron. Stránka to musí umět zobrazit, ne spadnout.
    """
    directory = Path(directory) if directory else get_backup_dir()
    if not directory.exists():
        return None

    dumps = list(directory.glob(f'{DUMP_FILENAME_PREFIX}*{DUMP_FILENAME_SUFFIX}'))
    if not dumps:
        return None

    latest = max(dumps, key=lambda path: path.stat().st_mtime)
    stat = latest.stat()
    return {
        'name': latest.name,
        'size': stat.st_size,
        'created_at': datetime.fromtimestamp(stat.st_mtime),
        'count': len(dumps),
    }
