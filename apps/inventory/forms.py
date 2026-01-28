from decimal import Decimal
from django import forms
from django.forms import inlineformset_factory
from django.core.exceptions import ValidationError
from .models import (
    GoodsReceipt, GoodsReceiptItem, Warehouse, Ingredient, 
    InventoryVerification, InventoryVerificationItem,
    StockTransfer, StockTransferItem, StockItem,
    StockWriteOff, StockWriteOffItem
)

# České DPH sazby platné v roce 2026
VAT_RATE_CHOICES = [
    (Decimal('21'), '21%'),
    (Decimal('12'), '12%'),
    (Decimal('0'), '0%'),
]


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
            'receipt_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
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
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
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
            'price': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'min': '0'}),
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
            'price_without_vat': forms.NumberInput(attrs={
                'class': 'form-control price-without-vat', 
                'step': '0.01', 
                'min': '0', 
                'onchange': 'calculateVAT(this)'
            }),
            'price': forms.NumberInput(attrs={
                'class': 'form-control price-with-vat',
                'step': '0.01',
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
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Filtrovat pouze aktivní suroviny
        from apps.core.models import Ingredient
        self.fields['ingredient'].queryset = Ingredient.objects.filter(is_active=True)
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
    
    def clean_warehouse(self):
        warehouse = self.cleaned_data.get('warehouse')
        
        if warehouse and warehouse.is_locked:
            raise ValidationError(
                f"Sklad '{warehouse.name}' je již uzamčen kvůli probíhající inventuře "
                f"zahájené {warehouse.locked_by_inventory.started_by.get_full_name() or warehouse.locked_by_inventory.started_by.username} "
                f"dne {warehouse.locked_by_inventory.started_at.strftime('%d.%m.%Y %H:%M')}."
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
                'min': '0',
                'required': True
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
        self.fields['ingredient'].queryset = Ingredient.objects.filter(is_active=True)


# Formset pro položky inventury
InventoryVerificationItemFormSet = inlineformset_factory(
    InventoryVerification,
    InventoryVerificationItem,
    form=InventoryVerificationItemForm,
    extra=1,  # 1 prázdný formulář pro přidání nové suroviny
    min_num=0,
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
            'transfer_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }
        labels = {
            'warehouse_from': 'Ze skladu',
            'warehouse_to': 'Do skladu',
            'transfer_date': 'Datum převodu',
            'notes': 'Poznámky',
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Odfiltrovat mezisklady - nelze je vybrat jako source nebo target
        self.fields['warehouse_from'].queryset = Warehouse.objects.filter(is_transit_warehouse=False)
        self.fields['warehouse_to'].queryset = Warehouse.objects.filter(is_transit_warehouse=False)
    
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
                'onchange': 'loadIngredientPrice(this)'
            }),
            'quantity': forms.NumberInput(attrs={
                'class': 'form-control',
                'step': '0.001',
                'min': '0',
                'required': True
            }),
            'unit_price_with_vat': forms.NumberInput(attrs={
                'class': 'form-control unit-price',
                'step': '0.01',
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
        
        # Filtrovat pouze aktivní suroviny
        from apps.core.models import Ingredient
        self.fields['ingredient'].queryset = Ingredient.objects.filter(is_active=True)
        
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
                    raise ValidationError({
                        'quantity': f"Nedostatečné množství. Dostupné: {stock_item.quantity_available} {ingredient.base_unit}"
                    })
                
                # Automaticky nastavit cenu ze skladu pokud není zadána
                if not cleaned_data.get('unit_price_with_vat'):
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
    max_num=100,  # Maximum 100 položek
    can_delete=True,  # Možnost smazání položky
)


class StockWriteOffForm(forms.ModelForm):
    """Formulář pro vytvoření odepsání mimo recepty."""
    
    class Meta:
        model = StockWriteOff
        fields = ['warehouse', 'category', 'write_off_date', 'notes']
        widgets = {
            'warehouse': forms.Select(attrs={'class': 'form-select'}),
            'category': forms.Select(attrs={'class': 'form-select'}),
            'write_off_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }
        labels = {
            'warehouse': 'Sklad',
            'category': 'Kategorie',
            'write_off_date': 'Datum odepisování',
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
        
        if warehouse:
            available_ingredients = StockItem.objects.filter(
                warehouse=warehouse,
                quantity__gt=0
            ).values_list('ingredient_id', flat=True)
            self.fields['ingredient'].queryset = Ingredient.objects.filter(
                id__in=available_ingredients
            ).order_by('name')


StockWriteOffItemFormSet = inlineformset_factory(
    StockWriteOff,
    StockWriteOffItem,
    form=StockWriteOffItemForm,
    extra=0,
    can_delete=True,
    min_num=1,
    validate_min=True,
)
