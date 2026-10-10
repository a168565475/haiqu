import json
import uuid
from pathlib import Path

from django.db import migrations


MASTER_DATA_NAMESPACE = uuid.UUID("ddbd95a1-4a33-4fa9-861c-50506eaf47dc")
RESOURCE_DIRECTORY = Path(__file__).resolve().parent.parent / "resources"


def load_snapshot(file_name):
    with (RESOURCE_DIRECTORY / file_name).open(encoding="utf-8") as source_file:
        payload = json.load(source_file)
    if payload.get("schema_version") != 1 or not isinstance(payload.get("records"), list):
        raise ValueError(f"标准数据资源 {file_name} 的格式无效。")
    return payload


def deterministic_id(resource_type, code):
    return uuid.uuid5(MASTER_DATA_NAMESPACE, f"{resource_type}:{code}")


def seed_standard_reference_data(apps, schema_editor):
    Country = apps.get_model("reference_data", "Country")
    Currency = apps.get_model("reference_data", "Currency")
    Incoterm = apps.get_model("reference_data", "Incoterm")

    country_snapshot = load_snapshot("countries_un_m49_2026-08-26.json")
    for record in country_snapshot["records"]:
        existing = Country.objects.filter(code=record["code"]).first()
        extra_data = {**(existing.extra_data if existing else {}), **record.get("extra_data", {})}
        values = {
            "alpha3_code": record["alpha3_code"],
            "numeric_code": record["numeric_code"],
            "chinese_name": record["chinese_name"],
            "english_name": record["english_name"],
            "status": "ACTIVE",
            "sort_order": record["sort_order"],
            "source_version": "UN M49 2026-08-26 / ISO 3166-1",
            "extra_data": extra_data,
        }
        if existing:
            Country.objects.filter(pk=existing.pk).update(**values)
        else:
            Country.objects.create(
                id=deterministic_id("COUNTRY", record["code"]),
                code=record["code"],
                **values,
            )

    currency_snapshot = load_snapshot("currencies_iso4217_2026-01-01.json")
    for record in currency_snapshot["records"]:
        existing = Currency.objects.filter(code=record["code"]).first()
        values = {
            "numeric_code": record["numeric_code"],
            "decimal_places": record["decimal_places"],
            "symbol": record["symbol"],
            "chinese_name": record["chinese_name"],
            "english_name": record["english_name"],
            "status": "ACTIVE",
            "sort_order": record["sort_order"],
            "source_version": "ISO 4217 List One 2026-01-01",
            "extra_data": record.get("extra_data", {}),
        }
        if existing:
            Currency.objects.filter(pk=existing.pk).update(**values)
        else:
            Currency.objects.create(
                id=deterministic_id("CURRENCY", record["code"]),
                code=record["code"],
                **values,
            )

    incoterm_snapshot = load_snapshot("incoterms_2020.json")
    for record in incoterm_snapshot["records"]:
        existing = Incoterm.objects.filter(code=record["code"]).first()
        values = {
            "chinese_name": record["chinese_name"],
            "english_name": record["english_name"],
            "rules_version": "2020",
            "transport_scope": record["transport_scope"],
            "status": "ACTIVE",
            "sort_order": record["sort_order"],
            "source_version": "ICC Incoterms 2020",
            "extra_data": {
                "translation_note": incoterm_snapshot["source"]["translation_note"],
            },
        }
        if existing:
            Incoterm.objects.filter(pk=existing.pk).update(**values)
        else:
            Incoterm.objects.create(
                id=deterministic_id("INCOTERM", record["code"]),
                code=record["code"],
                **values,
            )


class Migration(migrations.Migration):
    dependencies = [
        ("reference_data", "0007_exchangerate_incoterm_paymentmethod_port_and_more"),
    ]

    operations = [
        migrations.RunPython(seed_standard_reference_data, migrations.RunPython.noop),
    ]
