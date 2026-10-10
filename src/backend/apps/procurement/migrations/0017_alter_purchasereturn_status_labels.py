from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("procurement", "0016_purchase_order_purchasing"),
    ]

    operations = [
        migrations.AlterField(
            model_name="purchasereturn",
            name="status",
            field=models.CharField(
                choices=[
                    ("QUALITY_GENERATED", "品质生成 · 待确认退货"),
                    ("PROCUREMENT_CONFIRMED", "已确认退货 · 待退货完成"),
                    ("COMPLETED", "退货完成"),
                ],
                default="QUALITY_GENERATED",
                max_length=30,
            ),
        ),
    ]
