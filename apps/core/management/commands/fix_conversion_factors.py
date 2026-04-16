"""
Management command pro opravu chybných konverzních faktorů surovin.

Opravuje:
1. Suroviny kde baseUnit == recipeUnit ale conversionFactor != 1
   (např. Cuketa kg→kg s faktorem 1000 místo 1)
2. Olivový olej: ml→l by mělo mít faktor 1000, ne 100
3. Tortilla: ks na skladě = balení (6 ks), potřeba baseUnit="bal", conversionFactor=6
"""

from django.core.management.base import BaseCommand
from decimal import Decimal

from apps.core.models import Ingredient


class Command(BaseCommand):
    help = 'Opraví chybné konverzní faktory surovin importovaných ze zálohy'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Pouze zobrazí změny bez jejich provedení',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        fixed_count = 0

        if dry_run:
            self.stdout.write(self.style.WARNING('=== DRY RUN — žádné změny nebudou provedeny ===\n'))

        # --- 1. Suroviny se stejnou base/recipe jednotkou a špatným faktorem ---
        # Pozor: u hmotnostních (kg) a objemových (l) jednotek to znamená,
        # že recipeUnit by měla být g/ml (ne kg/l), protože recepty používají gramy.
        same_unit_bad_factor = Ingredient.objects.exclude(
            conversion_factor=Decimal('1')
        ).extra(
            where=["base_unit = recipe_unit"]
        )

        if same_unit_bad_factor.exists():
            self.stdout.write(self.style.MIGRATE_HEADING(
                'Suroviny se stejnou skladovou a receptovou jednotkou, ale faktorem != 1:'
            ))
            for ing in same_unit_bad_factor:
                if ing.base_unit == 'kg' and ing.conversion_factor == Decimal('1000'):
                    # kg→kg s faktorem 1000 = ve skutečnosti recepty používají gramy
                    self.stdout.write(
                        f'  {ing.name}: recipeUnit kg→g (recepty používají gramy)'
                    )
                    if not dry_run:
                        ing.recipe_unit = 'g'
                        ing.save(update_fields=['recipe_unit'])
                elif ing.base_unit == 'l' and ing.conversion_factor == Decimal('1000'):
                    # l→l s faktorem 1000 = ve skutečnosti recepty používají ml
                    self.stdout.write(
                        f'  {ing.name}: recipeUnit l→ml (recepty používají mililitry)'
                    )
                    if not dry_run:
                        ing.recipe_unit = 'ml'
                        ing.save(update_fields=['recipe_unit'])
                else:
                    # Kusové nebo jiné: faktor musí být 1
                    self.stdout.write(
                        f'  {ing.name}: {ing.base_unit}→{ing.recipe_unit} '
                        f'faktor {ing.conversion_factor} → 1.000'
                    )
                    if not dry_run:
                        ing.conversion_factor = Decimal('1')
                        ing.save(update_fields=['conversion_factor'])
                fixed_count += 1

        # --- 2. Olivový olej: ml→l faktor 100 → 1000 ---
        try:
            olivovy_olej = Ingredient.objects.get(name='Olivový olej')
            if olivovy_olej.base_unit == 'l' and olivovy_olej.recipe_unit == 'ml' and olivovy_olej.conversion_factor == Decimal('100'):
                self.stdout.write(self.style.MIGRATE_HEADING(
                    '\nOlivový olej: oprava konverzního faktoru ml→l:'
                ))
                self.stdout.write(
                    f'  {olivovy_olej.name}: faktor {olivovy_olej.conversion_factor} → 1000.000'
                )
                if not dry_run:
                    olivovy_olej.conversion_factor = Decimal('1000')
                    olivovy_olej.save(update_fields=['conversion_factor'])
                fixed_count += 1
        except Ingredient.DoesNotExist:
            pass

        # --- 3. Tortilla: ks→ks → bal→ks s faktorem 16 ---
        try:
            tortilla = Ingredient.objects.get(name='Tortilla')
            if tortilla.base_unit == 'ks' and tortilla.recipe_unit == 'ks' and tortilla.conversion_factor == Decimal('1'):
                self.stdout.write(self.style.MIGRATE_HEADING(
                    '\nTortilla: oprava jednotek (balení po 16 kusech):'
                ))
                self.stdout.write(
                    f'  {tortilla.name}: baseUnit ks→bal, conversionFactor 1→16'
                )
                if not dry_run:
                    tortilla.base_unit = 'bal'
                    tortilla.unit = 'bal'
                    tortilla.conversion_factor = Decimal('16')
                    tortilla.save(update_fields=['base_unit', 'unit', 'conversion_factor'])
                fixed_count += 1
        except Ingredient.DoesNotExist:
            pass

        # --- Souhrn ---
        self.stdout.write('')
        if dry_run:
            self.stdout.write(self.style.WARNING(
                f'DRY RUN dokončen: {fixed_count} surovin by bylo opraveno.'
            ))
            self.stdout.write('Spusťte bez --dry-run pro provedení změn.')
        else:
            self.stdout.write(self.style.SUCCESS(
                f'Hotovo: {fixed_count} surovin opraveno.'
            ))
