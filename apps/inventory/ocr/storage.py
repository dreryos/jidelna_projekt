"""
Dočasné úložiště naskenovaných dokladů.

Fotka dokladu je pracovní materiál, ne archiv. Slouží jen k tomu, aby si
uživatel mohl při kontrole položek prohlédnout originál. Jakmile je příjemka
potvrzená, foto se maže; co nikdo nepotvrdil, vyprší po `OCR_SCAN_RETENTION_DAYS`.

Pro audit zůstává rozpoznaná anotace v databázi – je malá, čitelná a na rozdíl
od fotky se z ní dá zpětně zjistit, co systém z dokladu přečetl.

Soubory leží v `MEDIA_ROOT/receipt_scans/<RRRR-MM-DD>/<uuid>.<přípona>`.
Datum v cestě znamená, že úklid nemusí sahat na metadata souborů – stačí mu
názvy adresářů.
"""
import logging
import re
import uuid
from datetime import date, datetime, timedelta

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage

logger = logging.getLogger('apps.inventory')

SCAN_SUBDIR = 'receipt_scans'
DEFAULT_RETENTION_DAYS = 7

EXTENSION_BY_MIME = {
    'image/jpeg': 'jpg',
    'image/png': 'png',
    'application/pdf': 'pdf',
}

DAY_DIR_RE = re.compile(r'^\d{4}-\d{2}-\d{2}$')

# Značka posledního úklidu. Projekt nemá frontu ani plánovač, takže se úklid
# veze na nahrávání dokladů – tenhle soubor hlídá, aby proběhl nejvýš jednou
# denně a nezdržoval každý upload.
PURGE_MARKER = f'{SCAN_SUBDIR}/.last-purge'


def retention_days():
    return int(getattr(settings, 'OCR_SCAN_RETENTION_DAYS', DEFAULT_RETENTION_DAYS))


def save_scan(content, mime_type='image/jpeg', today=None):
    """
    Uloží sken a vrátí cestu relativní k MEDIA_ROOT.

    Název souboru je náhodné UUID – původní název od uživatele se nepoužívá,
    aby se do cesty nedostalo nic, co tam nepatří.
    """
    day = (today or date.today()).isoformat()
    extension = EXTENSION_BY_MIME.get(mime_type, 'jpg')
    name = f'{SCAN_SUBDIR}/{day}/{uuid.uuid4().hex}.{extension}'

    saved_name = default_storage.save(name, ContentFile(content))
    logger.info('Uložen sken dokladu %s (%d kB)', saved_name, len(content) // 1024)
    return saved_name


def delete_scan(path):
    """
    Smaže jeden sken. Volá se po potvrzení příjemky – dál už není k ničemu.

    Returns:
        True, pokud soubor existoval a byl smazán.
    """
    if not path:
        return False

    if not default_storage.exists(path):
        return False

    default_storage.delete(path)
    logger.info('Smazán sken dokladu %s', path)
    return True


def purge_expired_scans(days=None, today=None, dry_run=False):
    """
    Smaže skeny starší než daný počet dní.

    Rozhoduje se podle data v cestě, ne podle času úpravy souboru, takže
    výsledek nezávisí na tom, jestli něco souborům nesáhlo na mtime.

    Returns:
        dict se statistikou: `deleted_files`, `deleted_days`, `kept_days`, `bytes`.
    """
    days = retention_days() if days is None else int(days)
    cutoff = (today or date.today()) - timedelta(days=days)

    stats = {'deleted_files': 0, 'deleted_days': 0, 'kept_days': 0, 'bytes': 0}

    if not default_storage.exists(SCAN_SUBDIR):
        return stats

    day_dirs, _files = default_storage.listdir(SCAN_SUBDIR)
    for day_dir in day_dirs:
        if not DAY_DIR_RE.match(day_dir):
            logger.warning('Ve složce se skeny je neočekávaný adresář %s', day_dir)
            continue

        day = datetime.strptime(day_dir, '%Y-%m-%d').date()
        if day > cutoff:
            stats['kept_days'] += 1
            continue

        _purge_day(day_dir, stats, dry_run)
        stats['deleted_days'] += 1

    logger.info(
        'Úklid skenů (lhůta %d dní, hranice %s): smazáno %d souborů z %d dnů, '
        '%d kB%s',
        days, cutoff, stats['deleted_files'], stats['deleted_days'],
        stats['bytes'] // 1024, ' (nanečisto)' if dry_run else '',
    )
    return stats


def _purge_day(day_dir, stats, dry_run):
    prefix = f'{SCAN_SUBDIR}/{day_dir}'
    try:
        _subdirs, files = default_storage.listdir(prefix)
    except FileNotFoundError:
        # Souběžný worker může celý den domazat (soubory i adresář) dřív,
        # než sem dorazí tenhle – `purge_expired_scans` sestavil seznam
        # dnů z dřívějšího `listdir(SCAN_SUBDIR)`, mezitím zastaralého.
        # Prázdný adresář je přesně to, co tenhle úklid chtěl dosáhnout.
        return

    for file_name in files:
        path = f'{prefix}/{file_name}'
        try:
            stats['bytes'] += default_storage.size(path)
        except (OSError, NotImplementedError):
            pass
        if not dry_run:
            try:
                default_storage.delete(path)
            except FileNotFoundError:
                # `maybe_purge()` běží synchronně při nahrávání dokladu –
                # se dvěma gunicorn workery může na stejný den narazit
                # i druhý souběžný upload. Kdo smaže soubor jako druhý,
                # ho už nenajde; výsledek (soubor pryč) je stejný, takže
                # se to nemá počítat za chybu.
                pass
        stats['deleted_files'] += 1

    if dry_run:
        return

    # Prázdný adresář po dni umí uklidit jen lokální úložiště; u ostatních
    # backendů adresáře stejně neexistují, takže chybu ignorujeme.
    try:
        default_storage.delete(prefix)
    except (OSError, NotImplementedError):
        pass


def maybe_purge(today=None):
    """
    Uklidí prošlé skeny, pokud dnes úklid ještě neproběhl.

    Volá se při nahrání dalšího dokladu. Díky tomu lhůta platí i tam, kde nikdo
    nenastavil cron – `manage.py purge_receipt_scans` zůstává jako spolehlivější
    cesta pro nasazení, kde plánovač je.

    Returns:
        statistika úklidu, nebo None, když se dnes uklízet nemuselo.
    """
    today = today or date.today()
    stamp = today.isoformat()

    if _read_purge_marker() == stamp:
        return None

    # Značku zapisujeme před úklidem. Když úklid spadne, nezacyklí se na něm
    # každý další upload; příště to zkusí cron nebo zítřejší nahrání.
    _write_purge_marker(stamp)
    return purge_expired_scans(today=today)


def _read_purge_marker():
    if not default_storage.exists(PURGE_MARKER):
        return None
    try:
        with default_storage.open(PURGE_MARKER) as marker:
            return marker.read().decode('ascii').strip()
    except (OSError, UnicodeDecodeError):
        return None


def _write_purge_marker(stamp):
    try:
        if default_storage.exists(PURGE_MARKER):
            default_storage.delete(PURGE_MARKER)
        default_storage.save(PURGE_MARKER, ContentFile(stamp.encode('ascii')))
    except OSError as exc:
        logger.warning('Značku úklidu skenů se nepodařilo zapsat: %s', exc)
