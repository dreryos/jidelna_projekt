from django.db import models
from apps.core.models import Ingredient
from apps.canteens.models import Warehouse

class StockItem(models.Model):
    """Skladová položka"""
    ingredient = models.ForeignKey(Ingredient, on_delete=models.CASCADE, verbose_name="Surovina")
    warehouse = models.ForeignKey(Warehouse, on_delete=models.CASCADE, related_name='stock_items', verbose_name="Sklad")
    quantity = models.DecimalField(max_digits=10, decimal_places=3, default=0, verbose_name="Množství na skladě")
    price = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="Nákupní cena za jednotku")

    def __str__(self):
        return f"{self.ingredient.name} v {self.warehouse.name}: {self.quantity} {self.ingredient.unit}"

    class Meta:
        verbose_name = "Skladová položka"
        verbose_name_plural = "Skladové položky"
        unique_together = ('ingredient', 'warehouse')
