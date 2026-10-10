from django.db import migrations


def create_policy(apps, schema_editor):
    Policy = apps.get_model("workflow", "SlaPolicy")
    Policy.objects.using(schema_editor.connection.alias).get_or_create(
        policy_code="INQUIRY_WORKTIME_202609",
        defaults={
            "display_name": "询盘大小周处理时限", "target_type": "INQUIRY",
            "response_minutes": 240, "resolution_minutes": 120, "is_enabled": True,
            "config_data": {"work_calendar": {
                "mode": "ALTERNATING_WEEKS_V1", "timezone": "Asia/Shanghai",
                "rest_saturday": "2026-09-05", "periods": [[510, 720], [810, 1050]],
            }},
        },
    )


class Migration(migrations.Migration):
    dependencies = [("inquiries", "0007_inquiry_priority"), ("workflow", "0003_task_center_foundation")]
    operations = [migrations.RunPython(create_policy, migrations.RunPython.noop)]
