from django import forms
from apps.core.models import Recipe, RecipeIngredient, Ingredient
from apps.core.widgets import DecimalFormField

class RecipeIngredientForm(forms.ModelForm):
    """
    Formulář pro ingredience v receptu s vlastním widgetem pro desetinná čísla.
    """
    quantity_per_portion = DecimalFormField(
        label="Množství na 1 porci",
        help_text="Množství suroviny na 1 porci v receptových jednotkách (např. gramy)",
        required=True,
    )
    
    class Meta:
        model = RecipeIngredient
        fields = ('ingredient', 'quantity_per_portion', 'notes')
        widgets = {
            'ingredient': forms.Select(attrs={'class': 'form-control'}),
            'notes': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Poznámka (volitelné)'}),
        }


class RecipeForm(forms.ModelForm):
    """
    Formulář pro recept.
    """
    class Meta:
        model = Recipe
        fields = ['code', 'name', 'category', 'description', 'base_portions']
        widgets = {
            'code': forms.TextInput(attrs={'class': 'form-control'}),
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'category': forms.Select(attrs={'class': 'form-control'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'base_portions': forms.NumberInput(attrs={'class': 'form-control', 'min': 1}),
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
