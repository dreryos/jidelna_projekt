"""Správa aliasů dodavatelských názvů: seznam, přidání, úprava, smazání."""
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from apps.core.models import Ingredient, UserProfile
from apps.inventory.models import Supplier, SupplierItemAlias


class AliasManagementTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('kuchar', password='x')
        UserProfile.objects.get_or_create(user=self.user)
        self.client.force_login(self.user)
        self.supplier = Supplier.objects.create(name='Testovací dodavatel A', slug='test-dodavatel-a')
        self.flour = Ingredient.objects.create(name='Hladká mouka', unit='kg', base_unit='kg')
        self.sugar = Ingredient.objects.create(name='Cukr', unit='kg', base_unit='kg')

    def _alias(self, name='MOUKA HLADKA 1KG', ingredient=None, **kw):
        return SupplierItemAlias.objects.create(
            supplier=kw.pop('supplier', self.supplier), raw_name=name,
            ingredient=ingredient or self.flour, **kw,
        )

    def test_list_filters_by_ingredient(self):
        self._alias('MOUKA')
        self._alias('CUKR', ingredient=self.sugar)

        response = self.client.get(reverse('inventory:alias_list'), {'ingredient': self.sugar.pk})

        self.assertContains(response, 'CUKR')
        self.assertNotContains(response, 'MOUKA')

    def test_list_search_matches_code(self):
        self._alias('MOUKA', item_code='731005')
        self._alias('CUKR', ingredient=self.sugar, item_code='999')

        response = self.client.get(reverse('inventory:alias_list'), {'q': '731005'})

        self.assertContains(response, 'MOUKA')
        self.assertNotContains(response, 'CUKR')

    def test_list_filter_without_code(self):
        self._alias('S KODEM', item_code='1')
        self._alias('BEZ KODU')

        response = self.client.get(reverse('inventory:alias_list'), {'bez_kodu': '1'})

        self.assertContains(response, 'BEZ KODU')
        self.assertNotContains(response, 'S KODEM')

    def test_create_sets_keys_and_author(self):
        response = self.client.post(reverse('inventory:alias_add'), {
            'supplier': self.supplier.pk, 'raw_name': 'Mouka hladká 1kg CZ',
            'item_code': ' 731005 ', 'ingredient': self.flour.pk,
            'unit': 'kg', 'unit_factor': '1',
        })

        self.assertEqual(response.status_code, 302)
        alias = SupplierItemAlias.objects.get()
        self.assertEqual(alias.raw_key, 'mouka hladka 1kg cz')
        self.assertEqual(alias.core_key, 'mouka hladka')
        self.assertEqual(alias.item_code, '731005')
        self.assertEqual(alias.created_by, self.user)

    def test_unit_factor_accepts_decimal_comma(self):
        self.client.post(reverse('inventory:alias_add'), {
            'supplier': self.supplier.pk, 'raw_name': 'Karton', 'ingredient': self.flour.pk,
            'unit': 'ks', 'unit_factor': '0,5',
        })

        self.assertEqual(SupplierItemAlias.objects.get().unit_factor, Decimal('0.5'))

    def test_duplicate_name_is_form_error_not_server_error(self):
        self._alias('MOUKA HLADKA 1KG')

        response = self.client.post(reverse('inventory:alias_add'), {
            'supplier': self.supplier.pk, 'raw_name': 'Mouka hladká 1kg',
            'ingredient': self.flour.pk, 'unit_factor': '1',
        })

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'už u tohoto dodavatele existuje')
        self.assertEqual(SupplierItemAlias.objects.count(), 1)

    def test_same_name_for_other_supplier_is_allowed(self):
        other = Supplier.objects.create(name='Testovací dodavatel B', slug='test-dodavatel-b')
        self._alias('MOUKA')

        response = self.client.post(reverse('inventory:alias_add'), {
            'supplier': other.pk, 'raw_name': 'MOUKA', 'ingredient': self.flour.pk,
            'unit_factor': '1',
        })

        self.assertEqual(response.status_code, 302)
        self.assertEqual(SupplierItemAlias.objects.count(), 2)

    def test_alias_needs_ingredient_or_ignored_flag(self):
        response = self.client.post(reverse('inventory:alias_add'), {
            'supplier': self.supplier.pk, 'raw_name': 'NIC', 'unit_factor': '1',
        })

        self.assertEqual(response.status_code, 200)
        self.assertEqual(SupplierItemAlias.objects.count(), 0)

    def test_ignored_alias_with_ingredient_is_rejected(self):
        response = self.client.post(reverse('inventory:alias_add'), {
            'supplier': self.supplier.pk, 'raw_name': 'DOPRAVA',
            'ingredient': self.flour.pk, 'is_ignored': 'on', 'unit_factor': '1',
        })

        self.assertEqual(response.status_code, 200)
        self.assertEqual(SupplierItemAlias.objects.count(), 0)

    def test_edit_corrects_wrong_ingredient(self):
        alias = self._alias('CHLÉB KONZ. BK ROHLIK')

        self.client.post(reverse('inventory:alias_edit', args=[alias.pk]), {
            'supplier': self.supplier.pk, 'raw_name': alias.raw_name,
            'ingredient': self.sugar.pk, 'unit_factor': '1',
        })

        alias.refresh_from_db()
        self.assertEqual(alias.ingredient, self.sugar)

    def test_edit_keeps_alias_with_deactivated_ingredient(self):
        """Deaktivace suroviny nesmí zablokovat úpravu jiných polí aliasu."""
        alias = self._alias('MOUKA', ingredient=self.flour)
        Ingredient.objects.filter(pk=self.flour.pk).update(is_active=False)

        response = self.client.post(reverse('inventory:alias_edit', args=[alias.pk]), {
            'supplier': self.supplier.pk, 'raw_name': 'MOUKA',
            'item_code': '555', 'ingredient': self.flour.pk, 'unit_factor': '1',
        })

        self.assertEqual(response.status_code, 302)
        alias.refresh_from_db()
        self.assertEqual(alias.item_code, '555')

    def test_inactive_ingredient_is_not_offered_for_new_alias(self):
        Ingredient.objects.filter(pk=self.sugar.pk).update(is_active=False)

        response = self.client.get(reverse('inventory:alias_add'))

        self.assertNotContains(response, 'Cukr (kg)')

    def test_edit_does_not_overwrite_usage_counters(self):
        """Import zaznamená použití po načtení formuláře: úprava ho nesmí smazat."""
        from unittest import mock
        from apps.inventory.alias_views import AliasUpdateView
        alias = self._alias('MOUKA', times_used=1)
        original = AliasUpdateView.get_object

        def stale_get_object(view, *args, **kwargs):
            instance = original(view, *args, **kwargs)     # načteno se starým počitadlem
            SupplierItemAlias.objects.filter(pk=instance.pk).update(times_used=9)
            return instance

        with mock.patch.object(AliasUpdateView, 'get_object', stale_get_object):
            response = self.client.post(reverse('inventory:alias_edit', args=[alias.pk]), {
                'supplier': self.supplier.pk, 'raw_name': 'MOUKA',
                'item_code': '1', 'ingredient': self.flour.pk, 'unit_factor': '1',
            })

        self.assertEqual(response.status_code, 302)
        alias.refresh_from_db()
        self.assertEqual(alias.times_used, 9)
        self.assertEqual(alias.item_code, '1')

    def test_edit_recomputes_keys_from_new_name(self):
        alias = self._alias('MOUKA')

        self.client.post(reverse('inventory:alias_edit', args=[alias.pk]), {
            'supplier': self.supplier.pk, 'raw_name': 'Mouka polohrubá 1kg CZ',
            'ingredient': self.flour.pk, 'unit_factor': '1',
        })

        alias.refresh_from_db()
        self.assertEqual(alias.raw_key, 'mouka polohruba 1kg cz')
        self.assertEqual(alias.core_key, 'mouka polohruba')

    def test_concurrent_duplicate_is_field_error_not_server_error(self):
        """Kontrola v clean() proběhne dřív, než souběžný požadavek zapíše."""
        from unittest import mock
        from apps.inventory.forms import SupplierItemAliasForm

        def racing_clean(form):
            # souběžný požadavek zapsal stejný název mezi kontrolou a uložením
            SupplierItemAlias.objects.create(
                supplier=self.supplier, raw_name='MOUKA', ingredient=self.flour,
            )
            return form.cleaned_data

        with mock.patch.object(SupplierItemAliasForm, 'clean', racing_clean):
            response = self.client.post(reverse('inventory:alias_add'), {
                'supplier': self.supplier.pk, 'raw_name': 'MOUKA',
                'ingredient': self.flour.pk, 'unit_factor': '1',
            })

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'mezitím vznikl')
        self.assertEqual(SupplierItemAlias.objects.count(), 1)

    def test_unit_factor_renders_as_text_input(self):
        """Prohlížeč odmítá hodnotu s čárkou v poli type=number."""
        response = self.client.get(reverse('inventory:alias_add'))

        self.assertContains(response, 'name="unit_factor"')
        self.assertContains(response, 'type="text" name="unit_factor"')

    def test_edit_can_keep_own_name(self):
        """Uložení beze změny názvu nesmí hlásit kolizi sám se sebou."""
        alias = self._alias('MOUKA')

        response = self.client.post(reverse('inventory:alias_edit', args=[alias.pk]), {
            'supplier': self.supplier.pk, 'raw_name': 'MOUKA',
            'ingredient': self.flour.pk, 'unit_factor': '1',
        })

        self.assertEqual(response.status_code, 302)

    def test_delete(self):
        alias = self._alias('MOUKA')

        response = self.client.post(reverse('inventory:alias_delete', args=[alias.pk]))

        self.assertEqual(response.status_code, 302)
        self.assertFalse(SupplierItemAlias.objects.filter(pk=alias.pk).exists())

    def test_delete_keeps_other_aliases(self):
        alias = self._alias('MOUKA')
        other = self._alias('CUKR', ingredient=self.sugar)

        self.client.post(reverse('inventory:alias_delete', args=[alias.pk]))

        self.assertTrue(SupplierItemAlias.objects.filter(pk=other.pk).exists())

    def test_readonly_user_cannot_write(self):
        profile = self.user.profile
        profile.is_readonly = True
        profile.save()
        alias = self._alias('MOUKA')

        delete = self.client.post(reverse('inventory:alias_delete', args=[alias.pk]))
        create = self.client.post(reverse('inventory:alias_add'), {
            'raw_name': 'X', 'ingredient': self.flour.pk, 'unit_factor': '1',
        })

        self.assertEqual(delete.status_code, 403)
        self.assertEqual(create.status_code, 403)
        self.assertTrue(SupplierItemAlias.objects.filter(pk=alias.pk).exists())

    def test_anonymous_is_redirected(self):
        self.client.logout()
        response = self.client.get(reverse('inventory:alias_list'))
        self.assertEqual(response.status_code, 302)

    def test_ingredient_list_links_to_aliases_with_count(self):
        self._alias('MOUKA')
        self._alias('MOUKA 2')

        response = self.client.get(reverse('core:ingredient_list'))

        self.assertContains(response, f'?ingredient={self.flour.pk}')


class SynonymTest(TestCase):
    """Synonymum suroviny = globální alias; hledá se i podle podobnosti.

    Příklad záměrně není `džem` → marmeláda: to už pokrývá slovník `SYNONYMS`
    v kódu a test by prošel i bez synonyma.
    """

    def setUp(self):
        self.user = User.objects.create_user('kuchar', password='x')
        UserProfile.objects.get_or_create(user=self.user)
        self.client.force_login(self.user)
        self.jam = Ingredient.objects.create(name='Brambory', unit='kg', base_unit='kg')
        self.honey = Ingredient.objects.create(name='Med', unit='kg', base_unit='kg')
        self.supplier = Supplier.objects.create(name='Testovací dodavatel A', slug='test-dodavatel-a')

    def _resolver(self):
        from apps.inventory.matching import IngredientResolver
        return IngredientResolver(self.supplier, ingredients=[self.jam, self.honey])

    def test_without_synonym_product_is_not_matched(self):
        match = self._resolver().resolve('ZEMÁKY RANÉ PRAKTIK 1*5KG')

        self.assertNotEqual(match.ingredient, self.jam)

    def test_synonym_matches_by_similarity_not_only_exact_name(self):
        SupplierItemAlias.objects.create(
            supplier=None, raw_name='zemáky', ingredient=self.jam,
        )

        match = self._resolver().resolve('ZEMÁKY RANÉ PRAKTIK 1*5KG')

        self.assertEqual(match.ingredient, self.jam)
        self.assertEqual(match.source, 'fuzzy')

    def test_synonym_exact_name_is_automatic(self):
        SupplierItemAlias.objects.create(
            supplier=None, raw_name='zemáky', ingredient=self.jam,
        )

        match = self._resolver().resolve('Zemáky')

        self.assertEqual(match.source, 'alias_global')
        self.assertTrue(match.is_automatic)

    def test_supplier_alias_is_not_used_as_synonym(self):
        """Alias jednoho dodavatele nesmí ovlivnit fuzzy hledání u všech."""
        other = Supplier.objects.create(name='Testovací dodavatel B', slug='test-dodavatel-b')
        SupplierItemAlias.objects.create(supplier=other, raw_name='zemáky', ingredient=self.jam)

        match = self._resolver().resolve('ZEMÁKY RANÉ PRAKTIK 1*5KG')

        self.assertNotEqual(match.source, 'fuzzy')

    def test_ignored_global_alias_is_not_a_synonym(self):
        SupplierItemAlias.objects.create(supplier=None, raw_name='doprava', is_ignored=True)

        match = self._resolver().resolve('DOPRAVA PRAHA')

        self.assertIsNone(match.ingredient)

    def test_form_creates_synonym_without_supplier(self):
        response = self.client.post(reverse('inventory:alias_add'), {
            'supplier': '', 'raw_name': 'zemáky', 'ingredient': self.jam.pk,
            'unit_factor': '1',
        })

        self.assertEqual(response.status_code, 302)
        alias = SupplierItemAlias.objects.get()
        self.assertIsNone(alias.supplier)
        self.assertEqual(alias.ingredient, self.jam)

    def test_synonym_filter_excludes_global_ignored_lines(self):
        """Globální nezbožní řádek není synonymum, resolver ho tak nepoužívá."""
        SupplierItemAlias.objects.create(supplier=None, raw_name='zemáky', ingredient=self.jam)
        SupplierItemAlias.objects.create(supplier=None, raw_name='doprava', is_ignored=True)

        response = self.client.get(reverse('inventory:alias_list'), {'supplier': 'global'})

        self.assertContains(response, 'zemáky')
        self.assertNotContains(response, 'doprava')

    def test_list_marks_synonym(self):
        SupplierItemAlias.objects.create(supplier=None, raw_name='zemáky', ingredient=self.jam)

        response = self.client.get(reverse('inventory:alias_list'), {'supplier': 'global'})

        self.assertContains(response, 'synonymum')

    def test_add_synonym_page_explains_it(self):
        response = self.client.get(
            reverse('inventory:alias_add'), {'synonym': '1', 'ingredient': self.jam.pk},
        )

        self.assertContains(response, 'další jméno suroviny')
