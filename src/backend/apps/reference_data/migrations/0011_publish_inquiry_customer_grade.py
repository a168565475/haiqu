from copy import deepcopy

from django.db import migrations
from django.utils import timezone


def publish_inquiry_customer_grade(apps, schema_editor):
    ConfigRelease = apps.get_model("reference_data", "ConfigRelease")
    ReferenceDictionary = apps.get_model("reference_data", "ReferenceDictionary")
    latest_release = ConfigRelease.objects.filter(status="PUBLISHED").order_by("-version").first()
    if latest_release is None:
        raise RuntimeError("发布询价等级前缺少已发布的基础配置快照。")

    snapshot = deepcopy(latest_release.snapshot)
    inquiry_grade = ReferenceDictionary.objects.get(category_code="CUSTOMER_GRADE", item_code="F")
    grade_options = snapshot.setdefault("dictionary_options", {}).setdefault("CUSTOMER_GRADE", [])
    grade_options = [item for item in grade_options if item["id"] != str(inquiry_grade.pk)]
    grade_options.append(
        {
            "id": str(inquiry_grade.pk),
            "code": inquiry_grade.item_code,
            "label": inquiry_grade.display_name,
            "english_label": inquiry_grade.english_name,
            "status": inquiry_grade.status,
            "sort_order": inquiry_grade.sort_order,
            "color": inquiry_grade.color,
            "extra": {**inquiry_grade.extra_data, "description": inquiry_grade.description},
        }
    )
    snapshot["dictionary_options"]["CUSTOMER_GRADE"] = sorted(
        grade_options, key=lambda item: (item["sort_order"], item["code"])
    )
    latest_version = ConfigRelease.objects.order_by("-version").values_list("version", flat=True).first() or 0
    ConfigRelease.objects.create(
        version=latest_version + 1,
        status="PUBLISHED",
        notes="新增 F（询价）客户等级，并明确其不代表客户质量高低。",
        snapshot=snapshot,
        published_at=timezone.now(),
    )


class Migration(migrations.Migration):

    dependencies = [
        ("reference_data", "0010_seed_inquiry_customer_grade"),
    ]

    operations = [
        migrations.RunPython(publish_inquiry_customer_grade, migrations.RunPython.noop),
    ]
