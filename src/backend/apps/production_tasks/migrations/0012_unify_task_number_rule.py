from django.db import migrations


RULE_DEFAULTS = {
    "prefix": "HT",
    "format_pattern": "{prefix}{short_year}{sequence}",
    "sequence_padding": 3,
    "date_granularity": "YEAR",
    "reset_policy": "NEVER",
    "is_configured": True,
    "status": "ACTIVE",
}


def apply_rule(apps, schema_editor):
    number_rule = apps.get_model("reference_data", "NumberRule")
    for number_type, chinese_name, sort_order in (
        ("PRODUCTION_ORDER", "生产任务单号（销售订单来源）", 59),
        ("PRODUCTION_TASK", "生产任务单号", 60),
    ):
        number_rule.objects.update_or_create(
            number_type=number_type,
            defaults={
                **RULE_DEFAULTS,
                "chinese_name": chinese_name,
                "sort_order": sort_order,
            },
        )


def restore_rule(apps, schema_editor):
    number_rule = apps.get_model("reference_data", "NumberRule")
    number_rule.objects.filter(number_type="PRODUCTION_ORDER").update(
        prefix="MO",
        format_pattern="{prefix}-{date}-{sequence}",
        sequence_padding=6,
        date_granularity="MONTH",
        chinese_name="生产订单号",
    )
    number_rule.objects.filter(number_type="PRODUCTION_TASK").update(
        prefix="HT",
        format_pattern="{prefix}-{date}-{sequence}",
        sequence_padding=6,
        date_granularity="MONTH",
        chinese_name="生产任务单号",
    )


class Migration(migrations.Migration):
    dependencies = [
        ("production_tasks", "0011_task_source_request_key"),
        ("sales_orders", "0004_salesorder_buyer_address"),
    ]

    operations = [migrations.RunPython(apply_rule, restore_rule)]
