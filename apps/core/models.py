from django.db import models
from decimal import Decimal
from django.conf import settings
from django.contrib.auth import get_user_model
from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.canteens.models import Canteen

# Create your models here.

"""
Tento modul obsahuje sdílené modely používané napříč projektem:
- Category: kategorie receptů (Příloha I, II, Polévky, Hlavní jídla atd.)
- Ingredient: základní surovina (název + jednotka + konverze)
- Recipe: recept, který může obsahovat více surovin přes RecipeIngredient
- RecipeIngredient: norma (množství suroviny na 1 porci)

Metoda `calculate_portion_price` počítá cenu porce pro zadanou jídelnu na základě
průměrné ceny surovin v jejích skladech.
"""

class Category(models.Model):
    """Kategorie receptů (Příloha I, Polévky, Hlavní jídla atd.)"""
    code = models.CharField(max_length=10, unique=True, verbose_name="Kód kategorie")
    name = models.CharField(max_length=100, verbose_name="Název kategorie")

    def __str__(self):
        return f"{self.code} - {self.name}"

    class Meta:
        verbose_name = "Kategorie receptu"
        verbose_name_plural = "Kategorie receptů"
        ordering = ['code']


class Ingredient(models.Model):
    """Surovina s podporou konverze jednotek"""
    name = models.CharField(max_length=100, unique=True, verbose_name="Název suroviny")
    
    # Původní jednotka (nyní používáno jako base_unit)
    unit = models.CharField(max_length=10, verbose_name="Měrná jednotka") # např. kg, l, ks
    
    # Nová pole pro konverzi jednotek
    base_unit = models.CharField(max_length=10, default='kg', verbose_name="Skladová jednotka", 
                                  help_text="Jednotka používaná na skladě (kg, l, ks)")
    recipe_unit = models.CharField(max_length=10, default='g', verbose_name="Receptová jednotka",
                                    help_text="Jednotka používaná v receptech (g, ml, ks)")
    conversion_factor = models.DecimalField(max_digits=10, decimal_places=3, default=Decimal('1000'), 
                                           verbose_name="Konverzní faktor",
                                           help_text="Koeficient převodu z receptové na skladovou jednotku (např. 1000 pro g→kg)")

    def convert_to_base_unit(self, quantity_in_recipe_unit):
        """
        Převede množství z receptové jednotky na skladovou jednotku.
        Např: 1500g -> 1.5kg (při conversion_factor=1000)
        """
        return quantity_in_recipe_unit / self.conversion_factor

    def convert_to_recipe_unit(self, quantity_in_base_unit):
        """
        Převede množství ze skladové jednotky na receptovou jednotku.
        Např: 1.5kg -> 1500g (při conversion_factor=1000)
        """
        return quantity_in_base_unit * self.conversion_factor

    def __str__(self):
        return f"{self.name} ({self.base_unit})"

    class Meta:
        verbose_name = "Surovina"
        verbose_name_plural = "Suroviny"

class Recipe(models.Model):
    """Recept"""
    # Základní informace
    code = models.CharField(max_length=20, verbose_name="Kód receptu", blank=True, 
                           help_text="Generuje se automaticky podle kategorie (např. 'PL-001', 'HJ-042')")
    name = models.CharField(max_length=200, verbose_name="Název receptu")
    description = models.TextField(verbose_name="Postup přípravy", blank=True)
    
    # Kategorie a počet porcí
    category = models.ForeignKey(Category, on_delete=models.SET_NULL, null=True, blank=False,
                                 verbose_name="Kategorie", related_name='recipes')
    base_portions = models.PositiveIntegerField(default=10, verbose_name="Základní počet porcí",
                                                help_text="Referenční počet porcí pro normu (obvykle 10)")
    
    ingredients = models.ManyToManyField(
        Ingredient,
        through='RecipeIngredient',
        verbose_name="Suroviny"
    )
    
    def save(self, *args, **kwargs):
        """Automatické generování kódu receptu při vytvoření"""
        if not self.code and self.category:
            # Najdeme nejvyšší číslo receptu v této kategorii
            last_recipe = Recipe.objects.filter(
                category=self.category
            ).exclude(
                code=''
            ).order_by('-id').first()
            
            if last_recipe and last_recipe.code:
                # Pokusíme se extrahovat číslo z posledního kódu
                try:
                    last_number = int(last_recipe.code.split('-')[-1])
                    next_number = last_number + 1
                except (ValueError, IndexError):
                    # Pokud se nepodaří extrahovat číslo, začneme od 1
                    next_number = 1
            else:
                # První recept v kategorii
                next_number = 1
            
            # Vygenerujeme nový kód ve formátu "KATEGORIE-XXX"
            self.code = f"{self.category.code}-{next_number:03d}"
        
        super().save(*args, **kwargs)

    def calculate_portion_price(self, canteen, portions=1, portion_coefficient=1.0, price_date=None):
        """
        Vypočítá cenu porce pro danou jídelnu.
        Cena se počítá na základě průměrné ceny surovin ve skladech dané jídelny.
        
        Args:
            canteen: Jídelna
            portions: Počet porcí (výchozí 1)
            portion_coefficient: Koeficient velikosti porce (1.0 = normální, 0.5 = poloviční atd.)
            price_date: Datum pro historické ceny (None = aktuální ceny)
        
        Returns:
            dict: {'total': celková cena, 'per_portion': cena za porci}
        """
        from apps.inventory.models import StockItem, IngredientPriceHistory
        from django.db.models import Avg

        total_price = Decimal('0')

        recipe_ingredients = self.recipeingredient_set.all()

        for item in recipe_ingredients:
            if price_date is not None:
                # Použijeme historické ceny pro každý sklad
                warehouses = canteen.warehouses.all()
                prices = []
                for warehouse in warehouses:
                    price = IngredientPriceHistory.get_price_at_date(
                        item.ingredient, 
                        warehouse, 
                        price_date
                    )
                    if price > 0:
                        prices.append(price)
                
                # Průměr z historických cen
                avg_price = sum(prices) / len(prices) if prices else Decimal('0')
            else:
                # Použijeme aktuální ceny
                avg_price_data = StockItem.objects.filter(
                    ingredient=item.ingredient,
                    warehouse__canteen=canteen
                ).aggregate(avg_price=Avg('price'))
                avg_price = avg_price_data.get('avg_price') or Decimal('0')

            # Vypočítáme množství v základních jednotkách (kg)
            quantity_needed = item.get_quantity_in_base_unit(portions, portion_coefficient)
            
            # Cena = množství × průměrná cena za jednotku
            total_price += quantity_needed * avg_price

        price_per_portion = total_price / Decimal(str(portions)) if portions > 0 else Decimal('0')

        return {
            'total': round(total_price, 2),
            'per_portion': round(price_per_portion, 2)
        }

    def __str__(self):
        if self.code and self.category:
            return f"[{self.category.code}-{self.code}] {self.name}"
        elif self.code:
            return f"[{self.code}] {self.name}"
        return self.name

    class Meta:
        verbose_name = "Recept"
        verbose_name_plural = "Recepty"
        unique_together = [['category', 'code']]  # Kombinace kategorie a kódu musí být jedinečná

class RecipeIngredient(models.Model):
    """Norma pro recept (spojovací tabulka) - množství na 1 porci"""
    recipe = models.ForeignKey(Recipe, on_delete=models.CASCADE, verbose_name="Recept", related_name="recipeingredient_set")
    ingredient = models.ForeignKey(Ingredient, on_delete=models.CASCADE, verbose_name="Surovina")
    
    # Nová struktura - pouze množství na 1 porci v receptových jednotkách (obvykle gramy)
    quantity_per_portion = models.DecimalField(
        max_digits=10, 
        decimal_places=3, 
        verbose_name="Množství na 1 porci",
        help_text="Množství suroviny na 1 porci v receptových jednotkách (např. gramy)"
    )
    
    notes = models.CharField(
        max_length=200, 
        blank=True, 
        verbose_name="Poznámka",
        help_text="Poznámky k surovině (např. 'dle potřeby', 'na osmažení')"
    )

    def get_quantity_in_base_unit(self, portions=1, coefficient=1.0):
        """
        Vypočítá celkové množství v základních jednotkách (kg, l) pro dané množství porcí.
        
        Args:
            portions: Počet porcí
            coefficient: Koeficient velikosti porce (1.0 = normální, 0.5 = poloviční atd.)
        
        Returns:
            Decimal: Množství v základních jednotkách
        """
        # Množství v receptových jednotkách (gramy)
        quantity_recipe_unit = self.quantity_per_portion * Decimal(str(portions)) * Decimal(str(coefficient))
        
        # Převod na základní jednotky (kg)
        quantity_base_unit = self.ingredient.convert_to_base_unit(quantity_recipe_unit)
        
        return quantity_base_unit

    def __str__(self):
        return f"{self.recipe.name} - {self.ingredient.name}: {self.quantity_per_portion}{self.ingredient.recipe_unit}/porci"

    class Meta:
        verbose_name = "Norma receptu"
        verbose_name_plural = "Normy receptů"
        unique_together = ('recipe', 'ingredient')


class UserProfile(models.Model):
    """
    Rozšiřuje výchozí model User o pole specifická pro aplikaci.
    Tento profil propojuje uživatele s jídelnami, které smí spravovat.
    """
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='profile',
        verbose_name="Uživatel"
    )
    canteens = models.ManyToManyField(
        Canteen,
        blank=True,
        verbose_name="Přiřazené jídelny",
        help_text="Jídelny, které může tento uživatel spravovat."
    )

    def __str__(self):
        return f"Profil pro {self.user.username}"

    class Meta:
        verbose_name = "Uživatelský profil"
        verbose_name_plural = "Uživatelské profily"


@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def create_or_update_user_profile(sender, instance, created, **kwargs):
    """
    Signál, který automaticky vytvoří nebo aktualizuje profil uživatele
    při uložení objektu User.
    """
    if created:
        UserProfile.objects.create(user=instance)
    else:
        # Zajistí vytvoření profilu, pokud neexistuje (pro starší uživatele)
        UserProfile.objects.get_or_create(user=instance)
