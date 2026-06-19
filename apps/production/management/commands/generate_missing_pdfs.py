"""
Management command pro generování chybějících PDF souborů výdejek.
"""

import logging
import time
from datetime import datetime
from django.core.management.base import BaseCommand
from django.db.models import Q
from apps.production.models import PickingListDocument
from apps.production.utils import generate_picking_list_pdf_file

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Vygeneruje PDF soubory pro všechny výdejky, které je nemají'

    def add_arguments(self, parser):
        parser.add_argument(
            '--limit',
            type=int,
            default=None,
            help='Maximální počet dokumentů ke zpracování'
        )
        parser.add_argument(
            '--canteen',
            type=int,
            default=None,
            help='ID jídelny - zpracovat pouze dokumenty této jídelny'
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Pouze vypsat co by se stalo, nic neprovádět'
        )
        parser.add_argument(
            '--include-archived',
            action='store_true',
            help='Zahrnout i archivované výdejky (výchozí: pouze aktivní)'
        )

    def handle(self, *args, **options):
        limit = options['limit']
        canteen_id = options['canteen']
        dry_run = options['dry_run']
        include_archived = options['include_archived']

        # Setup logování do souboru
        log_filename = f'logs/pdf_migration_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log'
        file_handler = logging.FileHandler(log_filename)
        file_handler.setLevel(logging.INFO)
        formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

        self.stdout.write(self.style.SUCCESS('=== Generování chybějících PDF výdejek ===\n'))
        
        # Sestavení querysetu
        queryset = PickingListDocument.objects.filter(
            Q(pdf_file='') | Q(pdf_file__isnull=True)
        )
        
        if not include_archived:
            queryset = queryset.filter(archived=False)
            self.stdout.write('Filtr: pouze ne-archivované výdejky')
        
        if canteen_id:
            queryset = queryset.filter(canteen_id=canteen_id)
            self.stdout.write(f'Filtr: pouze jídelna ID {canteen_id}')
        
        queryset = queryset.select_related('canteen', 'created_by').order_by('created_at')
        
        total_count = queryset.count()
        
        if limit:
            queryset = queryset[:limit]
            self.stdout.write(f'Limit: zpracování maximálně {limit} dokumentů')
        
        to_process = queryset.count()
        
        self.stdout.write(f'\nCelkem výdejek bez PDF: {total_count}')
        self.stdout.write(f'K zpracování: {to_process}\n')
        
        if dry_run:
            self.stdout.write(self.style.WARNING('=== DRY RUN MODE - nic se neprovede ===\n'))
            for doc in queryset:
                self.stdout.write(
                    f'  - ID {doc.id}: {doc.name}, '
                    f'jídelna: {doc.canteen.name}, '
                    f'{doc.date_from} až {doc.date_to}, '
                    f'archivováno: {doc.archived}'
                )
            return
        
        if to_process == 0:
            self.stdout.write(self.style.SUCCESS('Všechny výdejky již mají PDF! ✓'))
            return
        
        # Zpracování
        success_count = 0
        error_count = 0
        skipped_count = 0
        
        self.stdout.write('Zpracování...\n')
        start_time = time.time()
        
        for idx, document in enumerate(queryset, 1):
            doc_info = f'[{idx}/{to_process}] ID {document.id}: {document.name} ({document.canteen.name})'
            
            try:
                self.stdout.write(f'  Generuji: {doc_info}', ending='')
                logger.info(f'Generating PDF for document {document.id}')
                
                doc_start = time.time()
                generate_picking_list_pdf_file(document, base_url='/')
                doc_time = time.time() - doc_start
                
                success_count += 1
                self.stdout.write(self.style.SUCCESS(f' ✓ ({doc_time:.1f}s)'))
                logger.info(f'Successfully generated PDF for document {document.id} in {doc_time:.1f}s')
                
            except Exception as e:
                error_count += 1
                error_msg = str(e)
                self.stdout.write(self.style.ERROR(f' ✗ Chyba: {error_msg}'))
                logger.error(f'Failed to generate PDF for document {document.id}: {error_msg}', exc_info=True)
                
                # Pokračujeme i při chybě
                continue
        
        # Závěrečná statistika
        total_time = time.time() - start_time
        
        self.stdout.write('\n' + '='*60)
        self.stdout.write(self.style.SUCCESS(f'Hotovo za {total_time:.1f}s'))
        self.stdout.write(f'\nStatistika:')
        self.stdout.write(self.style.SUCCESS(f'  ✓ Úspěšně vygenerováno: {success_count}'))
        
        if error_count > 0:
            self.stdout.write(self.style.ERROR(f'  ✗ Selhalo: {error_count}'))
        
        if skipped_count > 0:
            self.stdout.write(self.style.WARNING(f'  ⊘ Přeskočeno: {skipped_count}'))
        
        avg_time = total_time / to_process if to_process > 0 else 0
        self.stdout.write(f'\nPrůměrný čas: {avg_time:.1f}s na dokument')
        
        self.stdout.write(f'\nLog uložen do: {log_filename}')
        
        logger.info(
            f'Migration completed: {success_count} success, {error_count} errors, '
            f'{skipped_count} skipped in {total_time:.1f}s'
        )
