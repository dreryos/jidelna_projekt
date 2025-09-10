from django.db import models

# Create your models here.

"""
Tento modul obsahuje sdílené modely používané napříč projektem:
- Ingredient: základní surovina (název + jednotka)
- Recipe: recept, který může obsahovat více surovin přes RecipeIngredient
- RecipeIngredient: norma (množství suroviny pro dospělou a dětskou porci)

Metoda `calculate_portion_price` počítá cenu porce pro zadanou jídelnu na základě
průměrné ceny surovin v jejích skladech.
"""

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

    def calculate_portion_price(self, canteen):
        """
        Vypočítá cenu dospělé a dětské porce pro danou jídelnu.
        Cena se počítá na základě průměrné ceny surovin ve skladech dané jídelny.
        """
        from apps.inventory.models import StockItem
        from django.db.models import Avg, F

        total_price_adult = 0
        total_price_child = 0

        recipe_ingredients = self.recipeingredient_set.all()

        for item in recipe_ingredients:
            # Najdeme průměrnou cenu suroviny ve všech skladech dané jídelny
            avg_price_data = StockItem.objects.filter(
                ingredient=item.ingredient,
                warehouse__canteen=canteen
            ).aggregate(avg_price=Avg('price'))

            avg_price = avg_price_data.get('avg_price') or 0

            # Vypočítáme cenu pro danou surovinu v receptu
            total_price_adult += item.quantity_adult * avg_price
            total_price_child += item.quantity_child * avg_price

        return {
            'adult': round(total_price_adult, 2),
            'child': round(total_price_child, 2)
        }

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
