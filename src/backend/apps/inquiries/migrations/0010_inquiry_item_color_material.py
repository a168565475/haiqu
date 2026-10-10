import re

from django.db import migrations, models


def split_legacy_specification(value):
    """只拆分带明确标签的历史文本，未标注的内容保持原样。"""
    original = str(value or "").strip()
    if not original:
        return "", "", ""

    values = {}
    for label in ("颜色", "材质"):
        match = re.search(rf"(?:^|[；;])\s*{label}\s*[:：]\s*([^；;]*)", original)
        if match:
            values[label] = match.group(1).strip()

    specification = original
    for label in ("颜色", "材质"):
        specification = re.sub(
            rf"(?:^|[；;])\s*{label}\s*[:：]\s*[^；;]*",
            "",
            specification,
        )
    specification = specification.strip(" ;；\t\r\n")
    specification = re.sub(r"[；;]\s*[；;]", "；", specification)
    return specification, values.get("颜色", ""), values.get("材质", "")


def split_existing_items(apps, schema_editor):
    InquiryItem = apps.get_model("inquiries", "InquiryItem")
    database_alias = schema_editor.connection.alias
    items = InquiryItem.objects.using(database_alias).all().only("id", "specification", "color", "material")
    changed = []
    for item in items.iterator(chunk_size=500):
        if item.color or item.material:
            continue
        specification, color, material = split_legacy_specification(item.specification)
        if not color and not material:
            continue
        item.specification = specification
        item.color = color
        item.material = material
        changed.append(item)
    if changed:
        InquiryItem.objects.using(database_alias).bulk_update(
            changed,
            ["specification", "color", "material"],
            batch_size=500,
        )


class Migration(migrations.Migration):
    dependencies = [("inquiries", "0009_inquiry_stage_time_limits")]

    operations = [
        migrations.AddField(
            model_name="inquiryitem",
            name="color",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AddField(
            model_name="inquiryitem",
            name="material",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.RunPython(split_existing_items, migrations.RunPython.noop),
    ]
