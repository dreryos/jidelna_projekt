"""Varování na nezavřené položky výdejek.

Výdejky se vyplňují na papíře a zpětně se přepisují. Když se na to zapomene,
zůstávají položky nezavřené, drží blokaci na skladu a zkreslují objednávkový
report. Tohle varování to má ukázat dřív, než se to nakupí na tisíce položek.
"""
from datetime import date, timedelta
from decimal import Decimal
from itertools import count

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from apps.canteens.models import Canteen, Warehouse
from apps.core.models import Ingredient, UserProfile
from apps.production.models import PickingList, PickingListDocument
from apps.production.utils import STALE_PICKING_DAYS, stale_picking_summary

TODAY = date(2026, 10, 5)


class StalePickingBase(TestCase):
    """Společné příprava dat; vlastní testy nemá."""

    def setUp(self):
        self.creator = User.objects.create_user('creator')
        self.canteen_a = Canteen.objects.create(name='Jídelna A')
        self.canteen_b = Canteen.objects.create(name='Jídelna B')
        self.warehouse = {
            self.canteen_a.pk: Warehouse.objects.create(name='Sklad A', canteen=self.canteen_a),
            self.canteen_b.pk: Warehouse.objects.create(name='Sklad B', canteen=self.canteen_b),
        }
        self._seq = count(1)
        self.superuser = User.objects.create_superuser('admin', password='x')

    def _item(self, canteen, days_old, status=PickingList.Status.PENDING, document=None):
        """Položka v dokumentu, jehož poslední den je `days_old` dní před TODAY.

        Bez `document` vznikne dokument nový; s ním se položka přidá do existujícího.
        """
        n = next(self._seq)
        day = TODAY - timedelta(days=days_old)
        document = document or PickingListDocument.objects.create(
            name=f'Doc {n}', canteen=canteen, date_from=day, date_to=day,
            created_by=self.creator,
        )
        ingredient = Ingredient.objects.create(
            name=f'Surovina {n}', unit='kg', base_unit='kg', recipe_unit='kg',
            conversion_factor=Decimal('1'),
        )
        extra = {'quantity_actual': Decimal('1')} if status == PickingList.Status.COMPLETED else {}
        return PickingList.objects.create(
            document=document, warehouse=self.warehouse[canteen.pk],
            ingredient=ingredient, quantity_planned=Decimal('1'),
            status=status, **extra,
        )

    def _user_of(self, *canteens):
        user = User.objects.create_user(f'u{next(self._seq)}')
        profile, _ = UserProfile.objects.get_or_create(user=user)
        profile.canteens.set(canteens)
        return user



class StalePickingTest(StalePickingBase):
    def test_threshold_is_fourteen_days(self):
        self.assertEqual(STALE_PICKING_DAYS, 14)

    def test_item_older_than_threshold_is_reported(self):
        self._item(self.canteen_a, days_old=15)
        rows = stale_picking_summary(self.superuser, today=TODAY)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['items'], 1)

    def test_item_exactly_at_threshold_is_not_reported(self):
        """Dokument ze dne před 14 dny ještě není "starší než 14 dní"."""
        self._item(self.canteen_a, days_old=14)
        self.assertEqual(stale_picking_summary(self.superuser, today=TODAY), [])

    def test_completed_items_are_ignored(self):
        self._item(self.canteen_a, days_old=60, status=PickingList.Status.COMPLETED)
        self.assertEqual(stale_picking_summary(self.superuser, today=TODAY), [])

    def test_counts_items_documents_and_oldest(self):
        first = self._item(self.canteen_a, days_old=20)
        self._item(self.canteen_a, days_old=20, document=first.document)
        oldest = self._item(self.canteen_a, days_old=40)
        row = stale_picking_summary(self.superuser, today=TODAY)[0]
        self.assertEqual(row['items'], 3)
        self.assertEqual(row['documents'], 2)
        self.assertEqual(row['oldest'], TODAY - timedelta(days=40))
        self.assertEqual(row['oldest_document_id'], oldest.document_id)

    def test_user_sees_only_own_canteens(self):
        self._item(self.canteen_a, days_old=20)
        self._item(self.canteen_b, days_old=20)
        rows = stale_picking_summary(self._user_of(self.canteen_a), today=TODAY)
        self.assertEqual([r['canteen_name'] for r in rows], ['Jídelna A'])

    def test_superuser_sees_all_canteens(self):
        self._item(self.canteen_a, days_old=20)
        self._item(self.canteen_b, days_old=20)
        rows = stale_picking_summary(self.superuser, today=TODAY)
        self.assertEqual({r['canteen_name'] for r in rows}, {'Jídelna A', 'Jídelna B'})

    def test_user_without_profile_sees_nothing(self):
        self._item(self.canteen_a, days_old=20)
        user = User.objects.create_user('bezprofilu')
        UserProfile.objects.filter(user=user).delete()
        self.assertEqual(stale_picking_summary(user, today=TODAY), [])


class HomePageTest(StalePickingBase):
    """Úvodní stránka: varování se ukazuje a čítač přihlášených zmizel."""

    def test_home_shows_warning(self):
        # Na úvodní stránce se datum bere z aktuálního dne, ne z TODAY.
        self._item(self.canteen_a, days_old=(TODAY - date.today()).days + 30)
        self.client.force_login(self.superuser)
        response = self.client.get(reverse('home'))
        self.assertContains(response, 'Nezavřené výdejky')
        self.assertContains(response, 'Jídelna A')

    def test_home_without_stale_items_has_no_warning(self):
        self.client.force_login(self.superuser)
        response = self.client.get(reverse('home'))
        self.assertNotContains(response, 'Nezavřené výdejky')

    def test_home_no_longer_shows_logged_in_users_counter(self):
        self.client.force_login(self.superuser)
        response = self.client.get(reverse('home'))
        self.assertNotContains(response, 'přihlášených uživatelů')
