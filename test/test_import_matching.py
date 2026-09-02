"""
Testy napojení resolveru na importy příjemek.

Import z fotky, z CSV i z XML používají stejné pomocné funkce ve
`views.py`, takže se všechny učí do jedné tabulky aliasů.
"""
import pytest
from django.contrib.auth import get_user_model

from apps.core.models import Ingredient
from apps.inventory.models import Supplier, SupplierItemAlias

pytestmark = pytest.mark.django_db


@pytest.fixture
def bolero():
    return Supplier.objects.create(name='BOLERO Fruit', slug='bolero-w', ico='68524358')


@pytest.fixture
def suroviny():
    return {
        'jablko': Ingredient.objects.create(name='Jablko', unit='kg', base_unit='kg'),
        'cibule': Ingredient.objects.create(name='Cibule', unit='kg', base_unit='kg'),
        'rohlik': Ingredient.objects.create(name='Rohlík', unit='ks', base_unit='ks'),
    }


# --- Napojení na import příjemek ---

@pytest.fixture
def doklad():
    """Data dokladu v podobě, jakou do session ukládají všechny tři importy."""
    return {
        'supplier': 'BOLERO Fruit, Aleš Bolek',
        'supplier_ico': '68524358',
        'items': [
            {'item_name': 'Jablko Gala IT', 'unit': 'kg'},
            {'item_name': 'Cibule cal.70/90 25kg NL', 'unit': 'kg'},
            {'item_name': 'Zaokrouhlení', 'unit': 'ks'},
        ],
    }


def test_import_doplni_navrhy_k_polozkam(bolero, suroviny, doklad):
    from apps.inventory.views import _apply_ingredient_matching

    _apply_ingredient_matching(doklad, list(suroviny.values()))

    jablko, cibule, zaokrouhleni = doklad['items']
    assert jablko['suggested_ingredient_name'] == 'Jablko'
    assert cibule['suggested_ingredient_name'] == 'Cibule'
    assert zaokrouhleni['is_ignored'] is True
    # Dodavatele poznáme podle IČO na dokladu.
    assert doklad['supplier_id'] == bolero.id


def test_import_se_nauci_a_podruhe_uz_je_to_jiste(bolero, suroviny, doklad):
    """
    Celý smysl fáze: první doklad je odhad, druhý už stojí na potvrzení.
    """
    from apps.inventory.views import (
        _apply_ingredient_matching, _remember_ingredient_mapping,
    )
    user = get_user_model().objects.create_user('skladnik-b')

    _apply_ingredient_matching(doklad, list(suroviny.values()))
    assert doklad['items'][0]['match_source'] == 'fuzzy'
    assert doklad['items'][0]['is_automatic'] is False

    # Uživatel potvrdil, co mu import navrhl.
    ulozeno = _remember_ingredient_mapping(
        doklad,
        [(doklad['items'][0], suroviny['jablko']),
         (doklad['items'][1], suroviny['cibule'])],
        user,
    )
    assert ulozeno == 2

    dalsi_doklad = {
        'supplier': 'BOLERO Fruit',
        'supplier_ico': '68524358',
        # Jiná země původu i jiná gramáž než minule.
        'items': [
            {'item_name': 'Jablko Gala PL', 'unit': 'kg'},
            {'item_name': 'Cibule cal 70/90 10kg AT/NL', 'unit': 'kg'},
        ],
    }
    _apply_ingredient_matching(dalsi_doklad, list(suroviny.values()))

    for polozka in dalsi_doklad['items']:
        assert polozka['is_automatic'] is True
        assert polozka['match_ratio'] >= 95


def test_import_bez_rozpoznaneho_dodavatele_se_neuci(suroviny, doklad):
    from apps.inventory.views import _remember_ingredient_mapping
    user = get_user_model().objects.create_user('skladnik-c')

    ulozeno = _remember_ingredient_mapping(
        doklad, [(doklad['items'][0], suroviny['jablko'])], user,
    )

    assert ulozeno == 0
    assert SupplierItemAlias.objects.count() == 0


def test_import_bez_ica_pozna_dodavatele_podle_nazvu(bolero, suroviny):
    """Dodací list z CSV ani XML IČO nenese, jen název."""
    from apps.inventory.views import _apply_ingredient_matching

    doklad = {'supplier': 'BOLERO Fruit', 'items': [{'item_name': 'Jablko Gala IT'}]}

    _apply_ingredient_matching(doklad, list(suroviny.values()))

    assert doklad['supplier_id'] == bolero.id
