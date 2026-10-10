from django.db import migrations


def register_return_number(apps, schema_editor):
    NumberRule = apps.get_model("reference_data", "NumberRule")
    NumberRule.objects.using(schema_editor.connection.alias).get_or_create(
        number_type="PURCHASE_RETURN",
        defaults={
            "chinese_name": "采购退货单", "prefix": "TH", "format_pattern": "{prefix}-{date}-{sequence}",
            "sequence_name": "haiqu_purchase_return_number_seq", "date_granularity": "MONTH",
            "sequence_padding": 6, "reset_policy": "NEVER", "is_configured": True,
        },
    )


class Migration(migrations.Migration):
    dependencies = [("procurement", "0013_purchase_completion_and_returns")]
    operations = [
        migrations.RunSQL("CREATE SEQUENCE IF NOT EXISTS haiqu_purchase_return_number_seq START WITH 1", reverse_sql=migrations.RunSQL.noop),
        migrations.RunPython(register_return_number, reverse_code=migrations.RunPython.noop),
    ]
