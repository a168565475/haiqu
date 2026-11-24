from django.db import migrations


def register_purchase_payable_number_rule(apps, schema_editor):
    number_rule = apps.get_model("reference_data", "NumberRule")
    number_rule.objects.using(schema_editor.connection.alias).update_or_create(
        number_type="PURCHASE_PAYABLE",
        defaults={
            "chinese_name": "采购应付编号",
            "prefix": "CGYF",
            "format_pattern": "{prefix}{short_date}{sequence}",
            "sequence_name": "",
            "sequence_padding": 3,
            "date_granularity": "DAY",
            "reset_policy": "DAILY",
            "is_configured": True,
            "sort_order": 520,
            "description": "前缀CGYF+YYMMDD+至少三位日流水；采购应付来源单确认后保留编号。",
        },
    )


class Migration(migrations.Migration):
    dependencies = [("reference_data", "0031_material_public_configuration")]

    operations = [migrations.RunPython(register_purchase_payable_number_rule, migrations.RunPython.noop)]
