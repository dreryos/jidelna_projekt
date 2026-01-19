"""
Signály pro modul production
"""
from django.db.models.signals import pre_save
from django.dispatch import receiver
from .models import ProductionOrder


@receiver(pre_save, sender=ProductionOrder)
def copy_vat_rate_from_recipe(sender, instance, **kwargs):
    """
    Automaticky zkopíruje selling_vat_rate z Recipe při vytváření nového ProductionOrder.
    Pouze pokud je ProductionOrder nový (nemá pk) a selling_vat_rate má výchozí hodnotu.
    """
    # Kontrola, zda jde o nový záznam
    if instance.pk is None and instance.recipe:
        # Zkopírovat selling_vat_rate z receptu, pokud nebyla explicitně změněna
        # (ponecháváme možnost uživateli nastavit jinou hodnotu při vytváření)
        from decimal import Decimal
        if instance.selling_vat_rate == Decimal('12.00'):  # Výchozí hodnota
            instance.selling_vat_rate = instance.recipe.selling_vat_rate
