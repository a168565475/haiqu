import django.contrib.postgres.constraints
import django.contrib.postgres.fields.ranges
from django.contrib.postgres.operations import BtreeGistExtension
from django.db import migrations, models


def assert_no_approved_scope_overlap(apps, schema_editor):
    wage_scheme = apps.get_model("workshop_reporting", "WageScheme")
    rows = wage_scheme.objects.filter(status="APPROVED").values(
        "id", "product_line_id", "workshop_id", "effective_from", "effective_to"
    ).order_by("product_line_id", "workshop_id", "effective_from", "id")
    previous_by_scope = {}
    for row in rows.iterator(chunk_size=500):
        scope = (row["product_line_id"], row["workshop_id"])
        has_previous = scope in previous_by_scope
        previous_end = previous_by_scope.get(scope)
        if has_previous and (
            previous_end is None or row["effective_from"] is None or row["effective_from"] <= previous_end
        ):
            raise RuntimeError(
                "工价方案存在同一订单产品和车间的已批准日期重叠，"
                "请先只读审计并人工确认历史数据，迁移不会自动改价。"
            )
        current_end = row["effective_to"]
        if not has_previous:
            previous_by_scope[scope] = current_end
        elif previous_end is None or current_end is None:
            previous_by_scope[scope] = None
        else:
            previous_by_scope[scope] = max(previous_end, current_end)


class Migration(migrations.Migration):
    dependencies = [
        ("organizations", "0002_seed_root_organization"),
        ("production_scheduling", "0005_backfill_scheduled_tasks_in_production"),
        ("production_tasks", "0014_alter_production_task_ready_label"),
        ("workshop_config", "0006_operation_reporting_unit"),
        ("workshop_reporting", "0007_workreport_history_snapshots"),
    ]

    operations = [
        migrations.RunPython(assert_no_approved_scope_overlap, migrations.RunPython.noop),
        BtreeGistExtension(),
        migrations.AddConstraint(
            model_name="wagescheme",
            constraint=django.contrib.postgres.constraints.ExclusionConstraint(
                condition=models.Q(("status", "APPROVED")),
                expressions=[
                    ("product_line", "="),
                    ("workshop", "="),
                    (
                        models.Func(
                            models.F("effective_from"), models.F("effective_to"), models.Value("[]"),
                            function="DATERANGE",
                            output_field=django.contrib.postgres.fields.ranges.DateRangeField(),
                        ),
                        "&&",
                    ),
                ],
                name="wage_scheme_approved_scope_no_overlap",
            ),
        ),
    ]
