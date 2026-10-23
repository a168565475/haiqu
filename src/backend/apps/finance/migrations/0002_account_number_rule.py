from django.db import migrations


def register_rule(apps, schema_editor):
    apps.get_model("reference_data", "NumberRule").objects.using(schema_editor.connection.alias).get_or_create(
        number_type="FINANCE_ACCOUNT", defaults={
            "chinese_name": "公司账户编号", "prefix": "ZH", "format_pattern": "{prefix}{short_date}{sequence}",
            "sequence_padding": 3, "date_granularity": "DAY", "reset_policy": "DAILY", "is_configured": True,
            "sort_order": 500, "description": "前缀ZH+YYMMDD+至少三位日流水；原表编码保留；成功删除不回退。",
        })


class Migration(migrations.Migration):
    dependencies = [("finance", "0001_initial")]
    operations = [migrations.RunPython(register_rule, migrations.RunPython.noop)]
