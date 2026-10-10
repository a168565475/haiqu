import django.core.validators
from django.db import migrations, models
from django.utils import timezone


def _temporary_numbers(PurchaseOrder):
    orders = list(PurchaseOrder.objects.order_by("created_at", "id"))
    for index, order in enumerate(orders, start=1):
        order.order_number = f"TMP-PURCHASE-{index:012d}"
    if orders:
        PurchaseOrder.objects.bulk_update(orders, ["order_number"])
    return orders


def apply_daily_purchase_numbers(apps, schema_editor):
    PurchaseOrder = apps.get_model("procurement", "PurchaseOrder")
    NumberRule = apps.get_model("reference_data", "NumberRule")
    orders = _temporary_numbers(PurchaseOrder)
    daily_counts = {}
    for order in orders:
        business_date = timezone.localtime(order.created_at).date()
        daily_counts[business_date] = daily_counts.get(business_date, 0) + 1
        daily_number = daily_counts[business_date]
        if daily_number > 99:
            raise RuntimeError(f"{business_date:%Y-%m-%d} 的采购订单超过 99 张，无法转换为两位当日流水。")
        order.order_number = f"CGDD{business_date:%Y%m%d}{daily_number:02d}"
    if orders:
        PurchaseOrder.objects.bulk_update(orders, ["order_number"])

    NumberRule.objects.filter(number_type="PURCHASE_ORDER").update(
        prefix="CGDD",
        format_pattern="{prefix}{date}{sequence}",
        sequence_padding=2,
        date_granularity="DAY",
        reset_policy="DAILY",
        description="采购订单号：CGDD+年月日+两位当日流水；每日从01开始，单日上限99张。",
    )


def restore_monthly_purchase_numbers(apps, schema_editor):
    PurchaseOrder = apps.get_model("procurement", "PurchaseOrder")
    NumberRule = apps.get_model("reference_data", "NumberRule")
    orders = _temporary_numbers(PurchaseOrder)
    for index, order in enumerate(orders, start=1):
        business_date = timezone.localtime(order.created_at).date()
        order.order_number = f"CG-{business_date:%Y%m}-{index:06d}"
    if orders:
        PurchaseOrder.objects.bulk_update(orders, ["order_number"])

    NumberRule.objects.filter(number_type="PURCHASE_ORDER").update(
        prefix="CG",
        format_pattern="{prefix}-{date}-{sequence}",
        sequence_padding=6,
        date_granularity="MONTH",
        reset_policy="NEVER",
        description="采购订单模块新建编号规则：CG-年月-六位全局流水；不是历史编号识别结果。",
    )


class Migration(migrations.Migration):
    dependencies = [
        ("procurement", "0002_purchase_orders"),
        ("reference_data", "0025_number_rule_daily_granularity"),
    ]

    operations = [
        migrations.AlterField(
            model_name="purchaseorder",
            name="order_number",
            field=models.CharField(
                max_length=50,
                unique=True,
                validators=[
                    django.core.validators.RegexValidator(
                        message="采购订单号必须是 CGDD 加 8 位日期和 2 位当日流水。",
                        regex="^CGDD[0-9]{8}[0-9]{2}$",
                    )
                ],
            ),
        ),
        migrations.RunPython(apply_daily_purchase_numbers, restore_monthly_purchase_numbers),
    ]
