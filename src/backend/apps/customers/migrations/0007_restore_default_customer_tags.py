import uuid

from django.db import migrations


TAG_NAMESPACE = uuid.UUID("73264b13-138d-4c45-853e-8d8ec5a1f327")

DEFAULT_TAGS = (
    ("KEY_CUSTOMER", "重点客户", "#E5484D", "需要重点投入和持续关注"),
    ("EUROPE_MARKET", "欧洲市场", "#3E63DD", "主要面向欧洲市场"),
    ("OUTDOOR_PRODUCTS", "户外用品", "#2B9A66", "户外用品相关客户"),
    ("ANNUAL_FRAMEWORK", "年度框架", "#A15C00", "存在年度框架合作"),
)


def restore_default_customer_tags(apps, schema_editor):
    CustomerTag = apps.get_model("customers", "CustomerTag")
    for tag_code, tag_name, color, description in DEFAULT_TAGS:
        CustomerTag.objects.get_or_create(
            tag_code=tag_code,
            defaults={
                "id": uuid.uuid5(TAG_NAMESPACE, tag_code),
                "tag_name": tag_name,
                "color": color,
                "description": description,
            },
        )


class Migration(migrations.Migration):
    dependencies = [
        ("customers", "0006_cus05_contact_employment"),
    ]

    operations = [
        migrations.RunPython(restore_default_customer_tags, migrations.RunPython.noop),
    ]
