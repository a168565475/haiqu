import uuid

from django.db import migrations


DICTIONARY_NAMESPACE = uuid.UUID("8af1f68d-366f-4d5c-9dfb-67ee1c507bd2")

SOUTHEAST_ASIA_COUNTRIES = (
    ("BN", "文莱", 10),
    ("KH", "柬埔寨", 20),
    ("ID", "印度尼西亚", 30),
    ("LA", "老挝", 40),
    ("MY", "马来西亚", 50),
    ("MM", "缅甸", 60),
    ("PH", "菲律宾", 70),
    ("SG", "新加坡", 80),
    ("TH", "泰国", 90),
    ("TL", "东帝汶", 100),
    ("VN", "越南", 110),
)


def country_id(item_code):
    return uuid.uuid5(DICTIONARY_NAMESPACE, f"COUNTRY_REGION:{item_code}")


def seed_southeast_asia_countries(apps, schema_editor):
    ReferenceDictionary = apps.get_model("reference_data", "ReferenceDictionary")

    for item_code, display_name, sort_order in SOUTHEAST_ASIA_COUNTRIES:
        ReferenceDictionary.objects.update_or_create(
            category_code="COUNTRY_REGION",
            item_code=item_code,
            defaults={
                "id": country_id(item_code),
                "display_name": display_name,
                "description": f"东南亚国家/地区，ISO 3166-1 Alpha-2：{item_code}",
                "status": "ACTIVE",
                "sort_order": sort_order,
                "extra_data": {"region": "SOUTHEAST_ASIA"},
                "archived_at": None,
                "archive_reason": "",
            },
        )


class Migration(migrations.Migration):
    dependencies = [
        ("reference_data", "0004_update_customer_grade_definitions"),
    ]

    operations = [
        migrations.RunPython(seed_southeast_asia_countries, migrations.RunPython.noop),
    ]
