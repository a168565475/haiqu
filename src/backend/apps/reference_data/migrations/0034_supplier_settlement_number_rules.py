from django.db import migrations


def register_supplier_settlement_number_rules(apps, schema_editor):
    rules = apps.get_model("reference_data", "NumberRule").objects.using(schema_editor.connection.alias)
    for number_type, name, prefix, order in (
        ("SUPPLIER_PAYMENT", "供应商实付编号", "GYFK", 526),
        ("SUPPLIER_OFFSET", "供应商抵账编号", "GYDZ", 527),
    ):
        rules.update_or_create(number_type=number_type, defaults={
            "chinese_name": name, "prefix": prefix, "format_pattern": "{prefix}{short_date}{sequence}",
            "sequence_name": "", "sequence_padding": 3, "date_granularity": "DAY", "reset_policy": "DAILY",
            "is_configured": True, "sort_order": order, "description": f"前缀{prefix}+YYMMDD+至少三位日流水。",
        })


class Migration(migrations.Migration):
    dependencies = [("reference_data", "0033_supplier_payment_application_number_rule")]

    operations = [migrations.RunPython(register_supplier_settlement_number_rules, migrations.RunPython.noop)]
