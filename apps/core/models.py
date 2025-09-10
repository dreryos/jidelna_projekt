from django.db import models

# Create your models here.

class Ingredient(models.Model):
    """Surovina"""
    name = models.CharField(max_length=100, unique=True, verbose_name="Název suroviny")
    unit = models.CharField(max_length=10, verbose_name="Měrná jednotka") # např. kg, l, ks

    def __str__(self):
        return f"{self.name} ({self.unit})"

    class Meta:
        verbose_name = "Surovina"
        verbose_name_plural = "Suroviny"

class Recipe(models.Model):
    """Recept"""
    name = models.CharField(max_length=200, unique=True, verbose_name="Název receptu")
    description = models.TextField(verbose_name="Postup přípravy", blank=True)
    ingredients = models.ManyToManyField(
        Ingredient,
        through='RecipeIngredient',
        verbose_name="Suroviny"
    )

    def __str__(self):
        return self.name

    class Meta:
        verbose_name = "Recept"
        verbose_name_plural = "Recepty"

class RecipeIngredient(models.Model):
    """Norma pro recept (spojovací tabulka)"""
    recipe = models.ForeignKey(Recipe, on_delete=models.CASCADE, verbose_name="Recept")
    ingredient = models.ForeignKey(Ingredient, on_delete=models.CASCADE, verbose_name="Surovina")
    quantity_adult = models.DecimalField(max_digits=10, decimal_places=3, verbose_name="Množství pro dospělou porci")
    quantity_child = models.DecimalField(max_digits=10, decimal_places=3, verbose_name="Množství pro dětskou porci")

    def __str__(self):
        return f"{self.recipe.name} - {self.ingredient.name}"

    class Meta:
        verbose_name = "Norma receptu"
        verbose_name_plural = "Normy receptů"
        unique_together = ('recipe', 'ingredient')
