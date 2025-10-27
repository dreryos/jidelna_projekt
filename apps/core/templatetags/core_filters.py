from django import template
from decimal import Decimal

register = template.Library()

@register.filter(name='format_decimal')
def format_decimal(value, decimal_places=None):
    """
    Formátuje desetinné číslo - odstraní zbytečné nuly a použije čárku jako oddělovač.
    Zachová až 3 desetinná místa, pokud jsou neprázdná, nebo použije zadaný počet.
    
    Použití:
        {{ value|format_decimal }}  - automaticky odstraní koncové nuly
        {{ value|format_decimal:2 }}  - zobrazí přesně 2 desetinná místa
    """
    if value is None or value == '':
        return ''
    
    try:
        # Převedení na Decimal pro přesnou práci s čísly
        if not isinstance(value, Decimal):
            value = Decimal(str(value))
        
        if decimal_places is not None:
            # Zaokrouhlení na požadovaný počet míst
            quantizer = Decimal('0.1') ** int(decimal_places)
            value = value.quantize(quantizer)
            result = f"{value:.{decimal_places}f}"
        else:
            # Formátování bez exponenciálního zápisu
            # Zjistíme, kolik desetinných míst skutečně potřebujeme
            str_value = str(value)
            if 'E' in str_value or 'e' in str_value:
                # Pokud je v exponenciálním tvaru, převedeme na normální zápis
                # s maximálně 3 desetinnými místy
                result = f"{value:.3f}"
            else:
                # Normalizace pro odstranění koncových nul
                normalized = value.normalize()
                result = str(normalized)
                # Pokud je stále v exponenciálním tvaru, převedeme
                if 'E' in result or 'e' in result:
                    result = f"{value:.3f}"
            
            # Odstranění zbytečných koncových nul
            if '.' in result:
                result = result.rstrip('0').rstrip('.')
        
        # Nahrazení tečky čárkou
        result = result.replace('.', ',')
        
        return result
    except (ValueError, TypeError, ArithmeticError):
        return value


@register.filter(name='format_price')
def format_price(value):
    """
    Formátuje cenu - vždy zobrazí 2 desetinná místa s čárkou.
    
    Použití:
        {{ value|format_price }}
    """
    if value is None or value == '':
        return '0,00'
    
    try:
        if not isinstance(value, Decimal):
            value = Decimal(str(value))
        
        # Zaokrouhlení na 2 desetinná místa
        value = value.quantize(Decimal('0.01'))
        
        return f"{value:.2f}".replace('.', ',')
    except (ValueError, TypeError, ArithmeticError):
        return value
