"""
Regresní test seznamu naučených aliasů v Django adminu.

Sloupec „Mapuje se na" vykresluje u odškrtnutých řádků kurzívu přes
`format_html`. Bez formátovacího argumentu vyhazuje `format_html` od
Djanga 5.0 `TypeError`, takže celý changelist spadl na chybu 500, jakmile
v něm byl jediný alias s `is_ignored=True` – a takové vznikají běžně
(doprava, obaly, zaokrouhlení). Admin je přitom jediné místo, kde se dá
špatně naučené mapování opravit, takže pád tuhle cestu úplně zavíral.
"""
import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from apps.core.models import Ingredient
from apps.inventory.models import Supplier, SupplierItemAlias

pytestmark = pytest.mark.django_db

CHANGELIST = reverse('admin:inventory_supplieritemalias_changelist')


@pytest.fixture
def spravce(client):
    user = get_user_model().objects.create_superuser(
        username='admin-alias', email='admin@example.com', password='heslo12345',
    )
    client.force_login(user)
    return user


@pytest.fixture
def dodavatel():
    return Supplier.objects.create(name='Pekárna Ukázka', slug='pekarna-admin-test')


def test_changelist_projde_s_nezboznim_radkem(client, spravce, dodavatel):
    """Alias označený jako nezbožní řádek nesmí shodit seznam."""
    SupplierItemAlias.objects.create(
        supplier=dodavatel, raw_name='Doprava', is_ignored=True,
    )

    response = client.get(CHANGELIST)

    assert response.status_code == 200
    assert 'nezbožní řádek' in response.content.decode()


def test_changelist_projde_s_namapovanou_surovinou(client, spravce, dodavatel):
    """Běžný alias se surovinou se vypíše názvem suroviny."""
    surovina = Ingredient.objects.create(name='Rohlík', unit='ks', base_unit='ks')
    SupplierItemAlias.objects.create(
        supplier=dodavatel, raw_name='ROHLÍK TUKOVÝ 43g', ingredient=surovina,
    )

    response = client.get(CHANGELIST)

    assert response.status_code == 200
    assert 'Rohlík' in response.content.decode()
