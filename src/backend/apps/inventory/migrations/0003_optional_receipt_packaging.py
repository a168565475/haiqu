import django.core.validators
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("inventory", "0002_finished_goods_sequences")]

    operations = [
        migrations.RemoveConstraint(
            model_name="finishedgoodsreceipt",
            name="inv_receipt_pack_positive",
        ),
        migrations.AlterField(
            model_name="finishedgoodsreceipt",
            name="quantity_per_box",
            field=models.PositiveBigIntegerField(
                blank=True,
                null=True,
                validators=[django.core.validators.MinValueValidator(1)],
            ),
        ),
        migrations.AlterField(
            model_name="finishedgoodsreceipt",
            name="box_count",
            field=models.PositiveBigIntegerField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name="finishedgoodsreceipt",
            name="tail_quantity",
            field=models.PositiveBigIntegerField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name="finishedgoodsreceipt",
            name="occupied_box_slots",
            field=models.PositiveBigIntegerField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name="finishedgoodsreceipt",
            name="remaining_box_slots",
            field=models.PositiveBigIntegerField(blank=True, null=True),
        ),
        migrations.AddConstraint(
            model_name="finishedgoodsreceipt",
            constraint=models.CheckConstraint(
                condition=models.Q(quantity_per_box__isnull=True) | models.Q(quantity_per_box__gt=0),
                name="inv_receipt_pack_positive",
            ),
        ),
    ]
