"""
Management command pro kontrolu ProductionOrder před migrací 0008.
Identifikuje záznamy bez menu_plan a bez canteen_id.
"""

from django.core.management.base import BaseCommand
from django.db.models import Q
from apps.production.models import ProductionOrder


class Command(BaseCommand):
    help = 'Zkontroluje ProductionOrder před migrací na menu-first architekturu'

    def _display_orders_with_canteen(self, orders_with_canteen):
        """Zobrazí souhrn záznamů s canteen_id seskupený podle jídelen"""
        from django.db.models import Count
        
        with_count = orders_with_canteen.count()
        self.stdout.write(self.style.SUCCESS(f'\n✓ {with_count} záznamů s canteen_id - budou automaticky migrovány'))
        
        self.stdout.write('  Rozdělení podle jídelen:')
        for stat in (
            orders_with_canteen
            .values('canteen__name')
            .annotate(count=Count('id'))
            .order_by('canteen__name')
        ):
            self.stdout.write(f'    - {stat["canteen__name"]}: {stat["count"]} příkazů')
    
    def _display_orders_without_canteen(self, orders_without_canteen):
        """Zobrazí záznamy bez canteen_id a návod na jejich opravu"""
        without_count = orders_without_canteen.count()
        self.stdout.write(self.style.ERROR(f'\n✗ {without_count} záznamů BEZ canteen_id - BLOKUJÍ MIGRACI!'))
        self.stdout.write(self.style.ERROR('  Tyto záznamy musí být opraveny před spuštěním migrace 0008:'))
        
        for order in orders_without_canteen:
            self.stdout.write(
                f'    - ID {order.id}: {order.recipe.name if order.recipe else "bez receptu"}, '
                f'datum: {order.date}'
            )
        
        self.stdout.write(self.style.WARNING('\n  Možnosti řešení:'))
        self.stdout.write('  1. Přiřadit správnou jídelnu v Django admin: /admin/production/productionorder/')
        self.stdout.write('  2. Použít Django shell:')
        self.stdout.write('     python manage.py shell')
        self.stdout.write('     >>> from apps.production.models import ProductionOrder')
        self.stdout.write('     >>> order = ProductionOrder.objects.get(id=<ID>)')
        self.stdout.write('     >>> order.canteen = <jídelna>')
        self.stdout.write('     >>> order.save()')
        self.stdout.write('  3. Smazat nevalidní záznamy (pokud jsou zastaralé)')
        
        self.stdout.write(self.style.ERROR('\n⚠️  MIGRACE 0008 SELŽE, dokud nebudou tyto záznamy opraveny!'))

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS('='*80))
        self.stdout.write(self.style.SUCCESS('Kontrola ProductionOrder před migrací 0008'))
        self.stdout.write(self.style.SUCCESS('='*80))
        
        # Najdeme orphan orders a cachujeme count
        orphan_qs = ProductionOrder.objects.filter(menu_plan__isnull=True)
        orphan_count = orphan_qs.count()
        
        if orphan_count == 0:
            self.stdout.write(self.style.SUCCESS('\n✓ Všechny ProductionOrder již mají přiřazený MenuPlan'))
            self.stdout.write(self.style.SUCCESS('  Migrace 0008 není potřeba.'))
            return
        
        self.stdout.write(self.style.WARNING(f'\n⚠️  Nalezeno {orphan_count} ProductionOrder bez MenuPlan'))
        
        # Rozdělíme na ty s/bez canteen
        orders_with_canteen = orphan_qs.filter(canteen__isnull=False)
        orders_without_canteen = orphan_qs.filter(canteen__isnull=True)
        
        with_count = orders_with_canteen.count()
        without_count = orders_without_canteen.count()
        
        if with_count > 0:
            self._display_orders_with_canteen(orders_with_canteen)
        
        if without_count > 0:
            self._display_orders_without_canteen(orders_without_canteen)
        else:
            self.stdout.write(self.style.SUCCESS('\n✓ Všechny orphan záznamy mají canteen_id'))
            self.stdout.write(self.style.SUCCESS('  Migrace 0008 proběhne bez problémů.'))
        
        self.stdout.write(self.style.SUCCESS('\n' + '='*80))

