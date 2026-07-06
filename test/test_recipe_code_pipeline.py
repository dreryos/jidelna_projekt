"""
Testy cesty RecipeForm -> Recipe.save() -> DB, zaměřené na auto-generování
pole `code` (models.py: Recipe.save).

Skutečný stav:
- unique_together ('category', 'code') — kód je unikátní jen V RÁMCI kategorie
- zbytek aplikace ale hledá GLOBÁLNĚ: Recipe.objects.get(code=...)
  v importu jídelníčků (template_views.py:466, 542, 1121)
  a get_or_create(code=...) v obnově zálohy (backup.py:1941)
- generátor kódu bere poslední záznam podle id (ne max číslo) a na
  neparsovatelném kódu spadne na next_number=1

Důsledky, které testy dokumentují:
1. duplicitní kód napříč kategoriemi projde -> get(code=...) vyhodí
   MultipleObjectsReturned nebo tiše vrátí cizí recept
2. kolize generátoru uvnitř kategorie skončí nechyceným IntegrityError
   (500 pro uživatele) místo validační chyby formuláře

Testy popisují ŽÁDOUCÍ chování — na současném kódu selžou a tím
problémy odhalí.
"""
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.urls import reverse

from apps.core.models import Category, Recipe
from apps.core import views as core_views


@pytest.fixture
def hj(db):
    return Category.objects.create(code='HJ', name='Hlavní jídla')


@pytest.fixture
def pl(db):
    return Category.objects.create(code='PL', name='Přílohy')


@pytest.fixture
def user(db):
    return get_user_model().objects.create_user(username='kuchar', password='x')


def _recipe_form_data(category, name):
    """POST data pro RecipeForm + prázdný inline formset ingrediencí
    (view ho staví z request.POST, management form je povinný)."""
    prefix = core_views.RecipeIngredientFormSet().prefix
    return {
        'category': category.pk,
        'name': name,
        'description': '',
        'selling_vat_rate': '12',
        f'{prefix}-TOTAL_FORMS': '0',
        f'{prefix}-INITIAL_FORMS': '0',
        f'{prefix}-MIN_NUM_FORMS': '0',
        f'{prefix}-MAX_NUM_FORMS': '1000',
    }


# ---------------------------------------------------------------------------
# 1) Kód musí být unikátní globálně, ne jen v rámci kategorie
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_recipe_code_must_be_globally_unique(hj, pl):
    """get(code=...) v importech a záloze hledá globálně — stejný kód
    ve dvou kategoriích rozbije vyhledání (MultipleObjectsReturned)."""
    Recipe.objects.create(name='Rýže', category=pl, code='PL-001')
    with pytest.raises((IntegrityError, ValidationError)):
        Recipe.objects.create(name='Kuře', category=hj, code='PL-001')


# ---------------------------------------------------------------------------
# 2) Kolize generátoru nesmí skončit 500 (nechycený IntegrityError)
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_recipe_create_survives_unparsable_last_code(client, user, hj):
    """Poslední recept v kategorii s neparsovatelným kódem (ruční zásah,
    import) shodí generátor na next_number=1 -> HJ-001 už existuje ->
    unique_together -> IntegrityError propadne až uživateli jako 500."""
    client.force_login(user)

    resp = client.post(reverse('core:recipe_add'), _recipe_form_data(hj, 'Guláš'))
    assert resp.status_code == 302
    assert Recipe.objects.get(name='Guláš').code == 'HJ-001'

    Recipe.objects.create(name='Import', category=hj, code='HJ-ABC')

    # Nesmí vyhodit výjimku; buď uloží s volným kódem, nebo vrátí
    # formulář s validační chybou.
    resp = client.post(reverse('core:recipe_add'), _recipe_form_data(hj, 'Svíčková'))
    assert resp.status_code in (200, 302)
    if resp.status_code == 302:
        codes = list(Recipe.objects.values_list('code', flat=True))
        assert len(codes) == len(set(codes))


# ---------------------------------------------------------------------------
# 3) Změna kategorie při editaci nechá kód se starým prefixem
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_category_change_does_not_leak_duplicate_code(client, user, hj, pl):
    """Recipe.save generuje kód jen při prázdném code. Přesun PL-001 do HJ
    nechá kód PL-001; další nový recept v PL dostane od generátoru zase
    PL-001 (unique_together to dovolí — jiná kategorie) -> globální
    duplicita -> get(code='PL-001') rozbité."""
    client.force_login(user)

    resp = client.post(reverse('core:recipe_add'), _recipe_form_data(pl, 'Rýže'))
    assert resp.status_code == 302
    ryze = Recipe.objects.get(name='Rýže')
    assert ryze.code == 'PL-001'

    # Přesun do HJ přes RecipeUpdateView — kód zůstane PL-001
    resp = client.post(
        reverse('core:recipe_edit', args=[ryze.pk]),
        _recipe_form_data(hj, 'Rýže'),
    )
    assert resp.status_code == 302

    # Nový recept v PL — generátor kategorii PL vidí prázdnou -> PL-001
    resp = client.post(reverse('core:recipe_add'), _recipe_form_data(pl, 'Brambory'))
    assert resp.status_code == 302

    codes = list(Recipe.objects.values_list('code', flat=True))
    assert len(codes) == len(set(codes)), (
        f'Duplicitní kódy receptů: {sorted(codes)} — '
        'get(code=...) v importech vyhodí MultipleObjectsReturned.'
    )
