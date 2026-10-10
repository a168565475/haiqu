import uuid

from django.db import migrations


DICTIONARY_NAMESPACE = uuid.UUID("8af1f68d-366f-4d5c-9dfb-67ee1c507bd2")

CUSTOMER_GRADES = (
    ("A", "A", "非常优质", 10),
    ("B", "B", "优质", 20),
    ("C", "C", "良好", 30),
    ("D", "D", "一般", 40),
    ("E", "E", "较差", 50),
)


def dictionary_id(item_code):
    return uuid.uuid5(DICTIONARY_NAMESPACE, f"CUSTOMER_GRADE:{item_code}")


def update_customer_grade_definitions(apps, schema_editor):
    ReferenceDictionary = apps.get_model("reference_data", "ReferenceDictionary")

    for item_code, display_name, description, sort_order in CUSTOMER_GRADES:
        item, created = ReferenceDictionary.objects.get_or_create(
            category_code="CUSTOMER_GRADE",
            item_code=item_code,
            defaults={
                "id": dictionary_id(item_code),
                "display_name": display_name,
                "description": description,
                "status": "ACTIVE",
                "sort_order": sort_order,
                "extra_data": {},
            },
        )
        if not created:
            ReferenceDictionary.objects.filter(pk=item.pk).update(
                display_name=display_name,
                description=description,
                status="ACTIVE",
                sort_order=sort_order,
            )


class Migration(migrations.Migration):
    dependencies = [
        ("reference_data", "0003_seed_customer_profile_dictionaries"),
    ]

    operations = [
        migrations.RunPython(update_customer_grade_definitions, migrations.RunPython.noop),
    ]
