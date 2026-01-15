from django.db import models

"""
Modely pro správu jídelny a jejích skladů.
- Canteen: reprezentuje provozovnu (jídelnu)
- Warehouse: konkrétní sklad patřící k jídelně (např. Hlavní sklad, Mrazák)

Poznámka: zásoby (`StockItem`) budou vázány na `Warehouse`.
"""

# Create your models here.

class Canteen(models.Model):
    """Jídelna"""
    name = models.CharField(max_length=150, unique=True, verbose_name="Název jídelny")
    address = models.CharField(max_length=255, verbose_name="Adresa", blank=True)

    def __str__(self):
        return self.name

    class Meta:
        verbose_name = "Jídelna"
        verbose_name_plural = "Jídelny"

class Warehouse(models.Model):
    """Sklad"""
    name = models.CharField(max_length=100, verbose_name="Název skladu")
    canteen = models.ForeignKey(Canteen, on_delete=models.CASCADE, related_name='warehouses', verbose_name="Jídelna")
    is_locked = models.BooleanField(
        default=False,
        verbose_name="Zamčeno",
        help_text="Sklad je zamčen kvůli probíhající inventuře"
    )
    locked_by_inventory = models.ForeignKey(
        'inventory.InventoryVerification',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='+',
        verbose_name="Zamčeno inventurou"
    )

    def __str__(self):
        return f"{self.name} ({self.canteen.name})"

    class Meta:
        verbose_name = "Sklad"
        verbose_name_plural = "Sklady"
        unique_together = ('name', 'canteen')
