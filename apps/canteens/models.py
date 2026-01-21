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
    
    def get_or_create_transit_warehouse(self):
        """
        Vrátí nebo vytvoří mezisklad pro převody pro tuto jídelnu.
        Každá jídelna má právě jeden transit warehouse.
        """
        transit_warehouse, created = self.warehouses.get_or_create(
            is_transit_warehouse=True,
            defaults={
                'name': f'{self.name} - Převody'
            }
        )
        return transit_warehouse

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
    is_transit_warehouse = models.BooleanField(
        default=False,
        verbose_name="Mezisklad pro převody",
        help_text="Tento sklad slouží jako mezisklad při převodech mezi sklady"
    )

    def __str__(self):
        return f"{self.name} ({self.canteen.name})"

    class Meta:
        verbose_name = "Sklad"
        verbose_name_plural = "Sklady"
        unique_together = ('name', 'canteen')
        constraints = [
            models.UniqueConstraint(
                fields=['canteen'],
                condition=models.Q(is_transit_warehouse=True),
                name='unique_transit_warehouse_per_canteen'
            )
        ]
