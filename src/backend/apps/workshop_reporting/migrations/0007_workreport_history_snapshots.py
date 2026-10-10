from django.db import migrations, models


def backfill_work_report_snapshots(apps, schema_editor):
    work_report = apps.get_model("workshop_reporting", "WorkReport")
    queryset = work_report.objects.select_related(
        "product_line__production_task", "scheme", "recorder_employee"
    )
    for report in queryset.iterator(chunk_size=500):
        task = report.product_line.production_task
        report.task_number_snapshot = task.task_number
        report.order_number_snapshot = task.order_number
        report.product_name_snapshot = report.scheme.product_name_snapshot
        report.product_number_snapshot = report.scheme.product_number_snapshot
        report.recorder_name_snapshot = report.recorder_employee.display_name
        report.save(update_fields=[
            "task_number_snapshot", "order_number_snapshot", "product_name_snapshot",
            "product_number_snapshot", "recorder_name_snapshot",
        ])


class Migration(migrations.Migration):
    dependencies = [("workshop_reporting", "0006_wagescheme_parent_version_unique")]

    operations = [
        migrations.AddField(
            model_name="workreport", name="task_number_snapshot",
            field=models.CharField(max_length=50, null=True),
        ),
        migrations.AddField(
            model_name="workreport", name="order_number_snapshot",
            field=models.CharField(max_length=100, null=True),
        ),
        migrations.AddField(
            model_name="workreport", name="product_name_snapshot",
            field=models.CharField(max_length=200, null=True),
        ),
        migrations.AddField(
            model_name="workreport", name="product_number_snapshot",
            field=models.CharField(max_length=100, null=True),
        ),
        migrations.AddField(
            model_name="workreport", name="recorder_name_snapshot",
            field=models.CharField(max_length=150, null=True),
        ),
        migrations.RunPython(backfill_work_report_snapshots, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="workreport", name="task_number_snapshot",
            field=models.CharField(max_length=50),
        ),
        migrations.AlterField(
            model_name="workreport", name="order_number_snapshot",
            field=models.CharField(max_length=100),
        ),
        migrations.AlterField(
            model_name="workreport", name="product_name_snapshot",
            field=models.CharField(max_length=200),
        ),
        migrations.AlterField(
            model_name="workreport", name="product_number_snapshot",
            field=models.CharField(max_length=100),
        ),
        migrations.AlterField(
            model_name="workreport", name="recorder_name_snapshot",
            field=models.CharField(max_length=150),
        ),
    ]
