# Generated manually

from django.db import migrations

# Reální dodavatelé z produkčních dokladů (viz `inventory_goodsreceipt.supplier`
# – volný text z OCR/ručního zadání). Katalog `Supplier` dosud obsahoval jen
# interní placeholdery ze staré migrace (Zelinář, Pekárna, ...), takže se na
# skutečné dodávky nikdy nenapojil `find_supplier()` a naučené přepočty/aliasy
# (`SupplierItemAlias`) se pro ně vůbec neukládaly.
#
# IČO ověřené (Bolero Fruit z reálné OCR anotace v DB, ostatní zadal uživatel
# ručně podle rejstříku).
NOVI_DODAVATELE = [
    # slug, name, ico
    ('bidfood', 'Bidfood Czech Republic s.r.o.', '28234642'),
    ('makro-real', 'MAKRO Cash & Carry ČR s.r.o.', '26450691'),
    ('bolero-real', 'Bolero Fruit, Aleš Bolek', '68524358'),
    ('dk-open', 'DK OPEN, spol. s r.o.', '48200620'),
]


def vytvorit_dodavatele(apps, schema_editor):
    """
    `get_or_create(slug=...)` by nenašlo řádek, který už existuje pod jiným
    slugem se stejným (unikátním) `name` – vytvoření by pak spadlo na
    IntegrityError. A kdyby řádek pod tímhle slugem už existoval (ruční
    zásah, dřívější částečný deploy), `defaults` by se použily jen při
    vytvoření – chybějící IČO by zůstalo chybějící napořád.

    Proto se hledá napřed podle `name`, pak podle `slug`, a když se něco
    najde, aktualizují se všechna pole – ne jen doplní to, co chybí.
    """
    Supplier = apps.get_model('inventory', 'Supplier')

    for slug, name, ico in NOVI_DODAVATELE:
        supplier_data = {
            'name': name,
            'slug': slug,
            'ico': ico,
            'template_cache_key': f'supplier_template_{slug}',
            'is_active': True,
        }
        supplier = Supplier.objects.filter(name=name).first()
        if supplier is None:
            supplier = Supplier.objects.filter(slug=slug).first()
        if supplier is None:
            Supplier.objects.create(**supplier_data)
        else:
            Supplier.objects.filter(pk=supplier.pk).update(**supplier_data)


class Migration(migrations.Migration):

    dependencies = [
        ('inventory', '0027_goodsreceiptitem_unit_resolved_and_more'),
    ]

    operations = [
        # Vracet migraci smazáním podle slugu je nebezpečné – smazal by se
        # i řádek, který mezitím osídlily reálné příjemky nebo ruční úprava
        # (kaskádově i jeho aliasy a šablony surovin). Bez zpětné operace to
        # nejde bezpečně udělat, tak se rollback bere jako no-op.
        migrations.RunPython(vytvorit_dodavatele, migrations.RunPython.noop),
    ]
