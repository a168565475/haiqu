import uuid

from django.db import migrations


DICTIONARY_NAMESPACE = uuid.UUID("8af1f68d-366f-4d5c-9dfb-67ee1c507bd2")

DICTIONARY_ITEMS = (
    ("CUSTOMER_ATTENTION", "KEY_ACCOUNT", "重点客户", "需要重点投入和持续关注的客户", 10),
    ("CUSTOMER_ATTENTION", "FOCUS", "重点关注", "近期存在明确机会或风险的客户", 20),
    ("CUSTOMER_ATTENTION", "ROUTINE", "常规跟进", "按标准节奏维护的客户", 30),
    ("CUSTOMER_ATTENTION", "LOW_FREQUENCY", "低频维护", "暂时降低跟进频率的客户", 40),
    ("COMMUNICATION_TYPE", "EMAIL", "邮件", "", 10),
    ("COMMUNICATION_TYPE", "PHONE", "电话", "", 20),
    ("COMMUNICATION_TYPE", "ONLINE_MEETING", "线上会议", "", 30),
    ("COMMUNICATION_TYPE", "IN_PERSON_MEETING", "当面拜访", "", 40),
    ("COMMUNICATION_TYPE", "INSTANT_MESSAGE", "即时通讯", "微信、WhatsApp 等即时通讯工具", 50),
    ("COMMUNICATION_TYPE", "OTHER", "其他", "", 90),
    ("INQUIRY_SOURCE", "EMAIL", "邮件询价", "", 10),
    ("INQUIRY_SOURCE", "WEBSITE", "网站询价", "", 20),
    ("INQUIRY_SOURCE", "EXHIBITION", "展会", "", 30),
    ("INQUIRY_SOURCE", "REFERRAL", "转介绍", "", 40),
    ("INQUIRY_SOURCE", "OTHER", "其他", "", 90),
)


def dictionary_id(category_code, item_code):
    return uuid.uuid5(DICTIONARY_NAMESPACE, f"{category_code}:{item_code}")


def seed_core_dictionaries(apps, schema_editor):
    ReferenceDictionary = apps.get_model("reference_data", "ReferenceDictionary")
    for category_code, item_code, display_name, description, sort_order in DICTIONARY_ITEMS:
        ReferenceDictionary.objects.get_or_create(
            category_code=category_code,
            item_code=item_code,
            defaults={
                "id": dictionary_id(category_code, item_code),
                "display_name": display_name,
                "description": description,
                "status": "ACTIVE",
                "sort_order": sort_order,
                "extra_data": {},
            },
        )


def remove_seeded_core_dictionaries(apps, schema_editor):
    ReferenceDictionary = apps.get_model("reference_data", "ReferenceDictionary")
    seeded_ids = [
        dictionary_id(category_code, item_code)
        for category_code, item_code, *_ in DICTIONARY_ITEMS
    ]
    ReferenceDictionary.objects.filter(id__in=seeded_ids).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("reference_data", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(seed_core_dictionaries, remove_seeded_core_dictionaries),
    ]
