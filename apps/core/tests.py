"""Testy jádra aplikace.

Zatím jen zálohování databáze - tedy to, co po sobě umí nechat nejhorší
škodu, když se přehlédne.
"""

from datetime import datetime, timedelta
from pathlib import Path
import tempfile

from django.contrib.auth.models import User
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from apps.core.db_backup import (
    build_pg_dump_command,
    build_pg_dump_env,
    dump_filename,
    latest_dump_info,
    prune_old_dumps,
)


class DumpCommandTest(TestCase):
    """Sestavení příkazu `pg_dump` a jeho prostředí."""

    DATABASE = {
        'NAME': 'spiz',
        'USER': 'spiz',
        'PASSWORD': 'tajne-heslo',
        'HOST': 'db',
        'PORT': '5432',
    }

    def test_password_not_in_arguments(self):
        """Heslo v argumentech by bylo vidět v `ps` každému na stroji."""
        command = build_pg_dump_command(self.DATABASE)
        self.assertNotIn('tajne-heslo', ' '.join(command))

    def test_password_passed_via_environment(self):
        env = build_pg_dump_env(self.DATABASE)
        self.assertEqual(env['PGPASSWORD'], 'tajne-heslo')

    def test_empty_password_sets_no_variable(self):
        """Prázdné PGPASSWORD by přebilo `.pgpass` a autentizaci rozbilo."""
        env = build_pg_dump_env({**self.DATABASE, 'PASSWORD': ''})
        self.assertNotIn('PGPASSWORD', env)

    def test_command_uses_custom_format(self):
        command = build_pg_dump_command(self.DATABASE)
        self.assertEqual(command[0], 'pg_dump')
        self.assertIn('--format=custom', command)
        # Bez --no-owner by zálohu nešlo nasadit pod jiným db uživatelem.
        self.assertIn('--no-owner', command)
        self.assertIn('--no-privileges', command)
        self.assertEqual(command[-1], 'spiz')

    def test_dump_filename_format(self):
        name = dump_filename(datetime(2026, 9, 17, 3, 17))
        self.assertEqual(name, 'spiz_2026-09-17_0317.dump')


class PruneDumpsTest(TestCase):
    """Mazání starých záloh."""

    def _make_dump(self, directory, name, age_days):
        path = Path(directory) / name
        path.write_bytes(b'x')
        moment = (datetime.now() - timedelta(days=age_days)).timestamp()
        import os
        os.utime(path, (moment, moment))
        return path

    def test_prunes_only_old_dumps(self):
        with tempfile.TemporaryDirectory() as directory:
            old = self._make_dump(directory, 'spiz_2026-01-01_0317.dump', 30)
            fresh = self._make_dump(directory, 'spiz_2026-09-17_0317.dump', 1)

            prune_old_dumps(directory, keep=7)

            self.assertFalse(old.exists())
            self.assertTrue(fresh.exists())

    def test_keep_zero_deletes_nothing(self):
        """keep=0 by jinak smazalo i zálohu, která právě vznikla."""
        with tempfile.TemporaryDirectory() as directory:
            old = self._make_dump(directory, 'spiz_2026-01-01_0317.dump', 30)

            self.assertEqual(prune_old_dumps(directory, keep=0), [])
            self.assertTrue(old.exists())

    def test_unrelated_files_are_kept(self):
        """V adresáři může ležet cokoli jiného - mažeme jen svoje zálohy."""
        with tempfile.TemporaryDirectory() as directory:
            other = Path(directory) / 'poznamky.txt'
            other.write_text('nesmazat')
            import os
            moment = (datetime.now() - timedelta(days=30)).timestamp()
            os.utime(other, (moment, moment))

            prune_old_dumps(directory, keep=7)

            self.assertTrue(other.exists())

    def test_returns_none_without_dumps(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertIsNone(latest_dump_info(directory))

    def test_returns_newest_dump(self):
        with tempfile.TemporaryDirectory() as directory:
            self._make_dump(directory, 'spiz_2026-09-15_0317.dump', 2)
            newest = self._make_dump(directory, 'spiz_2026-09-17_0317.dump', 0)

            info = latest_dump_info(directory)

            self.assertEqual(info['name'], newest.name)
            self.assertEqual(info['count'], 2)


class DumpDownloadPermissionTest(TestCase):
    """Kdo smí stáhnout kompletní zálohu databáze.

    Dump obsahuje hashe hesel všech uživatelů, e-maily a data všech jídelen
    bez ohledu na `UserProfile.canteens`. Kdo ho má, má celou aplikaci -
    proto je tenhle test o oprávněních, ne o formátu souboru.
    """

    def setUp(self):
        self.url = reverse('core:backup_download_dump')
        self.superuser = User.objects.create_superuser(
            'sef', 'sef@example.com', 'heslo123'
        )
        self.staff = User.objects.create_user(
            'personal', 'personal@example.com', 'heslo123', is_staff=True
        )
        self.user = User.objects.create_user(
            'kuchar', 'kuchar@example.com', 'heslo123'
        )

    def test_anonymous_redirected_to_login(self):
        response = self.client.post(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertIn('/login', response['Location'])

    def test_regular_user_forbidden(self):
        self.client.force_login(self.user)
        self.assertEqual(self.client.post(self.url).status_code, 403)

    def test_staff_user_forbidden(self):
        """`is_staff` nestačí - do adminu smí víc lidí než k celé databázi."""
        self.client.force_login(self.staff)
        self.assertEqual(self.client.post(self.url).status_code, 403)

    def test_get_not_allowed(self):
        """GET by šel vyvolat odkazem nebo <img> z cizí stránky."""
        self.client.force_login(self.superuser)
        self.assertEqual(self.client.get(self.url).status_code, 405)

    def test_post_without_csrf_token_forbidden(self):
        """POST bez CSRF tokenu musí skončit 403.

        Výchozí testovací klient CSRF **nekontroluje**, takže by odstranění
        ochrany žádný jiný test neodhalil - jen by se tiše přestalo hlídat,
        že požadavek přišel z naší stránky. Proto klient
        s `enforce_csrf_checks=True`.
        """
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.superuser)

        self.assertEqual(client.post(self.url).status_code, 403)

    @override_settings(DB_DUMP_DOWNLOAD_ENABLED=False)
    def test_kill_switch_blocks_superuser(self):
        self.client.force_login(self.superuser)
        response = self.client.post(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response['Location'], reverse('core:backup_page'))


class HomeInventoryScopeTest(TestCase):
    """Upozornění na probíhající inventury na úvodní stránce.

    Každý dotaz nad daty jídelny musí respektovat jídelny uživatele. Úvodní
    stránka dřív ukazovala probíhající inventury všech jídelen, takže zaměstnanec
    jedné jídelny viděl sklady a jména kolegů z jiných.
    """

    def setUp(self):
        from apps.canteens.models import Canteen, Warehouse
        from apps.core.models import UserProfile
        from apps.inventory.models import InventoryVerification

        self.starter = User.objects.create_user('starter')
        self.canteen_a = Canteen.objects.create(name='Jídelna A')
        self.canteen_b = Canteen.objects.create(name='Jídelna B')
        for canteen in (self.canteen_a, self.canteen_b):
            warehouse = Warehouse.objects.create(name=f'Sklad {canteen.name}', canteen=canteen)
            InventoryVerification.objects.create(
                warehouse=warehouse,
                status=InventoryVerification.Status.IN_PROGRESS,
                started_by=self.starter,
                created_by=self.starter,
            )

        self.user_a = User.objects.create_user('uzivatel_a')
        profile, _ = UserProfile.objects.get_or_create(user=self.user_a)
        profile.canteens.set([self.canteen_a])
        self.superuser = User.objects.create_superuser('admin', password='x')

    def _home(self, user):
        self.client.force_login(user)
        return self.client.get(reverse('home'))

    def test_user_sees_only_own_canteen_inventories(self):
        response = self._home(self.user_a)
        self.assertContains(response, 'Sklad Jídelna A')
        self.assertNotContains(response, 'Sklad Jídelna B')

    def test_superuser_sees_all_inventories(self):
        response = self._home(self.superuser)
        self.assertContains(response, 'Sklad Jídelna A')
        self.assertContains(response, 'Sklad Jídelna B')

    def test_user_without_profile_sees_no_inventories(self):
        from apps.core.models import UserProfile
        user = User.objects.create_user('bezprofilu')
        UserProfile.objects.filter(user=user).delete()
        response = self._home(user)
        self.assertNotContains(response, 'Probíhající inventury')
