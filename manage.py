#!/usr/bin/env python
"""Django's command-line utility for administrative tasks.

Tento soubor je vstupním bodem pro příkazy jako `runserver`, `migrate`, `createsuperuser` atd.
Zde se nastaví proměnná prostředí `DJANGO_SETTINGS_MODULE` a předá se řízení Django CLI.
"""
import os
import sys


def main():
    """Spustí administrativní příkazy Django."""
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'spiz_project.settings')
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Are you sure it's installed and "
            "available on your PYTHONPATH environment variable? Did you "
            "forget to activate a virtual environment?"
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == '__main__':
    main()
