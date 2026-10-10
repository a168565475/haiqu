from django.db import migrations


def set_yearly_reset(apps, schema_editor):
    number_rule = apps.get_model("reference_data", "NumberRule")
    number_rule.objects.filter(
        number_type__in=["PRODUCTION_ORDER", "PRODUCTION_TASK"],
    ).update(reset_policy="YEARLY")


def restore_never_reset(apps, schema_editor):
    number_rule = apps.get_model("reference_data", "NumberRule")
    number_rule.objects.filter(
        number_type__in=["PRODUCTION_ORDER", "PRODUCTION_TASK"],
    ).update(reset_policy="NEVER")


class Migration(migrations.Migration):
    dependencies = [
        ("production_tasks", "0012_unify_task_number_rule"),
        ("reference_data", "0026_number_rule_yearly_reset"),
    ]

    operations = [migrations.RunPython(set_yearly_reset, restore_never_reset)]
