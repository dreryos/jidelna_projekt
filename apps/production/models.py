from django.db import models
from apps.core.models import Recipe, Ingredient
from apps.canteens.models import Canteen

class ProductionOrder(models.Model):
    """Výrobní příkaz"""
    recipe = models.ForeignKey(Recipe, on_delete=models.PROTECT, verbose_name="Recept")
    canteen = models.ForeignKey(Canteen, on_delete=models.PROTECT, verbose_name="Jídelna")
    portions_adult = models.PositiveIntegerField(verbose_name="Počet dospělých porcí")
    portions_child = models.PositiveIntegerField(verbose_name="Počet dětských porcí")
    date = models.DateField(verbose_name="Datum vaření")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Vytvořeno")

    def __str__(self):
        return f"Výroba: {self.recipe.name} pro {self.canteen.name} na den {self.date.strftime('%d.%m.%Y')}"

    class Meta:
        verbose_name = "Výrobní příkaz"
        verbose_name_plural = "Výrobní příkazy"

class PickingList(models.Model):
    """Výdejka surovin"""
    class Status(models.TextChoices):
        PENDING = 'PENDING', 'Čeká na vydání'
        COMPLETED = 'COMPLETED', 'Vydáno'

    production_order = models.ForeignKey(ProductionOrder, on_delete=models.CASCADE, related_name='picking_list_items', verbose_name="Výrobní příkaz")
    ingredient = models.ForeignKey(Ingredient, on_delete=models.PROTECT, verbose_name="Surovina")
    quantity_planned = models.DecimalField(max_digits=10, decimal_places=3, verbose_name="Plánované množství")
    quantity_actual = models.DecimalField(max_digits=10, decimal_places=3, null=True, blank=True, verbose_name="Skutečně vydané množství")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING, verbose_name="Stav")

    def __str__(self):
        return f"Výdejka pro: {self.ingredient.name} ({self.quantity_planned} {self.ingredient.unit})"

    class Meta:
        verbose_name = "Položka výdejky"
        verbose_name_plural = "Položky výdejky"
        unique_together = ('production_order', 'ingredient')
