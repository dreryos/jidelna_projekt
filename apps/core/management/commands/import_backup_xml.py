from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from apps.core.backup import import_backup_xml


class Command(BaseCommand):
    help = 'Importuje zálohu receptů a surovin z XML (merge, doplňuje chybějící hodnoty).'

    def add_arguments(self, parser):
        parser.add_argument('xml_file', type=str, help='Cesta k XML souboru s backupem')
        parser.add_argument('--dry-run', action='store_true', help='Pouze validace bez zápisu změn')
        parser.add_argument('--username', type=str, default=None,
                            help='Uživatelské jméno pro záznamy vyžadující autora (výchozí: první superuser)')

    def handle(self, *args, **options):
        xml_file = options['xml_file']
        dry_run = options['dry_run']
        username = options.get('username')

        User = get_user_model()
        if username:
            try:
                user = User.objects.get(username=username)
            except User.DoesNotExist:
                raise CommandError(f"Uživatel '{username}' neexistuje.")
        else:
            user = User.objects.filter(is_superuser=True).first()
            if user is None:
                raise CommandError('Nebyl nalezen žádný superuser. Zadejte --username.')

        try:
            with open(xml_file, 'rb') as f:
                xml_content = f.read()
        except FileNotFoundError:
            raise CommandError(f'Soubor {xml_file} nebyl nalezen')

        report = import_backup_xml(xml_content, dry_run=dry_run, user=user)

        if dry_run:
            self.stdout.write(self.style.WARNING('Dry-run: změny nebyly uloženy.'))

        for key, value in report.items():
            self.stdout.write(f'{key}: {value}')

        self.stdout.write(self.style.SUCCESS('Import dokončen.'))
