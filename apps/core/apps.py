from django.apps import AppConfig


class CoreConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.core'

    def ready(self):
        from django.db.backends.signals import connection_created

        from .collation import register_czech_collation

        connection_created.connect(register_czech_collation)
