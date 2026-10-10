from django.db import migrations, models


def assert_single_version_chain(apps, schema_editor):
    wage_scheme = apps.get_model("workshop_reporting", "WageScheme")
    duplicate_root = wage_scheme.objects.filter(parent_scheme__isnull=True).values(
        "product_line_id", "workshop_id"
    ).annotate(total=models.Count("id")).filter(total__gt=1).exists()
    duplicate_child = wage_scheme.objects.filter(parent_scheme__isnull=False).values(
        "parent_scheme_id"
    ).annotate(total=models.Count("id")).filter(total__gt=1).exists()
    if duplicate_root or duplicate_child:
        raise RuntimeError(
            "工价方案存在多根或分支版本链，请先只读审计并人工确认历史数据，"
            "迁移不会自动删除或合并方案。"
        )


class Migration(migrations.Migration):
    dependencies = [
        ("organizations", "0002_seed_root_organization"),
        ("production_scheduling", "0005_backfill_scheduled_tasks_in_production"),
        ("production_tasks", "0014_alter_production_task_ready_label"),
        ("workshop_config", "0006_operation_reporting_unit"),
        ("workshop_reporting", "0008_wagescheme_approved_scope_no_overlap"),
    ]

    operations = [
        migrations.RunPython(assert_single_version_chain, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="wagescheme",
            constraint=models.UniqueConstraint(
                condition=models.Q(("parent_scheme__isnull", True)),
                fields=("product_line", "workshop"),
                name="wage_scheme_scope_root_unique",
            ),
        ),
        migrations.AddConstraint(
            model_name="wagescheme",
            constraint=models.UniqueConstraint(
                condition=models.Q(("parent_scheme__isnull", False)),
                fields=("parent_scheme",),
                name="wage_scheme_parent_single_child",
            ),
        ),
    ]
