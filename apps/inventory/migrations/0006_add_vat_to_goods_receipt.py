# Generated migration for adding VAT fields to GoodsReceiptItem

from django.db import migrations, models
from decimal import Decimal


class Migration(migrations.Migration):

    dependencies = [
        ('inventory', '0005_goodsreceipt_goodsreceiptitem'),
    ]

    operations = [
        migrations.AddField(
            model_name='goodsreceiptitem',
            name='price_without_vat',
            field=models.DecimalField(
                blank=True,
                decimal_places=2,
                max_digits=10,
                null=True,
                verbose_name='Cena bez DPH za jednotku'
            ),
        ),
        migrations.AddField(
            model_name='goodsreceiptitem',
            name='vat_rate',
            field=models.DecimalField(
                decimal_places=2,
                default=Decimal('21.00'),
                max_digits=5,
                verbose_name='Sazba DPH (%)'
            ),
        ),
        migrations.AddField(
            model_name='goodsreceiptitem',
            name='vat_amount',
            field=models.DecimalField(
                blank=True,
                decimal_places=2,
                max_digits=10,
                null=True,
                verbose_name='Částka DPH za jednotku'
            ),
        ),
        migrations.AlterField(
            model_name='goodsreceiptitem',
            name='price',
            field=models.DecimalField(
                decimal_places=2,
                max_digits=10,
                verbose_name='Nákupní cena za jednotku (vč. DPH)'
            ),
        ),
    ]
