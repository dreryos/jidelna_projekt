from django import forms
from django.forms import inlineformset_factory
from datetime import date, timedelta
from decimal import Decimal

from .models import ProductionOrder, MenuPlan, MenuPlanCoefficient
from apps.core.widgets import DecimalFormField


class ProductionOrderForm(forms.ModelForm):
    """
    Formulář pro vytvoření/úpravu výrobního příkazu.
    Podporuje novou strukturu s koeficientem porce.
    """
    
    # Celkový počet porcí (součet dospělých a dětských)
    total_portions = forms.IntegerField(
        label="Celkový počet porcí",
        min_value=1,
        required=True,
        widget=forms.NumberInput(attrs={
            'class': 'form-control',
            'placeholder': 'Zadejte celkový počet porcí'
        }),
        help_text="Celkový počet porcí (všechny typy dohromady)"
    )
    
    # Koeficient velikosti porce s custom widgetem
    portion_coefficient = DecimalFormField(
        label="Koeficient velikosti porce",
        required=True,
        initial=Decimal('1.0'),
        help_text="1.0 = normální porce, 0.5 = poloviční, 1.5 = větší, atd.",
        widget=forms.NumberInput(attrs={
            'class': 'form-control',
            'step': '0.01',
            'min': '0.1',
            'max': '5.0',
            'placeholder': '1,0'
        })
    )
    
    class Meta:
        model = ProductionOrder
        fields = ['recipe', 'canteen', 'date', 'portion_coefficient']
        widgets = {
            'recipe': forms.Select(attrs={'class': 'form-control'}),
            'canteen': forms.Select(attrs={'class': 'form-control'}),
            'date': forms.DateInput(attrs={
                'type': 'date',
                'class': 'form-control',
                'min': date.today().strftime('%Y-%m-%d')
            }),
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['recipe'].empty_label = "Vyberte recept"
        self.fields['canteen'].empty_label = "Vyberte jídelnu"
        
        # Nastavíme výchozí datum na zítra
        if not self.instance.pk:
            self.fields['date'].initial = date.today() + timedelta(days=1)
            self.fields['total_portions'].initial = 50
        else:
            # Při editaci načteme total_portions
            self.fields['total_portions'].initial = self.instance.total_portions
    
    def save(self, commit=True):
        instance = super().save(commit=False)
        
        # Nastavíme portions_adult na celkový počet porcí
        # portions_child necháme na 0 (jen pro zpětnou kompatibilitu)
        instance.portions_adult = self.cleaned_data['total_portions']
        instance.portions_child = 0
        
        if commit:
            instance.save()
        
        return instance


class ProductionOrderFormAdvanced(forms.ModelForm):
    """
    Rozšířený formulář pro výrobní příkazy s možností zadání 
    dospělých a dětských porcí zvlášť (s různými koeficienty).
    """
    
    portions_adult = forms.IntegerField(
        label="Počet dospělých porcí",
        min_value=0,
        required=False,
        initial=0,
        widget=forms.NumberInput(attrs={
            'class': 'form-control',
            'placeholder': 'Počet dospělých porcí'
        })
    )
    
    portions_child = forms.IntegerField(
        label="Počet dětských porcí",
        min_value=0,
        required=False,
        initial=0,
        widget=forms.NumberInput(attrs={
            'class': 'form-control',
            'placeholder': 'Počet dětských porcí'
        })
    )
    
    portion_coefficient = DecimalFormField(
        label="Koeficient velikosti porce",
        required=True,
        initial=Decimal('1.0'),
        help_text="Koeficient se aplikuje na všechny porce (dospělé i dětské)",
        widget=forms.NumberInput(attrs={
            'class': 'form-control',
            'step': '0.01',
            'min': '0.1',
            'max': '5.0',
            'placeholder': '1,0'
        })
    )
    
    class Meta:
        model = ProductionOrder
        fields = ['recipe', 'canteen', 'date', 'portions_adult', 'portions_child', 'portion_coefficient']
        widgets = {
            'recipe': forms.Select(attrs={'class': 'form-control'}),
            'canteen': forms.Select(attrs={'class': 'form-control'}),
            'date': forms.DateInput(attrs={
                'type': 'date',
                'class': 'form-control',
                'min': date.today().strftime('%Y-%m-%d')
            }),
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['recipe'].empty_label = "Vyberte recept"
        self.fields['canteen'].empty_label = "Vyberte jídelnu"
        
        # Nastavíme výchozí datum na zítra
        if not self.instance.pk:
            self.fields['date'].initial = date.today() + timedelta(days=1)
    
    def clean(self):
        cleaned_data = super().clean()
        portions_adult = cleaned_data.get('portions_adult', 0) or 0
        portions_child = cleaned_data.get('portions_child', 0) or 0
        
        if portions_adult + portions_child == 0:
            raise forms.ValidationError(
                "Musíte zadat alespoň jednu porci (dospělou nebo dětskou)."
            )
        
        return cleaned_data


class MenuPlanForm(forms.ModelForm):
    """Formulář pro vytvoření/úpravu jídelníčku - pouze základní údaje"""
    
    default_total_portions = forms.IntegerField(
        label="Výchozí počet porcí",
        min_value=1,
        initial=50,
        required=True,
        widget=forms.NumberInput(attrs={
            'class': 'form-control',
            'placeholder': 'Zadejte výchozí počet porcí'
        }),
        help_text="Tento počet bude automaticky předvyplněn při přidávání jídel"
    )
    
    class Meta:
        model = MenuPlan
        fields = ['name', 'canteen', 'date_from', 'date_to']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'canteen': forms.Select(attrs={'class': 'form-control'}),
            'date_from': forms.DateInput(attrs={
                'type': 'date',
                'class': 'form-control',
                'min': date.today().strftime('%Y-%m-%d')
            }),
            'date_to': forms.DateInput(attrs={
                'type': 'date',
                'class': 'form-control',
                'min': date.today().strftime('%Y-%m-%d')
            }),
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['canteen'].empty_label = "Vyberte jídelnu"
        
        # Nastavíme výchozí data
        if not self.instance.pk:
            self.fields['date_from'].initial = date.today() + timedelta(days=1)
            self.fields['date_to'].initial = date.today() + timedelta(days=7)
        else:
            # Při editaci načteme výchozí počet porcí
            self.fields['default_total_portions'].initial = (
                self.instance.default_portions_adult + self.instance.default_portions_child
            )
    
    def save(self, commit=True):
        instance = super().save(commit=False)
        
        # Uložíme výchozí počet porcí do polí pro zpětnou kompatibilitu
        total = self.cleaned_data['default_total_portions']
        instance.default_portions_adult = total
        instance.default_portions_child = 0
        
        if commit:
            instance.save()
        
        return instance
    
    def clean(self):
        cleaned_data = super().clean()
        date_from = cleaned_data.get('date_from')
        date_to = cleaned_data.get('date_to')
        
        if date_from and date_to and date_to < date_from:
            raise forms.ValidationError(
                "Datum konce nemůže být před datem začátku."
            )
        
        return cleaned_data


class MenuPlanCoefficientForm(forms.ModelForm):
    """Formulář pro jeden výchozí koeficient"""
    
    coefficient = DecimalFormField(
        label="Koeficient",
        required=True,
        initial=Decimal('1.0'),
        widget=forms.NumberInput(attrs={
            'class': 'form-control',
            'step': '0.01',
            'min': '0.1',
            'max': '5.0',
            'placeholder': '1,0'
        })
    )
    
    class Meta:
        model = MenuPlanCoefficient
        fields = ['name', 'coefficient', 'order']
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Např. "Normální porce"'
            }),
            'order': forms.NumberInput(attrs={
                'class': 'form-control',
                'min': '0',
                'placeholder': '0'
            })
        }


# Formset pro správu koeficientů v rámci jídelníčku
MenuPlanCoefficientFormSet = inlineformset_factory(
    MenuPlan,
    MenuPlanCoefficient,
    form=MenuPlanCoefficientForm,
    extra=1,  # Výchozí počet prázdných formulářů
    can_delete=True,
    min_num=1,  # Minimálně jeden koeficient musí být
    validate_min=True,
    max_num=10  # Maximum 10 koeficientů pro rozumnost
)
