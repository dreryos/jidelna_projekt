"""Testy servírování nápovědy (MkDocs) za přihlášením."""
import pytest
from django.contrib.auth.models import User
from django.test import Client

from apps.core import views as core_views


@pytest.fixture
def help_site(tmp_path, monkeypatch):
    """Dočasný adresář se sestavenou nápovědou."""
    (tmp_path / 'index.html').write_text('<h1>SPÍŽ – Nápověda</h1>', encoding='utf-8')
    monkeypatch.setattr(core_views, 'HELP_SITE_DIR', tmp_path)
    return tmp_path


@pytest.fixture
def user(db):
    return User.objects.create_user(username='tester', password='heslo12345')


@pytest.mark.django_db
def test_anonymous_redirected_to_login(help_site):
    response = Client().get('/napoveda/index.html')
    assert response.status_code == 302
    assert '/accounts/login/' in response['Location']


@pytest.mark.django_db
def test_logged_in_user_sees_help(help_site, user):
    client = Client()
    client.force_login(user)
    response = client.get('/napoveda/index.html')
    assert response.status_code == 200
    assert 'Nápověda'.encode() in b''.join(response.streaming_content)


@pytest.mark.django_db
def test_help_index_redirects_to_index_html(help_site, user):
    client = Client()
    client.force_login(user)
    response = client.get('/napoveda/')
    assert response.status_code == 302
    assert response['Location'].endswith('/napoveda/index.html')


@pytest.mark.django_db
def test_path_traversal_returns_404(help_site, user):
    client = Client()
    client.force_login(user)
    response = client.get('/napoveda/%2e%2e/spiz_project/settings.py')
    assert response.status_code == 404


@pytest.mark.django_db
def test_missing_page_returns_404(help_site, user):
    client = Client()
    client.force_login(user)
    response = client.get('/napoveda/neexistuje.html')
    assert response.status_code == 404
