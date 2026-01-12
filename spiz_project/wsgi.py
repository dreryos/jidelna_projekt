"""
WSGI config for spiz_project project.

It exposes the WSGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/6.0/howto/deployment/wsgi/
"""

import os

from django.core.wsgi import get_wsgi_application

# WSGI (Web Server Gateway Interface) slouží k nasazení aplikace na server (např. gunicorn, uWSGI).
# Tento modul nastaví proměnnou `application`, kterou webserver použije k obsluze požadavků.

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'spiz_project.settings')

application = get_wsgi_application()
