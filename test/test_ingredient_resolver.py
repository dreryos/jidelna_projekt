"""
Testy resolveru, který mapuje dodavatelské názvy na suroviny.

Ověřuje pořadí vrstev (potvrzené mapování má přednost před odhadem),
samoučení při dokončení importu a to, že se resolver nedotazuje databáze
na každý řádek dokladu zvlášť.
"""
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model

from apps.core.models import Ingredient
from apps.inventory.matching import (
    FUZZY_THRESHOLD, IngredientResolver, calculate_similarity,
)
from apps.inventory.models import Supplier, SupplierItemAlias

pytestmark = pytest.mark.django_db


@pytest.fixture
def bolero():
    return Supplier.objects.create(name='BOLERO Fruit', slug='bolero-f', ico='68524358')


@pytest.fixture
def makro():
    return Supplier.objects.create(name='Makro', slug='makro-cz')


@pytest.fixture
def suroviny():
    return {
        'jablko': Ingredient.objects.create(name='Jablko', unit='kg', base_unit='kg'),
        'cibule': Ingredient.objects.create(name='Cibule', unit='kg', base_unit='kg'),
        'rohlik': Ingredient.objects.create(name='Rohlík', unit='ks', base_unit='ks'),
    }


# --- Pořadí vrstev ---

def test_alias_dodavatele_na_presny_nazev(bolero, suroviny):
    SupplierItemAlias.objects.create(
        supplier=bolero, raw_name='Jablko Gala IT', ingredient=suroviny['jablko'],
    )

    match = IngredientResolver(bolero).resolve('Jablko Gala IT')

    assert match.ingredient == suroviny['jablko']
    assert match.source == 'alias'
    assert match.confidence == 100
    assert match.is_automatic is True


def test_alias_zabere_i_na_jinou_zemi_puvodu(bolero, suroviny):
    """Naučeno na IT, na dokladu přijde PL – je to totéž zboží."""
    SupplierItemAlias.objects.create(
        supplier=bolero, raw_name='Jablko Gala IT', ingredient=suroviny['jablko'],
    )

    match = IngredientResolver(bolero).resolve('Jablko Gala PL')

    assert match.ingredient == suroviny['jablko']
    assert match.source == 'alias_core'
    assert match.is_automatic is True


def test_alias_zabere_i_na_jinou_gramaz(bolero, suroviny):
    SupplierItemAlias.objects.create(
        supplier=bolero, raw_name='Cibule cal.70/90 25kg NL', ingredient=suroviny['cibule'],
    )

    match = IngredientResolver(bolero).resolve('Cibule cal 70/90 10kg AT/NL')

    assert match.ingredient == suroviny['cibule']
    assert match.source == 'alias_core'


def test_globalni_alias_plati_pro_vsechny(makro, suroviny):
    SupplierItemAlias.objects.create(raw_name='Jablko Gala', ingredient=suroviny['jablko'])

    match = IngredientResolver(makro).resolve('Jablko Gala')

    assert match.ingredient == suroviny['jablko']
    assert match.source == 'alias_global'
    assert match.is_automatic is True


def test_alias_ciziho_dodavatele_je_jen_navrh(bolero, makro, suroviny):
    """Makro pojmenovává zboží jinak, takže se to musí potvrdit ručně."""
    SupplierItemAlias.objects.create(
        supplier=bolero, raw_name='Jablko Gala IT', ingredient=suroviny['jablko'],
    )

    match = IngredientResolver(makro).resolve('Jablko Gala CZ')

    assert match.ingredient == suroviny['jablko']
    assert match.source == 'alias_other_supplier'
    assert match.is_automatic is False


def test_z_cizich_aliasu_vyhraje_nejpouzivanejsi(bolero, makro, suroviny):
    treti = Supplier.objects.create(name='Zelenina s.r.o.', slug='zelenina-sro')
    SupplierItemAlias.objects.create(
        supplier=bolero, raw_name='Cibule žlutá', ingredient=suroviny['jablko'],
        times_used=1,
    )
    SupplierItemAlias.objects.create(
        supplier=treti, raw_name='Cibule žlutá', ingredient=suroviny['cibule'],
        times_used=40,
    )

    match = IngredientResolver(makro).resolve('Cibule žlutá')

    assert match.ingredient == suroviny['cibule']


def test_alias_ma_prednost_pred_obecnym_pravidlem(bolero, suroviny):
    """
    Dodavatel prodává palety jako zboží. Obecné pravidlo by na „Doprava"
    řeklo nezbožní řádek, ale potvrzené mapování je silnější.
    """
    SupplierItemAlias.objects.create(
        supplier=bolero, raw_name='Doprava zdarma bonus', ingredient=suroviny['jablko'],
    )

    match = IngredientResolver(bolero).resolve('Doprava zdarma bonus')

    assert match.is_ignored is False
    assert match.ingredient == suroviny['jablko']


def test_obecne_pravidlo_chytne_zaokrouhleni(bolero, suroviny):
    match = IngredientResolver(bolero).resolve('Zaokrouhlení')

    assert match.is_ignored is True
    assert match.source == 'rule'
    assert match.ingredient is None


def test_naucený_nezbozni_radek(bolero, suroviny):
    """Obalový materiál, který obecné pravidlo schválně nechytá."""
    SupplierItemAlias.objects.create(
        supplier=bolero, raw_name='Paleta EUR výměnná', is_ignored=True,
    )

    match = IngredientResolver(bolero).resolve('Paleta EUR výměnná')

    assert match.is_ignored is True
    assert match.source == 'alias'
    assert match.ingredient is None


def test_fuzzy_jako_posledni_zachrana(bolero, suroviny):
    match = IngredientResolver(bolero).resolve('Jablko Golden IT')

    assert match.ingredient == suroviny['jablko']
    assert match.source == 'fuzzy'
    assert match.is_automatic is False


def test_nic_nenalezeno(bolero, suroviny):
    match = IngredientResolver(bolero).resolve('Šroubovák křížový PH2')

    assert match.ingredient is None
    assert match.source == 'none'
    assert match.confidence == 0


# --- Samoučení ---

def test_potvrzeni_zalozi_alias(bolero, suroviny):
    resolver = IngredientResolver(bolero)
    user = get_user_model().objects.create_user('skladnik-a')

    alias = resolver.remember('Jablko Gala IT', ingredient=suroviny['jablko'], user=user)

    assert alias.supplier == bolero
    assert alias.raw_key == 'jablko gala it'
    assert alias.times_used == 1
    assert alias.created_by == user


def test_druhy_dodak_uz_sedne_sam(bolero, suroviny):
    """Celý smysl tabulky: co uživatel jednou potvrdil, se příště namapuje samo."""
    IngredientResolver(bolero).remember('Jablko Gala IT', ingredient=suroviny['jablko'])

    match = IngredientResolver(bolero).resolve('Jablko Gala IT')

    assert match.is_automatic is True
    assert match.ingredient == suroviny['jablko']


def test_opakovane_potvrzeni_pricte_pouziti(bolero, suroviny):
    resolver = IngredientResolver(bolero)
    resolver.remember('Jablko Gala IT', ingredient=suroviny['jablko'])
    alias = resolver.remember('Jablko Gala IT', ingredient=suroviny['jablko'])

    alias.refresh_from_db()
    assert alias.times_used == 2
    assert SupplierItemAlias.objects.count() == 1


def test_oprava_mapovani_prepise_alias(bolero, suroviny):
    """Uživatel opravil špatný alias – platí jeho poslední rozhodnutí."""
    resolver = IngredientResolver(bolero)
    resolver.remember('Cibule žlutá', ingredient=suroviny['jablko'])

    resolver.remember('Cibule žlutá', ingredient=suroviny['cibule'])

    assert SupplierItemAlias.objects.count() == 1
    assert IngredientResolver(bolero).resolve('Cibule žlutá').ingredient == suroviny['cibule']


def test_potvrzeni_nezbozniho_radku(bolero, suroviny):
    alias = IngredientResolver(bolero).remember('Paleta EUR', is_ignored=True)

    assert alias.is_ignored is True
    assert alias.ingredient is None


def test_prepocet_jednotky_se_zapamatuje(bolero, suroviny):
    """Pekárna fakturuje kartony po dvanácti, sklad vede kusy."""
    IngredientResolver(bolero).remember(
        'Rohlík tukový karton', ingredient=suroviny['rohlik'],
        unit='bal', unit_factor=Decimal('12'),
    )

    match = IngredientResolver(bolero).resolve('Rohlík tukový karton')

    assert match.unit_factor == Decimal('12')


def test_nic_k_zapamatovani(bolero, suroviny):
    resolver = IngredientResolver(bolero)

    assert resolver.remember('', ingredient=suroviny['jablko']) is None
    assert resolver.remember('Nějaká položka') is None
    assert SupplierItemAlias.objects.count() == 0


# --- Výkon ---

def test_resolver_nechodi_do_databaze_na_kazdy_radek(bolero, suroviny,
                                                     django_assert_num_queries):
    SupplierItemAlias.objects.create(
        supplier=bolero, raw_name='Jablko Gala IT', ingredient=suroviny['jablko'],
    )
    resolver = IngredientResolver(bolero)
    radky = ['Jablko Gala IT', 'Cibule žlutá', 'Zaokrouhlení', 'Rohlík tukový 43g'] * 5

    with django_assert_num_queries(0):
        vysledky = [resolver.resolve(radek) for radek in radky]

    assert len(vysledky) == 20


# --- Skórovací funkce ---

def test_bez_spolecneho_slova_se_skore_zastropuje():
    """Znaková podobnost sama o sobě nesmí stačit na návrh."""
    assert calculate_similarity('jablko gala', 'jahoda mrazena') <= FUZZY_THRESHOLD


def test_shoda_prvniho_slova_pomaha():
    assert calculate_similarity('jablko gala', 'jablko') > FUZZY_THRESHOLD


# --- Rozpoznání dodavatele ---

def test_dodavatel_se_hleda_prednostne_podle_ica(bolero):
    from apps.inventory.matching import find_supplier

    assert find_supplier(name='Úplně jiný název', ico='68524358') == bolero


def test_dodavatel_podle_zkraceneho_nazvu(bolero):
    """Na dokladu je celý obchodní název, v systému zkrácený."""
    from apps.inventory.matching import find_supplier

    assert find_supplier(name='BOLERO Fruit, Aleš Bolek') == bolero


def test_nejednoznacny_nazev_nevraci_nic(bolero):
    from apps.inventory.matching import find_supplier

    Supplier.objects.create(name='BOLERO', slug='bolero-kratke')

    assert find_supplier(name='BOLERO Fruit, Aleš Bolek') is None


def test_bez_dodavatele_se_alias_neuklada(suroviny):
    """Globální alias platí pro všechny, nesmí vzniknout jen tak."""
    resolver = IngredientResolver(supplier=None)

    assert resolver.remember('Jablko Gala IT', ingredient=suroviny['jablko']) is None
    assert SupplierItemAlias.objects.count() == 0


def test_globalni_alias_jen_na_vyzadani(suroviny):
    resolver = IngredientResolver(supplier=None, allow_global_learning=True)

    alias = resolver.remember('Jablko Gala IT', ingredient=suroviny['jablko'])

    assert alias is not None and alias.supplier is None


# --- Jednotky ---

def test_shodna_jednotka_neprepocitava(bolero, suroviny):
    match = IngredientResolver(bolero).resolve('Jablko Gala IT', unit='kg')

    assert match.target_unit == 'kg'
    assert match.unit_factor == Decimal('1')
    assert match.needs_unit_check is False


def test_jednoznacny_prevod_se_udela_sam(bolero):
    """Doklad v kilech, sklad v gramech – poměr je daný."""
    Ingredient.objects.create(name='Mouka', unit='g', base_unit='g')

    match = IngredientResolver(bolero).resolve('Mouka hladká', unit='kg')

    assert match.unit_factor == Decimal('1000')
    assert match.needs_unit_check is False


def test_nejednoznacny_prevod_se_oznaci_k_dotazu(bolero):
    """Kolik váží jeden salát, systém neví, a hádat nesmí."""
    Ingredient.objects.create(name='Salát ledový', unit='kg', base_unit='kg')

    match = IngredientResolver(bolero).resolve('Salát ledový CZ', unit='ks')

    assert match.needs_unit_check is True
    assert match.unit_factor == Decimal('1')


def test_naucený_prevod_prebije_dotaz(bolero, suroviny):
    """Uživatel jednou řekl, že v kartonu je dvanáct kusů."""
    SupplierItemAlias.objects.create(
        supplier=bolero, raw_name='Rohlík karton', ingredient=suroviny['rohlik'],
        unit='bal', unit_factor=Decimal('12'),
    )

    match = IngredientResolver(bolero).resolve('Rohlík karton', unit='bal')

    assert match.unit_factor == Decimal('12')
    assert match.needs_unit_check is False


def test_nezbozni_radek_jednotky_neresi(bolero):
    match = IngredientResolver(bolero).resolve('Zaokrouhlení', unit='ks')

    assert match.needs_unit_check is False


def test_naucený_prevod_neplati_pro_jinou_jednotku(bolero, suroviny):
    """
    Dodavatel přešel z kartonů na kusy. Starý poměr 12 by naskladnil
    dvanáctinásobek.
    """
    SupplierItemAlias.objects.create(
        supplier=bolero, raw_name='Rohlík tukový', ingredient=suroviny['rohlik'],
        unit='bal', unit_factor=Decimal('12'),
    )

    match = IngredientResolver(bolero).resolve('Rohlík tukový', unit='ks')

    assert match.unit_factor == Decimal('1')
    assert match.needs_unit_check is False
