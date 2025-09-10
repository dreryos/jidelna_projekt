from django.db import models

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

    def __str__(self):
        return f"{self.name} ({self.canteen.name})"

    class Meta:
        verbose_name = "Sklad"
        verbose_name_plural = "Sklady"
        unique_together = ('name', 'canteen')
