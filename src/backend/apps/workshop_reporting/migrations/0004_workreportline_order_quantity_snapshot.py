from django.db import migrations, models


def backfill_order_quantity(apps, schema_editor):
    work_report_line = apps.get_model("workshop_reporting", "WorkReportLine")
    for line in work_report_line.objects.select_related("report__product_line").iterator(chunk_size=500):
        line.order_quantity_snapshot = line.report.product_line.quantity
        line.save(update_fields=["order_quantity_snapshot"])


class Migration(migrations.Migration):
    dependencies = [("workshop_reporting", "0003_alter_workitem_unit")]

    operations = [
        migrations.AddField(
            model_name="workreportline",
            name="order_quantity_snapshot",
            field=models.PositiveBigIntegerField(null=True),
        ),
        migrations.RunPython(backfill_order_quantity, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="workreportline",
            name="order_quantity_snapshot",
            field=models.PositiveBigIntegerField(),
        ),
    ]
