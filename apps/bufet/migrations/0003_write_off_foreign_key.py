"""BufetImport.write_off_id (holé celé číslo) -> ForeignKey na StockWriteOff.

Automaticky generovaná varianta by pole smazala (`RemoveField`) a založila
znovu (`AddField`), takže by u stávajících importů zmizela vazba na odepsání,
které import vytvořil. Proto se pole přejmenuje a změní jeho typ; sloupec
`write_off_id` v databázi zůstává a hodnoty v něm také.

Před změnou typu se vynulují odkazy na odepsání, která už neexistují. Odepsání
jde smazat (`StockWriteOffDeleteView`), takže po takovém smazání zůstalo v importu
číslo, které nikam nevede. Cizí klíč by na takové hodnotě migraci shodil.
"""

import django.db.models.deletion
from django.db import migrations, models


def null_dangling_write_offs(apps, schema_editor):
    BufetImport = apps.get_model('bufet', 'BufetImport')
    StockWriteOff = apps.get_model('inventory', 'StockWriteOff')
    (
        BufetImport.objects
        .filter(write_off_id__isnull=False)
        .exclude(write_off_id__in=StockWriteOff.objects.values('id'))
        .update(write_off_id=None)
    )


class Migration(migrations.Migration):

    dependencies = [
        ('bufet', '0002_remove_bufetimportitem_barcode_and_more'),
        ('inventory', '0028_create_real_suppliers'),
    ]

    operations = [
        migrations.RunPython(null_dangling_write_offs, migrations.RunPython.noop),
        migrations.RenameField(
            model_name='bufetimport',
            old_name='write_off_id',
            new_name='write_off',
        ),
        migrations.AlterField(
            model_name='bufetimport',
            name='write_off',
            field=models.ForeignKey(
                blank=True,
                help_text='Záznam StockWriteOff vytvořený při potvrzení importu',
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='bufet_imports',
                to='inventory.stockwriteoff',
                verbose_name='Odepsání ze skladu',
            ),
        ),
    ]
