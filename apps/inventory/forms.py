from decimal import Decimal
from django import forms
from django.forms import inlineformset_factory
from django.core.exceptions import ValidationError
from .models import GoodsReceipt, GoodsReceiptItem, Warehouse, Ingredient, InventoryVerification, InventoryVerificationItem

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


class GoodsReceiptItemForm(forms.ModelForm):
    """Formulář pro jednu položku příjmu zboží."""
    
    class Meta:
        model = GoodsReceiptItem
        fields = ['ingredient', 'warehouse', 'quantity', 'price_without_vat', 'vat_rate', 'notes']
        widgets = {
            'ingredient': forms.Select(attrs={'class': 'form-select', 'required': True}),
            'warehouse': forms.Select(attrs={'class': 'form-select warehouse-select', 'required': True}),
            'quantity': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.001', 'min': '0', 'required': True}),
            'price_without_vat': forms.NumberInput(attrs={
                'class': 'form-control price-without-vat', 
                'step': '0.01', 
                'min': '0', 
                'required': True,
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
            'vat_rate': 'DPH %',
            'notes': 'Poznámka',
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Nastavení choices pro DPH sazbu
        self.fields['vat_rate'] = forms.ChoiceField(
            choices=VAT_RATE_CHOICES,
            initial=Decimal('12'),  # Výchozí 12%
            required=True,
            label='DPH %',
            widget=forms.Select(attrs={
                'class': 'form-select vat-rate-select',
                'required': True,
                'onchange': 'calculateVAT(this)'
            })
        )
        # Označení povinných polí
        for field_name in ['ingredient', 'warehouse', 'quantity', 'price_without_vat', 'vat_rate']:
            if field_name in self.fields:
                self.fields[field_name].required = True


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
