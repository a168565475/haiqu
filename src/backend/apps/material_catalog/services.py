from django.db import IntegrityError, transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.core.api.concurrency import etag_for_instance, require_matching_etag
from apps.core.audit import write_audit_log
from apps.reference_data.models import ProductionUnit

from .definitions import SPRAY_FIELDS, TEMPLATES
from .models import MaterialAllowedUnit, MaterialAttributeValue, MaterialCatalog, MaterialScope
from .selectors import catalog_detail


def _locked_catalog(catalog_id, request):
    catalog = get_object_or_404(
        MaterialCatalog.objects.select_for_update(), pk=catalog_id, archived_at__isnull=True
    )
    require_matching_etag(request, catalog)
    return catalog


def _scope_fields(catalog, scope):
    if scope == MaterialScope.BASE:
        return TEMPLATES[catalog.template_key]["fields"]
    if scope == MaterialScope.SPRAY and catalog.spray_enabled and TEMPLATES[catalog.template_key]["supports_spray"]:
        return SPRAY_FIELDS
    raise ValidationError({"scope": "该物料未启用所选属性组。"})


def _snapshot_response(catalog):
    return catalog_detail(catalog), etag_for_instance(catalog)


def _finish_change(catalog, before, action, request):
    # 子项变更也刷新主档版本；前端始终以整份档案的 ETag 串行写入。
    catalog.save(update_fields=["spray_enabled", "updated_at"])
    after, etag = _snapshot_response(catalog)
    write_audit_log(
        object_type="MATERIAL_CATALOG", object_id=catalog.pk, action=action,
        actor_employee=getattr(request, "employee", None),
        before_data=before, after_data=after, request=request,
    )
    return after, etag


def _archive(option, request):
    option.archived_at = timezone.now()
    option.archived_by_employee = getattr(request, "employee", None)
    option.archive_reason = "从原料管理移除可选值"
    option.save(update_fields=["archived_at", "archived_by_employee", "archive_reason", "updated_at"])


def _restore(option):
    option.archived_at = None
    option.archived_by_employee = None
    option.archive_reason = ""
    option.save(update_fields=["archived_at", "archived_by_employee", "archive_reason", "updated_at"])


def create_catalog(*, data, request):
    try:
        with transaction.atomic():
            catalog = MaterialCatalog.objects.create(**data)
            if any(field["key"] == "color" for field in TEMPLATES[catalog.template_key]["fields"]):
                MaterialAttributeValue.objects.create(catalog=catalog, scope=MaterialScope.BASE, field_key="color", value="无颜色")
            after, etag = _snapshot_response(catalog)
            write_audit_log(
                object_type="MATERIAL_CATALOG", object_id=catalog.pk, action="CREATED",
                actor_employee=getattr(request, "employee", None), after_data=after, request=request,
            )
            return after, etag
    except IntegrityError as exc:
        if getattr(getattr(exc.__cause__, "diag", None), "constraint_name", None) == "mat_catalog_category_name_uniq":
            raise ValidationError({"name": "该类别下已存在相同品名。"}) from exc
        raise


@transaction.atomic
def set_spray(*, catalog_id, enabled, request):
    catalog = _locked_catalog(catalog_id, request)
    if enabled and not TEMPLATES[catalog.template_key]["supports_spray"]:
        raise ValidationError({"spray_enabled": "只有管材和五金支持喷塑属性。"})
    before = catalog_detail(catalog)
    catalog.spray_enabled = enabled
    # 包含软删记录，避免重复开启时擅自恢复用户已经移除的默认颜色。
    if enabled and not catalog.attribute_values.filter(scope=MaterialScope.SPRAY).exists():
        MaterialAttributeValue.objects.create(catalog=catalog, scope=MaterialScope.SPRAY, field_key="color", value="无颜色")
    return _finish_change(catalog, before, "SPRAY_CHANGED", request)


@transaction.atomic
def add_value(*, catalog_id, data, request):
    catalog = _locked_catalog(catalog_id, request)
    fields = _scope_fields(catalog, data["scope"])
    definition = next((field for field in fields if field["key"] == data["field_key"] and field["kind"] != "unit"), None)
    if definition is None:
        raise ValidationError({"field_key": "该属性不在当前类别及属性组的固定名单中。"})
    parent_id = data.get("parent_id")
    if definition["kind"] == "dimension":
        if parent_id is None or not catalog.attribute_values.filter(
            pk=parent_id, scope=MaterialScope.BASE, field_key="shape", archived_at__isnull=True
        ).exists():
            raise ValidationError({"parent_id": "截面尺寸必须选择本物料有效的截面形状。"})
    elif parent_id is not None:
        raise ValidationError({"parent_id": "只有截面尺寸可以关联截面形状。"})
    before = catalog_detail(catalog)
    values = {"catalog": catalog, "scope": data["scope"], "field_key": data["field_key"], "value": data["value"], "parent_id": parent_id}
    existing = MaterialAttributeValue.objects.filter(**values).first()
    if existing is not None:
        if existing.archived_at is None:
            raise ValidationError({"value": "该属性值已存在。"})
        _restore(existing)
        action = "VALUE_RESTORED"
    else:
        MaterialAttributeValue.objects.create(**values)
        action = "VALUE_ADDED"
    return _finish_change(catalog, before, action, request)


@transaction.atomic
def remove_value(*, catalog_id, value_id, request):
    catalog = _locked_catalog(catalog_id, request)
    option = get_object_or_404(MaterialAttributeValue, pk=value_id, catalog=catalog, archived_at__isnull=True)
    _scope_fields(catalog, option.scope)
    if option.dimensions.filter(archived_at__isnull=True).exists():
        raise ValidationError({"parent_id": "该形状仍有截面尺寸，请先逐项移除尺寸。"})
    before = catalog_detail(catalog)
    _archive(option, request)
    return _finish_change(catalog, before, "VALUE_REMOVED", request)


@transaction.atomic
def add_unit(*, catalog_id, data, request):
    catalog = _locked_catalog(catalog_id, request)
    _scope_fields(catalog, data["scope"])
    unit = ProductionUnit.objects.filter(pk=data["unit_id"], status="ACTIVE", archived_at__isnull=True).first()
    if unit is None:
        raise ValidationError({"unit_id": "单位不存在、已停用或已归档。"})
    before = catalog_detail(catalog)
    existing = MaterialAllowedUnit.objects.filter(catalog=catalog, scope=data["scope"], unit=unit).first()
    if existing is not None:
        if existing.archived_at is None:
            raise ValidationError({"unit_id": "该属性组已包含此可用单位。"})
        _restore(existing)
        action = "UNIT_RESTORED"
    else:
        MaterialAllowedUnit.objects.create(catalog=catalog, scope=data["scope"], unit=unit)
        action = "UNIT_ADDED"
    return _finish_change(catalog, before, action, request)


@transaction.atomic
def remove_unit(*, catalog_id, option_id, request):
    catalog = _locked_catalog(catalog_id, request)
    option = get_object_or_404(MaterialAllowedUnit, pk=option_id, catalog=catalog, archived_at__isnull=True)
    _scope_fields(catalog, option.scope)
    before = catalog_detail(catalog)
    _archive(option, request)
    return _finish_change(catalog, before, "UNIT_REMOVED", request)
