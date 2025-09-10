from django.db import models
from django.core.exceptions import ValidationError

class Surovina(models.Model):
    """
    Model reprezentující jednu položku (surovinu) na skladě.
    """
    # Definice pro výběr jednotek, abychom předešli překlepům
    class Jednotky(models.TextChoices):
        KILOGRAM = 'kg', 'Kilogram'
        LITER = 'l', 'Litr'
        KUS = 'ks', 'Kus'
        GRAM = 'g', 'Gram'

    nazev = models.CharField(max_length=100, unique=True, verbose_name="Název suroviny")
    aktualni_mnozstvi = models.DecimalField(
        max_digits=10, decimal_places=3, default=0.0, verbose_name="Aktuální množství"
    )
    jednotka = models.CharField(
        max_length=2, choices=Jednotky.choices, default=Jednotky.KILOGRAM, verbose_name="Jednotka"
    )
    prumerna_nakupni_cena = models.DecimalField(
        max_digits=10, decimal_places=2, default=0.0, verbose_name="Průměrná nákupní cena (za jednotku)"
    )
    # Automaticky zaznamená, kdy byla položka naposledy aktualizována
    posledni_aktualizace = models.DateTimeField(auto_now=True)

    def __str__(self):
        """Textová reprezentace objektu v adminu a jinde."""
        return f"{self.nazev} ({self.aktualni_mnozstvi} {self.jednotka})"

    def clean(self):
        """Zajišťuje, že množství na skladě neklesne pod nulu."""
        if self.aktualni_mnozstvi < 0:
            raise ValidationError('Množství na skladě nemůže být záporné.')

    class Meta:
        verbose_name = "Surovina"
        verbose_name_plural = "Suroviny na skladě"
        ordering = ['nazev'] # Seřadí suroviny podle názvu