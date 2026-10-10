from django.db import migrations


COMPLAINT_DICTIONARIES = {
    "COMPLAINT_TYPE": [
        ("QUALITY", "质量问题", 10, {"sla_multiplier": 1.0}),
        ("DELIVERY", "交期问题", 20, {"sla_multiplier": 1.0}),
        ("PACKAGING", "包装问题", 30, {"sla_multiplier": 1.2}),
        ("DOCUMENTATION", "单证问题", 40, {"sla_multiplier": 0.8}),
        ("SERVICE", "服务问题", 50, {"sla_multiplier": 1.0}),
        ("OTHER", "其他", 60, {"sla_multiplier": 1.2}),
    ],
    "COMPLAINT_SEVERITY": [
        (
            "GENERAL",
            "一般",
            10,
            {"first_response_hours": 24, "resolution_business_days": 7},
        ),
        (
            "IMPORTANT",
            "重要",
            20,
            {"first_response_hours": 8, "resolution_business_days": 5},
        ),
        (
            "SERIOUS",
            "严重",
            30,
            {"first_response_hours": 4, "resolution_business_days": 3},
        ),
        (
            "CRITICAL",
            "重大",
            40,
            {"first_response_hours": 1, "resolution_business_days": 1},
        ),
    ],
}


def seed_complaint_dictionaries(apps, schema_editor):
    ReferenceDictionary = apps.get_model("reference_data", "ReferenceDictionary")
    for category_code, rows in COMPLAINT_DICTIONARIES.items():
        for item_code, display_name, sort_order, extra_data in rows:
            ReferenceDictionary.objects.update_or_create(
                category_code=category_code,
                item_code=item_code,
                defaults={
                    "display_name": display_name,
                    "description": "CRM 客诉模块配置项",
                    "status": "ACTIVE",
                    "sort_order": sort_order,
                    "extra_data": extra_data,
                    "archived_at": None,
                    "archived_by_employee_id": None,
                    "archive_reason": "",
                },
            )


def remove_complaint_dictionaries(apps, schema_editor):
    ReferenceDictionary = apps.get_model("reference_data", "ReferenceDictionary")
    ReferenceDictionary.objects.filter(category_code__in=COMPLAINT_DICTIONARIES.keys()).delete()


class Migration(migrations.Migration):
    dependencies = [("reference_data", "0005_seed_southeast_asia_countries")]

    operations = [
        migrations.RunPython(seed_complaint_dictionaries, remove_complaint_dictionaries),
    ]
