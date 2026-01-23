from django import forms
from apps.core.models import Recipe, RecipeIngredient, Ingredient
from apps.core.widgets import DecimalFormField
from apps.core.constants import VAT_RATE_CHOICES

class RecipeIngredientForm(forms.ModelForm):
    """
    Formulář pro ingredience v receptu s vlastním widgetem pro desetinná čísla.
    """
    quantity_per_portion = DecimalFormField(
        label="Množství na 1 porci",
        help_text="",  # Help text moved to table header
        required=True,
    )
    
    class Meta:
        model = RecipeIngredient
        fields = ('ingredient', 'quantity_per_portion', 'notes')
        widgets = {
            'ingredient': forms.Select(attrs={'class': 'form-control'}),
            'notes': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Poznámka (volitelné)'}),
        }
        help_texts = {
            'notes': '',  # Help text moved to table header
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Filtrovat pouze aktivní suroviny v autocomplete
        self.fields['ingredient'].queryset = Ingredient.objects.filter(is_active=True)


class RecipeForm(forms.ModelForm):
    """
    Formulář pro recept.
    Kód receptu se generuje automaticky podle kategorie.
    """
    class Meta:
        model = Recipe
        fields = ['category', 'name', 'description', 'selling_vat_rate']
        widgets = {
            'category': forms.Select(attrs={'class': 'form-control', 'required': True}),
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'selling_vat_rate': forms.Select(
                choices=VAT_RATE_CHOICES,
                attrs={'class': 'form-control'}
            ),
        }
        help_texts = {
            'category': 'Vyberte kategorii - kód receptu se vygeneruje automaticky (např. PL-001, HJ-042)',
            'selling_vat_rate': 'Výchozí DPH sazba pro tento recept při prodeji (lze změnit při výrobě)',
        }


class IngredientForm(forms.ModelForm):
    """
    Formulář pro suroviny s podporou desetinných čísel pro conversion_factor.
    """
    conversion_factor = DecimalFormField(
        label="Převodní koeficient",
        help_text="Koeficient pro převod mezi receptovou a skladovou jednotkou (např. 1000 pro g→kg)",
        required=True,
    )
    
    class Meta:
        model = Ingredient
        fields = ['name', 'unit', 'base_unit', 'recipe_unit', 'conversion_factor']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'unit': forms.TextInput(attrs={'class': 'form-control'}),
            'base_unit': forms.TextInput(attrs={'class': 'form-control'}),
            'recipe_unit': forms.TextInput(attrs={'class': 'form-control'}),
        }

    def clean(self):
        data = super().clean()

        # Pokud uživatel změní pouze "unit" a nechá base_unit prázdnou,
        # synchronizujeme base_unit s unit pro lepší UX a zpětnou kompatibilitu.
        unit = data.get('unit')
        base_unit = data.get('base_unit')
        if unit and (not base_unit):
            data['base_unit'] = unit

        return data
