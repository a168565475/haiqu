import re

from django.db import migrations, models
from pypinyin import Style, lazy_pinyin


_NON_SEARCH_CHARACTERS = re.compile(r"[^0-9a-z]+")
_PINYIN_MODELS = (
    ("TubeProductName", "product_name"),
    ("TubeMaterial", "material_name"),
    ("TubeShape", "shape_name"),
)


def _compact_latin(value):
    return _NON_SEARCH_CHARACTERS.sub("", str(value or "").casefold())


def _build_pinyin_search(value):
    source = str(value or "").strip()
    if not source:
        return ""
    full_syllables = [
        token
        for token in (_compact_latin(item) for item in lazy_pinyin(source, style=Style.NORMAL, strict=False))
        if token
    ]
    initial_syllables = [
        token
        for token in (_compact_latin(item) for item in lazy_pinyin(source, style=Style.FIRST_LETTER, strict=False))
        if token
    ]
    candidates = ("".join(full_syllables), " ".join(full_syllables), "".join(initial_syllables))
    return " ".join(dict.fromkeys(candidate for candidate in candidates if candidate))


def backfill_tube_pinyin_search(apps, schema_editor):
    db_alias = schema_editor.connection.alias
    for model_name, source_field in _PINYIN_MODELS:
        model = apps.get_model("reference_data", model_name)
        records = list(model.objects.using(db_alias).all())
        for record in records:
            record.pinyin_search = _build_pinyin_search(getattr(record, source_field, ""))
        if records:
            model.objects.using(db_alias).bulk_update(records, ["pinyin_search"], batch_size=500)


class Migration(migrations.Migration):
    dependencies = [
        ("reference_data", "0022_seed_raw_material_category"),
    ]

    operations = [
        migrations.AddField(
            model_name="tubeproductname",
            name="pinyin_search",
            field=models.TextField(blank=True, default="", editable=False),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="tubematerial",
            name="pinyin_search",
            field=models.TextField(blank=True, default="", editable=False),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="tubeshape",
            name="pinyin_search",
            field=models.TextField(blank=True, default="", editable=False),
            preserve_default=False,
        ),
        migrations.RunPython(backfill_tube_pinyin_search, migrations.RunPython.noop),
    ]
