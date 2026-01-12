"""
ASGI config for spiz_project project.

It exposes the ASGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/6.0/howto/deployment/asgi/
"""

import os

from django.core.asgi import get_asgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'spiz_project.settings')

application = get_asgi_application()

# ASGI (Asynchronous Server Gateway Interface) se používá pro async servery a websockety.
# Tady je místo, kde byste přidali middleware pro websockety nebo long-polling, pokud bude potřeba.
