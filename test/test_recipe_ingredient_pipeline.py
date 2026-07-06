"""
Testy cesty RecipeIngredientForm -> RecipeIngredient: od POST požadavku po commit do DB.

Každý test dokumentuje jednu díru mezi tím, co formulář validuje,
a tím, co model/DB skutečně dovolí. Testy popisují ŽÁDOUCÍ chování,
takže na současném kódu selžou a tím problém odhalí.
"""
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.db import IntegrityError
from django.urls import reverse

from apps.core.models import Category, Ingredient, Recipe, RecipeIngredient
from apps.core.forms import RecipeIngredientForm
from apps.core import views as core_views


@pytest.fixture
def category(db):
    return Category.objects.create(code='HJ', name='Hlavní jídla')


@pytest.fixture
def ingredient(db):
    return Ingredient.objects.create(
        name='Mouka', unit='kg', base_unit='kg', recipe_unit='g',
        conversion_factor=Decimal('1000'),
    )


@pytest.fixture
def user(db):
    return get_user_model().objects.create_user(username='kuchar', password='x')


def _formset_prefix():
    return core_views.RecipeIngredientFormSet().prefix


def _recipe_post_data(category, rows):
    """Sestaví POST data pro RecipeForm + inline formset ingrediencí.

    rows: list dictů {'id': .., 'ingredient': .., 'quantity': .., 'notes': ..}
    """
    prefix = _formset_prefix()
    data = {
        'category': category.pk,
        'name': 'Testovací recept',
        'description': '',
        'selling_vat_rate': '12',
        f'{prefix}-TOTAL_FORMS': str(len(rows)),
        f'{prefix}-INITIAL_FORMS': str(sum(1 for r in rows if r.get('id'))),
        f'{prefix}-MIN_NUM_FORMS': '0',
        f'{prefix}-MAX_NUM_FORMS': '1000',
    }
    for i, row in enumerate(rows):
        data[f'{prefix}-{i}-id'] = str(row.get('id') or '')
        data[f'{prefix}-{i}-ingredient'] = str(row['ingredient'])
        data[f'{prefix}-{i}-quantity_per_portion'] = str(row['quantity'])
        data[f'{prefix}-{i}-notes'] = row.get('notes', '')
    return data


# ---------------------------------------------------------------------------
# 1) Formulář ani model nehlídají kladné množství
# ---------------------------------------------------------------------------

@pytest.mark.django_db
@pytest.mark.parametrize('quantity', ['0', '-5'])
def test_quantity_per_portion_must_be_positive(ingredient, quantity):
    """quantity_per_portion nemá min_value ve formu ani MinValueValidator
    v modelu — nula i záporné množství projde až do DB a následně vyrobí
    záporné/nulové požadavky ve výdejkách."""
    form = RecipeIngredientForm(data={
        'ingredient': ingredient.pk,
        'quantity_per_portion': quantity,
        'notes': '',
    })
    assert not form.is_valid(), (
        f'Formulář přijal množství {quantity} — chybí min_value/MinValueValidator.'
    )


# ---------------------------------------------------------------------------
# 2) Deaktivovaná surovina rozbije editaci existujícího receptu
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_recipe_edit_preserves_row_with_inactive_ingredient(client, user, category, ingredient):
    """Form filtruje ingredient queryset na is_active=True, ale model FK
    žádné takové omezení nemá. Existující řádek s deaktivovanou surovinou
    pak při editaci receptu neprojde validací (a v <select> se vykreslí bez
    vybrané hodnoty — prohlížeč pošle první aktivní surovinu, tichá záměna).
    Beze změny odeslaný formulář musí projít a řádek zachovat."""
    recipe = Recipe.objects.create(name='Testovací recept', category=category)
    row = RecipeIngredient.objects.create(
        recipe=recipe, ingredient=ingredient, quantity_per_portion=Decimal('100'),
    )
    ingredient.is_active = False
    ingredient.save(update_fields=['is_active'])

    client.force_login(user)
    data = _recipe_post_data(category, [
        {'id': row.pk, 'ingredient': ingredient.pk, 'quantity': '100'},
    ])
    response = client.post(reverse('core:recipe_edit', args=[recipe.pk]), data)

    assert response.status_code == 302, (
        'Editace receptu s deaktivovanou surovinou neprošla — '
        'form queryset (is_active=True) je přísnější než model.'
    )
    row.refresh_from_db()
    assert row.ingredient_id == ingredient.pk


# ---------------------------------------------------------------------------
# 3) form_valid není atomické — Recipe se commitne i když ingredience selžou
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_recipe_not_created_when_ingredient_save_fails(client, user, category, ingredient, monkeypatch):
    """RecipeCreateView.form_valid volá form.save() a pak ingredients.save()
    bez transaction.atomic. Když uložení ingrediencí selže (race na
    unique_together, zmanipulovaný management form), v DB zůstane recept
    bez ingrediencí."""
    def boom(self, *args, **kwargs):
        raise IntegrityError('UNIQUE constraint failed: core_recipeingredient')

    monkeypatch.setattr(core_views.RecipeIngredientFormSet, 'save', boom)

    client.force_login(user)
    data = _recipe_post_data(category, [
        {'ingredient': ingredient.pk, 'quantity': '100'},
    ])
    with pytest.raises(IntegrityError):
        client.post(reverse('core:recipe_add'), data)

    assert Recipe.objects.count() == 0, (
        'Recipe se commitl, přestože uložení ingrediencí selhalo — '
        'form_valid potřebuje transaction.atomic.'
    )
