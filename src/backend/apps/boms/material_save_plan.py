"""整单原料预检和确认：规划阶段只读，确认凭据不在数据库中落地。"""
from copy import copy, deepcopy
from decimal import Decimal
from hashlib import sha256
import json
from uuid import uuid4

from django.core import signing
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.serializers.json import DjangoJSONEncoder
from django.db import connection
from django.db.models import Q
from django.db.models.functions import Trim
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.core.api.concurrency import etag_for_instance
from apps.core.api.exceptions import Conflict
from apps.core.audit import write_audit_log
from apps.products.models import RawMaterialInformation
from apps.reference_data.models import (AccessoryColor, AccessoryMaterial, AccessoryProductName,
    AccessorySpecification, FabricMaterial, FabricSpecification, FabricWidth, ProductCategory,
    ProductColor, ProductionUnit)
from .fabric_material_sync import fabric_parameter_values, synchronize_fabric_material, _specification
from .duplicate_lines import validate_duplicate_material_lines
from .models import BomLine, BomSection
from .pipe_material_sync import pipe_parameter_values, synchronize_pipe_material


SALT = "bom-material-save-confirmation-v1"
SOURCE_FIELDS = ("source_inventory_material_id", "source_raw_material_id",
                 "source_packaging_material_id", "source_cutting_material_id")
REFERENCE_MODELS = (
    ("source_fabric_material_id", FabricMaterial),
    ("source_accessory_material_id", AccessoryMaterial),
    ("source_accessory_product_name_id", AccessoryProductName),
    ("source_accessory_specification_id", AccessorySpecification),
    ("source_accessory_color_id", AccessoryColor),
    ("source_fabric_specification_id", FabricSpecification),
    ("source_fabric_width_id", FabricWidth),
    ("source_product_color_id", ProductColor),
)


class MaterialConfirmationRequired(Conflict):
    api_error_code = "MATERIAL_CREATION_CONFIRMATION_REQUIRED"
    default_detail = "待新增原料尚未确认或预检结果已变化，请重新预检并确认后保存。"


def _digest(value):
    return sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, cls=DjangoJSONEncoder,
                             separators=(",", ":")).encode()).hexdigest()


def _input_digest(request):
    body = {key: value for key, value in request.data.items() if key != "confirmation_token"}
    body.setdefault("intent", "draft")
    return _digest(body)


def require_save_permissions(request, intent):
    if intent == "verify" and not request.user.has_perm("boms.verify_bom"):
        raise PermissionDenied("当前账号没有确认 BOM 的权限。")


def lock_material_references(sections, *, bom):
    # 和原管材同步使用同一个锁，两个 BOM 同时确认相同新身份也只会建一档。
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(hashtextextended('bom-pipe-material-sync-v1', 0))")
    rows = [line for section in sections for line in section["lines"]]
    rows.extend(BomLine.objects.filter(section__bom=bom).values_list("raw_values", flat=True))
    for field, model in REFERENCE_MODELS:
        ids = {line.get(field) for line in rows if line.get(field)}
        list(model.objects.filter(pk__in=ids).order_by("pk").select_for_update())


def _identity(source):
    color = ("color", str(source.color_id)) if source.color_id else ("snapshot", source.color_snapshot.strip())
    return (source.item_type, str(source.category_id), source.material_name.strip(),
            _specification(source.specification), source.material.strip(), str(source.unit_id), color,
            source.is_packaging_auxiliary, source.box_shape)


def _source_data(source):
    # 自动编号、UUID 和追溯备注不属于用户确认的属性；其余实际建档字段必须与预检一致。
    return {field: getattr(source, field) for field in (
        "item_type", "category_id", "material_name", "specification", "unit_id", "color_id",
        "color_snapshot", "material", "warehouse_number", "warehouse_name", "diameter", "length",
        "width", "thickness", "is_packaging_auxiliary", "box_shape", "source_unique_check",
    )}


def _active(source):
    return (source.archived_at is None and source.category.archived_at is None
            and source.category.status == "ACTIVE" and source.unit.archived_at is None
            and source.unit.status == "ACTIVE")


def _validate_source(source, label):
    try:
        source.full_clean()
    except DjangoValidationError as error:
        raise ValidationError({"sections": f"{label}原料档案参数无效：{'；'.join(error.messages)}"}) from error


def _generic_source(proposed, sources, *, request, label, current_id=""):
    matches = sorted((source for source in sources if _active(source) and _identity(source) == _identity(proposed)),
                     key=lambda source: (source.material_number, str(source.pk)))
    source = next((source for source in matches if str(source.pk) == str(current_id)), None)
    if source or matches:
        return source or matches[0]
    if not request.user.has_perm("products.add_rawmaterialinformation"):
        raise PermissionDenied(f"{label}需要新增原料，当前账号缺少新增原料权限。")
    if any(item.material_number == proposed.material_number for item in sources) or RawMaterialInformation.objects.filter(
        material_number=proposed.material_number,
    ).exists():
        raise ValidationError({"sections": f"{label}填写的品号已被其他属性的原料占用。"})
    _validate_source(proposed, label)
    sources.append(proposed)
    return proposed


def _auxiliary_source(line, sources, request):
    raw = line.raw_values
    fields = ("source_accessory_product_name_id", "source_accessory_specification_id",
              "source_accessory_color_id", "source_accessory_material_id")
    if not all(raw.get(field) for field in fields):
        return None
    label = f"辅料类第 {line.line_number} 行"
    category = ProductCategory.objects.filter(category_name="辅料", item_type="MATERIAL",
        status="ACTIVE", archived_at__isnull=True).first()
    unit = ProductionUnit.objects.filter(unit_name=line.unit, status="ACTIVE", archived_at__isnull=True).first()
    if category is None or unit is None:
        raise ValidationError({"sections": f"{label}须使用有效的辅料类别和生产单位。"})
    proposed = RawMaterialInformation(material_number=f"FL-{uuid4().hex.upper()}", item_type="MATERIAL",
        category=category, unit=unit, material_name=line.part_name, specification=_specification(line.specification),
        material=line.material, color_snapshot=str(raw.get("accessory_color") or "").strip())
    matches = [source for source in sources if _active(source) and _identity(source) == _identity(proposed)]
    if not matches:
        warehouses = list(RawMaterialInformation.objects.filter(item_type="MATERIAL", category=category,
            archived_at__isnull=True, warehouse_name="辅料仓").exclude(warehouse_number="").order_by()
            .values_list("warehouse_number", "warehouse_name").distinct())
        if len(warehouses) != 1:
            raise ValidationError({"sections": f"{label}未找到唯一有效的辅料仓，请先核对原料仓库资料。"})
        proposed.warehouse_number, proposed.warehouse_name = warehouses[0]
    return _generic_source(proposed, sources, request=request, label=label,
                           current_id=raw.get("source_inventory_material_id"))


def build_material_save_plan(*, bom, sections, request, for_update=False):
    from .services import _editable_model_values, _merged_raw_values, _tube_specification
    from .material_flow_bom import apply_line_quantities, inherit_cutting_fabric_attributes, is_meter_fabric_section, is_pipe_cutting_line
    from .material_flow_calculations import CUTTING_QUANTITY_FIELDS

    existing = {line.pk: line for line in BomLine.objects.filter(section__bom=bom).select_related("section")}
    source_ids, materials, names = set(), set(), set()
    for section in sections:
        for data in section["lines"]:
            old = existing.get(data.get("id"))
            if data.get("id") and old is None:
                raise ValidationError({"sections": "存在不属于当前 BOM 的用料明细。"})
            source_ids.update(data.get(field) for field in SOURCE_FIELDS if data.get(field))
            if old:
                source_ids.update((old.raw_values or {}).get(field) for field in SOURCE_FIELDS if (old.raw_values or {}).get(field))
            materials.add(str(data.get("material", old.material if old else "")).strip())
            names.add(str(data.get("part_name", old.part_name if old else "")).strip())
    for field, model in REFERENCE_MODELS[:2]:
        ids = {line.get(field) for section in sections for line in section["lines"] if line.get(field)}
        ids.update(line.raw_values.get(field) for line in existing.values() if line.raw_values.get(field))
        source_ids.update(model.objects.filter(pk__in=ids).exclude(inventory_raw_material=None)
                          .values_list("inventory_raw_material_id", flat=True))
    materials.discard("")
    names.discard("")
    queryset = RawMaterialInformation.objects.annotate(
        normalized_material=Trim("material"), normalized_name=Trim("material_name"),
    ).filter(
        Q(pk__in=source_ids) | Q(normalized_material__in=materials) | Q(normalized_name__in=names),
    ).select_related("category", "unit", "color").order_by("pk")
    if for_update:
        queryset = queryset.select_for_update(of=("self",))
    sources = list(queryset)
    pipe_sources = [source for source in sources if _active(source) and source.item_type == "MATERIAL"
                    and source.category.item_type == "MATERIAL" and source.category.category_name == "管材" and source.unit.unit_name == "根"]
    fabric_sources = [source for source in sources if _active(source) and source.item_type == "MATERIAL"
                      and source.category.item_type == "MATERIAL" and source.category.category_name == "面料" and source.unit.unit_name == "米"]
    planned_lines, locations, inputs, lines_by_client_key = {}, {}, {}, {}
    for section_index, section_data in enumerate(sections):
        section = BomSection(bom=bom, title=section_data["title"], section_type=section_data["section_type"])
        for line_number, data in enumerate(section_data["lines"], 1):
            old = existing.get(data.get("id"))
            line = copy(old) if old else BomLine()
            line.section, line.line_number = section, line_number
            values, calculated = _editable_model_values(data, section.section_type, bom.order_quantity,
                                                        existing_line=old, section_title=section.title)
            for field, value in values.items():
                setattr(line, field, value)
            for field in CUTTING_QUANTITY_FIELDS:
                if field in data:
                    setattr(line, field, data[field])
            line.raw_values = _merged_raw_values(deepcopy(old.raw_values) if old else {}, data,
                                                section.section_type, section.title, calculated)
            planned_lines[(section_index, line_number)] = line
            inputs[line.pk] = (data, old)
            if data.get("client_key"):
                lines_by_client_key[data["client_key"]] = line
    lines_by_id = {line.pk: line for line in planned_lines.values()}
    # 先规划面料，再按同次保存的来源属性规划裁片，不能用裁片自填属性判重或建档。
    for line in sorted(planned_lines.values(), key=lambda row: row.section.title.strip() == "裁剪明细"):
        data, old = inputs[line.pk]
        section, line_number = line.section, line.line_number
        pending = data.get("_pending_raw_source")
        if section.title.strip() == "裁剪明细":
            source_key = data.get("fabric_source_client_key")
            source_id = data.get("fabric_source_line_id", None if source_key else line.fabric_source_line_id)
            if source_key and source_id:
                raise ValidationError({"sections": "来源面料不能同时指定已保存行和未保存行。"})
            fabric = lines_by_client_key.get(source_key) if source_key else lines_by_id.get(source_id)
            if (source_key or source_id) and (fabric is None or not is_meter_fabric_section(fabric.section)):
                raise ValidationError({"sections": f"裁剪第 {line_number} 行须选择本 BOM 保留的面料行。"})
            line.fabric_source_line = fabric
            inherit_cutting_fabric_attributes(line)
            if pending is not None and not is_pipe_cutting_line(line):
                pending = copy(pending)
                pending.material = line.material
                pending.color_id = (fabric.raw_values or {}).get("source_product_color_id") if fabric else None
                pending.color_snapshot = line.raw_values["cutting_color"]
        source = None
        if pending is not None:
            source = _generic_source(pending, sources, request=request,
                                     label=f"{section.title}第 {line_number} 行")
        elif section.section_type == "PROFILE":
            if synchronize_pipe_material(line, bom=bom, actor_employee=None, request=request, sources=pipe_sources,
                had_parameters=bool(old and any(pipe_parameter_values(old.raw_values or {}).values()))):
                line.specification = _tube_specification(pipe_parameter_values(line.raw_values))
        elif section.title == "面料类":
            synchronize_fabric_material(line, bom=bom, actor_employee=None, request=request, sources=fabric_sources,
                                        previous_parameters=fabric_parameter_values(old) if old else None)
        elif section.title == "辅料类":
            source = _auxiliary_source(line, sources, request)
        if source:
            line.raw_values["source_inventory_material_id"] = str(source.pk)
            line.raw_material, line.category, line.unit = source.material_number, source.category.category_name, source.unit.unit_name
            # 暂存新增行也保留各分区已有来源字段，刷新后的编辑和图片流程继续使用真实 UUID。
            if pending is not None:
                key = {"五金件": "source_raw_material_id", "塑料件类": "source_raw_material_id",
                       "包材类": "source_packaging_material_id", "裁剪明细": "source_cutting_material_id"}.get(section.title)
                if key:
                    line.raw_values[key] = str(source.pk)
                number_key = {"五金件": "hardware_material_number", "塑料件类": "plastic_material_number",
                              "包材类": "packaging_material_number", "裁剪明细": "cutting_material_number"}.get(section.title)
                if number_key:
                    line.raw_values[number_key] = source.material_number
                if section.title == "五金件":
                    line.raw_values["hardware_flow_unit"] = source.flow_unit or ""
                    if source.flow_unit.strip().upper() == "KG" and Decimal(data.get("unit_material_weight_kg") or "0") <= 0:
                        raise ValidationError({"sections": f"五金件第 {line_number} 行按公斤流转，须填写大于 0 的单个材料重量。"})
        apply_line_quantities(line, bom.order_quantity)
        source_id = line.raw_values.get("source_inventory_material_id")
        if source_id:
            locations.setdefault(str(source_id), []).append({"section_title": section.title, "line_number": line_number})
    new_sources = {str(source.pk): source for source in [*sources, *pipe_sources, *fabric_sources] if source._state.adding}
    entries = []
    for source_id, source in new_sources.items():
        data = _source_data(source)
        entries.append({"key": _digest(data), "item_type": source.item_type, "category_name": source.category.category_name,
            "material_name": source.material_name, "specification": source.specification,
            "color_name": source.color.color_name if source.color_id else source.color_snapshot,
            "color_label": " / ".join(part for part in (source.color.color_card, source.color.color_code,
                source.color.color_name) if part) if source.color_id else source.color_snapshot,
            "width": source.width if source.item_type == "MATERIAL" and source.category.category_name == "面料" else "",
            "material": source.material, "unit_name": source.unit.unit_name, "warehouse_name": source.warehouse_name,
            "locations": locations[source_id]})
    attributes = [{"position": position, "part_name": line.part_name, "material": line.material,
        "specification": line.specification, "unit": line.unit,
        "attributes": {key: value for key, value in line.raw_values.items() if key not in SOURCE_FIELDS
            and not key.endswith("material_number")}}
        for position, line in planned_lines.items()]
    return {"lines": planned_lines, "sources": list(new_sources.values()), "new_materials": entries,
            "attributes_digest": _digest(attributes)}


def material_save_preview(*, bom, sections, request, intent):
    require_save_permissions(request, intent)
    plan = build_material_save_plan(bom=bom, sections=sections, request=request)
    if intent == "verify":
        validate_duplicate_material_lines(plan["lines"].values())
    token = None
    if plan["new_materials"]:
        token = signing.dumps({"bom": str(bom.pk), "user": str(request.user.pk), "etag": etag_for_instance(bom),
            "intent": intent, "input": _input_digest(request), "attributes": plan["attributes_digest"],
            "approved": [item["key"] for item in plan["new_materials"]]}, salt=SALT, compress=True)
    return {"confirmation_token": token, "new_materials": plan["new_materials"]}


def persist_material_plan(*, plan, bom, request, actor_employee, intent, confirmation_token):
    if confirmation_token:
        try:
            confirmation = signing.loads(confirmation_token, salt=SALT, max_age=1800)
        except signing.BadSignature as error:
            raise MaterialConfirmationRequired() from error
        expected = {"bom": str(bom.pk), "user": str(request.user.pk), "etag": etag_for_instance(bom),
                    "intent": intent, "input": _input_digest(request), "attributes": plan["attributes_digest"]}
        if any(confirmation.get(key) != value for key, value in expected.items()):
            raise MaterialConfirmationRequired()
        if not {item["key"] for item in plan["new_materials"]}.issubset(set(confirmation.get("approved", []))):
            raise MaterialConfirmationRequired()
    elif plan["new_materials"]:
        raise MaterialConfirmationRequired()
    for source in plan["sources"]:
        source.save()
        write_audit_log(object_type="RAW_MATERIAL_INFORMATION", object_id=source.pk, action="CREATED",
            context_type="BOM", context_id=bom.pk, actor_employee=actor_employee, request=request,
            after_data={"material_number": source.material_number, **_source_data(source)})
