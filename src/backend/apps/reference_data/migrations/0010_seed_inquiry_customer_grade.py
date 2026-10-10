import uuid

from django.db import migrations


CUSTOMER_GRADE_NAMESPACE = uuid.UUID("8af1f68d-366f-4d5c-9dfb-67ee1c507bd2")


def seed_inquiry_customer_grade(apps, schema_editor):
    DictionaryType = apps.get_model("reference_data", "DictionaryType")
    ReferenceDictionary = apps.get_model("reference_data", "ReferenceDictionary")
    dictionary_type = DictionaryType.objects.get(code="CUSTOMER_GRADE")
    ReferenceDictionary.objects.update_or_create(
        category_code="CUSTOMER_GRADE",
        item_code="F",
        defaults={
            "id": uuid.uuid5(CUSTOMER_GRADE_NAMESPACE, "CUSTOMER_GRADE:F"),
            "dictionary_type": dictionary_type,
            "display_name": "F（询价）",
            "english_name": "Inquiry",
            "description": "恩特 ERP 历史询价等级；该值表示询价状态，不作为客户质量高低判断。",
            "sort_order": 60,
            "status": "ACTIVE",
            "extra_data": {
                "legacy_source": "ENTE_ERP",
                "semantic_warning": "INQUIRY_STAGE_AS_GRADE",
            },
        },
    )


class Migration(migrations.Migration):

    dependencies = [
        ("reference_data", "0009_numberrule"),
    ]

    operations = [
        migrations.RunPython(seed_inquiry_customer_grade, migrations.RunPython.noop),
    ]
