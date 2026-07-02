"""
Signály pro modul production
"""
from django.db.models.signals import pre_save, post_delete
from django.dispatch import receiver
from .models import ProductionOrder, PickingList


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


@receiver(post_delete, sender=PickingList)
def release_blocked_quantity_on_delete(sender, instance, **kwargs):
    """
    Uvolní blokované množství na skladě při smazání PENDING položky výdejky
    přiřazené k dokumentu. Pokrývá i cascade mazání (smazání dokumentu výdejky
    nebo výrobního příkazu, včetně mazání přes Django admin), které dříve
    nechávalo quantity_blocked trvale nafouknuté.
    """
    if instance.status != PickingList.Status.PENDING:
        return
    if not instance.document_id or not instance.warehouse_id:
        return

    from apps.inventory.models import StockItem
    try:
        stock_item = StockItem.objects.get(
            warehouse_id=instance.warehouse_id,
            ingredient_id=instance.ingredient_id,
        )
    except StockItem.DoesNotExist:
        return
    stock_item.unblock_quantity(instance.quantity_planned)
