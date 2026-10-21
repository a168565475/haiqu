import django.core.validators
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("procurement", "0021_purchaseorderline_material_attributes"),
        ("reference_data", "0029_shared_daily_number_rules"),
    ]

    operations = [
        migrations.AlterField(
            model_name="purchaseorder",
            name="order_number",
            field=models.CharField(
                max_length=50, unique=True,
                validators=[django.core.validators.RegexValidator(
                    regex=r"^CGDD(?:[0-9]{6}[0-9]{3,40}|[0-9]{8}[0-9]{2,38})$",
                    message="采购订单号必须是 CGDD 加 6 位日期和至少 3 位流水，兼容历史 8 位日期和至少 2 位流水，总长不超过 50 位。",
                )],
            ),
        ),
        migrations.AlterField(
            model_name="supplierpurchasesheet",
            name="sheet_number",
            field=models.CharField(
                max_length=50,
                validators=[django.core.validators.RegexValidator(
                    regex=r"^CGDD(?:[0-9]{6}[0-9]{3,40}|[0-9]{8}[0-9]{2,38})$",
                    message="采购表编号必须是 CGDD 加 6 位日期和至少 3 位流水，兼容历史 8 位日期和至少 2 位流水，总长不超过 50 位。",
                )],
            ),
        ),
    ]
