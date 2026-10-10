from django.db import migrations


NUMBER_RULES = (
    {
        "number_type": "SALES_ORDER",
        "chinese_name": "销售订单号",
        "prefix": "SO",
        "format_pattern": "{prefix}-{date}-{sequence}",
        "sequence_name": "haiqu_sales_order_number_seq",
        "sequence_padding": 6,
        "date_granularity": "MONTH",
        "sort_order": 58,
        "description": "销售订单号：SO-年月-六位全局流水。",
    },
    {
        "number_type": "PRODUCTION_ORDER",
        "chinese_name": "生产订单号",
        "prefix": "MO",
        "format_pattern": "{prefix}-{date}-{sequence}",
        "sequence_name": "haiqu_production_order_number_seq",
        "sequence_padding": 6,
        "date_granularity": "MONTH",
        "sort_order": 59,
        "description": "新销售订单链路生产订单号：MO-年月-六位全局流水；历史 HT 编号保持不变。",
    },
    {
        "number_type": "PURCHASE_REQUEST",
        "chinese_name": "采购申请号",
        "prefix": "PR",
        "format_pattern": "{prefix}-{date}-{sequence}",
        "sequence_name": "haiqu_purchase_request_number_seq",
        "sequence_padding": 6,
        "date_granularity": "MONTH",
        "sort_order": 64,
        "description": "采购申请号：PR-年月-六位全局流水。",
    },
)


def seed_number_rules(apps, schema_editor):
    number_rule = apps.get_model("reference_data", "NumberRule")
    for row in NUMBER_RULES:
        number_rule.objects.update_or_create(
            number_type=row["number_type"],
            defaults={**row, "status": "ACTIVE", "reset_policy": "NEVER", "is_configured": True},
        )


def remove_number_rules(apps, schema_editor):
    number_rule = apps.get_model("reference_data", "NumberRule")
    number_rule.objects.filter(number_type__in=[row["number_type"] for row in NUMBER_RULES]).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("sales_orders", "0001_initial"),
        ("reference_data", "0025_number_rule_daily_granularity"),
    ]

    operations = [
        migrations.RunSQL(
            sql="CREATE SEQUENCE IF NOT EXISTS haiqu_sales_order_number_seq;",
            reverse_sql="DROP SEQUENCE IF EXISTS haiqu_sales_order_number_seq;",
        ),
        migrations.RunSQL(
            sql="CREATE SEQUENCE IF NOT EXISTS haiqu_production_order_number_seq;",
            reverse_sql="DROP SEQUENCE IF EXISTS haiqu_production_order_number_seq;",
        ),
        migrations.RunSQL(
            sql="CREATE SEQUENCE IF NOT EXISTS haiqu_purchase_request_number_seq;",
            reverse_sql="DROP SEQUENCE IF EXISTS haiqu_purchase_request_number_seq;",
        ),
        migrations.RunPython(seed_number_rules, remove_number_rules),
    ]
