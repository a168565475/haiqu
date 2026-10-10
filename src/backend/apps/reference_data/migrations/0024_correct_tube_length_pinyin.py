import re

from django.db import migrations
from pypinyin import Style, lazy_pinyin, pinyin


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
    syllable_options = [
        [token for token in (_compact_latin(item) for item in options) if token]
        for options in pinyin(source, style=Style.NORMAL, heteronym=True, strict=False)
    ]
    full_syllables = [options[0] if options else "" for options in syllable_options]
    initial_syllables = [
        _compact_latin(item)
        for item in lazy_pinyin(source, style=Style.FIRST_LETTER, strict=False)
    ]
    candidates = [
        "".join(full_syllables),
        " ".join(token for token in full_syllables if token),
        "".join(initial_syllables),
    ]
    alternate_full = list(full_syllables)
    alternate_initials = list(initial_syllables)
    has_length_alias = False
    for index, options in enumerate(syllable_options):
        if "zhang" not in options or "chang" not in options or index >= len(alternate_full):
            continue
        alternate_full[index] = "chang"
        if index < len(alternate_initials):
            alternate_initials[index] = "c"
        has_length_alias = True
    if has_length_alias:
        candidates.extend((
            "".join(alternate_full),
            " ".join(token for token in alternate_full if token),
            "".join(alternate_initials),
        ))
    return " ".join(dict.fromkeys(candidate for candidate in candidates if candidate))


def correct_tube_length_pinyin(apps, schema_editor):
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
        ("reference_data", "0023_tube_pinyin_search"),
    ]

    operations = [
        migrations.RunPython(correct_tube_length_pinyin, migrations.RunPython.noop),
    ]
