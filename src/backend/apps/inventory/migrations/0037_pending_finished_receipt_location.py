import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("inventory", "0036_purchase_return_weight_only")]

    operations = [
        migrations.AlterField(
            model_name="finishedgoodsreceipt",
            name="location",
            field=models.ForeignKey(
                blank=True, null=True, on_delete=django.db.models.deletion.PROTECT,
                related_name="finished_goods_receipts", to="inventory.warehouselocation",
            ),
        ),
        migrations.AddConstraint(
            model_name="finishedgoodsreceipt",
            constraint=models.CheckConstraint(
                condition=models.Q(location__isnull=False) | models.Q(status="PENDING", source_type="PRODUCTION_ORDER"),
                name="inv_receipt_confirmed_location",
            ),
        ),
    ]
