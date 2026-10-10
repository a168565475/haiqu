import uuid

from django.db import migrations


CATEGORY_NAME = "喷塑五金"
CATEGORY_SOURCE = "来源：原料信息_20260831141210.xlsx（补充缺失类别）"
CATEGORY_ID = uuid.UUID("8e8863f0-bb49-50b8-a4ee-9b7cf5242182")


def seed_raw_material_category(apps, schema_editor):
    ProductCategory = apps.get_model("reference_data", "ProductCategory")
    db_alias = schema_editor.connection.alias
    current = ProductCategory.objects.using(db_alias).filter(category_name=CATEGORY_NAME).first()
    if current is not None:
        if current.item_type != "SEMI_FINISHED":
            raise RuntimeError("喷塑五金类别已存在，但品号类型不是半成品。")
        return

    max_sort_order = (
        ProductCategory.objects.using(db_alias).order_by("-sort_order").values_list("sort_order", flat=True).first()
        or 0
    )
    ProductCategory.objects.using(db_alias).create(
        id=CATEGORY_ID,
        item_type="SEMI_FINISHED",
        category_name=CATEGORY_NAME,
        status="ACTIVE",
        sort_order=max_sort_order + 1,
        description=CATEGORY_SOURCE,
    )


def remove_raw_material_category(apps, schema_editor):
    ProductCategory = apps.get_model("reference_data", "ProductCategory")
    db_alias = schema_editor.connection.alias
    ProductCategory.objects.using(db_alias).filter(
        id=CATEGORY_ID,
        category_name=CATEGORY_NAME,
        description=CATEGORY_SOURCE,
    ).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("reference_data", "0021_seed_accessory_data"),
    ]

    operations = [
        migrations.RunPython(seed_raw_material_category, remove_raw_material_category),
    ]
