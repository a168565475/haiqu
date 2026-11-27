import django.db.models.deletion
from django.db import migrations, models


def move_cutting_groups(apps, schema_editor):
    line_model = apps.get_model("workshop_reporting", "WageSchemeLine")
    group_model = apps.get_model("workshop_reporting", "WageSchemeLineCuttingGroup")
    alias = schema_editor.connection.alias
    groups = line_model.objects.using(alias).filter(counting_mode="GROUP").values_list("pk", "cutting_components")
    group_model.objects.using(alias).bulk_create(
        (group_model(line_id=line_id, components=components) for line_id, components in groups.iterator()),
        batch_size=500,
    )
    schema_editor.execute("SET CONSTRAINTS ALL IMMEDIATE")


def restore_cutting_groups(apps, schema_editor):
    line_model = apps.get_model("workshop_reporting", "WageSchemeLine")
    group_model = apps.get_model("workshop_reporting", "WageSchemeLineCuttingGroup")
    alias = schema_editor.connection.alias
    groups = group_model.objects.using(alias).values_list("line_id", "components")
    line_model.objects.using(alias).bulk_update(
        (line_model(pk=line_id, cutting_components=components) for line_id, components in groups.iterator()),
        ["cutting_components"],
        batch_size=500,
    )


class Migration(migrations.Migration):
    dependencies = [("workshop_reporting", "0017_cutting_groups_and_scheme_withdrawals")]

    operations = [
        migrations.CreateModel(
            name="WageSchemeLineCuttingGroup",
            fields=[
                (
                    "line",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.DO_NOTHING, primary_key=True,
                        related_name="+", serialize=False, to="workshop_reporting.wageschemeline",
                    ),
                ),
                ("components", models.JSONField()),
            ],
            options={"db_table": "workshop_wage_scheme_cutting_group"},
        ),
        migrations.RunPython(move_cutting_groups, restore_cutting_groups),
        migrations.RemoveField(model_name="wageschemeline", name="cutting_components"),
    ]
