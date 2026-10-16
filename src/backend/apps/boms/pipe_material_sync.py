"""按当前完整管材参数规划关联与待建档案，由整单确认服务统一保存。"""
from decimal import Decimal
from uuid import uuid4

from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.products.models import RawMaterialInformation
from apps.reference_data.models import ProductCategory, ProductionUnit
from .material_flow_calculations import MaterialFlowValueError, pipe_plan
from .selectors import pipe_dimension_numbers, pipe_material_dimensions


AUTO_PIPE_SHAPE_PREFIX = "BOM_PIPE_SHAPE_V1:"
PIPE_PARAMETER_FIELDS = ("tube_shape", "tube_diameter", "tube_thickness")
PIPE_LEGACY_COLUMNS = ("E", "F", "G")


def pipe_parameter_values(raw):
    values = {field: str(raw.get(field, raw.get(column, "")) or "").strip()
              for field, column in zip(PIPE_PARAMETER_FIELDS, PIPE_LEGACY_COLUMNS)}
    if values["tube_shape"] in {"Φ", "Ф", "φ"}:
        values["tube_shape"] = "圆管"
    return values


def _number_text(value):
    text = format(value, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def _active_pipes():
    return RawMaterialInformation.objects.filter(
        item_type="MATERIAL", category__item_type="MATERIAL", category__category_name="管材",
        category__status="ACTIVE", category__archived_at__isnull=True, archived_at__isnull=True,
        unit__unit_name="根", unit__status="ACTIVE", unit__archived_at__isnull=True,
    ).select_related("category", "unit").order_by("material_number", "id")


def synchronize_pipe_material(line, *, bom, actor_employee, request, sources, had_parameters=False):
    """仅准备内存中的关联/待建档案；统一确认门禁通过后由保存服务持久化。"""
    raw = line.raw_values
    label = f"管材类第 {line.line_number} 行"
    parameters = pipe_parameter_values(raw)
    diameter_text = parameters["tube_diameter"]
    thickness_text = parameters["tube_thickness"]
    diameter = pipe_dimension_numbers(diameter_text)
    thickness = pipe_dimension_numbers(thickness_text)
    if diameter_text and (not diameter or len(diameter) > 2):
        raise ValidationError({"sections": f"{label}的截面须为有效正数或两个正数尺寸。"})
    if thickness_text and (not thickness or len(thickness) != 1):
        raise ValidationError({"sections": f"{label}的厚度须为有效正数。"})

    shape = parameters["tube_shape"]
    material = line.material.strip()
    complete = (material not in {"", "/", "-", "—"} and shape not in {"", "/", "-", "—"}
                and diameter and thickness and str(line.length_value).strip()
                and str(line.unit_consumption).strip() and str(raw.get("tube_cut_piece_count") or "").strip())
    if not complete:
        if had_parameters or any(parameters.values()) or raw.get("pipe_source_sync_pending"):
            raw["pipe_source_sync_pending"] = True
        return
    try:
        plan = pipe_plan(cutting_length_mm=line.length_value, pieces_per_product=line.unit_consumption,
                         pieces_per_bar=raw["tube_cut_piece_count"], order_quantity=bom.order_quantity)
    except MaterialFlowValueError as error:
        raise ValidationError({"sections": f"{label}：{error}"}) from error
    length_mm = Decimal(plan["raw_bar_length_m"]) * 1000

    candidates = []
    for source in sources:
        if source.material.strip() != material:
            continue
        source_diameter, source_thickness, source_length, source_shape = pipe_material_dimensions(source)
        # 新档案明确记录用户所选形状；历史缺形状档案仅按完整尺寸兼容，不猜物理形状。
        if source.source_unique_check.startswith(AUTO_PIPE_SHAPE_PREFIX):
            source_shape = source.source_unique_check[len(AUTO_PIPE_SHAPE_PREFIX):]
            # 自动建档的 length 明确保存毫米；维护字典里的 D 形等名称无需通用规格解析器认识。
            recorded_length = pipe_dimension_numbers(source.length)
            source_length = recorded_length[0] if recorded_length and len(recorded_length) == 1 else None
        if (source_diameter == diameter and source_thickness == thickness and source_length == length_mm
                and (not source_shape or source_shape == shape)):
            candidates.append(source)
    candidates.sort(key=lambda item: (item.material_number, str(item.pk)))
    current_source_id = str(raw.get("source_inventory_material_id") or "")
    source = next((item for item in candidates if str(item.pk) == current_source_id), None)
    source = source or (candidates[0] if candidates else None)
    if source is None:
        if not request.user.has_perm("products.add_rawmaterialinformation"):
            raise PermissionDenied(f"{label}没有对应原料，当前账号缺少新增原料权限，无法同步保存。")
        category = ProductCategory.objects.filter(item_type="MATERIAL", category_name="管材",
                                                  status="ACTIVE", archived_at__isnull=True).first()
        unit = ProductionUnit.objects.filter(unit_name="根", status="ACTIVE", archived_at__isnull=True).first()
        warehouses = list(_active_pipes().filter(warehouse_name="原料管材仓").exclude(
            warehouse_number="",
        ).order_by().values_list("warehouse_number", "warehouse_name").distinct())
        if category is None or unit is None or len(warehouses) != 1:
            raise ValidationError({"sections": f"{label}无法同步原料，请检查有效管材类别、根单位和原料管材仓。"})
        diameter_value = "*".join(_number_text(value) for value in diameter)
        thickness_value = _number_text(thickness[0])
        length_value = _number_text(length_mm)
        specification = f"{shape} {diameter_value}*{thickness_value}*{length_value}"
        if len(line.part_name) > 200 or len(specification) > 300:
            raise ValidationError({"sections": f"{label}同步原料时品名不能超过 200 字符，规格不能超过 300 字符。"})
        source = RawMaterialInformation(
            material_number=f"GC-{uuid4().hex.upper()}", item_type="MATERIAL", category=category,
            material_name=line.part_name, material=material, specification=specification, unit=unit,
            diameter=diameter_value, thickness=thickness_value, length=length_value,
            warehouse_number=warehouses[0][0], warehouse_name=warehouses[0][1],
            source_unique_check=f"{AUTO_PIPE_SHAPE_PREFIX}{shape}",
            notes=f"由 {bom.bom_number} 管材类第 {line.line_number} 行保存时自动建档。",
        )
        try:
            source.full_clean()
        except DjangoValidationError as error:
            raise ValidationError({"sections": f"{label}原料档案参数无效：{'；'.join(error.messages)}"}) from error
        sources.append(source)
    raw["source_inventory_material_id"] = str(source.pk)
    raw.pop("pipe_source_sync_pending", None)
    line.raw_material = source.material_number
    line.category = source.category.category_name
    line.unit = source.unit.unit_name
    return True
