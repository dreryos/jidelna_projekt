"""
Management command pro kontrolu ProductionOrder před migrací 0008.
Identifikuje záznamy bez menu_plan a bez canteen_id.
"""

from django.core.management.base import BaseCommand
from django.db.models import Q
from apps.production.models import ProductionOrder


class Command(BaseCommand):
    help = 'Zkontroluje ProductionOrder před migrací na menu-first architekturu'

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS('='*80))
        self.stdout.write(self.style.SUCCESS('Kontrola ProductionOrder před migrací 0008'))
        self.stdout.write(self.style.SUCCESS('='*80))
        
        # Najdeme orphan orders
        orphan_orders = ProductionOrder.objects.filter(menu_plan__isnull=True)
        
        if not orphan_orders.exists():
            self.stdout.write(self.style.SUCCESS('\n✓ Všechny ProductionOrder již mají přiřazený MenuPlan'))
            self.stdout.write(self.style.SUCCESS('  Migrace 0008 není potřeba.'))
            return
        
        self.stdout.write(self.style.WARNING(f'\n⚠️  Nalezeno {orphan_orders.count()} ProductionOrder bez MenuPlan'))
        
        # Rozdělíme na ty s/bez canteen
        orders_with_canteen = orphan_orders.filter(canteen__isnull=False)
        orders_without_canteen = orphan_orders.filter(canteen__isnull=True)
        
        if orders_with_canteen.exists():
            self.stdout.write(self.style.SUCCESS(f'\n✓ {orders_with_canteen.count()} záznamů s canteen_id - budou automaticky migrovány'))
            
            # Zobrazíme souhrn podle jídelen
            from collections import defaultdict
            by_canteen = defaultdict(int)
            for order in orders_with_canteen:
                by_canteen[order.canteen.name] += 1
            
            self.stdout.write('  Rozdělení podle jídelen:')
            for canteen_name, count in sorted(by_canteen.items()):
                self.stdout.write(f'    - {canteen_name}: {count} příkazů')
        
        if orders_without_canteen.exists():
            self.stdout.write(self.style.ERROR(f'\n✗ {orders_without_canteen.count()} záznamů BEZ canteen_id - BLOKUJÍ MIGRACI!'))
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
        else:
            self.stdout.write(self.style.SUCCESS('\n✓ Všechny orphan záznamy mají canteen_id'))
            self.stdout.write(self.style.SUCCESS('  Migrace 0008 proběhne bez problémů.'))
        
        self.stdout.write(self.style.SUCCESS('\n' + '='*80))

