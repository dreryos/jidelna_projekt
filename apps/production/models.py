from django.db import models
from django.core.exceptions import ValidationError
from django.db import transaction

from apps.core.models import Recipe, Ingredient
from apps.canteens.models import Canteen, Warehouse
from apps.inventory.models import StockItem


"""
Tento modul obsahuje logiku pro plánování a provádění výroby:
- MenuPlan: jídelníček pro určité období
- ProductionOrder: reprezentuje plánované vaření (recept + počty porcí + jídelna) - nyní součást jídelníčku
- generate_picking_list: vytvoří položky výdejky podle norem receptu
- PickingList: položka výdejky obsahující plánované a skutečné množství, sklad a stav

Po změně stavu položky na COMPLETED se automaticky odečte `quantity_actual` ze skladu (StockItem).
Pokud položka v daném skladu neexistuje, vytvoří se záznam se záporným množstvím – to slouží jako upozornění na nedostatek.
"""


class MenuPlan(models.Model):
    """Jídelníček pro určité období"""
    name = models.CharField(max_length=200, verbose_name="Název jídelníčku")
    canteen = models.ForeignKey(Canteen, on_delete=models.PROTECT, verbose_name="Jídelna")
    date_from = models.DateField(verbose_name="Datum od")
    date_to = models.DateField(verbose_name="Datum do")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Vytvořeno")
    
    # Výchozí počty porcí pro nová jídla
    default_portions_adult = models.PositiveIntegerField(default=50, verbose_name="Výchozí počet dospělých porcí")
    default_portions_child = models.PositiveIntegerField(default=30, verbose_name="Výchozí počet dětských porcí")

    def __str__(self):
        return f"{self.name} ({self.canteen.name})"
    
    def get_days_count(self):
        """Vrátí počet dní v jídelníčku"""
        return (self.date_to - self.date_from).days + 1
    
    def get_total_orders(self):
        """Vrátí celkový počet jídel v jídelníčku"""
        return self.production_orders.count()

    class Meta:
        verbose_name = "Jídelníček"
        verbose_name_plural = "Jídelníčky"
        ordering = ['-created_at']


class ProductionOrder(models.Model):
    """Výrobní příkaz - nyní součást jídelníčku"""
    menu_plan = models.ForeignKey(MenuPlan, on_delete=models.CASCADE, related_name='production_orders', verbose_name="Jídelníček", null=True, blank=True)
    recipe = models.ForeignKey(Recipe, on_delete=models.PROTECT, verbose_name="Recept")
    canteen = models.ForeignKey(Canteen, on_delete=models.PROTECT, verbose_name="Jídelna")
    portions_adult = models.PositiveIntegerField(verbose_name="Počet dospělých porcí")
    portions_child = models.PositiveIntegerField(verbose_name="Počet dětských porcí")
    date = models.DateField(verbose_name="Datum vaření")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Vytvořeno")

    def save(self, *args, **kwargs):
        is_new = self._state.adding
        super().save(*args, **kwargs)
        if is_new:
            self.generate_picking_list()

    def generate_picking_list(self):
        """
        Vygeneruje položky na výdejce na základě norem receptu.
        Předvyplní sklad, který patří k jídelně a má danou surovinu.
        """
        if not self.recipe:
            return

        recipe_ingredients = self.recipe.recipeingredient_set.all()

        for item in recipe_ingredients:
            quantity_planned = (item.quantity_adult * self.portions_adult) + \
                               (item.quantity_child * self.portions_child)

            # Najdeme sklad, který patří k jídelně a má danou surovinu
            stock_item = StockItem.objects.filter(
                ingredient=item.ingredient,
                warehouse__canteen=self.canteen,
                quantity__gt=0
            ).first()
            
            prefilled_warehouse = stock_item.warehouse if stock_item else None

            PickingList.objects.create(
                production_order=self,
                ingredient=item.ingredient,
                quantity_planned=quantity_planned,
                warehouse=prefilled_warehouse
            )

    def get_required_ingredients(self):
        """Vrátí seznam surovin potřebných pro tento výrobní příkaz"""
        ingredients = []
        if not self.recipe:
            return ingredients
        
        for recipe_ingredient in self.recipe.recipeingredient_set.all():
            adult_amount = recipe_ingredient.quantity_adult * (self.portions_adult or 0)
            child_amount = recipe_ingredient.quantity_child * (self.portions_child or 0)
            total_amount = adult_amount + child_amount
            
            ingredients.append({
                'ingredient': recipe_ingredient.ingredient,
                'amount': total_amount,
                'unit': recipe_ingredient.ingredient.unit
            })
        
        return ingredients

    @property
    def total_portions(self):
        """Celkový počet porcí"""
        return (self.portions_adult or 0) + (self.portions_child or 0)

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
    warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT, verbose_name="Sklad", help_text="Sklad, ze kterého se má surovina vydat.", null=True, blank=False)
    ingredient = models.ForeignKey(Ingredient, on_delete=models.PROTECT, verbose_name="Surovina")
    quantity_planned = models.DecimalField(max_digits=10, decimal_places=3, verbose_name="Plánované množství")
    quantity_actual = models.DecimalField(max_digits=10, decimal_places=3, null=True, blank=True, verbose_name="Skutečně vydané množství")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING, verbose_name="Stav")

    def __str__(self):
        return f"Výdejka pro: {self.ingredient.name} ({self.quantity_planned} {self.ingredient.unit})"

    def clean(self):
        # Kontrola, zda sklad patří ke správné jídelně
        if self.warehouse and self.warehouse.canteen != self.production_order.canteen:
            raise ValidationError(f"Sklad '{self.warehouse}' nepatří k jídelně '{self.production_order.canteen}'.")
        
        # Kontrola, zda je vyplněno skutečné množství při dokončení
        if self.status == self.Status.COMPLETED and self.quantity_actual is None:
            raise ValidationError("Při dokončení výdeje musí být vyplněno skutečné množství.")

    def save(self, *args, **kwargs):
        self.clean() # Spustíme validaci před uložením
        
        # Sledujeme původní stav
        original_state = None
        if self.pk:
            original_state = PickingList.objects.get(pk=self.pk)

        super().save(*args, **kwargs)

        # Logika pro odečtení ze skladu
        # Spustí se pouze pokud je status změněn na COMPLETED
        if self.status == self.Status.COMPLETED and (original_state is None or original_state.status != self.Status.COMPLETED):
            if self.quantity_actual is not None and self.warehouse is not None:
                try:
                    with transaction.atomic():
                        stock_item = StockItem.objects.select_for_update().get(
                            warehouse=self.warehouse,
                            ingredient=self.ingredient
                        )
                        stock_item.quantity -= self.quantity_actual
                        stock_item.save()
                except StockItem.DoesNotExist:
                    # Případ, kdy položka ve skladu neexistuje - můžeme zalogovat chybu
                    # nebo vytvořit položku se záporným stavem
                    StockItem.objects.create(
                        warehouse=self.warehouse,
                        ingredient=self.ingredient,
                        quantity=-self.quantity_actual,
                        price=0 # Nemáme info o ceně, nutno dořešit
                    )

    class Meta:
        verbose_name = "Položka výdejky"
        verbose_name_plural = "Položky výdejky"
        unique_together = ('production_order', 'ingredient')
