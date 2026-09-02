"""
Testy převodu měrných jednotek mezi dokladem a skladem.

Sklad vede surovinu v jedné jednotce a množství z příjemky se do něj přičítá
přímo. Když se jednotky rozejdou a nikdo to nepřepočte, naskladní se nesmysl.
"""
from decimal import Decimal

import pytest

from apps.inventory.units import (
    conversion_factor, convert_line, units_are_compatible,
)


@pytest.mark.parametrize('zdroj,cil,ocekavano', [
    ('kg', 'g', Decimal('1000')),
    ('g', 'kg', Decimal('0.001')),
    ('kg', 'kg', Decimal('1')),
    ('KG', 'kg', Decimal('1')),
    ('l', 'ml', Decimal('1000')),
    ('dkg', 'g', Decimal('10')),
    ('ks', 'ks', Decimal('1')),
])
def test_jednoznacne_prevody(zdroj, cil, ocekavano):
    assert conversion_factor(zdroj, cil) == ocekavano


@pytest.mark.parametrize('zdroj,cil', [
    # Kolik váží jeden kus ví jen člověk.
    ('ks', 'kg'),
    ('kg', 'ks'),
    ('bal', 'ks'),
    # Bez znalosti hustoty se litry na kila nepřevedou.
    ('l', 'kg'),
    ('kg', 'l'),
    ('', 'kg'),
    ('kg', ''),
])
def test_nejednoznacne_prevody_vraci_none(zdroj, cil):
    """None není chyba – znamená „na tohle se musí zeptat"."""
    assert conversion_factor(zdroj, cil) is None
    assert units_are_compatible(zdroj, cil) is False


def test_prepocet_radku_zachova_celkovou_cenu():
    """Doklad říká 2 kg po 30 Kč. Sklad vede gramy."""
    mnozstvi, cena = convert_line(Decimal('2'), Decimal('30'), Decimal('1000'))

    assert mnozstvi == Decimal('2000')
    assert cena == Decimal('0.0300')
    # Celková cena řádku se převodem změnit nesmí.
    assert mnozstvi * cena == Decimal('2') * Decimal('30')


def test_prepocet_kartonu_na_kusy():
    """Pekárna fakturuje 3 kartony po 120 Kč, v kartonu je 12 rohlíků."""
    mnozstvi, cena = convert_line(Decimal('3'), Decimal('120'), Decimal('12'))

    assert mnozstvi == Decimal('36')
    assert cena == Decimal('10')
    assert mnozstvi * cena == Decimal('360')


def test_prepocet_beze_zmeny():
    assert convert_line(Decimal('6.7'), Decimal('54.9'), Decimal('1')) == (
        Decimal('6.7'), Decimal('54.9000'),
    )


@pytest.mark.parametrize('faktor', [Decimal('0'), Decimal('-1')])
def test_nekladny_prepocet_se_odmitne(faktor):
    with pytest.raises(ValueError, match='kladné'):
        convert_line(Decimal('1'), Decimal('1'), faktor)
