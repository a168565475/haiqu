from django.db import migrations


def seed_schedule_number_rule(apps, schema_editor):
    number_rule = apps.get_model("reference_data", "NumberRule")
    number_rule.objects.update_or_create(
        number_type="PRODUCTION_SCHEDULE",
        defaults={
            "chinese_name": "生产排产单号",
            "prefix": "PC",
            "format_pattern": "{prefix}-{date}-{sequence}",
            "sequence_name": "haiqu_production_schedule_number_seq",
            "sequence_padding": 3,
            "date_granularity": "DAY",
            "reset_policy": "NEVER",
            "is_configured": True,
            "sort_order": 62,
            "status": "ACTIVE",
        },
    )


def remove_schedule_number_rule(apps, schema_editor):
    apps.get_model("reference_data", "NumberRule").objects.filter(
        number_type="PRODUCTION_SCHEDULE"
    ).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("production_scheduling", "0001_initial"),
        ("reference_data", "0026_number_rule_yearly_reset"),
    ]

    operations = [
        migrations.RunSQL(
            "CREATE SEQUENCE IF NOT EXISTS haiqu_production_schedule_number_seq START WITH 1 INCREMENT BY 1;",
            reverse_sql="DROP SEQUENCE IF EXISTS haiqu_production_schedule_number_seq;",
        ),
        migrations.RunPython(seed_schedule_number_rule, remove_schedule_number_rule),
    ]
