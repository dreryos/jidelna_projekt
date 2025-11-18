from django.db import models
from apps.core.models import Ingredient
from apps.canteens.models import Warehouse

"""
Model pro evidenci zásob v konkrétních skladech.
- StockItem: propojovací entita mezi `Ingredient` a `Warehouse`, obsahuje množství a cenu.

Cenu používáme pro výpočet ceny porcí. Množství se aktualizuje při výdeji z výdejky (PickingList).
"""

class StockItem(models.Model):
    """Skladová položka"""
    ingredient = models.ForeignKey(Ingredient, on_delete=models.CASCADE, verbose_name="Surovina")
    warehouse = models.ForeignKey(Warehouse, on_delete=models.CASCADE, related_name='stock_items', verbose_name="Sklad")
    quantity = models.DecimalField(max_digits=10, decimal_places=3, default=0, verbose_name="Množství na skladě")
    quantity_blocked = models.DecimalField(max_digits=10, decimal_places=3, default=0, verbose_name="Blokované množství")
    price = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="Nákupní cena za jednotku")

    def __str__(self):
        return f"{self.ingredient.name} v {self.warehouse.name}: {self.quantity} {self.ingredient.unit}"
    
    @property
    def quantity_available(self):
        """Vrátí dostupné množství (celkové - blokované)"""
        return self.quantity - self.quantity_blocked
    
    def block_quantity(self, amount):
        """
        Zablokuje zadané množství ze skladu.
        Množství se neodečte ze skladu, pouze se zaznamená jako blokované.
        """
        from decimal import Decimal
        amount = Decimal(str(amount))
        if amount < 0:
            raise ValueError("Nelze blokovat záporné množství")
        self.quantity_blocked += amount
        self.save(update_fields=['quantity_blocked'])
    
    def unblock_quantity(self, amount):
        """
        Uvolní (odblokuje) zadané množství.
        Používá se když je výdejka zrušena nebo změněna.
        """
        from decimal import Decimal
        amount = Decimal(str(amount))
        if amount < 0:
            raise ValueError("Nelze odblokovat záporné množství")
        self.quantity_blocked -= amount
        if self.quantity_blocked < 0:
            self.quantity_blocked = Decimal('0')
        self.save(update_fields=['quantity_blocked'])

    class Meta:
        verbose_name = "Skladová položka"
        verbose_name_plural = "Skladové položky"
        unique_together = ('ingredient', 'warehouse')
