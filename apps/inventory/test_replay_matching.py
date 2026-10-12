"""Zpětné přehrání párování názvů z příjemek (`replay_matching`).

Měří, jak by si resolver vedl na dokladech, které už člověk potvrdil, s aliasy
ve stavu **před** daným dokladem. Kdyby se použily dnešní aliasy, každá položka
by si odpověděla sama, protože alias z ní vznikl.
"""
from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from apps.canteens.models import Canteen, Warehouse
from apps.core.models import Ingredient
from apps.inventory.management.commands.replay_matching import replay_matching
from apps.inventory.matching import IngredientResolver
from apps.inventory.models import (
    GoodsReceipt, GoodsReceiptItem, Supplier, SupplierItemAlias,
)


class ReplayMatchingTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('skladnik')
        canteen = Canteen.objects.create(name='Jídelna')
        self.warehouse = Warehouse.objects.create(name='Sklad', canteen=canteen)
        self.supplier = Supplier.objects.create(name='Dodavatel s.r.o.')
        self.flour = self._ingredient('Hladká mouka')
        self.sugar = self._ingredient('Cukr krupice')
        self.t0 = timezone.now() - timedelta(days=30)

    def _ingredient(self, name):
        return Ingredient.objects.create(
            name=name, unit='kg', base_unit='kg', recipe_unit='kg',
            conversion_factor=Decimal('1'),
        )

    def _receipt(self, days_after_t0):
        receipt = GoodsReceipt.objects.create(
            warehouse=self.warehouse, receipt_number=f'P{days_after_t0}-{GoodsReceipt.objects.count()}',
            receipt_date=date.today(), supplier='Dodavatel s.r.o.',
            supplier_obj=self.supplier, created_by=self.user,
            status=GoodsReceipt.Status.CONFIRMED,
        )
        GoodsReceipt.objects.filter(pk=receipt.pk).update(
            created_at=self.t0 + timedelta(days=days_after_t0)
        )
        return receipt

    def _item(self, receipt, source_name, ingredient):
        return GoodsReceiptItem.objects.create(
            goods_receipt=receipt, ingredient=ingredient, warehouse=self.warehouse,
            quantity=Decimal('1'), price=Decimal('10'), price_without_vat=Decimal('10'),
            vat_rate=Decimal('0'), vat_amount=Decimal('0'),
            source_name=source_name, source_unit='kg',
        )

    def _alias(self, raw_name, ingredient, days_after_t0):
        alias = IngredientResolver(supplier=self.supplier, ingredients=[]).remember(
            raw_name, ingredient=ingredient, unit='kg', user=self.user,
        )
        SupplierItemAlias.objects.filter(pk=alias.pk).update(
            created_at=self.t0 + timedelta(days=days_after_t0)
        )
        return alias

    def _by_source(self, result):
        return {row['source']: row for row in result['by_source']}

    def test_alias_older_than_receipt_is_used(self):
        self._alias('MOUKA HLADKA 1KG', self.flour, days_after_t0=1)
        self._item(self._receipt(5), 'MOUKA HLADKA 1KG', self.flour)

        result = replay_matching()

        row = self._by_source(result)['alias']
        self.assertEqual((row['count'], row['correct']), (1, 1))

    def test_alias_created_after_receipt_is_not_used(self):
        """Alias vzniká až při zpracování dokladu, takže si ho položka nesmí
        "předat sama sobě" - jinak by přesnost vyšla 100 % a nic by neříkala."""
        self._alias('MOUKA HLADKA 1KG', self.flour, days_after_t0=6)
        self._item(self._receipt(5), 'MOUKA HLADKA 1KG', self.flour)

        result = replay_matching()

        self.assertNotIn('alias', self._by_source(result))

    def test_items_without_source_name_are_excluded(self):
        """Ručně zadané příjemky nemají název z dokladu, nemá se z čeho přehrávat."""
        self._item(self._receipt(5), '', self.flour)
        self.assertEqual(replay_matching()['items'], 0)

    def test_correct_fuzzy_suggestion_is_counted_as_correct(self):
        self._item(self._receipt(5), 'Cukr krupice 1kg', self.sugar)

        fuzzy = self._by_source(replay_matching())['fuzzy']

        self.assertEqual((fuzzy['count'], fuzzy['correct']), (1, 1))

    def test_draft_receipts_are_excluded(self):
        receipt = self._receipt(5)
        GoodsReceipt.objects.filter(pk=receipt.pk).update(status=GoodsReceipt.Status.DRAFT)
        self._item(receipt, 'MOUKA HLADKA 1KG', self.flour)

        self.assertEqual(replay_matching()['items'], 0)

    def test_supplier_filter_matches_linked_supplier_name(self):
        receipt = self._receipt(5)
        GoodsReceipt.objects.filter(pk=receipt.pk).update(supplier='')
        self._item(receipt, 'MOUKA HLADKA 1KG', self.flour)

        self.assertEqual(replay_matching(supplier_name='Dodavatel')['items'], 1)
        self.assertEqual(replay_matching(supplier_name='Jiný')['items'], 0)

    def test_wrong_suggestion_is_counted_as_wrong(self):
        """Fuzzy návrh na jinou surovinu, než kterou člověk potvrdil."""
        self._item(self._receipt(5), 'Cukr krupice 1kg', self.flour)   # skutečně mouka

        result = replay_matching()

        fuzzy = self._by_source(result)['fuzzy']
        self.assertEqual((fuzzy['count'], fuzzy['correct']), (1, 0))

    def test_shares_add_up_to_everything(self):
        self._alias('MOUKA HLADKA 1KG', self.flour, days_after_t0=1)
        receipt = self._receipt(5)
        self._item(receipt, 'MOUKA HLADKA 1KG', self.flour)
        self._item(receipt, 'Cukr krupice 1kg', self.sugar)
        self._item(receipt, 'ZZZ nic podobného QQQ', self.sugar)

        result = replay_matching()

        self.assertEqual(result['items'], 3)
        self.assertEqual(sum(r['count'] for r in result['by_source']), 3)

    def test_replay_does_not_change_data(self):
        self._alias('MOUKA HLADKA 1KG', self.flour, days_after_t0=1)
        self._item(self._receipt(5), 'MOUKA HLADKA 1KG', self.flour)
        before = list(SupplierItemAlias.objects.values_list('pk', 'times_used', 'last_used_at'))

        replay_matching()

        self.assertEqual(
            list(SupplierItemAlias.objects.values_list('pk', 'times_used', 'last_used_at')), before
        )
