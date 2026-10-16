"""按面料完整身份规划米制原料，整单确认后保存，不修改材质字典映射。"""
from decimal import Decimal
import re
from uuid import uuid4

from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.products.models import RawMaterialInformation
from apps.reference_data.models import ProductCategory, ProductColor, ProductionUnit


FABRIC_REFERENCE_FIELDS = ("source_fabric_material_id", "source_fabric_specification_id",
                           "source_fabric_width_id", "source_product_color_id")


def _specification(value):
    # 仅统一明确的乘号和两侧空格，不猜单位、字母含义或规格大小写。
    return re.sub(r"\s*[*×]\s*", "*", str(value or "").strip())


def _width(value):
    text = str(value or "").strip()
    if len(text) > 100 or not re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", text):
        return None
    number = Decimal(text)
    return number if number > 0 else None


def fabric_parameter_values(line):
    raw = line.raw_values or {}
    return (line.material.strip(), _specification(line.specification), str(raw.get("fabric_width") or "").strip(),
            *(str(raw.get(field) or "") for field in FABRIC_REFERENCE_FIELDS))


def active_fabric_materials():
    return RawMaterialInformation.objects.filter(
        item_type="MATERIAL", category__item_type="MATERIAL", category__category_name="面料",
        category__status="ACTIVE", category__archived_at__isnull=True, archived_at__isnull=True,
        unit__unit_name="米", unit__status="ACTIVE", unit__archived_at__isnull=True,
    ).select_related("category", "unit", "color")


def synchronize_fabric_material(line, *, bom, actor_employee, request, sources, previous_parameters=None):
    raw = line.raw_values
    parameters = fabric_parameter_values(line)
    # 历史仅库存来源的行仍按原来源使用；不能把旧的展示快照当成新建档参数。
    has_references = any(parameters[3:])
    had_references = bool(previous_parameters and any(previous_parameters[3:]))
    if not has_references and not had_references and not raw.get("fabric_source_sync_pending"):
        return
    label = f"面料类第 {line.line_number} 行"
    material, specification, width_text = parameters[:3]
    width = _width(width_text)
    if width_text and width is None:
        raise ValidationError({"sections": f"{label}的门幅须为有效正数，不含单位。"})
    color_id = raw.get("source_product_color_id")
    try:
        color = ProductColor.objects.filter(pk=color_id).first() if color_id else None
    except DjangoValidationError as error:
        raise ValidationError({"sections": f"{label}的颜色来源无效，请重新选择后保存。"}) from error
    complete = material not in {"", "/", "-", "—"} and specification not in {"", "/", "-", "—"} and width and color
    if not complete:
        changed = previous_parameters is not None and parameters != previous_parameters
        # 新行的字典选择不是历史库存快照，不能借全局材质映射跳过缺失的身份字段。
        if changed or (previous_parameters is None and has_references):
            raw["fabric_source_sync_pending"] = True
        return

    candidates = [source for source in sources
                  if source.material.strip() == material and _specification(source.specification) == specification
                  and _width(source.width) == width and source.color_id == color.pk]
    candidates.sort(key=lambda source: (source.material_number, str(source.pk)))
    current_id = str(raw.get("source_inventory_material_id") or "")
    source = next((source for source in candidates if str(source.pk) == current_id), None)
    source = source or (candidates[0] if candidates else None)
    if source is None:
        if not request.user.has_perm("products.add_rawmaterialinformation"):
            raise PermissionDenied(f"{label}没有对应原料，当前账号缺少新增原料权限，无法同步保存。")
        if color.status != "ACTIVE" or color.archived_at is not None:
            raise ValidationError({"sections": f"{label}的颜色已停用或归档，请重新选择后保存。"})
        category = ProductCategory.objects.filter(item_type="MATERIAL", category_name="面料",
                                                  status="ACTIVE", archived_at__isnull=True).first()
        unit = ProductionUnit.objects.filter(unit_name="米", status="ACTIVE", archived_at__isnull=True).first()
        warehouses = list(active_fabric_materials().filter(warehouse_name="原料布面仓").exclude(
            warehouse_number="",
        ).order_by().values_list("warehouse_number", "warehouse_name").distinct())
        if category is None or unit is None or len(warehouses) != 1:
            raise ValidationError({"sections": f"{label}无法同步原料，请检查有效面料类别、米单位和原料布面仓。"})
        width_value = format(width, "f")
        if "." in width_value:
            width_value = width_value.rstrip("0").rstrip(".")
        source = RawMaterialInformation(
            material_number=f"ML-{uuid4().hex.upper()}", item_type="MATERIAL", category=category,
            material_name="布料", material=material, specification=specification, width=width_value, unit=unit,
            color=color, color_snapshot=color.color_name,
            warehouse_number=warehouses[0][0], warehouse_name=warehouses[0][1],
            notes=f"由 {bom.bom_number} 面料类第 {line.line_number} 行保存时自动建档。",
        )
        try:
            source.full_clean()
        except DjangoValidationError as error:
            raise ValidationError({"sections": f"{label}原料档案参数无效：{'；'.join(error.messages)}"}) from error
        sources.append(source)
    raw["source_inventory_material_id"] = str(source.pk)
    raw.pop("fabric_source_sync_pending", None)
    line.raw_material = source.material_number
    line.category = source.category.category_name
    line.unit = source.unit.unit_name
