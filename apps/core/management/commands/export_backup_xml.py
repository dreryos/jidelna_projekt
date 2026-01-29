from django.core.management.base import BaseCommand
from apps.core.backup import (
    export_backup_xml, 
    ALL_ENTITIES, 
    ENTITY_LABELS,
    get_required_entities
)


class Command(BaseCommand):
    help = 'Exportuje vybrané entity do XML zálohy. Bez parametrů exportuje základní entity (suroviny, kategorie, recepty).'

    def add_arguments(self, parser):
        # Přidáme argument pro každou entitu
        for entity in ALL_ENTITIES:
            parser.add_argument(
                f'--{entity.replace("_", "-")}',
                action='store_true',
                dest=f'include_{entity}',
                help=f'Zahrnout: {ENTITY_LABELS.get(entity, entity)}'
            )
        
        parser.add_argument(
            '--all',
            action='store_true',
            dest='include_all',
            help='Exportovat všechny dostupné entity'
        )
        
        parser.add_argument(
            '--output', '-o', type=str, default=None,
            help='Cesta k výstupnímu XML souboru (pokud není zadána, tiskne se na stdout)'
        )
        
        parser.add_argument(
            '--list-entities',
            action='store_true',
            help='Vypsat seznam dostupných entit a skončit'
        )

    def handle(self, *args, **options):
        # Vypsat seznam entit
        if options.get('list_entities'):
            self.stdout.write(self.style.MIGRATE_HEADING('Dostupné entity pro export:'))
            for entity in ALL_ENTITIES:
                label = ENTITY_LABELS.get(entity, entity)
                self.stdout.write(f"  --{entity.replace('_', '-'):25} {label}")
            self.stdout.write('')
            self.stdout.write('Použití:')
            self.stdout.write('  python manage.py export_backup_xml --ingredients --recipes -o backup.xml')
            self.stdout.write('  python manage.py export_backup_xml --all -o full_backup.xml')
            self.stdout.write('')
            return
        
        # Zjistíme které entity byly vybrány
        if options.get('include_all'):
            selected_entities = list(ALL_ENTITIES)
        else:
            selected_entities = []
            for entity in ALL_ENTITIES:
                if options.get(f'include_{entity}'):
                    selected_entities.append(entity)
        
        # Pokud nebyla vybrána žádná entita, použijeme výchozí
        if not selected_entities:
            selected_entities = None  # export_backup_xml použije DEFAULT_ENTITIES
            self.stdout.write(self.style.WARNING('Nebyly vybrány žádné entity, používám výchozí (suroviny, kategorie, recepty).'))
            self.stdout.write('Pro výpis všech entit použijte --list-entities')
        else:
            # Zobrazíme které entity budou exportovány včetně závislostí
            required = get_required_entities(selected_entities)
            self.stdout.write(self.style.MIGRATE_HEADING('Exportované entity:'))
            for entity in sorted(required):
                label = ENTITY_LABELS.get(entity, entity)
                if entity in selected_entities:
                    self.stdout.write(self.style.SUCCESS(f"  ✓ {label}"))
                else:
                    self.stdout.write(self.style.NOTICE(f"  → {label} (závislost)"))
        
        # Provedeme export
        try:
            xml_bytes = export_backup_xml(selected_entities)
        except Exception as e:
            self.stderr.write(self.style.ERROR(f'Chyba při exportu: {e}'))
            raise
        
        output_path = options.get('output')
        
        if output_path:
            with open(output_path, 'wb') as f:
                f.write(xml_bytes)
            self.stdout.write(self.style.SUCCESS(f'\nXML záloha uložena do {output_path}'))
        else:
            self.stdout.buffer.write(xml_bytes)
            self.stdout.write('\n')
