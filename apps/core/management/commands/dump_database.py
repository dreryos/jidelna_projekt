"""Automatická záloha databáze pro noční cron.

Spouští se z hostitelského cronu, ne z další služby v compose:

    17 3 * * * cd /opt/spiz && docker compose exec -T spiz python manage.py dump_database --keep 7

Čas 03:17, ne 03:00 - ať nekoliduje s ostatními nočními úlohami.
"""

from django.core.management.base import BaseCommand, CommandError

from apps.core.db_backup import get_backup_dir, write_dump_to_file


class Command(BaseCommand):
    help = 'Vytvoří zálohu databáze (pg_dump) a smaže zálohy starší než zadaný počet dní'

    def add_arguments(self, parser):
        parser.add_argument(
            '--output-dir',
            default=None,
            help='Adresář pro zálohy (výchozí podle nastavení DB_BACKUP_DIR)',
        )
        parser.add_argument(
            '--keep',
            type=int,
            default=7,
            help='Kolik dní zálohy držet (výchozí 7)',
        )

    def handle(self, *args, **options):
        directory = options['output_dir'] or get_backup_dir()
        keep = options['keep']

        try:
            path = write_dump_to_file(directory=directory, keep=keep)
        except (OSError, RuntimeError) as error:
            # CommandError = nenulový návratový kód, aby si toho cron všiml.
            # Tiché selhání zálohy je horší než žádná záloha, protože se
            # na ni mezitím spoléhá.
            raise CommandError(f'Zálohu se nepodařilo vytvořit: {error}')

        size_mb = path.stat().st_size / (1024 * 1024)
        self.stdout.write(self.style.SUCCESS(
            f'Záloha vytvořena: {path} ({size_mb:.1f} MB), držíme {keep} dní.'
        ))
