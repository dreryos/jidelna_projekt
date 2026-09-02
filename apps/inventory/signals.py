from django.db.models.signals import pre_delete
from django.dispatch import receiver

from .models import InventoryVerification


@receiver(pre_delete, sender=InventoryVerification)
def unlock_warehouse_on_inventory_delete(sender, instance, **kwargs):
    """Odemknout sklad při smazání inventury, aby nezůstal osiřelý zámek."""
    warehouse = instance.warehouse
    if warehouse.locked_by_inventory_id == instance.pk:
        warehouse.is_locked = False
        warehouse.locked_by_inventory = None
        warehouse.save(update_fields=['is_locked', 'locked_by_inventory'])
