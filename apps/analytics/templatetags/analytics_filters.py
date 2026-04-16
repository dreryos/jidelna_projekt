from django import template

register = template.Library()


@register.filter
def format_quantity(value, unit):
    """
    Formátuje množství podle jednotky:
    - Malé jednotky (g, ml, ks): 1 desetinné místo
    - Velké jednotky (kg, l, bal): 2 desetinná místa
    """
    try:
        value = float(value)
    except (ValueError, TypeError):
        return value

    if unit in ('g', 'ml', 'ks'):
        return f'{value:.1f}'
    else:
        return f'{value:.2f}'
