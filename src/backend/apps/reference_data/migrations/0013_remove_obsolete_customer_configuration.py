from copy import deepcopy

from django.db import migrations
from django.utils import timezone


REMOVED_CATEGORY = "CUSTOMER_CREDIT_GRADE"
AFFECTED_CATEGORIES = ("CUSTOMER_SOURCE", "CUSTOMER_TYPE", REMOVED_CATEGORY)


def publish_snapshot(apps):
    ConfigRelease = apps.get_model("reference_data", "ConfigRelease")
    ReferenceDictionary = apps.get_model("reference_data", "ReferenceDictionary")
    latest = ConfigRelease.objects.filter(status="PUBLISHED").order_by("-version").first()
    snapshot = deepcopy(latest.snapshot if latest else {})
    options = snapshot.setdefault("dictionary_options", {})
    for category_code in ("CUSTOMER_SOURCE", "CUSTOMER_TYPE"):
        rows = ReferenceDictionary.objects.filter(
            category_code=category_code,
            status="ACTIVE",
            archived_at__isnull=True,
        ).order_by("sort_order", "item_code")
        options[category_code] = [
            {
                "id": str(row.pk),
                "code": row.item_code,
                "label": row.display_name,
                "english_label": row.english_name,
                "status": row.status,
                "sort_order": row.sort_order,
                "color": row.color,
                "extra": {**row.extra_data, "description": row.description},
            }
            for row in rows
        ]
    options.pop(REMOVED_CATEGORY, None)
    latest_version = ConfigRelease.objects.order_by("-version").values_list("version", flat=True).first() or 0
    ConfigRelease.objects.create(
        version=latest_version + 1,
        status="PUBLISHED",
        notes="删除停用客户来源、停用客户类型与重复信用等级配置。",
        snapshot=snapshot,
        published_at=timezone.now(),
    )


def remove_obsolete_configuration(apps, schema_editor):
    DictionaryType = apps.get_model("reference_data", "DictionaryType")
    ReferenceDictionary = apps.get_model("reference_data", "ReferenceDictionary")

    ReferenceDictionary.objects.filter(
        category_code__in=("CUSTOMER_SOURCE", "CUSTOMER_TYPE"),
        status="INACTIVE",
    ).delete()
    ReferenceDictionary.objects.filter(category_code=REMOVED_CATEGORY).delete()
    DictionaryType.objects.filter(code=REMOVED_CATEGORY).delete()
    publish_snapshot(apps)


class Migration(migrations.Migration):
    dependencies = [
        ("customers", "0013_remove_customer_credit_grade"),
        ("reference_data", "0012_seed_ente_customer_configuration"),
    ]

    operations = [migrations.RunPython(remove_obsolete_configuration, migrations.RunPython.noop)]
