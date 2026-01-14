from django.db import models
from django.utils import timezone
from decimal import Decimal
from datetime import datetime
from django.db import transaction
from apps.core.models import Ingredient
from apps.canteens.models import Warehouse

"""
Model pro evidenci zásob v konkrétních skladech.
- StockItem: propojovací entita mezi `Ingredient` a `Warehouse`, obsahuje množství a cenu.
- IngredientPriceHistory: historie cen suroviny v konkrétním skladu pro přesné kalkulace.
- GoodsReceipt: dokument příjmu zboží
- GoodsReceiptItem: položka příjmu zboží (surovina, množství, cena)

Cenu používáme pro výpočet ceny porcí. Množství se aktualizuje při výdeji z výdejky (PickingList).
Historie cen umožňuje správné výpočty nákladů i při změně nákupních cen v čase.
"""

class StockItem(models.Model):
    """Skladová položka"""
    ingredient = models.ForeignKey(Ingredient, on_delete=models.CASCADE, verbose_name="Surovina")
    warehouse = models.ForeignKey(Warehouse, on_delete=models.CASCADE, related_name='stock_items', verbose_name="Sklad")
    quantity = models.DecimalField(max_digits=10, decimal_places=3, default=0, verbose_name="Množství na skladě")
    quantity_blocked = models.DecimalField(max_digits=10, decimal_places=3, default=0, verbose_name="Blokované množství")
    price = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="Nákupní cena za jednotku")

    def __str__(self):
        return f"{self.ingredient.name} v {self.warehouse.name}: {self.quantity} {self.ingredient.unit}"
    
    @property
    def quantity_available(self):
        """Vrátí dostupné množství (celkové - blokované)"""
        return self.quantity - self.quantity_blocked
    
    def block_quantity(self, amount):
        """
        Zablokuje zadané množství ze skladu.
        Množství se neodečte ze skladu, pouze se zaznamená jako blokované.
        """
        from decimal import Decimal
        amount = Decimal(str(amount))
        if amount < 0:
            raise ValueError("Nelze blokovat záporné množství")
        self.quantity_blocked += amount
        self.save(update_fields=['quantity_blocked'])
    
    def unblock_quantity(self, amount):
        """
        Uvolní (odblokuje) zadané množství.
        Používá se když je výdejka zrušena nebo změněna.
        """
        from decimal import Decimal
        amount = Decimal(str(amount))
        if amount < 0:
            raise ValueError("Nelze odblokovat záporné množství")
        self.quantity_blocked -= amount
        if self.quantity_blocked < 0:
            self.quantity_blocked = Decimal('0')
        # Pokud je blokované množství velmi blízko nule (< 0.001), nastavíme ho na přesně 0
        elif abs(self.quantity_blocked) < Decimal('0.001'):
            self.quantity_blocked = Decimal('0')
        self.save(update_fields=['quantity_blocked'])

    def save(self, *args, **kwargs):
        # Automatická oprava nepřesností pro kusové položky
        if self.ingredient.base_unit in ['ks', 'kus', 'kusy']:
             # Pokud je množství velmi blízko celému číslu (chyba < 0.005), zaokrouhlíme ho
             if abs(self.quantity - round(self.quantity)) < 0.005:
                 self.quantity = round(self.quantity)
             if abs(self.quantity_blocked - round(self.quantity_blocked)) < 0.005:
                 self.quantity_blocked = round(self.quantity_blocked)
        
        # Sledujeme změny ceny a zaznamenáváme do historie
        is_new = self._state.adding
        old_price = None
        if not is_new and self.pk:
            try:
                old_instance = StockItem.objects.get(pk=self.pk)
                old_price = old_instance.price
            except StockItem.DoesNotExist:
                pass
        
        super().save(*args, **kwargs)
        
        # Pokud se změnila cena nebo je to nový záznam, zaznamenáme do historie
        if is_new or (old_price is not None and old_price != self.price):
            IngredientPriceHistory.objects.create(
                ingredient=self.ingredient,
                warehouse=self.warehouse,
                price=self.price,
                valid_from=timezone.now()
            )

    class Meta:
        verbose_name = "Skladová položka"
        verbose_name_plural = "Skladové položky"
        unique_together = ('ingredient', 'warehouse')


class IngredientPriceHistory(models.Model):
    """
    Historie cen suroviny v konkrétním skladu.
    Umožňuje přesné výpočty nákladů receptů v čase i při změnách nákupních cen.
    """
    ingredient = models.ForeignKey(
        Ingredient, 
        on_delete=models.CASCADE, 
        related_name='price_history',
        verbose_name="Surovina"
    )
    warehouse = models.ForeignKey(
        Warehouse, 
        on_delete=models.CASCADE, 
        related_name='price_history',
        verbose_name="Sklad"
    )
    price = models.DecimalField(
        max_digits=10, 
        decimal_places=2, 
        verbose_name="Nákupní cena za jednotku"
    )
    valid_from = models.DateTimeField(
        default=timezone.now,
        verbose_name="Platnost od",
        help_text="Datum a čas od kdy platí tato cena"
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Vytvořeno"
    )
    
    class Meta:
        verbose_name = "Historie ceny suroviny"
        verbose_name_plural = "Historie cen surovin"
        ordering = ['-valid_from']
        indexes = [
            models.Index(fields=['ingredient', 'warehouse', '-valid_from']),
        ]
    
    def __str__(self):
        return f"{self.ingredient.name} v {self.warehouse.name}: {self.price} Kč od {self.valid_from.strftime('%d.%m.%Y')}"
    
    @classmethod
    def get_price_at_date(cls, ingredient, warehouse, date):
        """
        Vrátí cenu suroviny platnou k zadanému datu.
        
        Args:
            ingredient: Ingredient objekt
            warehouse: Warehouse objekt
            date: datetime objekt nebo date objekt
            
        Returns:
            Decimal: Cena nebo Decimal('0') pokud neexistuje záznam
        """
        # Převedeme date na datetime pokud je potřeba
        if hasattr(date, 'date'):
            # Je to už datetime
            query_date = date
        else:
            # Je to date, převedeme na datetime (začátek dne)
            query_date = datetime.combine(date, datetime.min.time())
            # Nastavíme timezone aware pokud je to zapnuto
            if timezone.is_aware(timezone.now()):
                query_date = timezone.make_aware(query_date)
        
        # Najdeme nejbližší starší záznam
        price_record = cls.objects.filter(
            ingredient=ingredient,
            warehouse=warehouse,
            valid_from__lte=query_date
        ).order_by('-valid_from').first()
        
        if price_record:
            return price_record.price
        
        # Pokud neexistuje historický záznam, vrátíme aktuální cenu ze StockItem
        try:
            stock_item = StockItem.objects.get(ingredient=ingredient, warehouse=warehouse)
            return stock_item.price
        except StockItem.DoesNotExist:
            return Decimal('0')


class GoodsReceipt(models.Model):
    """
    Dokument příjmu zboží.
    Slouží k evidenci příjmů surovin do skladu s cenou.
    """
    class Status(models.TextChoices):
        DRAFT = 'DRAFT', 'Koncept'
        CONFIRMED = 'CONFIRMED', 'Potvrzeno'
    
    warehouse = models.ForeignKey(
        Warehouse, 
        on_delete=models.PROTECT, 
        related_name='goods_receipts',
        verbose_name="Sklad"
    )
    receipt_number = models.CharField(
        max_length=50,
        verbose_name="Číslo dokladu",
        help_text="Např. číslo dodacího listu nebo faktury"
    )
    receipt_date = models.DateField(
        default=timezone.now,
        verbose_name="Datum příjmu"
    )
    supplier = models.CharField(
        max_length=200,
        blank=True,
        verbose_name="Dodavatel",
        help_text="Název dodavatele"
    )
    status = models.CharField(
        max_length=10,
        choices=Status.choices,
        default=Status.DRAFT,
        verbose_name="Stav"
    )
    notes = models.TextField(
        blank=True,
        verbose_name="Poznámky"
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Vytvořeno"
    )
    created_by = models.ForeignKey(
        'auth.User',
        on_delete=models.PROTECT,
        verbose_name="Vytvořil"
    )
    confirmed_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Potvrzeno dne"
    )
    
    def __str__(self):
        return f"Příjem {self.receipt_number} - {self.warehouse.name}"
    
    def get_total_value(self):
        """Vrátí celkovou hodnotu příjmu"""
        total = Decimal('0')
        for item in self.items.all():
            total += item.quantity * item.price
        return total
    
    def confirm(self):
        """
        Potvrdí příjem zboží - aktualizuje stavy ve skladu a ceny.
        Pouze pokud je ve stavu DRAFT.
        """
        if self.status != self.Status.DRAFT:
            raise ValueError("Příjem lze potvrdit pouze ve stavu Koncept")
        
        with transaction.atomic():
            for item in self.items.all():
                # Získání nebo vytvoření skladové položky
                stock_item, created = StockItem.objects.get_or_create(
                    ingredient=item.ingredient,
                    warehouse=self.warehouse,
                    defaults={
                        'quantity': Decimal('0'),
                        'price': item.price
                    }
                )
                
                # Přičtení množství
                stock_item.quantity += item.quantity
                
                # Aktualizace ceny - zapíše se do historie automaticky v save() StockItem
                if stock_item.price != item.price:
                    stock_item.price = item.price
                
                stock_item.save()
            
            # Změna stavu na potvrzeno
            self.status = self.Status.CONFIRMED
            self.confirmed_at = timezone.now()
            self.save()
    
    class Meta:
        verbose_name = "Příjem zboží"
        verbose_name_plural = "Příjmy zboží"
        ordering = ['-created_at']


class GoodsReceiptItem(models.Model):
    """
    Položka příjmu zboží - konkrétní surovina s množstvím a cenou.
    """
    goods_receipt = models.ForeignKey(
        GoodsReceipt,
        on_delete=models.CASCADE,
        related_name='items',
        verbose_name="Příjem zboží"
    )
    ingredient = models.ForeignKey(
        Ingredient,
        on_delete=models.PROTECT,
        verbose_name="Surovina"
    )
    warehouse = models.ForeignKey(
        Warehouse,
        on_delete=models.PROTECT,
        verbose_name="Sklad",
        help_text="Sklad, do kterého se surovina přijímá"
    )
    quantity = models.DecimalField(
        max_digits=10,
        decimal_places=3,
        verbose_name="Množství",
        help_text="Množství v základní jednotce suroviny"
    )
    price_without_vat = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name="Cena bez DPH za jednotku"
    )
    vat_rate = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal('21.00'),
        verbose_name="Sazba DPH (%)"
    )
    vat_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name="Částka DPH za jednotku"
    )
    price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        verbose_name="Nákupní cena za jednotku (vč. DPH)"
    )
    notes = models.CharField(
        max_length=200,
        blank=True,
        verbose_name="Poznámka",
        help_text="Např. šarže, expirace"
    )
    
    def __str__(self):
        return f"{self.ingredient.name}: {self.quantity} {self.ingredient.unit} @ {self.price} Kč"
    
    @property
    def total_price(self):
        """Vrátí celkovou cenu položky (množství × cena vč. DPH)"""
        return self.quantity * self.price
    
    @property
    def total_without_vat(self):
        """Vrátí celkovou cenu bez DPH"""
        if self.price_without_vat:
            return self.quantity * self.price_without_vat
        return Decimal('0')
    
    @property
    def total_vat(self):
        """Vrátí celkovou částku DPH"""
        if self.vat_amount:
            return self.quantity * self.vat_amount
        return Decimal('0')
    
    def calculate_vat_fields(self):
        """Vypočítá DPH pole z ceny s DPH a sazby DPH"""
        if self.price and self.vat_rate is not None:
            # Cena s DPH / (1 + sazba/100) = cena bez DPH
            vat_multiplier = 1 + (self.vat_rate / Decimal('100'))
            self.price_without_vat = (self.price / vat_multiplier).quantize(Decimal('0.01'))
            self.vat_amount = (self.price - self.price_without_vat).quantize(Decimal('0.01'))
    
    def save(self, *args, **kwargs):
        # Automatický výpočet DPH polí pokud nejsou vyplněny
        if self.price and not self.price_without_vat:
            self.calculate_vat_fields()
        super().save(*args, **kwargs)
    
    class Meta:
        verbose_name = "Položka příjmu zboží"
        verbose_name_plural = "Položky příjmu zboží"
        ordering = ['ingredient__name']
