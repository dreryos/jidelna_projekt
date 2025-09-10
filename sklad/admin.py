from django.contrib import admin
from .models import Surovina

@admin.register(Surovina)
class SurovinaAdmin(admin.ModelAdmin):
    """
    Nastavení pro zobrazení modelu Surovina v administraci.
    """
    list_display = ('nazev', 'aktualni_mnozstvi', 'jednotka', 'prumerna_nakupni_cena', 'posledni_aktualizace')
    list_filter = ('jednotka',)
    search_fields = ('nazev',)
    # Pole, která nelze přímo editovat v seznamu (množství se mění přes akce)
    readonly_fields = ('posledni_aktualizace',)