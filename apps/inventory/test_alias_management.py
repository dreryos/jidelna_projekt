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
        self.assertFalse(SupplierItemAlias.objects.exists())

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
