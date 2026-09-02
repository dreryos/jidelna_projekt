from django.db import models
from django.utils import timezone
from decimal import Decimal
from datetime import datetime
from django.db import transaction
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db.models.signals import post_save, pre_delete
from django.dispatch import receiver
from django.core.cache import cache
from apps.core.models import Ingredient
from apps.core.constants import VAT_RATE_CHOICES
from apps.canteens.models import Warehouse
import logging

logger = logging.getLogger(__name__)

class Supplier(models.Model):
    """Dodavatel s možností šablon surovin"""
    
    BUTTON_COLOR_CHOICES = [
        ('primary', 'Modrá (primary)'),
        ('secondary', 'Šedá (secondary)'),
        ('success', 'Zelená (success)'),
        ('danger', 'Červená (danger)'),
        ('warning', 'Oranžová (warning)'),
        ('info', 'Tyrkysová (info)'),
        ('light', 'Světlá (light)'),
        ('dark', 'Tmavá (dark)'),
        ('outline-primary', 'Obrys modrá'),
        ('outline-success', 'Obrys zelená'),
        ('outline-warning', 'Obrys oranžová'),
        ('outline-info', 'Obrys tyrkysová'),
    ]
    
    name = models.CharField(
        max_length=200,
        unique=True,
        verbose_name="Název dodavatele"
    )
    slug = models.SlugField(
        max_length=50,
        unique=True,
        verbose_name="Identifikátor",
        help_text="Jednoznačný identifikátor pro API (např. 'zelinar', 'pekarna')"
    )
    is_active = models.BooleanField(
        default=True,
        verbose_name="Aktivní",
        help_text="Deaktivování skryje dodavatele ze šablon"
    )
    icon_class = models.CharField(
        max_length=100,
        default='fa-box',
        verbose_name="Ikona",
        help_text="Font Awesome ikona (např. 'fa-carrot', 'fa-bread-slice', 'fa-box'). Seznam ikon: https://fontawesome.com/icons"
    )
    button_color = models.CharField(
        max_length=30,
        choices=BUTTON_COLOR_CHOICES,
        default='outline-primary',
        verbose_name="Barva tlačítka",
        help_text="Barva tlačítka v rychlých šablonách"
    )
    template_cache_key = models.CharField(
        max_length=100,
        blank=True,
        verbose_name="Cache klíč",
        help_text="Auto-generovaný klíč pro cache"
    )
    
    def __str__(self):
        return self.name
    
    def save(self, *args, **kwargs):
        if not self.template_cache_key:
            self.template_cache_key = f"supplier_template_{self.slug}"
        super().save(*args, **kwargs)
    
    def get_template_ingredients(self):
        """Vrátí všechny suroviny pro šablonu dodavatele"""
        return self.template_ingredients.select_related('ingredient').all()
    
    def invalidate_cache(self):
        """Invaliduje cache pro šablony tohoto dodavatele"""
        cache.delete(self.template_cache_key)
    
    class Meta:
        verbose_name = "Dodavatel"
        verbose_name_plural = "Dodavatelé"
        ordering = ['name']


class SupplierIngredientTemplate(models.Model):
    """Šablona surovin pro dodavatele s výchozími hodnotami"""
    supplier = models.ForeignKey(
        Supplier,
        on_delete=models.CASCADE,
        related_name='template_ingredients',
        verbose_name="Dodavatel"
    )
    ingredient = models.ForeignKey(
        Ingredient,
        on_delete=models.CASCADE,
        verbose_name="Surovina"
    )
    default_price_without_vat = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name="Výchozí cena bez DPH",
        help_text="Přednastavená cena bez DPH pro rychlejší vyplnění"
    )
    default_vat_rate = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        choices=VAT_RATE_CHOICES,
        default=Decimal('12'),
        verbose_name="Výchozí sazba DPH"
    )
    sort_order = models.PositiveIntegerField(
        default=0,
        verbose_name="Pořadí",
        help_text="Pořadí zobrazení v šabloně (0 = první)"
    )
    
    def __str__(self):
        return f"{self.supplier.name} - {self.ingredient.name}"
    
    @property
    def default_price_with_vat(self):
        """Vypočítá cenu s DPH pokud je zadána cena bez DPH"""
        if self.default_price_without_vat:
            vat_multiplier = Decimal('1') + (self.default_vat_rate / Decimal('100'))
            return self.default_price_without_vat * vat_multiplier
        return None
    
    class Meta:
        verbose_name = "Šablona suroviny"
        verbose_name_plural = "Šablony surovin"
        unique_together = ('supplier', 'ingredient')
        ordering = ['sort_order', 'ingredient__name']


# Signály pro automatické cache invalidation
@receiver(post_save, sender=Supplier)
def invalidate_supplier_cache_on_save(sender, instance, **kwargs):
    """Invaliduje cache při změně dodavatele"""
    instance.invalidate_cache()


@receiver(post_save, sender=SupplierIngredientTemplate)
def invalidate_supplier_template_cache_on_save(sender, instance, **kwargs):
    """Invaliduje cache při změně šablony surovin"""
    instance.supplier.invalidate_cache()

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
    vat_rate = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        choices=VAT_RATE_CHOICES,
        default=Decimal('12'),
        verbose_name="Sazba DPH"
    )
    price_without_vat = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name="Cena bez DPH"
    )

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
        Aktualizace probíhá atomicky přes F() výraz, aby souběžné blokace
        nepřepisovaly navzájem své hodnoty.
        """
        from decimal import Decimal
        amount = Decimal(str(amount))
        if amount < 0:
            raise ValueError("Nelze blokovat záporné množství")
        StockItem.objects.filter(pk=self.pk).update(
            quantity_blocked=models.F('quantity_blocked') + amount
        )
        self.refresh_from_db(fields=['quantity_blocked'])
        self._normalize_quantity_blocked()

    def unblock_quantity(self, amount):
        """
        Uvolní (odblokuje) zadané množství.
        Používá se když je výdejka zrušena nebo změněna.
        Aktualizace probíhá atomicky přes F() výraz.
        """
        from decimal import Decimal
        amount = Decimal(str(amount))
        if amount < 0:
            raise ValueError("Nelze odblokovat záporné množství")
        StockItem.objects.filter(pk=self.pk).update(
            quantity_blocked=models.F('quantity_blocked') - amount
        )
        self.refresh_from_db(fields=['quantity_blocked'])
        self._normalize_quantity_blocked()

    def _normalize_quantity_blocked(self):
        """
        Zaokrouhlí blokované množství po atomickém update:
        záporné nebo téměř nulové (< 0.001) hodnoty na přesnou 0,
        u kusových položek drobné nepřesnosti na celé číslo.
        """
        from decimal import Decimal
        normalized = self.quantity_blocked
        if normalized < 0 or abs(normalized) < Decimal('0.001'):
            normalized = Decimal('0')
        elif self.ingredient.base_unit in ['ks', 'kus', 'kusy']:
            if abs(normalized - round(normalized)) < Decimal('0.005'):
                normalized = Decimal(round(normalized))
        if normalized != self.quantity_blocked:
            StockItem.objects.filter(pk=self.pk).update(quantity_blocked=normalized)
            self.quantity_blocked = normalized

    def save(self, *args, **kwargs):
        # Výpočet ceny bez DPH (price je cena s DPH)
        if self.price is not None and self.vat_rate is not None:
             vat_multiplier = Decimal('1') + (self.vat_rate / Decimal('100'))
             self.price_without_vat = (self.price / vat_multiplier).quantize(Decimal('0.01'))

        # Automatická oprava nepřesností pro kusové položky
        if self.ingredient.base_unit in ['ks', 'kus', 'kusy']:
             # Pokud je množství velmi blízko celému číslu (chyba < 0.005), zaokrouhlíme ho
             if abs(self.quantity - round(self.quantity)) < Decimal('0.005'):
                 self.quantity = round(self.quantity)
             if abs(self.quantity_blocked - round(self.quantity_blocked)) < Decimal('0.005'):
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
    def _to_query_date(cls, date):
        """Interní helper: převede date/datetime na timezone-aware datetime."""
        if hasattr(date, 'date'):
            query_date = date
        else:
            query_date = datetime.combine(date, datetime.min.time())
            if timezone.is_aware(timezone.now()):
                query_date = timezone.make_aware(query_date)
        return query_date

    @classmethod
    def get_prices_bulk(cls, ingredient_ids, warehouse_ids, date):
        """
        Efektivně vrátí ceny pro více kombinací ingredience+sklad najednou (1 DB dotaz).

        Args:
            ingredient_ids: list ID ingrediencí
            warehouse_ids:  list ID skladů
            date:           datum nebo datetime pro historické ceny

        Returns:
            dict: {(ingredient_id, warehouse_id): Decimal(cena)}
        """
        if not ingredient_ids or not warehouse_ids:
            return {}

        query_date = cls._to_query_date(date)

        # Jeden dotaz pro všechny kombinace – z důvodu kompatibility se SQLite
        # řadíme v Pythonu místo DISTINCT ON (PostgreSQL-only).
        records = cls.objects.filter(
            ingredient_id__in=ingredient_ids,
            warehouse_id__in=warehouse_ids,
            valid_from__lte=query_date,
        ).order_by(
            'ingredient_id', 'warehouse_id', '-valid_from'
        ).values('ingredient_id', 'warehouse_id', 'price')

        prices: dict = {}
        for record in records:
            key = (record['ingredient_id'], record['warehouse_id'])
            if key not in prices:  # první = nejnovější (viz order_by)
                prices[key] = record['price']

        # Fallback: StockItem pro chybějící kombinace (jeden dotaz)
        missing_keys = {
            (iid, wid)
            for iid in ingredient_ids
            for wid in warehouse_ids
            if (iid, wid) not in prices
        }
        if missing_keys:
            missing_iids = list({k[0] for k in missing_keys})
            missing_wids = list({k[1] for k in missing_keys})
            for item in StockItem.objects.filter(
                ingredient_id__in=missing_iids,
                warehouse_id__in=missing_wids,
            ).values('ingredient_id', 'warehouse_id', 'price'):
                key = (item['ingredient_id'], item['warehouse_id'])
                if key in missing_keys:
                    prices[key] = item['price']

        return prices

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
        help_text="Název dodavatele (pro postupnou migraci)"
    )
    supplier_obj = models.ForeignKey(
        Supplier,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='goods_receipts',
        verbose_name="Dodavatel (nový)",
        help_text="Dodavatel s možností šablon"
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
        
        # Kontrola zda sklad není uzamčen
        if self.warehouse.is_locked:
            raise ValidationError(
                f"Sklad '{self.warehouse.name}' je uzamčen kvůli probíhající inventuře. "
                f"Nelze potvrdit příjem zboží na uzamčený sklad."
            )
        
        with transaction.atomic():
            for item in self.items.all():
                # Získání nebo vytvoření skladové položky
                stock_item, created = StockItem.objects.get_or_create(
                    ingredient=item.ingredient,
                    warehouse=self.warehouse,
                    defaults={
                        'quantity': Decimal('0'),
                        'price': item.price,
                        'vat_rate': item.vat_rate,
                        'price_without_vat': item.price_without_vat
                    }
                )
                
                # Přičtení množství
                stock_item.quantity += item.quantity
                
                # Aktualizace ceny a DPH - zapíše se do historie automaticky v save() StockItem
                if stock_item.price != item.price or stock_item.vat_rate != item.vat_rate:
                    stock_item.price = item.price
                    stock_item.vat_rate = item.vat_rate
                
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
        """Vypočítá všechny DPH pole"""
        if self.price_without_vat and self.vat_rate is not None:
            # Výpočet z ceny bez DPH
            vat_multiplier = Decimal('1') + (self.vat_rate / Decimal('100'))
            self.vat_amount = (self.price_without_vat * self.vat_rate / Decimal('100')).quantize(Decimal('0.01'))
            self.price = (self.price_without_vat + self.vat_amount).quantize(Decimal('0.01'))
        elif self.price and self.vat_rate is not None:
            # Výpočet z ceny s DPH (zpětný výpočet)
            vat_multiplier = Decimal('1') + (self.vat_rate / Decimal('100'))
            self.price_without_vat = (self.price / vat_multiplier).quantize(Decimal('0.01'))
            self.vat_amount = (self.price - self.price_without_vat).quantize(Decimal('0.01'))
    
    def save(self, *args, **kwargs):
        # Automatický výpočet DPH polí
        if self.price_without_vat and self.vat_rate is not None and not self.price:
            self.calculate_vat_fields()
        elif self.price and self.vat_rate is not None and not self.price_without_vat:
            self.calculate_vat_fields()
        super().save(*args, **kwargs)
    
    class Meta:
        verbose_name = "Položka příjmu zboží"
        verbose_name_plural = "Položky příjmu zboží"
        ordering = ['ingredient__name']


class InventoryVerification(models.Model):
    """
    Inventura skladu.
    Umožňuje fyzickou kontrolu stavu zásob a aktualizaci skladových množství.
    Během inventury je sklad zamčen - nelze provádět příjmy ani výdeje.
    """
    class Status(models.TextChoices):
        DRAFT = 'DRAFT', 'Koncept'
        IN_PROGRESS = 'IN_PROGRESS', 'Probíhá'
        COMPLETED = 'COMPLETED', 'Dokončeno'
        CANCELLED = 'CANCELLED', 'Zrušeno'
    
    warehouse = models.ForeignKey(
        Warehouse,
        on_delete=models.PROTECT,
        related_name='inventory_verifications',
        verbose_name="Sklad"
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.DRAFT,
        verbose_name="Stav"
    )
    notes = models.TextField(
        blank=True,
        verbose_name="Poznámky"
    )
    
    # Audit pole
    started_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Zahájeno"
    )
    started_by = models.ForeignKey(
        'auth.User',
        on_delete=models.PROTECT,
        related_name='inventories_started',
        null=True,
        blank=True,
        verbose_name="Zahájil"
    )
    completed_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Dokončeno"
    )
    completed_by = models.ForeignKey(
        'auth.User',
        on_delete=models.PROTECT,
        related_name='inventories_completed',
        null=True,
        blank=True,
        verbose_name="Dokončil"
    )
    cancelled_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Zrušeno"
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Vytvořeno"
    )
    created_by = models.ForeignKey(
        'auth.User',
        on_delete=models.PROTECT,
        related_name='inventories_created',
        verbose_name="Vytvořil"
    )
    
    class Meta:
        verbose_name = "Inventura"
        verbose_name_plural = "Inventury"
        ordering = ['-started_at', '-created_at']
    
    def __str__(self):
        return f"Inventura {self.warehouse.name} - {self.get_status_display()}"
    
    def start(self, user):
        """
        Zahájí inventuru - zamkne sklad a vytvoří položky pro všechny StockItem.
        
        Args:
            user: User objekt, který inventuru zahajuje
            
        Raises:
            ValidationError: Pokud je sklad již zamčen nebo inventura není ve stavu DRAFT
        """
        if self.status != self.Status.DRAFT:
            raise ValidationError("Inventuru lze zahájit pouze ve stavu Koncept")
        
        with transaction.atomic():
            # Zamknout řádek skladu na úrovni DB pro prevenci race condition
            warehouse = Warehouse.objects.select_for_update().get(pk=self.warehouse_id)
            
            # Kontrola zda sklad není již zamčen
            if warehouse.is_locked:
                locked_by = warehouse.locked_by_inventory
                if locked_by is None:
                    # Osiřelý zámek (inventura byla smazána bez odemčení skladu) - odemknout a pokračovat
                    warehouse.is_locked = False
                    warehouse.save(update_fields=['is_locked'])
                else:
                    raise ValidationError(
                        f"Sklad je již uzamčen inventurou zahájenou "
                        f"{locked_by.started_by.get_full_name() or locked_by.started_by.username} "
                        f"dne {locked_by.started_at.strftime('%d.%m.%Y %H:%M')}"
                    )
            
            # Zamknout sklad
            warehouse.is_locked = True
            warehouse.locked_by_inventory = self
            warehouse.save(update_fields=['is_locked', 'locked_by_inventory'])
            
            # Nastavit stav a audit pole
            self.status = self.Status.IN_PROGRESS
            self.started_at = timezone.now()
            self.started_by = user
            self.save()
            
            # Vytvořit položky pro všechny existující StockItem
            stock_items = StockItem.objects.filter(warehouse=warehouse).select_related('ingredient')
            for stock_item in stock_items:
                InventoryVerificationItem.objects.create(
                    verification=self,
                    ingredient=stock_item.ingredient,
                    system_quantity=stock_item.quantity,
                    is_newly_found=False
                )
            
            # Logování
            logger.info(
                f"Inventory verification {self.id} STARTED by user {user.id} ({user.username}) "
                f"for warehouse {warehouse.id} ({warehouse.name}) at {self.started_at}. "
                f"Items to verify: {stock_items.count()}"
            )
    
    def complete(self, user):
        """
        Dokončí inventuru - aktualizuje StockItem dle spočítaných množství a odemkne sklad.
        
        Args:
            user: User objekt, který inventuru dokončuje
            
        Raises:
            ValidationError: Pokud inventura není ve stavu IN_PROGRESS
        """
        if self.status != self.Status.IN_PROGRESS:
            raise ValidationError("Dokončit lze pouze probíhající inventuru")
        
        # Validace - všechny položky musí být spočítány
        uncounted_items = self.items.filter(counted_quantity__isnull=True)
        if uncounted_items.exists():
            uncounted_count = uncounted_items.count()
            raise ValidationError(
                f"Nelze dokončit inventuru. {uncounted_count} položek "
                f"nemá zadané spočítané množství."
            )
        
        with transaction.atomic():
            locked = InventoryVerification.objects.select_for_update().get(pk=self.pk)
            if locked.status != self.Status.IN_PROGRESS:
                raise ValidationError("Dokončit lze pouze probíhající inventuru")

            items_updated = 0
            items_created = 0
            total_discrepancies = 0

            for item in self.items.all():
                if item.counted_quantity is None:
                    continue
                
                # Vypočítat rozdíl
                item.difference = item.counted_quantity - item.system_quantity
                item.save(update_fields=['difference'])
                
                if item.difference != 0:
                    total_discrepancies += 1
                
                # Aktualizovat nebo vytvořit StockItem
                if item.is_newly_found:
                    # Nově nalezená surovina
                    stock_item, created = StockItem.objects.get_or_create(
                        ingredient=item.ingredient,
                        warehouse=self.warehouse,
                        defaults={
                            'quantity': item.counted_quantity,
                            'price': Decimal('0')  # Cena bude doplněna později
                        }
                    )
                    if created:
                        items_created += 1
                        logger.info(
                            f"Inventory {self.id} - NEW item created: {item.ingredient.name}, "
                            f"quantity: {item.counted_quantity}"
                        )
                    else:
                        stock_item.quantity = item.counted_quantity
                        stock_item.save(update_fields=['quantity'])
                        items_updated += 1
                else:
                    # Aktualizace existující položky
                    try:
                        stock_item = StockItem.objects.select_for_update().get(
                            ingredient=item.ingredient,
                            warehouse=self.warehouse
                        )
                        stock_item.quantity = item.counted_quantity
                        stock_item.save(update_fields=['quantity'])
                        items_updated += 1
                        
                        # Detailní log položky s rozdílem
                        logger.info(
                            f"Inventory {self.id} - Item: {item.ingredient.name}, "
                            f"expected: {item.system_quantity}, counted: {item.counted_quantity}, "
                            f"diff: {item.difference}"
                        )
                    except StockItem.DoesNotExist:
                        logger.warning(
                            f"Inventory {self.id} - StockItem not found for {item.ingredient.name}, "
                            f"creating new with quantity {item.counted_quantity}"
                        )
                        StockItem.objects.create(
                            ingredient=item.ingredient,
                            warehouse=self.warehouse,
                            quantity=item.counted_quantity,
                            price=Decimal('0')
                        )
                        items_created += 1
            
            # Odemknout sklad
            self.warehouse.is_locked = False
            self.warehouse.locked_by_inventory = None
            self.warehouse.save(update_fields=['is_locked', 'locked_by_inventory'])
            
            # Nastavit stav a audit pole
            self.status = self.Status.COMPLETED
            self.completed_at = timezone.now()
            self.completed_by = user
            self.save()
            
            # Summary log
            logger.info(
                f"Inventory verification {self.id} COMPLETED by user {user.id} ({user.username}) "
                f"for warehouse {self.warehouse.name} at {self.completed_at}. "
                f"Items updated: {items_updated}, Items created: {items_created}, "
                f"Discrepancies: {total_discrepancies}"
            )

    def zero_out_and_complete(self, user):
        """
        Vynuluje všechny položky inventury a rovnou ji dokončí.
        Určeno pro provozy, které na konci turnusu vyprodají celý sklad na nulu.

        Args:
            user: User objekt, který akci provádí

        Raises:
            ValidationError: Pokud inventura není ve stavu IN_PROGRESS
        """
        if self.status != self.Status.IN_PROGRESS:
            raise ValidationError("Vynulovat lze pouze probíhající inventuru")

        with transaction.atomic():
            self.items.update(counted_quantity=Decimal('0'))
            self.complete(user)
            transaction.on_commit(lambda: logger.info(
                f"Inventory verification {self.id} ZEROED OUT by user {user.id} ({user.username}) "
                f"for warehouse {self.warehouse.name}"
            ))

    def cancel(self, user):
        """
        Zruší probíhající inventuru - odemkne sklad bez aktualizace množství.
        Může zrušit pouze uživatel, který inventuru zahájil, nebo superuser.
        
        Args:
            user: User objekt, který inventuru ruší
            
        Raises:
            ValidationError: Pokud inventura není ve stavu IN_PROGRESS nebo user není started_by/superuser
        """
        if self.status != self.Status.IN_PROGRESS:
            raise ValidationError("Zrušit lze pouze probíhající inventuru")
        
        if self.started_by != user and not user.is_superuser:
            raise ValidationError(
                f"Inventuru může zrušit pouze uživatel, který ji zahájil "
                f"({self.started_by.get_full_name() or self.started_by.username}) "
                f"nebo administrátor"
            )
        
        with transaction.atomic():
            # Odemknout sklad
            self.warehouse.is_locked = False
            self.warehouse.locked_by_inventory = None
            self.warehouse.save(update_fields=['is_locked', 'locked_by_inventory'])
            
            # Nastavit stav
            self.status = self.Status.CANCELLED
            self.cancelled_at = timezone.now()
            self.save()
            
            # Logování
            logger.warning(
                f"Inventory verification {self.id} CANCELLED by user {user.id} ({user.username}) "
                f"for warehouse {self.warehouse.name} at {self.cancelled_at}"
            )
    
    def get_discrepancy_count(self):
        """Vrátí počet položek s rozdílem mezi evidencí a skutečností"""
        return self.items.exclude(difference=0).count()


class InventoryVerificationItem(models.Model):
    """
    Položka inventury - surovina se systémovým a spočítaným množstvím.
    """
    verification = models.ForeignKey(
        InventoryVerification,
        on_delete=models.CASCADE,
        related_name='items',
        verbose_name="Inventura"
    )
    ingredient = models.ForeignKey(
        Ingredient,
        on_delete=models.PROTECT,
        verbose_name="Surovina"
    )
    system_quantity = models.DecimalField(
        max_digits=10,
        decimal_places=3,
        default=0,
        verbose_name="Množství v evidenci",
        help_text="Množství dle systému před inventurou"
    )
    counted_quantity = models.DecimalField(
        max_digits=10,
        decimal_places=3,
        null=True,
        blank=True,
        verbose_name="Spočítané množství",
        help_text="Skutečně nalezené množství při inventuře"
    )
    difference = models.DecimalField(
        max_digits=10,
        decimal_places=3,
        default=0,
        verbose_name="Rozdíl",
        help_text="Rozdíl mezi spočítaným a systémovým množstvím"
    )
    is_newly_found = models.BooleanField(
        default=False,
        verbose_name="Nově nalezeno",
        help_text="Surovina nebyla v evidenci, ale byla nalezena při inventuře"
    )
    notes = models.TextField(
        blank=True,
        verbose_name="Poznámka"
    )
    
    class Meta:
        verbose_name = "Položka inventury"
        verbose_name_plural = "Položky inventury"
        ordering = ['ingredient__name']
        unique_together = ('verification', 'ingredient')
    
    def __str__(self):
        return f"{self.ingredient.name}: {self.counted_quantity or '?'} / {self.system_quantity}"


class StockTransfer(models.Model):
    """
    Převodka zboží mezi sklady.
    Workflow: DRAFT → IN_TRANSIT → COMPLETED
    - DRAFT: Návrh převodky, lze editovat
    - IN_TRANSIT: Zboží odečteno ze source, přidáno do transit warehouse
    - COMPLETED: Zboží převzato v cílovém skladu
    - CANCELLED: Zrušeno (lze jen z DRAFT nebo IN_TRANSIT)
    """
    STATUS_CHOICES = [
        ('DRAFT', 'Návrh'),
        ('IN_TRANSIT', 'V převozu'),
        ('COMPLETED', 'Dokončeno'),
        ('CANCELLED', 'Zrušeno'),
    ]
    
    warehouse_from = models.ForeignKey(
        Warehouse,
        on_delete=models.PROTECT,
        related_name='transfers_out',
        verbose_name="Ze skladu"
    )
    warehouse_to = models.ForeignKey(
        Warehouse,
        on_delete=models.PROTECT,
        related_name='transfers_in',
        verbose_name="Do skladu"
    )
    transfer_number = models.CharField(
        max_length=50,
        unique=True,
        verbose_name="Číslo převodky",
        help_text="Automaticky generované číslo převodky"
    )
    transfer_date = models.DateField(
        default=timezone.now,
        verbose_name="Datum převodky"
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='DRAFT',
        verbose_name="Stav"
    )
    notes = models.TextField(
        blank=True,
        verbose_name="Poznámka"
    )
    created_by = models.ForeignKey(
        'auth.User',
        on_delete=models.SET_NULL,
        null=True,
        related_name='created_transfers',
        verbose_name="Vytvořil"
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Vytvořeno"
    )
    started_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Zahájeno"
    )
    completed_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Dokončeno"
    )
    
    class Meta:
        verbose_name = "Převodka"
        verbose_name_plural = "Převodky"
        ordering = ['-created_at']
    
    def __str__(self):
        return f"Převodka {self.transfer_number} ({self.warehouse_from} → {self.warehouse_to})"
    
    def save(self, *args, **kwargs):
        """Automatické generování čísla převodky"""
        if not self.transfer_number:
            self.transfer_number = self._generate_transfer_number()

        super().save(*args, **kwargs)

    @staticmethod
    def _generate_transfer_number():
        """Vygeneruje další volné číslo ve formátu PRE-YYYYMMDD-XXX.

        Bere maximum ze všech čísel s dnešním prefixem - řazení podle
        stringu selhává od čísla 1000 ('999' > '1000') a neparsovatelné
        číslo nesmí resetovat číslování na 1. Kolize při souběhu skončí
        IntegrityError díky unique na transfer_number.
        """
        prefix = f"PRE-{timezone.localdate().strftime('%Y%m%d')}-"
        numbers = [
            int(number[len(prefix):])
            for number in StockTransfer.objects.filter(
                transfer_number__startswith=prefix
            ).values_list('transfer_number', flat=True)
            if number[len(prefix):].isdigit()
        ]
        return f"{prefix}{max(numbers, default=0) + 1:03d}"
    
    def clean(self):
        """Validace před uložením"""
        super().clean()
        
        # Kontrola že source != target - jen když jsou oba sklady vyplněné,
        # jinak by prázdný formulář hlásil "sklady musí být různé" (None == None)
        if self.warehouse_from_id and self.warehouse_to_id and self.warehouse_from_id == self.warehouse_to_id:
            raise ValidationError("Zdrojový a cílový sklad musí být různé.")

        # Kontrola že není použit transit warehouse jako source nebo target
        if self.warehouse_from_id and self.warehouse_from.is_transit_warehouse:
            raise ValidationError("Nelze převádět z meziskladu.")
        if self.warehouse_to_id and self.warehouse_to.is_transit_warehouse:
            raise ValidationError("Nelze převádět do meziskladu.")
    
    @transaction.atomic
    def start_transfer(self):
        """
        Zahájí převod - odečte zboží ze source a přidá do transit warehouse.
        Změní status na IN_TRANSIT.
        """
        if self.status != 'DRAFT':
            raise ValidationError(f"Nelze zahájit převod ve stavu {self.get_status_display()}.")
        
        # Kontrola zamčených skladů
        if self.warehouse_from.is_locked:
            raise ValidationError(f"Sklad {self.warehouse_from} je zamčen.")
        
        # Získáme transit warehouse
        transit_warehouse = self.warehouse_from.canteen.get_or_create_transit_warehouse()
        
        if transit_warehouse.is_locked:
            raise ValidationError(f"Mezisklad je zamčen.")
        
        # Zpracujeme všechny položky
        for item in self.items.all():
            # Najdeme StockItem ve zdrojovém skladu
            try:
                source_stock = StockItem.objects.select_for_update().get(
                    ingredient=item.ingredient,
                    warehouse=self.warehouse_from
                )
            except StockItem.DoesNotExist:
                raise ValidationError(
                    f"Surovina {item.ingredient.name} není na skladu {self.warehouse_from}."
                )
            
            # Kontrola dostupnosti
            if source_stock.quantity_available < item.quantity:
                raise ValidationError(
                    f"Nedostatečné množství {item.ingredient.name}. "
                    f"Dostupné: {source_stock.quantity_available}, požadováno: {item.quantity}"
                )
            
            # Odečteme ze source
            source_stock.quantity -= item.quantity
            source_stock.save(update_fields=['quantity'])
            
            # Přidáme do transit warehouse
            transit_stock, created = StockItem.objects.get_or_create(
                ingredient=item.ingredient,
                warehouse=transit_warehouse,
                defaults={
                    'quantity': item.quantity,
                    'price': item.unit_price_with_vat,
                    'vat_rate': source_stock.vat_rate,
                }
            )
            if not created:
                transit_stock.quantity += item.quantity
                transit_stock.save(update_fields=['quantity'])
        
        # Aktualizujeme status
        self.status = 'IN_TRANSIT'
        self.started_at = timezone.now()
        self.save(update_fields=['status', 'started_at'])
    
    @transaction.atomic
    def complete_transfer(self):
        """
        Dokončí převod - odečte z transit warehouse a přidá do target.
        Změní status na COMPLETED.
        """
        if self.status != 'IN_TRANSIT':
            raise ValidationError(f"Nelze dokončit převod ve stavu {self.get_status_display()}.")
        
        # Kontrola zamčených skladů
        if self.warehouse_to.is_locked:
            raise ValidationError(f"Sklad {self.warehouse_to} je zamčen.")
        
        # Získáme transit warehouse
        transit_warehouse = self.warehouse_from.canteen.get_or_create_transit_warehouse()
        
        # Zpracujeme všechny položky
        for item in self.items.all():
            # Najdeme StockItem v transit warehouse
            try:
                transit_stock = StockItem.objects.select_for_update().get(
                    ingredient=item.ingredient,
                    warehouse=transit_warehouse
                )
            except StockItem.DoesNotExist:
                raise ValidationError(
                    f"Surovina {item.ingredient.name} není v meziskladu."
                )
            
            # Kontrola množství
            if transit_stock.quantity < item.quantity:
                raise ValidationError(
                    f"Nedostatečné množství {item.ingredient.name} v meziskladu. "
                    f"Dostupné: {transit_stock.quantity}, požadováno: {item.quantity}"
                )
            
            # Odečteme z transit
            transit_stock.quantity -= item.quantity
            transit_stock.save(update_fields=['quantity'])

            # Přidáme do target
            target_stock, created = StockItem.objects.get_or_create(
                ingredient=item.ingredient,
                warehouse=self.warehouse_to,
                defaults={
                    'quantity': item.quantity,
                    'price': item.unit_price_with_vat,
                    'vat_rate': transit_stock.vat_rate,
                }
            )
            if not created:
                self._add_to_stock_with_average_price(target_stock, item)

        # Aktualizujeme status
        self.status = 'COMPLETED'
        self.completed_at = timezone.now()
        self.save(update_fields=['status', 'completed_at'])
    
    @transaction.atomic
    def start_and_complete(self):
        """
        Zahájí a okamžitě dokončí převod (pro rychlé převody v rámci lokality).
        Přeskočí mezisklad - přímo ze source do target.
        """
        if self.status != 'DRAFT':
            raise ValidationError(f"Nelze zahájit převod ve stavu {self.get_status_display()}.")
        
        # Kontrola zamčených skladů
        if self.warehouse_from.is_locked:
            raise ValidationError(f"Sklad {self.warehouse_from} je zamčen.")
        if self.warehouse_to.is_locked:
            raise ValidationError(f"Sklad {self.warehouse_to} je zamčen.")
        
        # Zpracujeme všechny položky
        for item in self.items.all():
            # Najdeme StockItem ve zdrojovém skladu
            try:
                source_stock = StockItem.objects.select_for_update().get(
                    ingredient=item.ingredient,
                    warehouse=self.warehouse_from
                )
            except StockItem.DoesNotExist:
                raise ValidationError(
                    f"Surovina {item.ingredient.name} není na skladu {self.warehouse_from}."
                )
            
            # Kontrola dostupnosti
            if source_stock.quantity_available < item.quantity:
                raise ValidationError(
                    f"Nedostatečné množství {item.ingredient.name}. "
                    f"Dostupné: {source_stock.quantity_available}, požadováno: {item.quantity}"
                )
            
            # Odečteme ze source
            source_stock.quantity -= item.quantity
            source_stock.save(update_fields=['quantity'])
            
            # Přidáme do target
            target_stock, created = StockItem.objects.get_or_create(
                ingredient=item.ingredient,
                warehouse=self.warehouse_to,
                defaults={
                    'quantity': item.quantity,
                    'price': item.unit_price_with_vat,
                    'vat_rate': source_stock.vat_rate,
                }
            )
            if not created:
                self._add_to_stock_with_average_price(target_stock, item)

        # Aktualizujeme status
        self.status = 'COMPLETED'
        self.started_at = timezone.now()
        self.completed_at = timezone.now()
        self.save(update_fields=['status', 'started_at', 'completed_at'])

    @staticmethod
    def _add_to_stock_with_average_price(target_stock, item):
        """Přičte položku do cílové skladové zásoby a přepočítá cenu
        váženým průměrem. Při nekladném výsledném množství (záporný
        zůstatek z dřívějška) průměrovat nelze - převezme se cena položky."""
        old_quantity = target_stock.quantity
        target_stock.quantity += item.quantity
        if target_stock.quantity > 0 and old_quantity >= 0:
            total_value = old_quantity * target_stock.price + item.quantity * item.unit_price_with_vat
            target_stock.price = (total_value / target_stock.quantity).quantize(Decimal('0.01'))
        else:
            target_stock.price = item.unit_price_with_vat
        target_stock.save(update_fields=['quantity', 'price'])
    
    @transaction.atomic
    def cancel(self):
        """
        Zruší převod. Pokud je IN_TRANSIT, vrátí zboží z transit warehouse zpět do source.
        """
        if self.status not in ['DRAFT', 'IN_TRANSIT']:
            raise ValidationError(f"Nelze zrušit převod ve stavu {self.get_status_display()}.")
        
        if self.status == 'IN_TRANSIT':
            # Musíme vrátit zboží z transit warehouse zpět do source
            transit_warehouse = self.warehouse_from.canteen.get_or_create_transit_warehouse()

            for item in self.items.all():
                # Vracíme jen to, co v meziskladu skutečně je - jinak by se
                # zásoba ve zdrojovém skladu uměle nafoukla
                try:
                    transit_stock = StockItem.objects.select_for_update().get(
                        ingredient=item.ingredient,
                        warehouse=transit_warehouse
                    )
                except StockItem.DoesNotExist:
                    logger.warning(
                        f"StockItem pro {item.ingredient} v transit warehouse nenalezen při rušení převodu - položka se nevrací."
                    )
                    continue

                return_quantity = min(transit_stock.quantity, item.quantity)
                if return_quantity <= 0:
                    logger.warning(
                        f"V meziskladu není co vracet pro {item.ingredient} při rušení převodu."
                    )
                    continue

                transit_stock.quantity -= return_quantity
                transit_stock.save(update_fields=['quantity'])

                # Vrátíme zpět do source
                source_stock, created = StockItem.objects.get_or_create(
                    ingredient=item.ingredient,
                    warehouse=self.warehouse_from,
                    defaults={
                        'quantity': return_quantity,
                        'price': item.unit_price_with_vat,
                        'vat_rate': transit_stock.vat_rate,
                    }
                )
                if not created:
                    source_stock.quantity += return_quantity
                    source_stock.save(update_fields=['quantity'])
        
        # Změníme status
        self.status = 'CANCELLED'
        self.save(update_fields=['status'])
    
    def get_total_value(self):
        """Vrátí celkovou hodnotu převodky"""
        total = Decimal('0')
        for item in self.items.all():
            total += item.get_total_price()
        return total


class StockTransferItem(models.Model):
    """
    Položka převodky - jednotlivá surovina s množstvím a cenou.
    """
    stock_transfer = models.ForeignKey(
        StockTransfer,
        on_delete=models.CASCADE,
        related_name='items',
        verbose_name="Převodka"
    )
    ingredient = models.ForeignKey(
        Ingredient,
        on_delete=models.PROTECT,
        verbose_name="Surovina"
    )
    quantity = models.DecimalField(
        max_digits=10,
        decimal_places=3,
        validators=[MinValueValidator(Decimal('0.001'))],
        verbose_name="Množství"
    )
    unit_price_with_vat = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        verbose_name="Jednotková cena s DPH",
        help_text="Automaticky převzato ze zdrojového skladu"
    )
    
    class Meta:
        verbose_name = "Položka převodky"
        verbose_name_plural = "Položky převodky"
        ordering = ['ingredient__name']
        unique_together = ('stock_transfer', 'ingredient')
    
    def __str__(self):
        return f"{self.ingredient.name}: {self.quantity} {self.ingredient.base_unit}"
    
    def get_total_price(self):
        """Vrátí celkovou cenu položky (množství × jednotková cena)"""
        return self.quantity * self.unit_price_with_vat


class StockWriteOff(models.Model):
    """
    Odepsání zboží mimo recepty (hygiena, bufet, ostatní).
    Položky se okamžitě odepisují ze skladu bez schvalovacího workflow.
    """
    class Category(models.TextChoices):
        CLEANING = 'CLEANING', 'Úklid'
        MAINTENANCE = 'MAINTENANCE', 'Údržba'
        LAUNDRY = 'LAUNDRY', 'Prádelna'
        STAFF_RS = 'STAFF_RS', 'Personál RS'
        EDUCATIONAL_STAFF = 'EDUCATIONAL_STAFF', 'Výchovný personál'
        TEACHERS = 'TEACHERS', 'Pedagogové'
        ACCOMMODATION = 'ACCOMMODATION', 'Ubytovací akce'
        BUFET_SALE = 'BUFET_SALE', 'Bufet – prodej'
        OTHER = 'OTHER', 'Ostatní'
    
    document_number = models.CharField(
        max_length=50,
        blank=True,
        verbose_name="Číslo dokladu",
        help_text="Číslo dokladu pro evidenci"
    )
    warehouse = models.ForeignKey(
        Warehouse,
        on_delete=models.PROTECT,
        related_name='write_offs',
        verbose_name="Sklad"
    )
    category = models.CharField(
        max_length=25,
        choices=Category.choices,
        default=Category.OTHER,
        verbose_name="Kategorie"
    )
    write_off_date = models.DateField(
        default=timezone.now,
        verbose_name="Datum odepisování"
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
    cash_register_import_id = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        unique=True,
        verbose_name="ID importu z kasy",
        help_text="Unikátní ID záznamu z pokladního systému"
    )
    imported_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Importováno dne"
    )
    
    def __str__(self):
        return f"Odepsání {self.get_category_display()} - {self.warehouse.name} ({self.write_off_date.strftime('%d.%m.%Y')})"
    
    def get_total_cost(self):
        """Vrátí celkovou nákupní cenu všech položek"""
        total = Decimal('0')
        for item in self.items.all():
            total += item.get_total_cost()
        return total
    
    class Meta:
        verbose_name = "Odepsání mimo recepty"
        verbose_name_plural = "Odepsání mimo recepty"
        ordering = ['-write_off_date', '-created_at']


class StockWriteOffItem(models.Model):
    """Položka odepsání - konkrétní surovina a množství"""
    write_off = models.ForeignKey(
        StockWriteOff,
        on_delete=models.CASCADE,
        related_name='items',
        verbose_name="Odepsání"
    )
    ingredient = models.ForeignKey(
        Ingredient,
        on_delete=models.PROTECT,
        verbose_name="Surovina"
    )
    quantity = models.DecimalField(
        max_digits=10,
        decimal_places=3,
        verbose_name="Množství"
    )
    unit_cost = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        verbose_name="Jednotková nákupní cena s DPH",
        help_text="Automaticky převzato ze skladu v okamžiku odepisování"
    )
    notes = models.CharField(
        max_length=200,
        blank=True,
        verbose_name="Poznámka k položce"
    )
    
    def __str__(self):
        return f"{self.ingredient.name}: {self.quantity} {self.ingredient.base_unit}"
    
    def get_total_cost(self):
        """Vrátí celkovou nákupní cenu (množství × jednotková cena)"""
        return self.quantity * self.unit_cost
    
    def save(self, *args, **kwargs):
        """
        Při vytvoření automaticky odepisuje ze skladu a zapisuje jednotkovou cenu.
        Při úpravě povoluje pouze změnu poznámky a prodejní ceny.
        """
        is_new = self._state.adding
        
        if is_new:
            try:
                stock_item = StockItem.objects.get(
                    ingredient=self.ingredient,
                    warehouse=self.write_off.warehouse
                )
                
                if stock_item.quantity < self.quantity:
                    raise ValidationError(
                        f"Nedostatek {self.ingredient.name} na skladě. "
                        f"Dostupné: {stock_item.quantity} {self.ingredient.base_unit}, "
                        f"Požadováno: {self.quantity} {self.ingredient.base_unit}"
                    )
                
                self.unit_cost = stock_item.price
                super().save(*args, **kwargs)
                
                stock_item.quantity -= self.quantity
                stock_item.save(update_fields=['quantity'])
                
            except StockItem.DoesNotExist:
                raise ValidationError(
                    f"Surovina {self.ingredient.name} není dostupná ve skladu {self.write_off.warehouse.name}"
                )
        else:
            super().save(*args, **kwargs)
    
    class Meta:
        verbose_name = "Položka odepsání"
        verbose_name_plural = "Položky odepsání"
        ordering = ['ingredient__name']
        unique_together = ('write_off', 'ingredient')


@receiver(pre_delete, sender=StockWriteOffItem)
def restore_stock_on_write_off_item_delete(sender, instance, **kwargs):
    """Při smazání položky odepsání vrátí odepsané množství zpět na sklad."""
    try:
        stock_item = StockItem.objects.get(
            ingredient=instance.ingredient,
            warehouse=instance.write_off.warehouse
        )
        stock_item.quantity += instance.quantity
        stock_item.save(update_fields=['quantity'])
        logger.info(
            f"Vráceno {instance.quantity} {instance.ingredient.base_unit} "
            f"{instance.ingredient.name} na sklad {instance.write_off.warehouse.name}"
        )
    except StockItem.DoesNotExist:
        logger.warning(
            f"Skladová položka pro {instance.ingredient.name} "
            f"ve skladu {instance.write_off.warehouse.name} neexistuje - "
            f"množství {instance.quantity} nebylo vráceno"
        )
