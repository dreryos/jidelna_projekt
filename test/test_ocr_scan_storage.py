"""
Testy dočasného úložiště skenů dokladů.

Fotky dokladů se nearchivují: po potvrzení příjemky se mažou hned, rozdělané
importy vyprší po nastavené lhůtě. Testy hlídají obojí a běží nad dočasným
MEDIA_ROOT, takže nesahají na skutečné úložiště.
"""
from datetime import date, timedelta

import pytest
from django.core.files.storage import default_storage
from django.test import override_settings

from apps.inventory.ocr import storage


@pytest.fixture
def media_root(tmp_path):
    with override_settings(MEDIA_ROOT=tmp_path, OCR_SCAN_RETENTION_DAYS=7):
        yield tmp_path


def test_ulozeni_skenu_vytvori_cestu_s_datem(media_root):
    path = storage.save_scan(b'data', 'image/jpeg', today=date(2026, 9, 2))

    assert path.startswith('receipt_scans/2026-09-02/')
    assert path.endswith('.jpg')
    assert default_storage.exists(path)


def test_nazev_souboru_neobsahuje_uzivatelsky_vstup(media_root):
    """Název od uživatele se zahazuje, v cestě je jen UUID."""
    first = storage.save_scan(b'a', 'image/jpeg')
    second = storage.save_scan(b'b', 'image/jpeg')

    assert first != second


def test_pdf_dostane_spravnou_priponu(media_root):
    path = storage.save_scan(b'%PDF-', 'application/pdf')

    assert path.endswith('.pdf')


def test_smazani_po_potvrzeni_prijemky(media_root):
    path = storage.save_scan(b'data', 'image/jpeg')

    assert storage.delete_scan(path) is True
    assert not default_storage.exists(path)
    # Opakované smazání nespadne – potvrzení se může zopakovat.
    assert storage.delete_scan(path) is False
    assert storage.delete_scan('') is False


def test_uklid_smaze_stare_a_nechá_cerstve(media_root):
    dnes = date(2026, 9, 2)
    stary = storage.save_scan(b'stary', 'image/jpeg', today=dnes - timedelta(days=8))
    hranicni = storage.save_scan(b'hranicni', 'image/jpeg', today=dnes - timedelta(days=7))
    cerstvy = storage.save_scan(b'cerstvy', 'image/jpeg', today=dnes - timedelta(days=6))

    stats = storage.purge_expired_scans(today=dnes)

    assert stats['deleted_files'] == 2
    assert not default_storage.exists(stary)
    # Sken starý přesně sedm dní lhůtu vyčerpal.
    assert not default_storage.exists(hranicni)
    assert default_storage.exists(cerstvy)


def test_uklid_nanecisto_nic_nemaze(media_root):
    path = storage.save_scan(b'data', 'image/jpeg', today=date(2026, 1, 1))

    stats = storage.purge_expired_scans(today=date(2026, 9, 2), dry_run=True)

    assert stats['deleted_files'] == 1
    assert default_storage.exists(path)


def test_uklid_bez_slozky_skenu_projde(media_root):
    assert storage.purge_expired_scans()['deleted_files'] == 0


def test_uklid_ignoruje_cizi_adresar(media_root):
    (media_root / 'receipt_scans' / 'neco-jineho').mkdir(parents=True)

    stats = storage.purge_expired_scans(today=date(2026, 9, 2))

    assert stats['deleted_files'] == 0
    assert (media_root / 'receipt_scans' / 'neco-jineho').exists()


def test_lhuta_se_bere_z_nastaveni(media_root):
    with override_settings(OCR_SCAN_RETENTION_DAYS=30):
        assert storage.retention_days() == 30


def test_uklid_pri_nahravani_probehne_jednou_denne(media_root):
    dnes = date(2026, 9, 2)
    storage.save_scan(b'stary', 'image/jpeg', today=dnes - timedelta(days=10))

    prvni = storage.maybe_purge(today=dnes)
    assert prvni is not None and prvni['deleted_files'] == 1

    # Druhé nahrání téhož dne už úklid nespouští.
    assert storage.maybe_purge(today=dnes) is None
    # Další den zase ano.
    assert storage.maybe_purge(today=dnes + timedelta(days=1)) is not None


def test_znacka_uklidu_neni_povazovana_za_sken(media_root):
    dnes = date(2026, 9, 2)
    storage.maybe_purge(today=dnes)

    stats = storage.purge_expired_scans(today=dnes + timedelta(days=30))

    assert stats['deleted_files'] == 0


def test_uklid_prezije_soubor_smazany_soubezne(media_root, monkeypatch):
    """
    `maybe_purge()` běží synchronně při nahrávání dokladu – se dvěma gunicorn
    workery může na stejný prošlý den narazit i souběžný upload. Oba si
    přečtou stejný výpis souborů (`listdir`), ale kdo smaže soubor jako
    druhý, ho už tam nenajde. Výsledek (soubor pryč) je stejný jako úspěch,
    ne chyba, se kterou má spadnout celý upload dokladu.
    """
    stary = date(2026, 9, 2) - timedelta(days=10)
    storage.save_scan(b'a', 'image/jpeg', today=stary)

    original_delete = default_storage.delete

    def delete_jako_by_uz_soubor_zmizel(path):
        original_delete(path)
        raise FileNotFoundError(path)

    monkeypatch.setattr(default_storage, 'delete', delete_jako_by_uz_soubor_zmizel)

    stats = {'deleted_files': 0, 'deleted_days': 0, 'kept_days': 0, 'bytes': 0}
    storage._purge_day(stary.isoformat(), stats, dry_run=False)

    assert stats['deleted_files'] == 1
