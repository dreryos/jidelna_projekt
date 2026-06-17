# Generated manually to make production_order nullable in PickingList model

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('production', '0018_add_cook_to_picking_list_document'),
    ]

    operations = [
        migrations.AlterField(
            model_name='pickinglist',
            name='production_order',
            field=models.ForeignKey(null=True, blank=True, on_delete=models.deletion.CASCADE, related_name='picking_list_items', to='production.productionorder', verbose_name='Výrobní příkaz'),
        ),
    ]