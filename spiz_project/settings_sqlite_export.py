"""Dočasný settings modul pro export dat z původní SQLite databáze.

Používá se jen jednou, při převodu na PostgreSQL:

    DJANGO_SETTINGS_MODULE=spiz_project.settings_sqlite_export \\
        .venv/bin/python manage.py dumpdata ...

Hlavní `settings.py` už SQLite nezná (a záměrně - viz komentář u `DATABASES`),
takže bez tohohle modulu by nešlo ze staré databáze nic přečíst. Po dokončení
převodu soubor smažte.
"""

from spiz_project.settings import *  # noqa: F401,F403
from spiz_project.settings import BASE_DIR

import os

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': os.environ.get('SQLITE_DB_PATH', str(BASE_DIR / 'db.sqlite3')),
    }
}
