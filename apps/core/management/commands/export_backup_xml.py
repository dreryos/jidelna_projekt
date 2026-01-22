from django.core.management.base import BaseCommand
from apps.core.backup import export_backup_xml


class Command(BaseCommand):
    help = 'Exportuje suroviny a recepty do XML zálohy (stdout).' 

    def add_arguments(self, parser):
        parser.add_argument(
            '--output', '-o', type=str, default=None,
            help='Cesta k výstupnímu XML souboru (pokud není zadána, tiskne se na stdout)'
        )

    def handle(self, *args, **options):
        xml_bytes = export_backup_xml()
        output_path = options.get('output')

        if output_path:
            with open(output_path, 'wb') as f:
                f.write(xml_bytes)
            self.stdout.write(self.style.SUCCESS(f'XML záloha uložena do {output_path}'))
        else:
            self.stdout.buffer.write(xml_bytes)
            self.stdout.write('')
