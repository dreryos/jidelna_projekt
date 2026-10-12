"""Zpětné přehrání párování názvů z dokladů nad stavem aliasů před dokladem.

Jen čte, nic nezapisuje. Pro každou potvrzenou příjemku položky s `source_name`
(název tak, jak stál na dokladu dodavatele) spustí `IngredientResolver` s aliasy,
které existovaly **před** vznikem dokladu, a porovná jeho odpověď se surovinou,
kterou člověk skutečně potvrdil. Výsledkem je, kolik řádků by systém poznal sám,
kolik by navrhl a kolik by nechal na člověku, a jak často by se přitom zmýlil.

Proč „před dokladem": alias vzniká až po vytvoření příjemky (`remember()`), takže
dnešní stav aliasů obsahuje u každé položky její vlastní odpověď. S ním by přesnost
vyšla ~100 % a nic by neříkala.

Omezení (data o minulém stavu se neukládají, nejdou dopočítat):
- alias, který člověk později přepsal, nese dnešní surovinu, ne tu původní,
- `times_used` aliasů je dnešní; rozhoduje jen o výběru mezi aliasy cizích
  dodavatelů (vrstva `alias_other_supplier`, která se nepředvyplňuje),
- dodavatel se bere z `supplier_obj` příjemky, jinak z textu přes `find_supplier`;
  jak byl určen při importu, se neukládá.
Přehrání je proto mírně příznivější než skutečnost; pro řádový odhad stačí.
"""
import json
from collections import Counter, defaultdict

from django.core.management.base import BaseCommand
from django.db.models import Q

from apps.inventory.matching import (
    AUTOMATIC_SOURCES, IngredientResolver, find_supplier,
)
from apps.inventory.models import GoodsReceipt, GoodsReceiptItem, SupplierItemAlias
from apps.core.models import Ingredient

FUZZY_BUCKET_WIDTH = 10


class ReplayResolver(IngredientResolver):
    """Resolver nad předaným seznamem aliasů místo celé tabulky."""

    def __init__(self, aliases, **kwargs):
        self._replay_aliases = aliases
        super().__init__(**kwargs)

    def _alias_source(self):
        return self._replay_aliases


def _supplier_for(receipt, cache):
    if receipt.supplier_obj_id:
        return receipt.supplier_obj
    name = receipt.supplier
    if name not in cache:
        cache[name] = find_supplier(name=name)
    return cache[name]


def replay_matching(supplier_name=None):
    """Vrátí slovník s výsledky přehrání (viz `report`)."""
    ingredients = list(Ingredient.objects.filter(is_active=True))
    aliases = list(SupplierItemAlias.objects.select_related('ingredient', 'supplier'))

    items = (
        GoodsReceiptItem.objects
        .exclude(source_name='')
        # Koncept ještě může projít úpravou suroviny; měří se jen potvrzené.
        .filter(goods_receipt__status=GoodsReceipt.Status.CONFIRMED)
        .select_related('goods_receipt', 'goods_receipt__supplier_obj')
        .order_by('goods_receipt__created_at', 'goods_receipt_id', 'pk')
    )
    if supplier_name:
        items = items.filter(
            Q(goods_receipt__supplier__icontains=supplier_name)
            | Q(goods_receipt__supplier_obj__name__icontains=supplier_name)
        )

    by_receipt = defaultdict(list)
    for item in items:
        by_receipt[item.goods_receipt].append(item)

    supplier_cache = {}
    stats = defaultdict(lambda: {'count': 0, 'correct': 0})
    fuzzy_buckets = defaultdict(lambda: {'count': 0, 'correct': 0})
    wrong_automatic = []
    total = 0

    for receipt, receipt_items in by_receipt.items():
        before = [a for a in aliases if a.created_at < receipt.created_at]
        resolver = ReplayResolver(
            before, supplier=_supplier_for(receipt, supplier_cache),
            ingredients=ingredients,
        )
        for item in receipt_items:
            total += 1
            match = resolver.resolve(item.source_name, unit=item.source_unit or None)
            correct = (
                match.ingredient is not None and not match.is_ignored
                and match.ingredient.pk == item.ingredient_id
            )
            stats[match.source]['count'] += 1
            stats[match.source]['correct'] += correct
            if match.source == 'fuzzy':
                lower = match.confidence // FUZZY_BUCKET_WIDTH * FUZZY_BUCKET_WIDTH
                fuzzy_buckets[lower]['count'] += 1
                fuzzy_buckets[lower]['correct'] += correct
            if match.source in AUTOMATIC_SOURCES and not correct:
                wrong_automatic.append({
                    'source_name': item.source_name,
                    'expected': item.ingredient.name,
                    'got': match.ingredient.name if match.ingredient else None,
                    'layer': match.source,
                })

    by_source = [
        {'source': source, **row} for source, row in
        sorted(stats.items(), key=lambda kv: -kv[1]['count'])
    ]
    automatic = sum(r['count'] for r in by_source if r['source'] in AUTOMATIC_SOURCES)
    automatic_ok = sum(r['correct'] for r in by_source if r['source'] in AUTOMATIC_SOURCES)
    return {
        'items': total,
        'receipts': len(by_receipt),
        'unique_names': len({i.source_name for r in by_receipt.values() for i in r}),
        'by_source': by_source,
        'fuzzy_buckets': [
            {'from': low, **row} for low, row in sorted(fuzzy_buckets.items())
        ],
        'automatic': automatic,
        'automatic_correct': automatic_ok,
        'needs_human': total - automatic,
        'wrong_automatic': wrong_automatic,
    }


def _pct(part, whole):
    return f'{100 * part / whole:.0f} %' if whole else '–'


class Command(BaseCommand):
    help = (
        'Zpětně přehraje párování názvů z potvrzených příjemek nad stavem aliasů '
        'před daným dokladem. Jen čte.'
    )

    def add_arguments(self, parser):
        parser.add_argument('--supplier', help='Jen doklady, kde název dodavatele obsahuje tento text')
        parser.add_argument('--json', action='store_true', help='Výstup jako JSON')

    def handle(self, *args, **options):
        result = replay_matching(supplier_name=options['supplier'])
        if options['json']:
            self.stdout.write(json.dumps(result, ensure_ascii=False, indent=2))
            return

        total = result['items']
        self.stdout.write(
            f"Položek: {total} na {result['receipts']} dokladech, "
            f"{result['unique_names']} unikátních názvů\n"
        )
        self.stdout.write(f"{'vrstva':<24}{'počet':>7}{'podíl':>8}{'správně':>10}")
        for row in result['by_source']:
            self.stdout.write(
                f"{row['source']:<24}{row['count']:>7}"
                f"{_pct(row['count'], total):>8}{_pct(row['correct'], row['count']):>10}"
            )
        self.stdout.write(
            f"\nAutomaticky předvyplněno: {result['automatic']} ({_pct(result['automatic'], total)}), "
            f"z toho správně {_pct(result['automatic_correct'], result['automatic'])}"
        )
        self.stdout.write(f"Musí rozhodnout člověk: {result['needs_human']} ({_pct(result['needs_human'], total)})")
        if result['fuzzy_buckets']:
            self.stdout.write('\nFuzzy podle jistoty:')
            for b in result['fuzzy_buckets']:
                self.stdout.write(
                    f"  {b['from']}–{b['from'] + FUZZY_BUCKET_WIDTH - 1} %: {b['count']:>4}, "
                    f"správně {_pct(b['correct'], b['count'])}"
                )
        if result['wrong_automatic']:
            self.stdout.write('\nAutomatické odpovědi, které byly špatně:')
            for w in result['wrong_automatic']:
                self.stdout.write(f"  [{w['layer']}] {w['source_name']} → {w['got']} (mělo být {w['expected']})")
