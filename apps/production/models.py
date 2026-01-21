from django.db import models
from django.core.exceptions import ValidationError
from django.db import transaction
from decimal import Decimal
import xml.etree.ElementTree as ET
import uuid

from apps.core.models import Recipe, Ingredient
from apps.core.constants import VAT_RATE_CHOICES
from apps.canteens.models import Canteen, Warehouse
from apps.inventory.models import StockItem
from .xml_parser import parse_menu_template_xml, MEAL_TYPE_MAPPING


"""
Tento modul obsahuje logiku pro plánování a provádění výroby:
- MenuPlan: jídelníček pro určité období
- MenuTemplate: XML šablona pro import jídelníčků
- ProductionOrder: reprezentuje plánované vaření (recept + počty porcí + jídelna) - nyní součást jídelníčku
- generate_picking_list: vytvoří položky výdejky podle norem receptu
- PickingList: položka výdejky obsahující plánované a skutečné množství, sklad a stav

Po změně stavu položky na COMPLETED se automaticky odečte `quantity_actual` ze skladu (StockItem).
Pokud položka v daném skladu neexistuje, vytvoří se záznam se záporným množstvím – to slouží jako upozornění na nedostatek.
"""


class MenuTemplate(models.Model):
    """XML šablona pro import jídelníčků"""
    name = models.CharField(max_length=200, verbose_name="Název šablony")
    description = models.TextField(blank=True, verbose_name="Popis", help_text="Stručný popis šablony a co obsahuje")
    xml_content = models.TextField(verbose_name="XML obsah", help_text="XML definice receptů a harmonogramu")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Vytvořeno")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Aktualizováno")

    def __str__(self):
        return self.name

    def parse_schedule_to_dict(self):
        """
        Parsuje XML harmonogram do struktury vhodné pro vizuální editor.
        
        Returns:
            dict: {
                day_index: [
                    {
                        'recipe_code': str,
                        'meal_type': str,
                        'note': str,
                        'unique_id': str,  # pro drag-drop tracking
                        'portion_count': int|None
                    },
                    ...
                ]
            }
        """
        if not self.xml_content:
            return {}
        
        try:
            parsed = parse_menu_template_xml(self.xml_content)
            schedule_dict = {}
            
            for day in parsed.get('schedule', []):
                day_index = day.get('date_offset', 0)
                meals = []
                
                for meal in day.get('meals', []):
                    meals.append({
                        'recipe_code': meal['recipe_code'],
                        'meal_type': meal['meal_type'],
                        'note': meal.get('note', ''),
                        'unique_id': str(uuid.uuid4()),
                        'portion_count': meal.get('portion_count')
                    })
                
                schedule_dict[day_index] = meals
            
            return schedule_dict
        except ValidationError:
            return {}
    
    def update_schedule_from_dict(self, schedule_dict):
        """
        Aktualizuje XML harmonogram ze slovníku z vizuálního editoru.
        
        Args:
            schedule_dict: dict ve formátu z parse_schedule_to_dict()
        
        Raises:
            ValidationError: pokud se nepodaří sestavit validní XML
        """
        if not self.xml_content:
            raise ValidationError("Šablona nemá XML obsah")
        
        try:
            root = ET.fromstring(self.xml_content)
        except ET.ParseError as e:
            raise ValidationError(f"Chyba při parsování XML: {str(e)}")
        
        # Najdeme nebo vytvoříme MenuSchedule sekci
        schedule_section = root.find('MenuSchedule')
        if schedule_section is None:
            schedule_section = ET.SubElement(root, 'MenuSchedule')
        
        # Odstraníme všechny existující dny
        for day_elem in list(schedule_section.findall('Day')):
            schedule_section.remove(day_elem)
        
        # Reverse mapping pro meal types
        meal_type_reverse = {v: k for k, v in MEAL_TYPE_MAPPING.items()}
        
        # Přidáme nové dny podle slovníku
        for day_index in sorted(schedule_dict.keys()):
            meals = schedule_dict[day_index]
            
            day_elem = ET.SubElement(schedule_section, 'Day')
            day_elem.set('name', f'Den {day_index + 1}')
            day_elem.set('dateOffset', str(day_index))
            
            for meal in meals:
                meal_elem = ET.SubElement(day_elem, 'Meal')
                meal_elem.set('recipeCode', meal['recipe_code'])
                meal_elem.set('type', meal_type_reverse.get(meal['meal_type'], 'obed'))
                
                if meal.get('note'):
                    meal_elem.set('note', meal['note'])
                if meal.get('portion_count') is not None:
                    meal_elem.set('portionCount', str(meal['portion_count']))
        
        # Převedeme zpět na string s pretty printing
        ET.indent(root, space='  ')
        self.xml_content = ET.tostring(root, encoding='unicode', xml_declaration=True)
        
        # Validujeme nové XML
        parse_menu_template_xml(self.xml_content)
    
    def get_stats(self):
        """
        Vrací statistiky šablony pro live preview.
        
        Returns:
            dict: {
                'days': int,
                'meals': int,
                'unique_recipes': int
            }
        """
        if not self.xml_content:
            return {'days': 0, 'meals': 0, 'unique_recipes': 0}
        
        try:
            parsed = parse_menu_template_xml(self.xml_content)
            schedule = parsed.get('schedule', [])
            
            total_meals = 0
            unique_recipes = set()
            
            for day in schedule:
                for meal in day.get('meals', []):
                    total_meals += 1
                    unique_recipes.add(meal['recipe_code'])
            
            return {
                'days': len(schedule),
                'meals': total_meals,
                'unique_recipes': len(unique_recipes)
            }
        except ValidationError:
            return {'days': 0, 'meals': 0, 'unique_recipes': 0}

    class Meta:
        verbose_name = "Šablona jídelníčku"
        verbose_name_plural = "Šablony jídelníčků"
        ordering = ['-created_at']


class MenuPlan(models.Model):
    """Jídelníček pro určité období"""
    name = models.CharField(max_length=200, verbose_name="Název jídelníčku")
    canteen = models.ForeignKey(Canteen, on_delete=models.PROTECT, verbose_name="Jídelna")
    date_from = models.DateField(verbose_name="Datum od")
    date_to = models.DateField(verbose_name="Datum do")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Vytvořeno")
    
    # Zachováno pro zpětnou kompatibilitu
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
    
    def get_default_coefficients(self):
        """Vrátí seznam výchozích koeficientů seřazených podle pořadí"""
        return self.default_coefficients.order_by('order')

    class Meta:
        verbose_name = "Jídelníček"
        verbose_name_plural = "Jídelníčky"
        ordering = ['-created_at']


class MenuPlanCoefficient(models.Model):
    """Výchozí koeficient porce pro jídelníček"""
    menu_plan = models.ForeignKey(MenuPlan, on_delete=models.CASCADE, related_name='default_coefficients', verbose_name="Jídelníček")
    name = models.CharField(max_length=100, verbose_name="Název", help_text="Např. 'Normální porce', 'Malá porce', 'Velká porce'")
    coefficient = models.DecimalField(
        max_digits=5, 
        decimal_places=2, 
        default=Decimal('1.0'),
        verbose_name="Koeficient",
        help_text="Např. 1.0 = normální, 0.5 = poloviční, 1.5 = větší"
    )
    order = models.PositiveIntegerField(default=0, verbose_name="Pořadí", help_text="Pořadí zobrazení (nižší číslo = dříve)")
    
    def __str__(self):
        return f"{self.name} ({self.coefficient})"
    
    class Meta:
        verbose_name = "Výchozí koeficient"
        verbose_name_plural = "Výchozí koeficienty"
        ordering = ['menu_plan', 'order']


class ProductionOrder(models.Model):
    """Výrobní příkaz - nyní součást jídelníčku"""
    
    class MealType(models.TextChoices):
        BREAKFAST = 'BREAKFAST', 'Snídaně'
        SNACK_MORNING = 'SNACK_MORNING', 'Svačina dopolední'
        LUNCH = 'LUNCH', 'Oběd'
        SNACK_AFTERNOON = 'SNACK_AFTERNOON', 'Svačina odpolední'
        DINNER = 'DINNER', 'Večeře'
    
    menu_plan = models.ForeignKey(MenuPlan, on_delete=models.CASCADE, related_name='production_orders', verbose_name="Jídelníček", null=False, blank=False)
    recipe = models.ForeignKey(Recipe, on_delete=models.PROTECT, verbose_name="Recept")
    canteen = models.ForeignKey(Canteen, on_delete=models.PROTECT, verbose_name="Jídelna", null=True, blank=True)
    date = models.DateField(verbose_name="Datum vaření")
    meal_type = models.CharField(
        max_length=20,
        choices=MealType.choices,
        default=MealType.LUNCH,
        blank=True,
        verbose_name="Typ jídla",
        help_text="Kategorie jídla (snídaně, oběd, večeře, svačina)",
        db_index=True
    )
    selling_vat_rate = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal('12.00'),
        choices=VAT_RATE_CHOICES,
        verbose_name="Sazba DPH při prodeji (%)",
        help_text="DPH sazba pro prodej tohoto jídla (zkopíruje se z receptu při vytvoření)"
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Vytvořeno")
    
    @property
    def resolved_canteen(self):
        """Vrátí jídelnu - buď z FK nebo z menu_plan (centralizovaná logika)"""
        return self.canteen or getattr(self.menu_plan, 'canteen', None)
    
    @property
    def has_overrides(self):
        """Vrátí True pokud existují nějaké overrides ingrediencí"""
        return self.ingredient_overrides.exists()
    
    def get_canteen(self):
        """Vrátí jídelnu - deprecated, použijte resolved_canteen"""
        return self.resolved_canteen
    
    def _sum_variants(self, fn):
        """Pomocná metoda pro sčítání hodnot přes všechny varianty porcí"""
        return sum(fn(v) for v in self.portion_variants.all())

    def save(self, *args, **kwargs):
        # Automaticky nastav canteen z menu_plan pokud není nastavena
        if self.menu_plan and not self.canteen:
            self.canteen = self.menu_plan.canteen
        
        is_new = self._state.adding
        super().save(*args, **kwargs)
        if is_new:
            self.generate_picking_list()

    def get_portion_variants(self):
        """Vrátí všechny varianty porcí pro tento výrobní příkaz"""
        return self.portion_variants.all()
    
    def get_total_effective_portions(self):
        """Vrátí celkový počet efektivních porcí ze všech variant"""
        total = Decimal('0')
        for variant in self.portion_variants.all():
            total += variant.portions * variant.coefficient
        return total

    def generate_picking_list(self):
        """
        Vygeneruje položky na výdejce na základě norem receptu.
        Množství se počítá ze všech variant porcí a převádí na základní jednotky (kg).
        Předvyplní sklad, který patří k jídelně a má danou surovinu.
        Zajistí, že všechny potřebné suroviny existují ve skladu s minimálně 0 ks.
        Respektuje ingredient overrides (přidané/upravené/odstraněné ingredience).
        """
        if not self.recipe:
            return

        # Zjistíme, zda existují overrides
        has_overrides = self.ingredient_overrides.exists()

        # Získáme slovník overrides pro rychlé vyhledávání
        overrides_dict = {}
        if has_overrides:
            for override in self.ingredient_overrides.select_related('ingredient'):
                overrides_dict[override.ingredient_id] = override

        # Zpracujeme ingredience z receptu
        processed_ingredient_ids = set()
        
        for item in self.recipe.recipeingredient_set.all():
            ingredient_id = item.ingredient_id
            processed_ingredient_ids.add(ingredient_id)
            
            # Kontrola, zda je ingredience odstraněná
            if ingredient_id in overrides_dict:
                override = overrides_dict[ingredient_id]
                if override.is_removed:
                    # Smazat existující položku výdejky pokud existuje
                    PickingList.objects.filter(
                        production_order=self,
                        ingredient=item.ingredient
                    ).delete()
                    continue
            
            # Vypočítáme celkové množství ze všech variant
            # Pokud existuje override, použijeme jeho množství
            if ingredient_id in overrides_dict and not overrides_dict[ingredient_id].is_removed:
                override = overrides_dict[ingredient_id]
                # Vytvoříme dočasný RecipeIngredient s přepsaným množstvím
                from apps.core.models import RecipeIngredient
                temp_item = RecipeIngredient(
                    ingredient=item.ingredient,
                    quantity_per_portion=override.quantity_per_portion or item.quantity_per_portion
                )
                total_quantity = self._sum_variants(
                    lambda v: temp_item.get_quantity_in_base_unit(
                        portions=v.portions,
                        coefficient=v.coefficient
                    )
                )
            else:
                total_quantity = self._sum_variants(
                    lambda v: item.get_quantity_in_base_unit(
                        portions=v.portions,
                        coefficient=v.coefficient
                    )
                )

            # Pokusíme se najít existující skladovou položku
            stock_item = None
            if self.resolved_canteen:
                stock_item = StockItem.objects.filter(
                    ingredient=item.ingredient,
                    warehouse__canteen=self.resolved_canteen
                ).first()

            prefilled_warehouse = None
            
            # Pokud surovina neexistuje v žádném skladu jídelny, vytvoříme ji s 0 ks
            if not stock_item and self.resolved_canteen:
                # Najdeme první sklad této jídelny
                warehouse = self.resolved_canteen.warehouses.first()
                if warehouse:
                    # Vytvoříme záznam suroviny s 0 ks
                    stock_item = StockItem.objects.create(
                        ingredient=item.ingredient,
                        warehouse=warehouse,
                        quantity=Decimal('0'),
                        price=Decimal('0')
                    )
            
            prefilled_warehouse = stock_item.warehouse if stock_item else None

            # Použijeme update_or_create místo create pro prevenci duplicit
            PickingList.objects.update_or_create(
                production_order=self,
                ingredient=item.ingredient,
                defaults={
                    'quantity_planned': total_quantity,
                    'warehouse': prefilled_warehouse,
                    'is_customized': has_overrides
                }
            )
        
        # Zpracujeme přidané ingredience (které nebyly v receptu)
        if has_overrides:
            for override in overrides_dict.values():
                if override.is_added and override.ingredient_id not in processed_ingredient_ids:
                    # Vytvoříme dočasný RecipeIngredient pro přidanou ingredienci
                    from apps.core.models import RecipeIngredient
                    temp_item = RecipeIngredient(
                        ingredient=override.ingredient,
                        quantity_per_portion=override.quantity_per_portion or Decimal('0')
                    )
                    
                    total_quantity = self._sum_variants(
                        lambda v: temp_item.get_quantity_in_base_unit(
                            portions=v.portions,
                            coefficient=v.coefficient
                        )
                    )
                    
                    # Najdeme skladovou položku
                    stock_item = None
                    if self.resolved_canteen:
                        stock_item = StockItem.objects.filter(
                            ingredient=override.ingredient,
                            warehouse__canteen=self.resolved_canteen
                        ).first()
                    
                    # Vytvoříme skladovou položku pokud neexistuje
                    if not stock_item and self.resolved_canteen:
                        warehouse = self.resolved_canteen.warehouses.first()
                        if warehouse:
                            stock_item = StockItem.objects.create(
                                ingredient=override.ingredient,
                                warehouse=warehouse,
                                quantity=Decimal('0'),
                                price=Decimal('0')
                            )
                    
                    prefilled_warehouse = stock_item.warehouse if stock_item else None
                    
                    PickingList.objects.update_or_create(
                        production_order=self,
                        ingredient=override.ingredient,
                        defaults={
                            'quantity_planned': total_quantity,
                            'warehouse': prefilled_warehouse,
                            'is_customized': True
                        }
                    )

    def get_required_ingredients(self):
        """Vrátí seznam surovin potřebných pro tento výrobní příkaz s použitím všech variant
        Respektuje overrides (upravené/přidané/odstraněné ingredience)"""
        ingredients = []
        if not self.recipe:
            return ingredients
        
        # Získáme slovník overrides pro rychlé vyhledávání
        overrides_dict = {}
        if self.has_overrides:
            for override in self.ingredient_overrides.select_related('ingredient'):
                overrides_dict[override.ingredient_id] = override
        
        # Zpracujeme ingredience z receptu
        processed_ingredient_ids = set()
        
        for recipe_ingredient in self.recipe.recipeingredient_set.all():
            ingredient_id = recipe_ingredient.ingredient_id
            processed_ingredient_ids.add(ingredient_id)
            
            # Kontrola, zda je ingredience odstraněná
            if ingredient_id in overrides_dict and overrides_dict[ingredient_id].is_removed:
                continue
            
            # Vypočítáme celkové množství ze všech variant
            total_amount = Decimal('0')
            total_amount_recipe_unit = Decimal('0')
            
            # Pokud existuje override, použijeme jeho množství
            quantity_per_portion = recipe_ingredient.quantity_per_portion
            if ingredient_id in overrides_dict and not overrides_dict[ingredient_id].is_removed:
                override = overrides_dict[ingredient_id]
                quantity_per_portion = override.quantity_per_portion or quantity_per_portion
            
            for variant in self.portion_variants.all():
                # Pro výpočet v base_unit musíme použít konverzi
                from apps.core.models import RecipeIngredient
                temp_item = RecipeIngredient(
                    ingredient=recipe_ingredient.ingredient,
                    quantity_per_portion=quantity_per_portion
                )
                amount = temp_item.get_quantity_in_base_unit(
                    portions=variant.portions,
                    coefficient=variant.coefficient
                )
                total_amount += amount
                total_amount_recipe_unit += (
                    quantity_per_portion * 
                    variant.portions * 
                    variant.coefficient
                )
            
            ingredients.append({
                'ingredient': recipe_ingredient.ingredient,
                'amount': total_amount,
                'unit': recipe_ingredient.ingredient.base_unit,
                'amount_recipe_unit': total_amount_recipe_unit,
                'recipe_unit': recipe_ingredient.ingredient.recipe_unit
            })
        
        # Přidáme nové ingredience (které nejsou v receptu)
        if overrides_dict:
            for override in overrides_dict.values():
                if override.is_added and override.ingredient_id not in processed_ingredient_ids:
                    total_amount = Decimal('0')
                    total_amount_recipe_unit = Decimal('0')
                    
                    for variant in self.portion_variants.all():
                        from apps.core.models import RecipeIngredient
                        temp_item = RecipeIngredient(
                            ingredient=override.ingredient,
                            quantity_per_portion=override.quantity_per_portion or Decimal('0')
                        )
                        amount = temp_item.get_quantity_in_base_unit(
                            portions=variant.portions,
                            coefficient=variant.coefficient
                        )
                        total_amount += amount
                        total_amount_recipe_unit += (
                            (override.quantity_per_portion or Decimal('0')) * 
                            variant.portions * 
                            variant.coefficient
                        )
                    
                    ingredients.append({
                        'ingredient': override.ingredient,
                        'amount': total_amount,
                        'unit': override.ingredient.base_unit,
                        'amount_recipe_unit': total_amount_recipe_unit,
                        'recipe_unit': override.ingredient.recipe_unit
                    })
        
        return ingredients
    
    def calculate_cost(self, canteen=None):
        """
        Vypočítá náklady na výrobu s respektováním ingredient overrides
        Vrací slovník s detaily nákladů
        """
        if not self.recipe:
            return {'total': Decimal('0'), 'per_portion': Decimal('0')}
        
        canteen = canteen or self.resolved_canteen
        if not canteen:
            return {'total': Decimal('0'), 'per_portion': Decimal('0')}
        
        total_cost = Decimal('0')
        
        # Získáme sloučené ingredience (s overrides)
        ingredients = self.get_required_ingredients()
        
        # Importujeme StockItem zde aby se zabránilo circular import
        from apps.inventory.models import StockItem
        
        for ing_data in ingredients:
            ingredient = ing_data['ingredient']
            amount = ing_data['amount']
            
            # Najdeme průměrnou cenu ingredience v této jídelně
            avg_price = StockItem.objects.filter(
                ingredient=ingredient,
                warehouse__canteen=canteen
            ).aggregate(avg_price=models.Avg('price'))['avg_price'] or Decimal('0')
            
            # Připočteme cenu této ingredience
            total_cost += amount * avg_price
        
        # Vypočítáme cenu na porci
        total_effective_portions = self.total_effective_portions
        per_portion = total_cost / total_effective_portions if total_effective_portions > 0 else Decimal('0')
        
        return {
            'total': total_cost.quantize(Decimal('0.01')),
            'per_portion': per_portion.quantize(Decimal('0.01'))
        }
    
    def calculate_selling_price(self, canteen=None):
        """
        Vypočítá prodejní cenu s DPH s respektováním ingredient overrides
        Vrací slovník s detaily cen
        """
        cost_data = self.calculate_cost(canteen)
        
        # Připočteme DPH
        vat_multiplier = Decimal('1') + (self.selling_vat_rate / Decimal('100'))
        
        total_with_vat = cost_data['total'] * vat_multiplier
        per_portion_with_vat = cost_data['per_portion'] * vat_multiplier
        vat_amount = total_with_vat - cost_data['total']
        
        return {
            'total': cost_data['total'].quantize(Decimal('0.01')),
            'per_portion': cost_data['per_portion'].quantize(Decimal('0.01')),
            'total_with_vat': total_with_vat.quantize(Decimal('0.01')),
            'per_portion_with_vat': per_portion_with_vat.quantize(Decimal('0.01')),
            'vat_amount': vat_amount.quantize(Decimal('0.01')),
            'vat_rate': self.selling_vat_rate
        }

    @property
    def total_portions(self):
        """Vrátí celkový počet porcí ze všech variant (bez koeficientů)"""
        return self._sum_variants(lambda v: v.portions)

    @property
    def total_effective_portions(self):
        """Vrátí celkový počet efektivních porcí ze všech variant (s aplikací koeficientů)"""
        return self._sum_variants(lambda v: v.portions * v.coefficient)

    def has_issued_picking_list(self):
        """Vrátí True, pokud pro tento výrobní příkaz existuje vydaná výdejka (přiřazená k dokumentu)"""
        return self.picking_list_items.filter(document__isnull=False).exists()

    def __str__(self):
        canteen = self.get_canteen()
        canteen_name = canteen.name if canteen else 'Bez jídelny'
        return f"Výroba: {self.recipe.name} pro {canteen_name} na den {self.date.strftime('%d.%m.%Y')}"

    class Meta:
        verbose_name = "Výrobní příkaz"
        verbose_name_plural = "Výrobní příkazy"


class ProductionOrderPortionVariant(models.Model):
    """Varianta porce pro výrobní příkaz (kombinace koeficientu a počtu porcí)"""
    production_order = models.ForeignKey(
        ProductionOrder, 
        on_delete=models.CASCADE, 
        related_name='portion_variants', 
        verbose_name="Výrobní příkaz"
    )
    coefficient = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal('1.0'),
        verbose_name="Koeficient",
        help_text="Např. 1.0 = normální, 0.75 = menší"
    )
    name = models.CharField(
        max_length=100,
        default='',
        blank=True,
        verbose_name="Název varianty",
        help_text="Např. Vedoucí, Děti, Normální porce"
    )
    portions = models.PositiveIntegerField(
        verbose_name="Počet porcí",
        help_text="Kolik porcí s tímto koeficientem"
    )
    order = models.PositiveIntegerField(
        default=0,
        verbose_name="Pořadí",
        help_text="Pořadí zobrazení"
    )
    
    def __str__(self):
        if self.name:
            return f"{self.name}: {self.portions}× (koef. {self.coefficient})"
        return f"{self.portions}× (koef. {self.coefficient})"
    
    @property
    def effective_portions(self):
        """Efektivní počet porcí (porce × koeficient)"""
        return self.portions * self.coefficient
    
    class Meta:
        verbose_name = "Varianta porce"
        verbose_name_plural = "Varianty porcí"
        ordering = ['production_order', 'order']


class PickingListDocument(models.Model):
    """Vygenerovaná výdejka jako dokument"""
    name = models.CharField(max_length=100, verbose_name="Název výdejky")
    canteen = models.ForeignKey('canteens.Canteen', on_delete=models.PROTECT, verbose_name="Jídelna")
    date_from = models.DateField(verbose_name="Datum od")
    date_to = models.DateField(verbose_name="Datum do")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Vytvořeno")
    created_by = models.ForeignKey('auth.User', on_delete=models.PROTECT, verbose_name="Vytvořil")
    archived = models.BooleanField(default=False, verbose_name="Archivováno")
    archived_at = models.DateTimeField(null=True, blank=True, verbose_name="Archivováno dne")
    
    def can_be_archived(self):
        """Kontroluje, zda mohou být všechny položky archivovány (všechny mají status COMPLETED)"""
        return self.items.exists() and not self.items.exclude(status=PickingList.Status.COMPLETED).exists()
    
    def __str__(self):
        return f"{self.name} - {self.canteen.name}"
    
    class Meta:
        verbose_name = "Dokument výdejky"
        verbose_name_plural = "Dokumenty výdejek"
        ordering = ['-created_at']


class PickingList(models.Model):
    """Výdejka surovin"""
    class Status(models.TextChoices):
        PENDING = 'PENDING', 'Čeká na vydání'
        COMPLETED = 'COMPLETED', 'Vydáno'

    production_order = models.ForeignKey(ProductionOrder, on_delete=models.CASCADE, related_name='picking_list_items', verbose_name="Výrobní příkaz")
    document = models.ForeignKey(PickingListDocument, on_delete=models.CASCADE, related_name='items', verbose_name="Dokument výdejky", null=True, blank=True)
    warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT, verbose_name="Sklad", help_text="Sklad, ze kterého se má surovina vydat.", null=True, blank=False)
    ingredient = models.ForeignKey(Ingredient, on_delete=models.PROTECT, verbose_name="Surovina")
    quantity_planned = models.DecimalField(max_digits=10, decimal_places=3, verbose_name="Plánované množství")
    quantity_actual = models.DecimalField(max_digits=10, decimal_places=3, null=True, blank=True, verbose_name="Skutečně vydané množství")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING, verbose_name="Stav")
    is_customized = models.BooleanField(
        default=False, 
        verbose_name="Je upraveno",
        help_text="Označuje, že tato výdejka patří k upravenému jídlu"
    )

    def __str__(self):
        return f"Výdejka pro: {self.ingredient.name} ({self.quantity_planned} {self.ingredient.unit})"

    def clean(self):
        # Kontrola, zda sklad patří ke správné jídelně
        order_canteen = self.production_order.get_canteen()
        if self.warehouse and order_canteen and self.warehouse.canteen != order_canteen:
            raise ValidationError(f"Sklad '{self.warehouse}' nepatří k jídelně '{order_canteen}'.")
        
        # Kontrola, zda sklad není uzamčen
        if self.warehouse and self.warehouse.is_locked:
            raise ValidationError(
                f"Sklad '{self.warehouse.name}' je uzamčen kvůli probíhající inventuře. "
                f"Nelze vytvářet ani dokončovat výdejky na uzamčený sklad."
            )
        
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
        
        # Logika pro blokování množství při přiřazení k dokumentu
        # Když je položka přidána k dokumentu, zablokujeme plánované množství
        if self.document and self.warehouse and (original_state is None or original_state.document is None):
            try:
                with transaction.atomic():
                    stock_item = StockItem.objects.select_for_update().get(
                        warehouse=self.warehouse,
                        ingredient=self.ingredient
                    )
                    stock_item.block_quantity(self.quantity_planned)
            except StockItem.DoesNotExist:
                # Vytvoříme skladovou položku s nulovou zásobou a zablokovaným množstvím
                StockItem.objects.create(
                    warehouse=self.warehouse,
                    ingredient=self.ingredient,
                    quantity=Decimal('0'),
                    quantity_blocked=self.quantity_planned,
                    price=Decimal('0')
                )

        # Logika pro odečtení ze skladu a uvolnění blokace
        # Spustí se pouze pokud je status změněn na COMPLETED
        if self.status == self.Status.COMPLETED and (original_state is None or original_state.status != self.Status.COMPLETED):
            if self.quantity_actual is not None and self.warehouse is not None:
                try:
                    with transaction.atomic():
                        stock_item = StockItem.objects.select_for_update().get(
                            warehouse=self.warehouse,
                            ingredient=self.ingredient
                        )
                        # Uvolníme blokované množství
                        stock_item.unblock_quantity(self.quantity_planned)
                        # Odečteme skutečně vydané množství ze skladu
                        stock_item.quantity -= self.quantity_actual

                        # Pokud je množství velmi blízko nule (< 0.001), nastavíme ho na přesně 0
                        if abs(stock_item.quantity) < Decimal('0.001'):
                            stock_item.quantity = Decimal('0')

                        stock_item.save()
                except StockItem.DoesNotExist:
                    # Případ, kdy položka ve skladu neexistuje - vytvoříme ji se záporným stavem
                    StockItem.objects.create(
                        warehouse=self.warehouse,
                        ingredient=self.ingredient,
                        quantity=-self.quantity_actual,
                        quantity_blocked=Decimal('0'),
                        price=Decimal('0')
                    )

    class Meta:
        verbose_name = "Položka výdejky"
        verbose_name_plural = "Položky výdejky"
        unique_together = ('production_order', 'ingredient')


class ProductionOrderRecipeOverride(models.Model):
    """Override globálního receptu pro konkrétní výrobní příkaz"""
    production_order = models.OneToOneField(
        ProductionOrder, 
        on_delete=models.CASCADE, 
        related_name='recipe_override',
        verbose_name="Výrobní příkaz"
    )
    is_customized = models.BooleanField(
        default=False, 
        verbose_name="Je upraveno",
        help_text="Označuje, že tento výrobní příkaz má upravené ingredience"
    )
    customization_note = models.TextField(
        blank=True, 
        verbose_name="Poznámka k úpravě",
        help_text="Důvod nebo popis úpravy receptu"
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Vytvořeno")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Aktualizováno")

    def __str__(self):
        return f"Override pro: {self.production_order}"

    class Meta:
        verbose_name = "Override receptu"
        verbose_name_plural = "Override receptů"


class ProductionOrderIngredientOverride(models.Model):
    """Override konkrétní ingredience pro výrobní příkaz"""
    production_order = models.ForeignKey(
        ProductionOrder, 
        on_delete=models.CASCADE, 
        related_name='ingredient_overrides',
        verbose_name="Výrobní příkaz"
    )
    ingredient = models.ForeignKey(
        Ingredient, 
        on_delete=models.PROTECT, 
        verbose_name="Surovina"
    )
    quantity_per_portion = models.DecimalField(
        max_digits=10, 
        decimal_places=3, 
        null=True, 
        blank=True,
        verbose_name="Množství na porci (g)",
        help_text="Přepsané množství na 1 porci. NULL = odstraněno z receptu"
    )
    original_quantity = models.DecimalField(
        max_digits=10, 
        decimal_places=3,
        verbose_name="Původní množství (g)",
        help_text="Původní množství z receptu pro referenci"
    )
    is_added = models.BooleanField(
        default=False, 
        verbose_name="Přidáno",
        help_text="Ingredience přidaná navíc (nebyla v původním receptu)"
    )
    is_removed = models.BooleanField(
        default=False, 
        verbose_name="Odstraněno",
        help_text="Ingredience odstraněná z receptu"
    )
    notes = models.CharField(
        max_length=200, 
        blank=True, 
        verbose_name="Poznámka",
        help_text="Poznámka k této úpravě"
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Vytvořeno")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Aktualizováno")

    def __str__(self):
        status = "přidáno" if self.is_added else ("odstraněno" if self.is_removed else "upraveno")
        return f"{self.ingredient.name} ({status})"

    class Meta:
        verbose_name = "Override ingredience"
        verbose_name_plural = "Override ingrediencí"
        unique_together = ('production_order', 'ingredient')
