def get_int_param(request, name):
    """Bezpečně přečte celočíselný GET parametr (pk/FK filtr).

    Chybějící i nečíselná hodnota (např. ``?warehouse=x``) vrátí ``None`` –
    filtr se tváří jako nezadaný. Bez toho ORM vyhodí ``ValueError`` a stránka
    skončí HTTP 500.
    """
    value = request.GET.get(name, '').strip()
    return int(value) if value.isascii() and value.isdigit() else None


def get_int_list_param(request, name):
    """Jako ``get_int_param``, ale pro opakovaný parametr (``?a=1&a=2``); nečíselné hodnoty vypustí."""
    return [int(v) for v in request.GET.getlist(name) if v.strip().isascii() and v.strip().isdigit()]
