"""
Regrese: nečíselná hodnota ID filtru v GET (např. ?warehouse=x) dřív vyvolala
ValueError z ORM a stránka končila HTTP 500. Nález lokálního ZAP testu.
Teď se takový filtr ignoruje, jako by nebyl zadán.
"""
import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from apps.core.http import get_int_param

pytestmark = pytest.mark.django_db

URLS = [
    ('core:recipe_list', 'category'),
    ('inventory:goods_receipt_list', 'supplier'),
    ('inventory:goods_receipt_list', 'warehouse'),
    ('inventory:stock_transfer_list', 'warehouse'),
    ('inventory:stock_write_off_list', 'warehouse'),
    ('inventory:stock_list', 'warehouse'),
    ('inventory:inventory_verification_list', 'warehouse'),
    ('production:menu_list', 'canteen'),
    ('analytics:write_off_analytics', 'warehouse'),
]


@pytest.mark.parametrize('name,param', URLS)
@pytest.mark.parametrize('value', ['x', '1x', '', '-1', '²', '9' * 40])
def test_necisly_filtr_nevrati_500(client, name, param, value):
    user = get_user_model().objects.create_superuser('vedouci', password='tajne')
    client.force_login(user)
    response = client.get(reverse(name), {param: value})
    assert response.status_code == 200


def test_get_int_param(rf):
    assert get_int_param(rf.get('/', {'a': '12'}), 'a') == 12
    assert get_int_param(rf.get('/', {'a': 'x'}), 'a') is None
    assert get_int_param(rf.get('/'), 'a') is None
