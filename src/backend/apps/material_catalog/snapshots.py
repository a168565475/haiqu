"""新业务创建时冻结所选材料内容；下游复制快照，不能重新读取目录覆盖。"""
import hashlib
import json
from uuid import UUID

from rest_framework.exceptions import ValidationError

from .definitions import SPRAY_FIELDS, TEMPLATES
from .colors import COLOR_FIELDS, color_metadata, uses_product_color_identity
from .models import MaterialScope


def build_material_snapshot(*, catalog, scope, processing_state, attributes, unit_id, required_fields, completed_craft=None, semi_kind=None, product_color=None):
    if catalog.archived_at is not None:
        raise ValidationError({"material_catalog_id": "原料品名已归档。"})
    if scope not in MaterialScope.values or (scope == MaterialScope.SPRAY and not catalog.spray_enabled):
        raise ValidationError({"scope": "该品名未启用所选属性组。"})
    fields = {field["key"]: MaterialScope.BASE for field in TEMPLATES[catalog.template_key]["fields"] if field["kind"] != "unit"}
    if scope == MaterialScope.SPRAY:
        fields.update({field["key"]: MaterialScope.SPRAY for field in SPRAY_FIELDS if field["kind"] != "unit"})
    if not isinstance(attributes, dict) or not attributes or any(key not in fields for key in attributes):
        raise ValidationError({"attributes": "包含当前品名不支持的属性。"})
    selected = {}
    for key, value in attributes.items():
        if not isinstance(value, str) or not value.strip() or len(value.strip()) > 300:
            raise ValidationError({"attributes": f"{key}必须为非空属性文字，且不超过300字。"})
        selected[key] = value.strip()
    # 维护档案允许逐步补选项；业务入口沿用自己的必要字段，不能把可选字段全部强制必填。
    if not set(required_fields).issubset(fields):
        raise ValueError("调用方的必要属性不属于当前模板。")
    missing = [key for key in required_fields if not selected.get(key) or selected[key] in {"/", "-", "—"}]
    if missing:
        raise ValidationError({"attributes": "缺少具体材料必要属性：" + "、".join(missing)})
    values = list(catalog.attribute_values.filter(archived_at__isnull=True))
    if product_color is not None and (not uses_product_color_identity(catalog, scope)
            or product_color.color_name != selected.get("color")):
        raise ValidationError({"product_color_id": "普通颜色与当前基础属性不匹配。"})
    shape = next((row for row in values if row.scope == MaterialScope.BASE and row.field_key == "shape" and row.value == selected.get("shape")), None)
    for key, value in selected.items():
        if not any(row.scope == fields[key] and row.field_key == key and
                   (row.product_color_id == product_color.pk if key == "color" and product_color is not None
                    else row.product_color_id is None and row.value == value) and
                   (key != "section_size" or (shape is not None and row.parent_id == shape.pk)) for row in values):
            raise ValidationError({"attributes": f"{key}不是当前品名/形状的有效选项，请先在同一事务中补录。"})
    option = catalog.allowed_units.filter(scope=scope, unit_id=unit_id, archived_at__isnull=True,
                                          unit__status="ACTIVE", unit__archived_at__isnull=True).select_related("unit").first()
    if option is None:
        raise ValidationError({"unit_id": "请选择当前品名与属性组的有效单位。"})
    if processing_state not in {"RAW", "PROCESSED"}:
        raise ValidationError({"processing_state": "请选择明确的原料或加工结果状态。"})
    if catalog.category_key == "FABRIC_SEMI" and processing_state != "PROCESSED":
        raise ValidationError({"processing_state": "裁片须保留实际加工结果状态。"})
    processed = processing_state == "PROCESSED"
    # 目录范围不是已完成工艺；加工调用方沿用既有库存工艺校验及车缝归并规则。
    craft = None
    if processed:
        if not isinstance(completed_craft, dict) or set(completed_craft) != {"id", "craft_type", "code"}:
            raise ValidationError({"completed_craft": "半成品须提供既有工艺ID、类型和代码。"})
        try:
            craft_id = str(UUID(str(completed_craft["id"])))
        except (ValueError, TypeError, AttributeError) as exc:
            raise ValidationError({"completed_craft": "已完成工艺ID无效。"}) from exc
        if completed_craft["craft_type"] not in {"INTERNAL", "EXTERNAL"} or not isinstance(completed_craft["code"], str) or not completed_craft["code"].strip():
            raise ValidationError({"completed_craft": "已完成工艺类型或代码无效。"})
        if semi_kind not in {"PIPE", "CUTTING", "HARDWARE"}:
            raise ValidationError({"semi_kind": "半成品须提供既有种类。"})
        craft = {"id": craft_id, "craft_type": completed_craft["craft_type"], "code": completed_craft["code"].strip()}
    elif completed_craft is not None or semi_kind is not None:
        raise ValidationError({"completed_craft": "原料不能伪造已完成工艺。"})
    display_values = [" ".join(filter(None, (product_color.color_card, product_color.color_code, product_color.color_name)))
                      if key == "color" and product_color is not None else value for key, value in selected.items()]
    return {
        "schema_version": 1, "catalog_id": str(catalog.pk), "catalog_version": catalog.updated_at.isoformat(),
        "category_key": catalog.category_key, "template_key": catalog.template_key, "name": catalog.name,
        "scope": scope, "processing_state": "PROCESSED" if processed else "RAW",
        "processing_stage": craft["code"] if craft else "RAW", "completed_craft": craft, "semi_kind": semi_kind,
        "attributes": selected, "unit_id": str(option.unit_id), "unit_name": option.unit.unit_name,
        "display_name": " / ".join([catalog.name, *display_values, option.unit.unit_name]),
        **(color_metadata(product_color) if product_color is not None else {}),
    }


def material_identity_key(snapshot):
    """仓库、库区、品质仍由库存层作为独立维度；来源与目录版本不参与材料身份。"""
    content = {key: snapshot[key] for key in ("catalog_id", "processing_state", "processing_stage", "completed_craft", "semi_kind", "attributes", "unit_id")}
    if snapshot.get("product_color_id"):
        # 新颜色身份参与区分；旧快照没有此标识时仍使用原算法，不能重算改变旧库存身份。
        content.update({key: snapshot.get(key, "") for key in COLOR_FIELDS})
    encoded = json.dumps(content, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf8")).hexdigest()
