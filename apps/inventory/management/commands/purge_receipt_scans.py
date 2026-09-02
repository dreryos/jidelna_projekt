"""
Úklid naskenovaných dokladů starších než daná lhůta.

Fotky dokladů jsou pracovní materiál. Po potvrzení příjemky se mažou rovnou,
tenhle příkaz uklízí to, co nikdo nedokončil. Pouštět denně z cronu:

    0 3 * * * cd /app && python manage.py purge_receipt_scans
"""
from django.core.management.base import BaseCommand

from apps.inventory.ocr.storage import purge_expired_scans, retention_days


class Command(BaseCommand):
    help = 'Smaže naskenované doklady starší než nastavená lhůta.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--days',
            type=int,
            default=None,
            help=f'Lhůta ve dnech (výchozí {retention_days()} podle nastavení).',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Jen vypíše, co by se smazalo.',
        )

    def handle(self, *args, **options):
        stats = purge_expired_scans(days=options['days'], dry_run=options['dry_run'])

        prefix = 'Ke smazání' if options['dry_run'] else 'Smazáno'
        self.stdout.write(self.style.SUCCESS(
            f'{prefix}: {stats["deleted_files"]} souborů '
            f'z {stats["deleted_days"]} dnů ({stats["bytes"] // 1024} kB). '
            f'Ponecháno {stats["kept_days"]} dnů v lhůtě.'
        ))
