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
    Supplier = apps.get_model('inventory', 'Supplier')

    for slug, name, ico in NOVI_DODAVATELE:
        Supplier.objects.get_or_create(
            slug=slug,
            defaults={
                'name': name,
                'ico': ico,
                'template_cache_key': f'supplier_template_{slug}',
                'is_active': True,
            },
        )


def smazat_dodavatele(apps, schema_editor):
    Supplier = apps.get_model('inventory', 'Supplier')
    Supplier.objects.filter(
        slug__in=[slug for slug, _, _ in NOVI_DODAVATELE]
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('inventory', '0027_goodsreceiptitem_unit_resolved_and_more'),
    ]

    operations = [
        migrations.RunPython(vytvorit_dodavatele, smazat_dodavatele),
    ]
