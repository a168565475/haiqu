import uuid

from django.db import migrations


DICTIONARY_NAMESPACE = uuid.UUID("8af1f68d-366f-4d5c-9dfb-67ee1c507bd2")

DICTIONARY_ITEMS = (
    ("CUSTOMER_GRADE", "A", "A级", "最高优先级客户", 10),
    ("CUSTOMER_GRADE", "B", "B级", "较高优先级客户", 20),
    ("CUSTOMER_GRADE", "C", "C级", "常规维护客户", 30),
    ("CUSTOMER_GRADE", "D", "D级", "低频维护客户", 40),
    ("CUSTOMER_TYPE", "IMPORTER", "进口商", "", 10),
    ("CUSTOMER_TYPE", "WHOLESALER", "批发商", "", 20),
    ("CUSTOMER_TYPE", "DISTRIBUTOR", "经销商", "", 30),
    ("CUSTOMER_TYPE", "RETAILER", "零售商", "", 40),
    ("CUSTOMER_TYPE", "SUPERMARKET", "商超", "", 50),
    ("CUSTOMER_TYPE", "ECOMMERCE", "电商", "", 60),
    ("CUSTOMER_TYPE", "BRAND", "品牌商", "", 70),
    ("CUSTOMER_TYPE", "OEM_ODM", "OEM/ODM 客户", "", 80),
    ("CUSTOMER_TYPE", "OTHER", "其他", "", 90),
    ("CUSTOMER_SOURCE", "EXHIBITION", "展会", "", 10),
    ("CUSTOMER_SOURCE", "WEBSITE", "官网", "", 20),
    ("CUSTOMER_SOURCE", "PLATFORM", "第三方平台", "", 30),
    ("CUSTOMER_SOURCE", "OUTBOUND", "主动开发", "", 40),
    ("CUSTOMER_SOURCE", "REFERRAL", "客户转介绍", "", 50),
    ("CUSTOMER_SOURCE", "IMPORT", "历史数据导入", "", 60),
    ("CUSTOMER_SOURCE", "OTHER", "其他", "", 90),
)


def dictionary_id(category_code, item_code):
    return uuid.uuid5(DICTIONARY_NAMESPACE, f"{category_code}:{item_code}")


def seed_customer_profile_dictionaries(apps, schema_editor):
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


def remove_customer_profile_dictionaries(apps, schema_editor):
    ReferenceDictionary = apps.get_model("reference_data", "ReferenceDictionary")
    ReferenceDictionary.objects.filter(
        id__in=[dictionary_id(category_code, item_code) for category_code, item_code, *_ in DICTIONARY_ITEMS]
    ).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("reference_data", "0002_seed_core_dictionaries"),
    ]

    operations = [
        migrations.RunPython(seed_customer_profile_dictionaries, remove_customer_profile_dictionaries),
    ]
