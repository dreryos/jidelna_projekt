"""
Testy analytiky kuchařů.

Bez filtru datumu se dřív počítaly úplně všechny výdejky od začátku
provozu – na produkci to na velkém datasetu spadlo do 520 (worker
nestihl request). Testy hlídají, že se bez zadaného filtru automaticky
omezí na posledních 30 dní, a že ruční filtr pořád funguje jako dřív.
"""
from datetime import date, timedelta

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from apps.canteens.models import Canteen
from apps.production.models import PickingListDocument

pytestmark = pytest.mark.django_db


@pytest.fixture
def uzivatel(client):
    user = get_user_model().objects.create_superuser('vedouci', password='tajne')
    client.force_login(user)
    return user


@pytest.fixture
def jidelna():
    return Canteen.objects.create(name='Jídelna Topinka')


def vytvor_dokument(jidelna, uzivatel, kdy, nazev='Výdejka'):
    return PickingListDocument.objects.create(
        name=nazev, canteen=jidelna, date_from=kdy, date_to=kdy,
        created_by=uzivatel,
    )


def test_bez_filtru_se_omezi_na_poslednich_30_dni(client, uzivatel, jidelna):
    dnes = date.today()
    cerstva = vytvor_dokument(jidelna, uzivatel, dnes - timedelta(days=5), 'Čerstvá')
    stara = vytvor_dokument(jidelna, uzivatel, dnes - timedelta(days=90), 'Stará')

    response = client.get(reverse('analytics:cook_analytics'))

    assert response.status_code == 200
    assert response.context['selected_date_from'] == (dnes - timedelta(days=30)).isoformat()
    assert response.context['selected_date_to'] == dnes.isoformat()

    dokumenty = [
        d['doc'] for _key, data in response.context['cook_stats_list']
        for d in data['documents']
    ]
    assert cerstva in dokumenty
    assert stara not in dokumenty


def test_rucni_filtr_zabere_i_stare_dokumenty(client, uzivatel, jidelna):
    dnes = date.today()
    stara = vytvor_dokument(jidelna, uzivatel, dnes - timedelta(days=90), 'Stará')

    response = client.get(reverse('analytics:cook_analytics'), {
        'date_from': (dnes - timedelta(days=100)).isoformat(),
    })

    assert response.status_code == 200
    # Ruční filtr se nemá přepisovat výchozím oknem.
    assert response.context['selected_date_to'] == ''

    dokumenty = [
        d['doc'] for _key, data in response.context['cook_stats_list']
        for d in data['documents']
    ]
    assert stara in dokumenty
