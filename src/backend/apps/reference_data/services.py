from collections import defaultdict

from django.apps import apps
from django.db import transaction
from django.db.models import Count
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.core.audit import write_audit_log
from apps.core.api.concurrency import etag_for_instance
from apps.core.api.concurrency import PreconditionFailed, PreconditionRequired

from .models import (
    ConfigRelease,
    ConfigReleaseStatus,
    Country,
    Currency,
    ParameterValueType,
    ReferenceDictionary,
    ReferenceStatus,
    SystemParameterDefinition,
)


# 字符串代码引用必须显式登记，不能对全库做动态扫描。
DICTIONARY_REFERENCE_REGISTRY = {
    "COMMUNICATION_TYPE": [("crm", "CustomerCommunication", "communication_type", "item_code")],
    "COMPLAINT_SEVERITY": [("customers", "CustomerComplaint", "severity_item_id", "id")],
    "COMPLAINT_TYPE": [("customers", "CustomerComplaint", "complaint_type_item_id", "id")],
    "CONTACT_LANGUAGE": [("customers", "CustomerContact", "preferred_language_code", "item_code")],
    "CONTACT_TIMEZONE": [("customers", "CustomerContact", "timezone_code", "timezone_code")],
    "COUNTRY_REGION": [
        ("customers", "CustomerAccount", "primary_country_code", "item_code"),
        ("customers", "CustomerTransactionEntity", "registration_country_code", "item_code"),
        ("customers", "CustomerTransactionEntity", "tax_country_code", "item_code"),
        ("customers", "CustomerEntityAddress", "country_code", "item_code"),
    ],
    "CUSTOMER_ATTENTION": [("customers", "CustomerAttentionReview", "attention_level_item_id", "id")],
    "CUSTOMER_GRADE": [("customers", "CustomerGradeReview", "grade_item_id", "id")],
    "CUSTOMER_SOURCE": [("customers", "CustomerSourceAttribution", "source_item_id", "id")],
    "CUSTOMER_TYPE": [("customers", "CustomerTypeAssignment", "type_item_id", "id")],
    "INQUIRY_SOURCE": [("inquiries", "Inquiry", "inquiry_source", "item_code")],
}


def _reference_value(item, source):
    if source == "id":
        return item.pk
    if source == "timezone_code":
        return item.extra_data.get("timezone_code", "")
    return item.item_code


def dictionary_reference_breakdown(item):
    breakdown = []
    for app_label, model_name, field_name, value_source in DICTIONARY_REFERENCE_REGISTRY.get(
        item.category_code,
        [],
    ):
        value = _reference_value(item, value_source)
        if value in (None, ""):
            continue
        model = apps.get_model(app_label, model_name)
        count = model.objects.filter(**{field_name: value}).count()
        if count:
            breakdown.append(
                {
                    "model": f"{app_label}.{model_name}",
                    "field": field_name,
                    "count": count,
                }
            )
    return breakdown


def dictionary_reference_count(item):
    return sum(row["count"] for row in dictionary_reference_breakdown(item))


def dictionary_reference_counts(items):
    """按登记的引用字段批量统计，保留每个字段及每个字典项的独立计数。"""
    items = list(items)
    counts = {item.pk: 0 for item in items}
    by_category = defaultdict(list)
    for item in items:
        by_category[item.category_code].append(item)
    for category, category_items in by_category.items():
        for app_label, model_name, field_name, value_source in DICTIONARY_REFERENCE_REGISTRY.get(category, []):
            model = apps.get_model(app_label, model_name)
            field = model._meta.get_field(field_name)
            item_values = []
            for item in category_items:
                value = _reference_value(item, value_source)
                if value not in (None, ""):
                    item_values.append((item.pk, field.get_prep_value(value)))
            values = {value for _, value in item_values}
            if not values:
                continue
            grouped = (
                model.objects.filter(**{f"{field_name}__in": values})
                .order_by().values(field_name).annotate(reference_count=Count("pk"))
            )
            by_value = {row[field_name]: row["reference_count"] for row in grouped}
            for item_id, value in item_values:
                counts[item_id] += by_value.get(value, 0)
    return counts


def dictionary_type_reference_count(dictionary_type):
    return sum(dictionary_reference_count(item) for item in dictionary_type.items.all())


def build_config_snapshot():
    grouped = defaultdict(list)
    items = ReferenceDictionary.objects.filter(
        dictionary_type__status=ReferenceStatus.ACTIVE,
        dictionary_type__archived_at__isnull=True,
        status=ReferenceStatus.ACTIVE,
        archived_at__isnull=True,
    ).select_related("dictionary_type").order_by("category_code", "sort_order", "item_code")
    for item in items:
        grouped[item.category_code].append(
            {
                "id": str(item.pk),
                "code": item.item_code,
                "label": item.display_name,
                "english_label": item.english_name,
                "status": item.status,
                "sort_order": item.sort_order,
                "color": item.color,
                "extra": {**item.extra_data, "description": item.description},
            }
        )

    parameter_values = {}
    definitions = SystemParameterDefinition.objects.filter(
        status=ReferenceStatus.ACTIVE,
        archived_at__isnull=True,
    ).select_related("value_record")
    for definition in definitions:
        value_record = getattr(definition, "value_record", None)
        parameter_values[definition.code] = (
            value_record.draft_value if value_record is not None else definition.default_value
        )

    return {
        "dictionary_options": dict(grouped),
        "system_parameters": parameter_values,
    }


def latest_published_release():
    return ConfigRelease.objects.filter(status=ConfigReleaseStatus.PUBLISHED).order_by("-version").first()


def pending_config_change_count():
    current_snapshot = build_config_snapshot()
    release = latest_published_release()
    if release is None:
        return sum(
            len(items) for items in current_snapshot["dictionary_options"].values()
        ) + len(current_snapshot["system_parameters"])

    published_snapshot = release.snapshot or {}
    change_count = 0
    current_options = current_snapshot["dictionary_options"]
    published_options = published_snapshot.get("dictionary_options", {})
    for type_code in set(current_options) | set(published_options):
        current_rows = {row["id"]: row for row in current_options.get(type_code, [])}
        published_rows = {row["id"]: row for row in published_options.get(type_code, [])}
        change_count += sum(
            current_rows.get(item_id) != published_rows.get(item_id)
            for item_id in set(current_rows) | set(published_rows)
        )

    current_parameters = current_snapshot["system_parameters"]
    published_parameters = published_snapshot.get("system_parameters", {})
    change_count += sum(
        current_parameters.get(code) != published_parameters.get(code)
        for code in set(current_parameters) | set(published_parameters)
    )
    return change_count


def publish_config(*, actor_employee=None, notes="", request=None, expected_etag=None):
    if not expected_etag:
        raise PreconditionRequired()
    with transaction.atomic():
        latest_release = ConfigRelease.objects.select_for_update().order_by("-version").first()
        if latest_release is not None and expected_etag != etag_for_instance(latest_release):
            raise PreconditionFailed()
        latest_version = latest_release.version if latest_release is not None else 0
        release = ConfigRelease.objects.create(
            version=latest_version + 1,
            status=ConfigReleaseStatus.DRAFT,
            notes=notes,
            snapshot={},
        )
        release.snapshot = build_config_snapshot()
        release.status = ConfigReleaseStatus.PUBLISHED
        release.published_at = timezone.now()
        release.published_by_employee = actor_employee
        release.save(
            update_fields=[
                "snapshot",
                "status",
                "published_at",
                "published_by_employee",
                "updated_at",
            ]
        )
        write_audit_log(
            object_type="CONFIG_RELEASE",
            object_id=release.pk,
            action="PUBLISHED",
            actor_employee=actor_employee,
            after_data={"version": release.version, "notes": release.notes},
            request=request,
        )
        return release


def published_dictionary_options(type_code, *, current_item_id=None):
    release = latest_published_release()
    if release is None:
        return [], None
    options = list(release.snapshot.get("dictionary_options", {}).get(type_code, []))
    if current_item_id and not any(row["id"] == str(current_item_id) for row in options):
        current = ReferenceDictionary.objects.filter(
            pk=current_item_id,
            category_code=type_code,
        ).first()
        if current is not None:
            options.append(
                {
                    "id": str(current.pk),
                    "code": current.item_code,
                    "label": current.display_name,
                    "english_label": current.english_name,
                    "status": current.status,
                    "sort_order": current.sort_order,
                    "color": current.color,
                    "extra": {
                        **current.extra_data,
                        "description": current.description,
                        "current_selection": True,
                    },
                }
            )
    return options, release.version


def published_dictionary_code_is_active(type_code, code):
    normalized_code = (code or "").strip().upper()
    if not normalized_code:
        return False
    options, _version = published_dictionary_options(type_code.strip().upper())
    return any(
        item["code"] == normalized_code and item["status"] == ReferenceStatus.ACTIVE
        for item in options
    )


def published_dictionary_item_id_is_active(type_code, item_id):
    if not item_id:
        return False
    options, _version = published_dictionary_options(type_code.strip().upper())
    normalized_id = str(item_id)
    return any(
        item["id"] == normalized_id and item["status"] == ReferenceStatus.ACTIVE
        for item in options
    )


def published_dictionary_groups(type_codes):
    release = latest_published_release()
    if release is None:
        return {code: [] for code in type_codes}, None
    source = release.snapshot.get("dictionary_options", {})
    return {code: list(source.get(code, [])) for code in type_codes}, release.version


def legacy_dictionary_groups(type_codes):
    grouped, version = published_dictionary_groups(type_codes)
    return {
        code: [
            {
                "id": row["id"],
                "item_code": row["code"],
                "display_name": row["label"],
                "english_name": row["english_label"],
                "description": row.get("extra", {}).get("description", ""),
                "sort_order": row["sort_order"],
                "extra_data": {
                    key: value
                    for key, value in row.get("extra", {}).items()
                    if key != "description"
                },
            }
            for row in rows
        ]
        for code, rows in grouped.items()
    }, version


def validate_parameter_value(definition, value):
    if value is None:
        return value
    if definition.value_type in {
        ParameterValueType.STRING,
        ParameterValueType.DATE_FORMAT,
        ParameterValueType.COUNTRY_CODE,
        ParameterValueType.CURRENCY_CODE,
    } and not isinstance(value, str):
        raise ValidationError({"draft_value": "该参数必须是文本。"})
    if definition.value_type == ParameterValueType.INTEGER and (
        not isinstance(value, int) or isinstance(value, bool)
    ):
        raise ValidationError({"draft_value": "该参数必须是整数。"})
    if definition.value_type == ParameterValueType.BOOLEAN and not isinstance(value, bool):
        raise ValidationError({"draft_value": "该参数必须是布尔值。"})
    if definition.value_type == ParameterValueType.COUNTRY_CODE and not Country.objects.filter(
        code=value,
        status=ReferenceStatus.ACTIVE,
        archived_at__isnull=True,
    ).exists():
        raise ValidationError({"draft_value": "国家 / 地区代码不存在或已停用。"})
    if definition.value_type == ParameterValueType.CURRENCY_CODE and not Currency.objects.filter(
        code=value,
        status=ReferenceStatus.ACTIVE,
        archived_at__isnull=True,
    ).exists():
        raise ValidationError({"draft_value": "币种代码不存在或已停用。"})
    rules = definition.validation_rules or {}
    if isinstance(value, int):
        if rules.get("min") is not None and value < rules["min"]:
            raise ValidationError({"draft_value": f"参数值不能小于 {rules['min']}。"})
        if rules.get("max") is not None and value > rules["max"]:
            raise ValidationError({"draft_value": f"参数值不能大于 {rules['max']}。"})
    return value
