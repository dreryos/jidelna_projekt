from django import forms
from decimal import Decimal

class DecimalInputWidget(forms.NumberInput):
    """
    Widget pro zadávání desetinných čísel.
    HTML5 number input vyžaduje tečku jako desetinný oddělovač.
    Vstup přijímá jak čárku, tak tečku díky DecimalFormField.to_python().
    """
    
    def __init__(self, attrs=None):
        default_attrs = {
            'step': '0.001',  # Umožňuje zadat až 3 desetinná místa
            'class': 'form-control',
            'inputmode': 'decimal',
        }
        if attrs:
            default_attrs.update(attrs)
        super().__init__(attrs=default_attrs)
    
    def format_value(self, value):
        """
        Formátuje hodnotu pro zobrazení ve formuláři.
        HTML5 number input vyžaduje tečku jako desetinný oddělovač.
        """
        if value is None or value == '':
            return ''
        
        try:
            if not isinstance(value, Decimal):
                value = Decimal(str(value))
            
            # Formátování s maximálně 3 desetinnými místy bez exponenciálního zápisu
            str_value = f"{value:.3f}"
            
            # Odstranění zbytečných koncových nul
            if '.' in str_value:
                str_value = str_value.rstrip('0').rstrip('.')
            
            # HTML5 number input vyžaduje tečku jako desetinný oddělovač
            return str_value
        except (ValueError, TypeError, ArithmeticError):
            return super().format_value(value)


class DecimalFormField(forms.DecimalField):
    """
    Pole pro desetinná čísla s podporou české lokalizace.
    Přijímá čárku i tečku jako desetinný oddělovač.
    """
    widget = DecimalInputWidget
    
    def __init__(self, *args, **kwargs):
        # Nastavení výchozích hodnot pro max_digits a decimal_places
        if 'max_digits' not in kwargs:
            kwargs['max_digits'] = 10
        if 'decimal_places' not in kwargs:
            kwargs['decimal_places'] = 3
        
        super().__init__(*args, **kwargs)
    
    def to_python(self, value):
        """
        Převede hodnotu z formuláře na Python Decimal.
        Podporuje jak čárku, tak tečku jako desetinný oddělovač.
        """
        if value in self.empty_values:
            return None
        
        # Nahradí čárku tečkou pro parsování
        if isinstance(value, str):
            value = value.replace(',', '.').replace(' ', '')
        
        return super().to_python(value)
