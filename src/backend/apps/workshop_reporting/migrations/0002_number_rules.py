from django.db import migrations


RULES = (
    ("WAGE_SCHEME", "工价方案编号", "GJ", "haiqu_wage_scheme_seq", 73),
    ("WORK_REPORT", "计件报工编号", "BG", "haiqu_work_report_seq", 74),
)


def seed_number_rules(apps, schema_editor):
    number_rule = apps.get_model("reference_data", "NumberRule")
    for number_type, chinese_name, prefix, sequence_name, sort_order in RULES:
        number_rule.objects.update_or_create(
            number_type=number_type,
            defaults={
                "chinese_name": chinese_name,
                "prefix": prefix,
                "format_pattern": "{prefix}-{date}-{sequence}",
                "sequence_name": sequence_name,
                "sequence_padding": 6,
                "date_granularity": "MONTH",
                "reset_policy": "NEVER",
                "is_configured": True,
                "sort_order": sort_order,
                "status": "ACTIVE",
                "description": "车间工价与计件报工模块正式业务编号。",
            },
        )


def remove_number_rules(apps, schema_editor):
    apps.get_model("reference_data", "NumberRule").objects.filter(
        number_type__in=[item[0] for item in RULES]
    ).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("workshop_reporting", "0001_initial"),
        ("reference_data", "0028_fill_supplemental_accessory_units"),
    ]

    operations = [
        migrations.RunSQL(
            "CREATE SEQUENCE IF NOT EXISTS haiqu_wage_scheme_seq START WITH 1 INCREMENT BY 1;",
            reverse_sql="DROP SEQUENCE IF EXISTS haiqu_wage_scheme_seq;",
        ),
        migrations.RunSQL(
            "CREATE SEQUENCE IF NOT EXISTS haiqu_work_report_seq START WITH 1 INCREMENT BY 1;",
            reverse_sql="DROP SEQUENCE IF EXISTS haiqu_work_report_seq;",
        ),
        migrations.RunPython(seed_number_rules, remove_number_rules),
    ]
