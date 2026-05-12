"""
Management command pro přepočet blokovaných množství na skladě.

Porovná aktuální hodnotu quantity_blocked u každé skladové položky
s očekávanou hodnotou vypočítanou ze součtu quantity_planned všech
PENDING položek výdejek přiřazených k dokumentu.

Příčina nesouladu: ruční mazání PickingListDocument přes Django admin
před implementací vlastního delete view (které odblokování provádí).

Použití:
    python manage.py recalculate_blocked_quantities
    python manage.py recalculate_blocked_quantities --fix
    python manage.py recalculate_blocked_quantities --canteen "Jídelna ZŠ"
"""

from django.core.management.base import BaseCommand
from django.db.models import Sum, Q
from decimal import Decimal

from apps.inventory.models import StockItem
from apps.production.models import PickingList


class Command(BaseCommand):
    help = 'Přepočítá blokovaná množství na складě podle aktivních výdejek'

    def add_arguments(self, parser):
        parser.add_argument(
            '--fix',
            action='store_true',
            help='Opraví nesouladné hodnoty quantity_blocked (bez tohoto přepínače jen zobrazí)',
        )
        parser.add_argument(
            '--canteen',
            type=str,
            default=None,
            help='Omezí kontrolu na konkrétní jídelnu (název)',
        )

    def handle(self, *args, **options):
        fix = options['fix']
        canteen_name = options.get('canteen')

        if fix:
            self.stdout.write(self.style.WARNING('=== REŽIM OPRAVY — hodnoty budou aktualizovány ===\n'))
        else:
            self.stdout.write(self.style.WARNING('=== DRY RUN — pouze zobrazení nesouladů (použijte --fix pro opravu) ===\n'))

        # Načteme všechny skladové položky
        stock_qs = StockItem.objects.select_related('ingredient', 'warehouse', 'warehouse__canteen')
        if canteen_name:
            stock_qs = stock_qs.filter(warehouse__canteen__name=canteen_name)

        # Vypočítáme očekávané blokované množství z PENDING PickingList položek
        # (pouze ty, které mají přiřazený dokument — bez dokumentu se ještě neblokují)
        expected_blocked = (
            PickingList.objects
            .filter(status=PickingList.Status.PENDING, document__isnull=False)
            .values('warehouse', 'ingredient')
            .annotate(total_planned=Sum('quantity_planned'))
        )
        expected_map = {
            (row['warehouse'], row['ingredient']): row['total_planned']
            for row in expected_blocked
        }

        ok_count = 0
        discrepancy_count = 0
        fixed_count = 0

        self.stdout.write(f"{'Jídelna':<25} {'Sklad':<20} {'Surovina':<30} {'Aktuální':>12} {'Očekávané':>12} {'Rozdíl':>12}")
        self.stdout.write('-' * 115)

        for item in stock_qs.order_by('warehouse__canteen__name', 'warehouse__name', 'ingredient__name'):
            key = (item.warehouse_id, item.ingredient_id)
            expected = expected_map.get(key, Decimal('0'))
            actual = item.quantity_blocked

            # Zaokrouhlíme pro porovnání (< 0.001 = nula)
            diff = actual - expected
            if abs(diff) < Decimal('0.001'):
                ok_count += 1
                continue

            discrepancy_count += 1
            canteen_display = item.warehouse.canteen.name if item.warehouse.canteen else '—'

            self.stdout.write(
                self.style.ERROR(
                    f"{canteen_display:<25} {item.warehouse.name:<20} {item.ingredient.name:<30} "
                    f"{actual:>12.3f} {expected:>12.3f} {diff:>+12.3f}"
                )
            )

            if fix:
                item.quantity_blocked = expected
                if item.quantity_blocked < Decimal('0'):
                    item.quantity_blocked = Decimal('0')
                item.save(update_fields=['quantity_blocked'])
                fixed_count += 1

        self.stdout.write('-' * 115)
        self.stdout.write(f'\nV pořádku:    {ok_count} položek')

        if discrepancy_count == 0:
            self.stdout.write(self.style.SUCCESS('Žádné nesoulady nalezeny — vše v pořádku.'))
        else:
            if fix:
                self.stdout.write(self.style.SUCCESS(
                    f'Opraveno: {fixed_count} položek (quantity_blocked přepočítán)'
                ))
            else:
                self.stdout.write(self.style.WARNING(
                    f'Nalezeno {discrepancy_count} nesouladů. Spusťte s --fix pro opravu.'
                ))
