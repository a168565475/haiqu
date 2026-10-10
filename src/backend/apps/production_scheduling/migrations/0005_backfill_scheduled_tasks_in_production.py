from django.db import migrations


def mark_tasks_with_active_schedule_in_production(apps, schema_editor):
    production_task = apps.get_model("production_tasks", "ProductionTask")
    production_schedule = apps.get_model("production_scheduling", "ProductionSchedule")
    scheduled_task_ids = production_schedule.objects.filter(
        record_status="ACTIVE",
        production_task__status="READY",
    ).values_list("production_task_id", flat=True)
    production_task.objects.filter(pk__in=scheduled_task_ids, status="READY").update(
        status="IN_PRODUCTION"
    )


class Migration(migrations.Migration):
    dependencies = [
        ("production_scheduling", "0004_parent_touch_and_history_guards"),
        ("production_tasks", "0014_alter_production_task_ready_label"),
    ]

    operations = [
        migrations.RunPython(
            mark_tasks_with_active_schedule_in_production,
            migrations.RunPython.noop,
        ),
    ]
