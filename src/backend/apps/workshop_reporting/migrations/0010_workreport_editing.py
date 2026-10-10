from django.db import migrations, models
import django.db.models.deletion


def backfill_updated_by(apps, schema_editor):
    work_report = apps.get_model("workshop_reporting", "WorkReport")
    work_report.objects.filter(updated_by_employee__isnull=True).update(
        updated_by_employee_id=models.F("recorder_employee_id")
    )


class Migration(migrations.Migration):
    dependencies = [("workshop_reporting", "0009_wagescheme_single_version_chain")]

    operations = [
        migrations.AddField(
            model_name="workreport",
            name="revision",
            field=models.PositiveIntegerField(default=1),
        ),
        migrations.AddField(
            model_name="workreport",
            name="updated_by_employee",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="updated_work_reports",
                to="organizations.employee",
            ),
        ),
        migrations.RunPython(backfill_updated_by, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="workreport",
            name="updated_by_employee",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="updated_work_reports",
                to="organizations.employee",
            ),
        ),
        migrations.AddConstraint(
            model_name="workreport",
            constraint=models.CheckConstraint(
                condition=models.Q(("revision__gt", 0)),
                name="work_report_revision_positive",
            ),
        ),
    ]
