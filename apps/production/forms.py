from django import forms
from django.forms import inlineformset_factory
from datetime import date, timedelta
from decimal import Decimal

from .models import MenuPlan, MenuPlanCoefficient
from apps.core.widgets import DecimalFormField


# ProductionOrderForm a ProductionOrderFormAdvanced byly odstraněny
# Výrobní příkazy se nyní vytvářejí pouze přes AJAX endpoint add_meal_to_menu


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
        # Extrahujeme user argument před voláním super().__init__
        user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        
        # Filtrujeme jídelny podle oprávnění uživatele
        if user:
            from apps.canteens.models import Canteen
            from django.core.exceptions import ObjectDoesNotExist
            
            if not user.is_superuser:
                try:
                    # Zobrazíme pouze jídelny přiřazené k uživateli
                    self.fields['canteen'].queryset = user.profile.canteens.all()
                except ObjectDoesNotExist:
                    # Pokud profil neexistuje, nezobrazíme žádné jídelny
                    self.fields['canteen'].queryset = Canteen.objects.none()
            else:
                # Superuživatel vidí všechny jídelny
                self.fields['canteen'].queryset = Canteen.objects.all()
        
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
