import logging
from decimal import Decimal, InvalidOperation
from django import forms
from django.forms import inlineformset_factory, BaseInlineFormSet
from django.core.exceptions import ValidationError, ObjectDoesNotExist
from django.db.models import Q
from .models import (
    GoodsReceipt, GoodsReceiptItem, Warehouse, Ingredient,
    InventoryVerification, InventoryVerificationItem,
    StockTransfer, StockTransferItem, StockItem,
    StockWriteOff, StockWriteOffItem
)

logger = logging.getLogger(__name__)

# České DPH sazby platné v roce 2026
VAT_RATE_CHOICES = [
    (Decimal('21'), '21%'),
    (Decimal('12'), '12%'),
    (Decimal('0'), '0%'),
]


class PriceInput(forms.NumberInput):
    """
    Vstupní pole pro jednotkovou cenu.

    Ceny se ukládají na šest desetinných míst, aby surovina vedená v gramech
    nepřišla zaokrouhlením o procenta hodnoty. Formulář ale musí zobrazit
    **plnou** hodnotu, ne zaokrouhlenou: kdyby ukazoval 0,05 místo 0,0549,
    stačilo by příjemku otevřít a uložit beze změny a přesnost by byla pryč.

    Koncové nuly se ořezávají, ať pole neukazuje „0,054900". Uživatel, který
    zadává haléře, tak vidí „54,9" a ne „54,900000".

    `step` je „any“, protože pevný krok 0,01 by prohlížeč u hodnot jako
    0,0549 označil za neplatné.
    """

    def format_value(self, value):
        if value in (None, ''):
            return ''

        try:
            number = Decimal(str(value))
        except (InvalidOperation, ValueError, TypeError):
            return super().format_value(value)

        # normalize() umí vyrobit exponenciální zápis (1E+2), quantize to vrátí
        # zpět na běžné číslo.
        trimmed = number.normalize()
        if trimmed == trimmed.to_integral_value():
            trimmed = trimmed.quantize(Decimal('1'))
        return str(trimmed)


class GoodsReceiptForm(forms.ModelForm):
    """Formulář pro vytvoření/editaci příjmu zboží."""
    default_warehouse = forms.ModelChoiceField(
        queryset=Warehouse.objects.all(),
        required=True,
        label='Výchozí sklad',
        help_text='Sklad bude automaticky předvyplněn u všech položek',
        widget=forms.Select(attrs={'class': 'form-select', 'id': 'default-warehouse'})
    )
    
    class Meta:
        model = GoodsReceipt
        fields = ['receipt_number', 'receipt_date', 'supplier', 'notes', 'warehouse']
        widgets = {
            'receipt_number': forms.TextInput(attrs={'class': 'form-control'}),
            'receipt_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}, format='%Y-%m-%d'),
            'supplier': forms.TextInput(attrs={'class': 'form-control'}),
            'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'warehouse': forms.Select(attrs={'class': 'form-select'}),
        }
        labels = {
            'receipt_number': 'Číslo dokladu',
            'receipt_date': 'Datum příjmu',
            'supplier': 'Dodavatel',
            'notes': 'Poznámky',
            'warehouse': 'Sklad',
        }
    
    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        # Filtrovat sklady podle přiřazených jídelen uživatele
        if user and not user.is_superuser:
            try:
                user_canteens = user.profile.canteens.all()
                warehouse_qs = Warehouse.objects.filter(canteen__in=user_canteens)
            except Exception:
                warehouse_qs = Warehouse.objects.none()
            self.fields['default_warehouse'].queryset = warehouse_qs
        # Warehouse je hlavní pole, default_warehouse je pomocné
        if 'warehouse' in self.fields:
            self.fields['warehouse'].widget = forms.HiddenInput()
            self.fields['warehouse'].required = False  # Nebude se validovat, protože je skryté
    
    def clean(self):
        cleaned_data = super().clean()
        warehouse = cleaned_data.get('warehouse')
        
        if warehouse and warehouse.is_locked:
            raise ValidationError(
                f"Sklad '{warehouse.name}' je uzamčen kvůli probíhající inventuře "
                f"zahájené {warehouse.locked_by_inventory.started_by.get_full_name() or warehouse.locked_by_inventory.started_by.username} "
                f"dne {warehouse.locked_by_inventory.started_at.strftime('%d.%m.%Y %H:%M')}. "
                f"Nelze vytvářet příjmy zboží na uzamčený sklad."
            )
        
        return cleaned_data


class StockItemForm(forms.ModelForm):
    """Formulář pro skladovou položku (admin).
    
    Pole vat_rate a price_without_vat jsou readonly - určují se automaticky
    z příjmů zboží (GoodsReceipt.confirm()).
    """

    class Meta:
        model = StockItem
        fields = ['ingredient', 'warehouse', 'quantity', 'quantity_blocked', 'price', 'vat_rate', 'price_without_vat']
        widgets = {
            'ingredient': forms.Select(attrs={'class': 'form-select'}),
            'warehouse': forms.Select(attrs={'class': 'form-select'}),
            'quantity': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.001', 'min': '0'}),
            'quantity_blocked': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.001', 'min': '0'}),
            'price': PriceInput(attrs={'class': 'form-control', 'min': '0'}),
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Pole vat_rate a price_without_vat nastavit jako disabled - nelze editovat
        for name in ["vat_rate", "price_without_vat"]:
            if name in self.fields:
                self.fields[name].disabled = True
                self.fields[name].required = False
        
        # Uložit originální hodnoty readonly polí
        if self.instance and self.instance.pk:
            self._original_vat_rate = self.instance.vat_rate
            self._original_price_without_vat = self.instance.price_without_vat
    
    def save(self, commit=True):
        """Ochrana proti přepsání readonly polí - vždy obnovit originální hodnoty."""
        instance = super().save(commit=False)
        
        # Pro existující záznamy obnovit readonly pole a explicitně nastavit, která pole se mají uložit
        if self.instance.pk and hasattr(self, '_original_vat_rate'):
            # Obnovit původní hodnoty PŘED save()
            instance.vat_rate = self._original_vat_rate
            instance.price_without_vat = self._original_price_without_vat
            
            if commit:
                # Použít update_fields pro částečnou aktualizaci - vynechat readonly pole
                # Získat seznam změněných polí kromě readonly
                update_fields = []
                for field_name in self.changed_data:
                    if field_name not in ['vat_rate', 'price_without_vat']:
                        update_fields.append(field_name)
                
                if update_fields:
                    instance.save(update_fields=update_fields)
                # Pokud nejsou změněna žádná pole (pouze readonly), neuložíme nic
        else:
            # Pro nové záznamy normální save
            if commit:
                instance.save()
        
        return instance


class GoodsReceiptItemForm(forms.ModelForm):
    """Formulář pro jednu položku příjmu zboží."""
    
    class Meta:
        model = GoodsReceiptItem
        fields = ['ingredient', 'warehouse', 'quantity', 'price_without_vat', 'price', 'vat_rate', 'notes']
        widgets = {
            'ingredient': forms.Select(attrs={'class': 'form-select', 'required': True}),
            'warehouse': forms.Select(attrs={'class': 'form-select warehouse-select', 'required': True}),
            'quantity': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.001', 'min': '0', 'required': True}),
            'price_without_vat': PriceInput(attrs={
                'class': 'form-control price-without-vat',
                'min': '0',
                'onchange': 'calculateVAT(this)'
            }),
            'price': PriceInput(attrs={
                'class': 'form-control price-with-vat',
                'min': '0',
                'onchange': 'calculateVAT(this)'
            }),
            'vat_rate': forms.Select(attrs={
                'class': 'form-select vat-rate-select', 
                'required': True,
                'onchange': 'calculateVAT(this)'
            }),
            'notes': forms.TextInput(attrs={'class': 'form-control'}),
        }
        labels = {
            'ingredient': 'Surovina',
            'warehouse': 'Sklad',
            'quantity': 'Množství',
            'price_without_vat': 'Cena bez DPH',
            'price': 'Cena s DPH',
            'vat_rate': 'DPH %',
            'notes': 'Poznámka',
        }
    
    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        # Filtrovat sklady podle přiřazených jídelen uživatele
        if user and not user.is_superuser:
            try:
                user_canteens = user.profile.canteens.all()
                self.fields['warehouse'].queryset = Warehouse.objects.filter(canteen__in=user_canteens)
            except Exception:
                self.fields['warehouse'].queryset = Warehouse.objects.none()
        # Filtrovat pouze aktivní suroviny
        from apps.core.models import Ingredient
        self.fields['ingredient'].queryset = Ingredient.objects.filter(is_active=True).order_by('name')
        # Nastavení choices pro DPH sazbu
        self.fields['vat_rate'] = forms.TypedChoiceField(
            choices=VAT_RATE_CHOICES,
            coerce=Decimal,
            required=True,
            label='DPH %',
            widget=forms.Select(attrs={
                'class': 'form-select vat-rate-select',
                'required': True,
                'onchange': 'calculateVAT(this)'
            })
        )
        # Zachovat DPH z instance při editaci, jinak výchozí 12%
        if self.instance and self.instance.pk:
            self.initial['vat_rate'] = self.instance.vat_rate
        else:
            self.initial.setdefault('vat_rate', Decimal('12'))
        # Označení povinných polí
        for field_name in ['ingredient', 'warehouse', 'quantity', 'vat_rate']:
            if field_name in self.fields:
                self.fields[field_name].required = True
        # Cenu je možné vyplnit s DPH nebo bez DPH, proto je necháváme nepovinné
        for field_name in ['price_without_vat', 'price']:
            if field_name in self.fields:
                self.fields[field_name].required = False

    def clean(self):
        cleaned_data = super().clean()
        price_without_vat = cleaned_data.get('price_without_vat')
        price_with_vat = cleaned_data.get('price')
        vat_rate = cleaned_data.get('vat_rate')

        if vat_rate in (None, ''):
            return cleaned_data

        if isinstance(vat_rate, str):
            vat_rate = Decimal(vat_rate)
        cleaned_data['vat_rate'] = vat_rate

        if price_without_vat is None and price_with_vat is None:
            raise ValidationError("Zadejte cenu bez DPH nebo cenu s DPH.")

        vat_multiplier = Decimal('1') + (vat_rate / Decimal('100'))

        if price_without_vat is not None:
            computed_price_with_vat = (price_without_vat * vat_multiplier).quantize(Decimal('0.01'))
            cleaned_data['price'] = computed_price_with_vat
        elif price_with_vat is not None:
            computed_price_without_vat = (price_with_vat / vat_multiplier).quantize(Decimal('0.01'))
            cleaned_data['price_without_vat'] = computed_price_without_vat

        return cleaned_data


# Formset pro položky příjmu
GoodsReceiptItemFormSet = inlineformset_factory(
    GoodsReceipt,
    GoodsReceiptItem,
    form=GoodsReceiptItemForm,
    extra=0,  # 0 prázdných formulářů při vytváření
    min_num=1,  # Minimálně 1 položka
    max_num=100,  # Maximum 100 položek
    validate_min=True,
    can_delete=True,  # Možnost smazání položky
)


class InventoryVerificationForm(forms.ModelForm):
    """Formulář pro vytvoření inventury."""
    
    class Meta:
        model = InventoryVerification
        fields = ['warehouse', 'notes']
        widgets = {
            'warehouse': forms.Select(attrs={'class': 'form-select'}),
            'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }
        labels = {
            'warehouse': 'Sklad',
            'notes': 'Poznámky',
        }
    
    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        # Filtrovat sklady podle přiřazených jídelen uživatele
        if user and not user.is_superuser:
            try:
                user_canteens = user.profile.canteens.all()
                self.fields['warehouse'].queryset = Warehouse.objects.filter(canteen__in=user_canteens)
            except Exception:
                self.fields['warehouse'].queryset = Warehouse.objects.none()
    
    def clean_warehouse(self):
        warehouse = self.cleaned_data.get('warehouse')
        
        if warehouse and warehouse.is_locked:
            locked_by = warehouse.locked_by_inventory
            if locked_by is None:
                # Osiřelý zámek (inventura byla smazána bez odemčení skladu) - odemknout
                warehouse.is_locked = False
                warehouse.save(update_fields=['is_locked'])
                return warehouse
            raise ValidationError(
                f"Sklad '{warehouse.name}' je již uzamčen kvůli probíhající inventuře "
                f"zahájené {locked_by.started_by.get_full_name() or locked_by.started_by.username} "
                f"dne {locked_by.started_at.strftime('%d.%m.%Y %H:%M')}."
            )
        
        return warehouse


class InventoryVerificationItemForm(forms.ModelForm):
    """Formulář pro zadání spočítaného množství u položky inventury."""
    
    class Meta:
        model = InventoryVerificationItem
        fields = ['ingredient', 'counted_quantity', 'notes']
        widgets = {
            'ingredient': forms.Select(attrs={'class': 'form-select'}),
            'counted_quantity': forms.NumberInput(attrs={
                'class': 'form-control',
                'step': '0.001',
                'min': '0'
            }),
            'notes': forms.TextInput(attrs={'class': 'form-control'}),
        }
        labels = {
            'ingredient': 'Surovina',
            'counted_quantity': 'Spočítané množství',
            'notes': 'Poznámka',
        }
    
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Filtrovat pouze aktivní suroviny
        from apps.core.models import Ingredient
        
        if self.instance.pk:
            # Pro existující instance zahrnout i aktuální surovinu (i když je neaktivní)
            # aby prošla validace hidden fieldu
            self.fields['ingredient'].queryset = Ingredient.objects.filter(
                Q(is_active=True) | Q(pk=self.instance.ingredient_id)
            )
        else:
            # Pro nové instance pouze aktivní
            self.fields['ingredient'].queryset = Ingredient.objects.filter(is_active=True)


class BaseInventoryVerificationItemFormSet(BaseInlineFormSet):
    """Vlastní formset, který ignoruje prázdné formuláře."""
    
    def _construct_form(self, i, **kwargs):
        """Konstruuj formulář a nastav pole jako nepovinná pro extra formuláře."""
        form = super()._construct_form(i, **kwargs)
        
        # Pro extra formuláře (nové, nevyplněné) nastav ingredient jako nepovinné
        if i >= self.initial_form_count():
            form.fields['ingredient'].required = False
        
        return form
    
    def clean(self):
        """Ignoruj chyby z prázdných formulářů."""
        # Nejdřív zavolej rodičovskou clean()
        try:
            super().clean()
        except Exception:
            # Pokud selže validace, pokračuj stejně - ošetříme prázdné formuláře
            pass
        
        # Zjisti, které formuláře jsou prázdné a odstraň jejich chyby
        for i, form in enumerate(self.forms):
            # Pokud je to existující instance, nevynechávat
            if form.instance.pk:
                continue
            
            # Zkontroluj raw POST data pro tento formulář
            prefix = form.prefix
            ingredient_key = f"{prefix}-ingredient"
            quantity_key = f"{prefix}-counted_quantity"
            notes_key = f"{prefix}-notes"
            
            has_ingredient = self.data.get(ingredient_key)
            has_quantity = self.data.get(quantity_key)
            has_notes = self.data.get(notes_key, '').strip()
            
            # Pokud formulář nemá žádná data, odstraň jeho chyby
            if not has_ingredient and not has_quantity and not has_notes:
                if i < len(self.errors) and self.errors[i]:
                    self.errors[i] = {}
    
    def save(self, commit=True):
        """Ulož formuláře, včetně existujících instancí bez ohledu na has_changed()."""
        saved_instances = []
        
        # Projdi všechny formuláře
        for form in self.forms:
            # Přeskoč formuláře bez cleaned_data (mají chyby nebo jsou prázdné)
            if not hasattr(form, 'cleaned_data') or not form.cleaned_data:
                continue
            
            # Existující instance - vždy ulož
            if form.instance.pk:
                # Aktualizuj hodnoty z formuláře
                for field_name in ['counted_quantity', 'notes']:
                    if field_name in form.cleaned_data:
                        setattr(form.instance, field_name, form.cleaned_data[field_name])
                
                if commit:
                    form.instance.save()
                saved_instances.append(form.instance)
            
            # Nové instance - ulož pouze pokud mají data
            elif form.has_changed():
                # Zkontroluj, zda má formulář nějaká relevantní data
                has_ingredient = form.cleaned_data.get('ingredient')
                
                if has_ingredient:
                    instance = form.save(commit=commit)
                    saved_instances.append(instance)
        
        return saved_instances


# Formset pro položky inventury
InventoryVerificationItemFormSet = inlineformset_factory(
    InventoryVerification,
    InventoryVerificationItem,
    form=InventoryVerificationItemForm,
    formset=BaseInventoryVerificationItemFormSet,
    extra=1,  # 1 prázdný formulář pro přidání nové suroviny
    min_num=0,
    validate_min=False,  # Umožní uložit formset i bez vyplnění všech položek
    max_num=500,
    can_delete=False,
)


class StockTransferForm(forms.ModelForm):
    """Formulář pro vytvoření/editaci převodky."""
    
    class Meta:
        model = StockTransfer
        fields = ['warehouse_from', 'warehouse_to', 'transfer_date', 'notes']
        widgets = {
            'warehouse_from': forms.Select(attrs={'class': 'form-select'}),
            'warehouse_to': forms.Select(attrs={'class': 'form-select'}),
            'transfer_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}, format='%Y-%m-%d'),
            'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }
        labels = {
            'warehouse_from': 'Ze skladu',
            'warehouse_to': 'Do skladu',
            'transfer_date': 'Datum převodu',
            'notes': 'Poznámky',
        }
    
    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        # Odfiltrovat mezisklady - nelze je vybrat jako source nebo target
        base_qs = Warehouse.objects.filter(is_transit_warehouse=False)
        # Filtrovat sklady podle přiřazených jídelen uživatele
        if user and not user.is_superuser:
            try:
                user_canteens = user.profile.canteens.all()
                base_qs = base_qs.filter(canteen__in=user_canteens)
            except ObjectDoesNotExist:
                logger.warning(
                    'User %s has no profile; hiding all warehouses in StockTransferForm.',
                    getattr(user, 'pk', user),
                )
                base_qs = Warehouse.objects.none()
        self.fields['warehouse_from'].queryset = base_qs
        self.fields['warehouse_to'].queryset = base_qs
    
    def clean(self):
        cleaned_data = super().clean()
        warehouse_from = cleaned_data.get('warehouse_from')
        warehouse_to = cleaned_data.get('warehouse_to')
        
        # Kontrola že source != target
        if warehouse_from and warehouse_to and warehouse_from == warehouse_to:
            raise ValidationError("Zdrojový a cílový sklad musí být různé.")
        
        # Kontrola že sklady nejsou mezisklady
        if warehouse_from and warehouse_from.is_transit_warehouse:
            raise ValidationError("Nelze převádět z meziskladu.")
        if warehouse_to and warehouse_to.is_transit_warehouse:
            raise ValidationError("Nelze převádět do meziskladu.")
        
        # Kontrola zamčení skladů
        if warehouse_from and warehouse_from.is_locked:
            raise ValidationError(
                f"Sklad '{warehouse_from.name}' je uzamčen kvůli probíhající inventuře. "
                f"Nelze vytvářet převodky ze zamčeného skladu."
            )
        if warehouse_to and warehouse_to.is_locked:
            raise ValidationError(
                f"Sklad '{warehouse_to.name}' je uzamčen kvůli probíhající inventuře. "
                f"Nelze vytvářet převodky do zamčeného skladu."
            )
        
        return cleaned_data


class StockTransferItemForm(forms.ModelForm):
    """Formulář pro jednu položku převodky."""
    
    # Přidáme pole pro zobrazení dostupného množství
    available_quantity = forms.DecimalField(
        required=False,
        disabled=True,
        label='Dostupné množství',
        widget=forms.NumberInput(attrs={'class': 'form-control', 'readonly': True})
    )
    
    class Meta:
        model = StockTransferItem
        fields = ['ingredient', 'quantity', 'unit_price_with_vat']
        widgets = {
            'ingredient': forms.Select(attrs={
                'class': 'form-select ingredient-select',
                'required': True,
            }),
            'quantity': forms.NumberInput(attrs={
                'class': 'form-control',
                'step': '0.001',
                'min': '0.001',
                'required': True
            }),
            'unit_price_with_vat': PriceInput(attrs={
                'class': 'form-control unit-price',
                'min': '0',
                'required': True,
                'readonly': True  # Cena se vyplní automaticky
            }),
        }
        labels = {
            'ingredient': 'Surovina',
            'quantity': 'Množství',
            'unit_price_with_vat': 'Jednotková cena s DPH',
        }
    
    def __init__(self, *args, warehouse_from=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.warehouse_from = warehouse_from

        # Cenu doplňuje server ze zdrojového skladu - pole je readonly,
        # takže nesmí být povinné (uživatel by chybu nemohl opravit).
        self.fields['unit_price_with_vat'].required = False

        # Nabízíme suroviny podle zdrojového skladu, včetně neaktivních -
        # co je fyzicky na skladě, musí jít převést. Bez zvoleného skladu
        # (první GET) necháme všechny; JS seznam přenačte po výběru skladu.
        from apps.core.models import Ingredient
        if self.warehouse_from:
            self.fields['ingredient'].queryset = Ingredient.objects.filter(
                stockitem__warehouse=self.warehouse_from,
                stockitem__quantity__gt=0,
            ).distinct()
        else:
            self.fields['ingredient'].queryset = Ingredient.objects.all()
        
        # Pokud máme instance a warehouse_from, nastavíme dostupné množství
        if self.instance.pk and self.instance.ingredient and warehouse_from:
            try:
                stock_item = StockItem.objects.get(
                    ingredient=self.instance.ingredient,
                    warehouse=warehouse_from
                )
                self.initial['available_quantity'] = stock_item.quantity_available
            except StockItem.DoesNotExist:
                self.initial['available_quantity'] = 0
    
    def clean(self):
        cleaned_data = super().clean()
        
        # Pokud je řádek označen ke smazání, přeskočíme validaci
        if cleaned_data.get('DELETE'):
            return cleaned_data
        
        ingredient = cleaned_data.get('ingredient')
        quantity = cleaned_data.get('quantity')
        
        # Pokud máme warehouse_from z formuláře, ověříme dostupnost
        if self.warehouse_from and ingredient and quantity:
            try:
                stock_item = StockItem.objects.get(
                    ingredient=ingredient,
                    warehouse=self.warehouse_from
                )
                if stock_item.quantity_available < quantity:
                    message = (
                        f"Nedostatečné množství. Dostupné: "
                        f"{stock_item.quantity_available} {ingredient.base_unit}"
                    )
                    if stock_item.quantity_blocked:
                        message += (
                            f" (celkem {stock_item.quantity}, "
                            f"blokováno {stock_item.quantity_blocked})"
                        )
                    raise ValidationError({'quantity': message})

                # Cena se vždy přebírá ze zdrojového skladu (server je autoritativní,
                # hodnota z readonly pole se ignoruje)
                cleaned_data['unit_price_with_vat'] = stock_item.price

            except StockItem.DoesNotExist:
                raise ValidationError({
                    'ingredient': f"Surovina '{ingredient.name}' není na skladu {self.warehouse_from}."
                })
        
        return cleaned_data


# Formset pro položky převodky
StockTransferItemFormSet = inlineformset_factory(
    StockTransfer,
    StockTransferItem,
    form=StockTransferItemForm,
    extra=1,  # 1 prázdný formulář
    min_num=1,  # Převodka musí mít alespoň jednu položku
    validate_min=True,
    max_num=100,  # Maximum 100 položek
    can_delete=True,  # Možnost smazání položky
)


class StockWriteOffForm(forms.ModelForm):
    """Formulář pro vytvoření odepsání mimo recepty."""
    
    class Meta:
        model = StockWriteOff
        fields = ['warehouse', 'category', 'write_off_date', 'document_number', 'notes']
        widgets = {
            'warehouse': forms.Select(attrs={'class': 'form-select'}),
            'category': forms.Select(attrs={'class': 'form-select'}),
            'write_off_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}, format='%Y-%m-%d'),
            'document_number': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Číslo dokladu'}),
            'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }
        labels = {
            'warehouse': 'Sklad',
            'category': 'Kategorie',
            'write_off_date': 'Datum odepisování',
            'document_number': 'Číslo dokladu',
            'notes': 'Poznámky',
        }
    
    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        
        if user and not user.is_superuser:
            try:
                user_canteens = user.profile.canteens.all()
                self.fields['warehouse'].queryset = Warehouse.objects.filter(canteen__in=user_canteens)
            except:
                self.fields['warehouse'].queryset = Warehouse.objects.none()


class StockWriteOffItemForm(forms.ModelForm):
    """Formulář pro jednu položku odepsání."""
    
    class Meta:
        model = StockWriteOffItem
        fields = ['ingredient', 'quantity', 'notes']
        widgets = {
            'ingredient': forms.Select(attrs={'class': 'form-select'}),
            'quantity': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.001', 'min': '0.001', 'required': True}),
            'notes': forms.TextInput(attrs={'class': 'form-control'}),
        }
        labels = {
            'ingredient': 'Surovina',
            'quantity': 'Množství',
            'notes': 'Poznámka',
        }
    
    def __init__(self, *args, warehouse=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.warehouse = warehouse
        # Queryset musí obsahovat aktivní ingredience A NAVÍC i neaktivní
        # (soft-smazané) ingredience, které stále mají zásobu na skladě –
        # ty je totiž potřeba umět odepsat (např. doprodej vyřazeného zboží).
        # Bez nich by výběr takové suroviny skončil chybou "Vyberte platnou
        # možnost". Omezení jen na sklad tu nepoužíváme (způsobilo by chybu
        # pro ID mimo queryset); dostupnost se validuje v clean().
        self.fields['ingredient'].queryset = Ingredient.objects.filter(
            Q(is_active=True) | Q(pk__in=StockItem.objects.values('ingredient'))
        ).order_by('name')

    def clean(self):
        cleaned_data = super().clean()

        if cleaned_data.get('DELETE'):
            return cleaned_data

        ingredient = cleaned_data.get('ingredient')
        quantity = cleaned_data.get('quantity')

        if self.warehouse and ingredient and quantity:
            try:
                stock_item = StockItem.objects.get(
                    ingredient=ingredient,
                    warehouse=self.warehouse
                )
                if stock_item.quantity < quantity:
                    raise ValidationError({
                        'quantity': (
                            f"Nedostatek {ingredient.name} na skladě. "
                            f"Dostupné: {stock_item.quantity} {ingredient.base_unit}, "
                            f"Požadováno: {quantity} {ingredient.base_unit}"
                        )
                    })
            except StockItem.DoesNotExist:
                raise ValidationError({
                    'ingredient': (
                        f"Surovina '{ingredient.name}' není dostupná "
                        f"ve skladu {self.warehouse}."
                    )
                })

        return cleaned_data


StockWriteOffItemFormSet = inlineformset_factory(
    StockWriteOff,
    StockWriteOffItem,
    form=StockWriteOffItemForm,
    extra=0,
    can_delete=True,
    min_num=1,
    validate_min=True,
)
