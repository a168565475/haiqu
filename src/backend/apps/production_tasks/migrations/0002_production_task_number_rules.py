from django.db import migrations


NUMBER_RULES = (
    {
        "number_type": "PRODUCTION_TASK",
        "chinese_name": "生产任务单号",
        "prefix": "HT",
        "format_pattern": "{prefix}-{date}-{sequence}",
        "sequence_name": "haiqu_production_task_number_seq",
        "sequence_padding": 6,
        "date_granularity": "MONTH",
        "sort_order": 60,
    },
    {
        "number_type": "SALES_CONTRACT",
        "chinese_name": "销售合同编号",
        "prefix": "HTC",
        "format_pattern": "{prefix}-{date}-{sequence}",
        "sequence_name": "haiqu_sales_contract_number_seq",
        "sequence_padding": 6,
        "date_granularity": "MONTH",
        "sort_order": 61,
    },
)


def seed_number_rules(apps, schema_editor):
    number_rule = apps.get_model("reference_data", "NumberRule")
    for row in NUMBER_RULES:
        number_rule.objects.update_or_create(
            number_type=row["number_type"],
            defaults={
                **row,
                "status": "ACTIVE",
                "reset_policy": "NEVER",
                "is_configured": True,
            },
        )


def remove_number_rules(apps, schema_editor):
    number_rule = apps.get_model("reference_data", "NumberRule")
    number_rule.objects.filter(number_type__in=[row["number_type"] for row in NUMBER_RULES]).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("production_tasks", "0001_initial"),
        ("reference_data", "0022_seed_raw_material_category"),
    ]

    operations = [
        migrations.RunSQL(
            sql="CREATE SEQUENCE IF NOT EXISTS haiqu_production_task_number_seq;",
            reverse_sql="DROP SEQUENCE IF EXISTS haiqu_production_task_number_seq;",
        ),
        migrations.RunSQL(
            sql="CREATE SEQUENCE IF NOT EXISTS haiqu_sales_contract_number_seq;",
            reverse_sql="DROP SEQUENCE IF EXISTS haiqu_sales_contract_number_seq;",
        ),
        migrations.RunPython(seed_number_rules, remove_number_rules),
    ]
