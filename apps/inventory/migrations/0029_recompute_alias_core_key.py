"""Přepočet `SupplierItemAlias.core_key` podle upraveného čištění názvů.

`core_name()` se naučilo odstraňovat čárové kódy (`GTIN: …`), balení zapsané
hvězdičkou (`4*500G`) a samostatné jednotky a sjednocovat zkratky (`SYNONYMS`). `core_key` se ukládá při vzniku
aliasu, takže u starších aliasů je v tabulce klíč podle dřívějších pravidel
a hledání podle nového klíče by je netrefilo.

Po změně `SYNONYMS` nebo pravidel v `naming.py` je potřeba další takováto
migrace (klíče se ukládají, nepočítají za běhu).

Mění se jen odvozený sloupec, `raw_key` ani vazby na suroviny se nedotýkají.
Zpětná migrace klíče **neobnoví**: staré pravidlo v kódu už neexistuje, takže
není z čeho počítat (kód migrace běží vždy s dnešním `core_name()`). Po návratu
na starší verzi aplikace proto přestanou hledání podle `core_key` trefovat
přepočtené aliasy; přesná shoda podle `raw_key` jede dál. Napravuje to
`SupplierItemAlias.save()` ve starší verzi, které klíč počítá znovu:

    for a in SupplierItemAlias.objects.all(): a.save()

Zpětná migrace tuhle instrukci vypíše. Ostrý chod nemá souběžné verze: aplikace
je jeden kontejner a `migrate` běží v entrypointu před startem serveru, takže
okno, kdy starý kód čte nové klíče, je v řádu sekund.
"""
from django.db import migrations

from apps.inventory.naming import core_name


def recompute(apps, schema_editor):
    SupplierItemAlias = apps.get_model('inventory', 'SupplierItemAlias')
    changed = 0
    for alias in SupplierItemAlias.objects.all().iterator():
        new_key = core_name(alias.raw_name)
        if new_key != alias.core_key:
            SupplierItemAlias.objects.filter(pk=alias.pk).update(core_key=new_key)
            changed += 1
    if changed:
        print(f'\n  inventory: přepočten core_key u {changed} aliasů', end='')


def warn_on_reverse(apps, schema_editor):
    print(
        '\n  inventory: core_key aliasů zůstává podle nových pravidel. Po návratu '
        'na starší verzi je přepočítejte: '
        'for a in SupplierItemAlias.objects.all(): a.save()',
        end='',
    )


class Migration(migrations.Migration):

    dependencies = [
        ('inventory', '0028_create_real_suppliers'),
    ]

    operations = [
        migrations.RunPython(recompute, warn_on_reverse),
    ]
