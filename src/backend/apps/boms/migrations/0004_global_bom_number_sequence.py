import re

from django.db import migrations


HISTORICAL_LAST_NUMBER = 349
BOM_NUMBER_PATTERN = re.compile(r"^BOM([0-9]{7})$")


def configure_bom_numbering(apps, schema_editor):
    Bom = apps.get_model("boms", "Bom")
    NumberRule = apps.get_model("reference_data", "NumberRule")
    database_alias = schema_editor.connection.alias

    NumberRule.objects.using(database_alias).update_or_create(
        number_type="BOM",
        defaults={
            "chinese_name": "BOM 编号",
            "prefix": "BOM",
            "format_pattern": "{prefix}{sequence}",
            "sequence_name": "haiqu_bom_number_seq",
            "sequence_padding": 7,
            "date_granularity": "NONE",
            "reset_policy": "NEVER",
            "is_configured": True,
            "sort_order": 63,
            "status": "ACTIVE",
            "description": "BOM 加七位全局流水号；历史最后编号为 BOM0000349。",
        },
    )

    boms = list(Bom.objects.using(database_alias).order_by("created_at", "id"))
    existing_sequence_values = []
    for bom in boms:
        match = BOM_NUMBER_PATTERN.fullmatch(bom.bom_number)
        if match:
            existing_sequence_values.append(int(match.group(1)))

    last_number = max([HISTORICAL_LAST_NUMBER, *existing_sequence_values])
    for bom in boms:
        if BOM_NUMBER_PATTERN.fullmatch(bom.bom_number):
            continue
        last_number += 1
        Bom.objects.using(database_alias).filter(pk=bom.pk).update(
            bom_number=f"BOM{last_number:07d}"
        )

    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            "SELECT setval('haiqu_bom_number_seq', %s, true)",
            [last_number],
        )


class Migration(migrations.Migration):
    dependencies = [
        ("boms", "0003_bomlineimagedraft"),
        ("reference_data", "0024_correct_tube_length_pinyin"),
    ]

    operations = [
        migrations.RunSQL(
            sql=(
                "CREATE SEQUENCE IF NOT EXISTS haiqu_bom_number_seq "
                "AS bigint START WITH 350 INCREMENT BY 1 MINVALUE 1 CACHE 1;"
            ),
            reverse_sql="DROP SEQUENCE IF EXISTS haiqu_bom_number_seq;",
        ),
        migrations.RunPython(configure_bom_numbering),
    ]
