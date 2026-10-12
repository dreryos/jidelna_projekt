"""Přepočet `SupplierItemAlias.core_key` podle upraveného čištění názvů.

`core_name()` se naučilo odstraňovat čárové kódy (`GTIN: …`), balení zapsané
hvězdičkou (`4*500G`) a samostatné jednotky a sjednocovat zkratky (`SYNONYMS`). `core_key` se ukládá při vzniku
aliasu, takže u starších aliasů je v tabulce klíč podle dřívějších pravidel
a hledání podle nového klíče by je netrefilo.

Po změně `SYNONYMS` nebo pravidel v `naming.py` je potřeba další takováto
migrace (klíče se ukládají, nepočítají za běhu).

Mění se jen odvozený sloupec, `raw_key` ani vazby na suroviny se nedotýkají.
Zpětná migrace je prázdná: starý tvar klíče už nic nepoužívá.
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


class Migration(migrations.Migration):

    dependencies = [
        ('inventory', '0028_create_real_suppliers'),
    ]

    operations = [
        migrations.RunPython(recompute, migrations.RunPython.noop),
    ]
