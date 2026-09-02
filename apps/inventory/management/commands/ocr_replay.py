"""
Vývojový příkaz: přežvýká uložené OCR anotace bez volání API.

Slouží k ladění normalizace nad reálnými doklady. Fixtura je složka, kterou
vypisuje Mistral – obsahuje `document-annotation.json` a `markdown.md`.

Příklady:
    python manage.py ocr_replay backups/bolero
    python manage.py ocr_replay backups/bolero/1hsItXfw.jpg --json
"""
import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.inventory.ocr.client import OcrError, load_fixture
from apps.inventory.ocr.normalize import to_receipt_data


class Command(BaseCommand):
    help = 'Přehraje uložené OCR anotace a vypíše, co z nich normalizace udělá.'

    def add_arguments(self, parser):
        parser.add_argument(
            'path',
            help='Složka s fixturou, nebo složka obsahující více fixtur.',
        )
        parser.add_argument(
            '--json',
            action='store_true',
            help='Vypíše celý receipt_data jako JSON místo přehledné tabulky.',
        )

    def handle(self, *args, **options):
        root = Path(options['path'])
        if not root.exists():
            raise CommandError(f'Cesta {root} neexistuje.')

        fixtures = self._collect_fixtures(root)
        if not fixtures:
            raise CommandError(f'V {root} nebyla nalezena žádná fixtura.')

        for fixture in fixtures:
            self._replay(fixture, as_json=options['json'])

    def _collect_fixtures(self, root):
        if (root / 'document-annotation.json').exists():
            return [root]
        return sorted(
            path.parent for path in root.glob('*/document-annotation.json')
        )

    def _replay(self, fixture, as_json):
        self.stdout.write(self.style.MIGRATE_HEADING(f'\n=== {fixture.name}'))
        try:
            payload = load_fixture(fixture)
            data = to_receipt_data(payload['annotation'])
        except OcrError as exc:
            self.stdout.write(self.style.ERROR(f'  {exc}'))
            return

        if as_json:
            self.stdout.write(json.dumps(data, ensure_ascii=False, indent=2, default=str))
            return

        self.stdout.write(
            f'  {data["doc_type"]} {data["receipt_number"]} '
            f'/ {data["receipt_date"]} / {data["supplier"]} (IČO {data["supplier_ico"] or "?"})'
        )
        basis = 's DPH' if data['prices_include_vat'] else 'bez DPH'
        self.stdout.write(f'  jednotkové ceny na dokladu: {basis}')

        for item in data['items']:
            flag = f'  [{item["ignore_reason"]}]' if item['is_ignored'] else ''
            self.stdout.write(
                f'    {item["item_name"]:<40.40} '
                f'{item["quantity"]:>10} {item["unit_mapped"]:<4} '
                f'{item["price_per_unit_net"]:>8} bez / {item["price_per_unit_gross"]:>8} s DPH '
                f'({item["vat_rate"]} %){flag}'
            )

        totals = data['totals']
        self.stdout.write(
            f'  doklad celkem: {totals["base"]} + {totals["vat"]} = {totals["total"]}'
        )

        for warning in data['warnings']:
            self.stdout.write(self.style.WARNING(f'  ! {warning}'))
