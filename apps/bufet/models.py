from django.db import models
from django.utils import timezone
from apps.canteens.models import Warehouse
from apps.core.models import Ingredient


class BufetImport(models.Model):
    """Import přehledu prodeje z pokladního systému FiskalPRO."""

    class Status(models.TextChoices):
        DRAFT = 'DRAFT', 'Náhled'
        CONFIRMED = 'CONFIRMED', 'Potvrzeno'

    warehouse = models.ForeignKey(
        Warehouse,
        on_delete=models.PROTECT,
        related_name='bufet_imports',
        verbose_name="Sklad",
    )
    filename = models.CharField(max_length=255, verbose_name="Název souboru")
    export_date = models.DateField(
        null=True, blank=True,
        verbose_name="Datum exportu",
        help_text="Datum vygenerování přehledu (z názvu souboru)",
    )
    status = models.CharField(
        max_length=10,
        choices=Status.choices,
        default=Status.DRAFT,
        verbose_name="Stav",
    )
    notes = models.TextField(blank=True, verbose_name="Poznámky")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Vytvořeno")
    created_by = models.ForeignKey(
        'auth.User',
        on_delete=models.PROTECT,
        verbose_name="Vytvořil",
    )
    write_off_id = models.IntegerField(
        null=True, blank=True,
        verbose_name="ID odepsání",
        help_text="ID záznamu StockWriteOff vytvořeného při potvrzení importu",
    )

    class Meta:
        verbose_name = "Import bufetu"
        verbose_name_plural = "Importy bufetu"
        ordering = ['-created_at']

    def __str__(self):
        return f"Bufet import {self.filename} – {self.warehouse}"

    def get_write_off_total_cost(self):
        """Celková nákupní cena odepsaného zboží (z interní DB, ne z exportu)."""
        if not self.write_off_id:
            return None
        from apps.inventory.models import StockWriteOff
        try:
            return StockWriteOff.objects.get(id=self.write_off_id).get_total_cost()
        except StockWriteOff.DoesNotExist:
            return None

    def get_mapped_count(self):
        """Počet položek spárovaných se surovinou."""
        return self.items.filter(ingredient__isnull=False, skip=False).count()

    def get_skipped_count(self):
        return self.items.filter(skip=True).count()


class BufetImportItem(models.Model):
    """Jedna řádka z CSV přehledu prodeje (agregovaná přes provozovny)."""

    bufet_import = models.ForeignKey(
        BufetImport,
        on_delete=models.CASCADE,
        related_name='items',
        verbose_name="Import",
    )
    article_code = models.CharField(max_length=50, verbose_name="Kód artiklíku")
    name = models.CharField(max_length=200, verbose_name="Název")
    quantity = models.DecimalField(
        max_digits=10, decimal_places=3, verbose_name="Prodané množství"
    )
    unit = models.CharField(max_length=20, default='ks', verbose_name="MJ")
    establishments = models.CharField(
        max_length=500, blank=True,
        verbose_name="Provozovny",
        help_text="Provozovny, kde bylo zboží prodáno (oddělené čárkou)",
    )
    ingredient = models.ForeignKey(
        Ingredient,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        verbose_name="Surovina",
        help_text="Spárovaná surovina ve skladu",
    )
    skip = models.BooleanField(
        default=False,
        verbose_name="Přeskočit",
        help_text="Tato položka nebude odepsána ze skladu",
    )

    class Meta:
        verbose_name = "Položka importu bufetu"
        verbose_name_plural = "Položky importu bufetu"
        ordering = ['name']

    def __str__(self):
        return f"{self.name} ({self.quantity} {self.unit})"
