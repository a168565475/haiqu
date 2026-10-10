import django.core.validators
from django.db import migrations, models


def update_purchase_number_description(apps, schema_editor):
    NumberRule = apps.get_model("reference_data", "NumberRule")
    NumberRule.objects.using(schema_editor.connection.alias).filter(
        number_type="PURCHASE_ORDER"
    ).update(
        description=(
            "采购订单与供应商采购表共用编号：CGDD+年月日+至少两位当日流水；"
            "每日从01开始，超过99继续100、101，流水最多38位；历史编号保持不变。"
        )
    )


class Migration(migrations.Migration):
    dependencies = [
        ("procurement", "0019_pipe_purchase_constraints"),
    ]

    operations = [
        migrations.AlterField(
            model_name="purchaseorder",
            name="order_number",
            field=models.CharField(
                max_length=50,
                unique=True,
                validators=[django.core.validators.RegexValidator(
                    regex=r"^CGDD[0-9]{8}[0-9]{2,38}$",
                    message="采购订单号必须是 CGDD 加 8 位日期和 2 至 38 位当日流水。",
                )],
            ),
        ),
        migrations.AlterField(
            model_name="supplierpurchasesheet",
            name="sheet_number",
            field=models.CharField(
                max_length=50,
                validators=[django.core.validators.RegexValidator(
                    regex=r"^CGDD[0-9]{8}[0-9]{2,38}$",
                    message="采购表编号必须是 CGDD 加 8 位日期和 2 至 38 位当日流水。",
                )],
            ),
        ),
        # 已有三位及以上编号不能退回旧校验；本迁移只支持向前应用。
        migrations.RunPython(update_purchase_number_description),
    ]
