from django.db import migrations


def populate_document_numbers(apps, schema_editor):
    """Vygeneruje čísla dokladů pro existující odpisy ve formátu YYMMDDHHMM."""
    StockWriteOff = apps.get_model('inventory', 'StockWriteOff')
    for wo in StockWriteOff.objects.filter(document_number=''):
        dt = wo.created_at
        wo.document_number = dt.strftime('%y%m%d%H%M')
        wo.save(update_fields=['document_number'])


class Migration(migrations.Migration):

    dependencies = [
        ('inventory', '0018_add_document_number_to_write_off'),
    ]

    operations = [
        migrations.RunPython(populate_document_numbers, migrations.RunPython.noop),
    ]
