from django.db import migrations


def register_supplier_payment_application_number_rule(apps, schema_editor):
    number_rule = apps.get_model("reference_data", "NumberRule")
    number_rule.objects.using(schema_editor.connection.alias).update_or_create(
        number_type="SUPPLIER_PAYMENT_APPLICATION",
        defaults={
            "chinese_name": "供应商付款申请编号",
            "prefix": "FKSQ",
            "format_pattern": "{prefix}{short_date}{sequence}",
            "sequence_name": "",
            "sequence_padding": 3,
            "date_granularity": "DAY",
            "reset_policy": "DAILY",
            "is_configured": True,
            "sort_order": 525,
            "description": "前缀FKSQ+YYMMDD+至少三位日流水；供应商付款申请提交时生成。",
        },
    )


class Migration(migrations.Migration):
    dependencies = [("reference_data", "0032_purchase_payable_number_rule")]

    operations = [migrations.RunPython(register_supplier_payment_application_number_rule, migrations.RunPython.noop)]
