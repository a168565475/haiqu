"""BOM 保存、导入、复制和确认共用的材料数量规则。"""
from decimal import Decimal, localcontext

from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework.exceptions import ValidationError

from apps.products.material_identity import DIRECT_RAW_MATERIAL_SOURCE_KEYS, resolve_bom_line_raw_material, resolve_cutting_fabric_material
from apps.reference_data.models import FabricMaterial
from .material_flow_calculations import (
    CUTTING_QUANTITY_FIELDS, MaterialFlowValueError, cutting_quantity_plan, decimal_quantity, pipe_plan, positive_integer,
)

PIPE_FIELDS = ("cutting_length_mm", "pieces_per_product", "pieces_per_bar", "raw_bar_length_m",
               "suggested_bar_count", "suggested_purchase_meters")


def is_meter_fabric_section(section):
    title = "".join(section.title.split())
    return section.section_type == "FABRIC" and not any(word in title for word in ("裁剪", "裁片")) and any(word in title for word in ("面辅料", "面料", "布料"))


def is_pipe_cutting_line(line):
    return "管材" in f"{line.category} {(line.raw_values or {}).get('cutting_category', '')}"


def inherit_cutting_fabric_attributes(line):
    if line.section.title.strip() != "裁剪明细" or is_pipe_cutting_line(line):
        return
    line.raw_values.pop("cutting_material_original", None)
    source = line.fabric_source_line
    source_values = source.raw_values or {} if source is not None else {}
    line.material = source.material if source is not None else ""
    line.raw_values["cutting_color"] = str(
        source_values.get("fabric_color_name") or source_values.get("fabric_color_code") or ""
    ).strip()


def validate_cutting_specification(specification, line_number):
    # 与公共库存身份保持同一占位口径，避免保存后才在入库时发现规格缺失。
    if (specification or "").strip() in {"", "/", "—", "-", "--", "–", "N/A", "n/a", "NULL", "null"}:
        raise ValidationError({"sections": f"“裁剪明细”第 {line_number} 行请填写实际规格，不能使用空白或“/”等占位内容。"})


def apply_line_quantities(line, order_quantity, *, require_complete=False, tolerate_legacy=False, recalculate_pipe=False):
    """旧展示字段只是新规则的投影；导入缺参留待补齐，不能猜每根切割支数。"""
    label = f"{line.section.title}第 {line.line_number} 行"
    if require_complete and line.section.section_type == "PROFILE" and (line.raw_values or {}).get("pipe_source_sync_pending"):
        raise ValidationError({"sections": f"{label}请补齐材质、形状、截面、厚度及切割参数，保存后再确认 BOM。"})
    if require_complete and is_meter_fabric_section(line.section) and (line.raw_values or {}).get("fabric_source_sync_pending"):
        raise ValidationError({"sections": f"{label}请补齐材质、规格、门幅和颜色并保存，自动关联原料后再确认 BOM。"})
    if require_complete and line.section.title.strip() == "裁剪明细":
        validate_cutting_specification(line.specification, line.line_number)
    cutting_values = {field: getattr(line, field) for field in CUTTING_QUANTITY_FIELDS}
    if any(value is not None for value in cutting_values.values()) and line.section.title.strip() != "裁剪明细":
        raise ValidationError({"sections": f"{label}只有裁剪明细可以填写每套片数和每成品套数。"})
    try:
        cutting_plan = cutting_quantity_plan(**cutting_values, order_quantity=order_quantity)
    except MaterialFlowValueError as error:
        # 新字段错误即使在复制或同步时也不能当成旧资料缺参而静默清除。
        raise ValidationError({"sections": f"{label}：{error}"}) from error
    material, _ = resolve_bom_line_raw_material(line)
    expected = ("管材", "根") if line.section.section_type == "PROFILE" else (("面料", "米") if is_meter_fabric_section(line.section) else None)
    if expected and material and not tolerate_legacy:
        if (material.item_type != "MATERIAL" or material.category.category_name != expected[0]
                or material.unit.unit_name != expected[1] or material.unit.status != "ACTIVE"
                or material.unit.archived_at is not None or material.category.status != "ACTIVE"
                or material.category.archived_at is not None):
            raise ValidationError({"sections": f"{label}须关联有效的{expected[0]}原料，库存单位为{expected[1]}。"})
    try:
        if line.section.section_type == "PROFILE":
            inputs = {"cutting_length_mm": line.length_value, "pieces_per_product": line.unit_consumption,
                      "pieces_per_bar": (line.raw_values or {}).get("tube_cut_piece_count", "")}
            for field, value in inputs.items():
                if str(value or "").strip():
                    positive_integer(value, field)
            line.total_consumption = str(positive_integer(positive_integer(inputs["pieces_per_product"], "pieces_per_product") * positive_integer(order_quantity, "order_quantity"), "demand_pieces")) if str(inputs["pieces_per_product"] or "").strip() else ""
            if not all(str(value or "").strip() for value in inputs.values()):
                if require_complete:
                    raise ValidationError({"sections": f"{label}请补齐整数切割长度、单耗和每根切割支数。"})
                snapshot = None
            else:
                inputs_changed = any(positive_integer(value, field) != getattr(line, field)
                                     for field, value in inputs.items())
                version = 3 if recalculate_pipe or inputs_changed else (line.raw_values or {}).get("pipe_plan_version", 2)
                snapshot = pipe_plan(**inputs, order_quantity=order_quantity, calculation_version=version)
            for field in PIPE_FIELDS:
                setattr(line, field, snapshot[field] if snapshot else None)
            line.branch_count = str(snapshot["suggested_bar_count"]) if snapshot else ""
            line.original_material_length = snapshot["raw_bar_length_m"] if snapshot else ""
            line.total_purchase_quantity = snapshot["suggested_purchase_meters"] if snapshot else ""
            line.raw_values = {**(line.raw_values or {}), "tube_cut_length_m": line.original_material_length}
            if snapshot:
                if snapshot.get("calculation_version", 2) == 3:
                    line.raw_values["pipe_plan_version"] = 3
                line.length_value = str(snapshot["cutting_length_mm"])
                line.unit_consumption = str(snapshot["pieces_per_product"])
                line.total_consumption = str(snapshot["demand_pieces"])
                line.raw_values["tube_cut_piece_count"] = str(snapshot["pieces_per_bar"])
                with localcontext() as ctx:
                    ctx.prec = 64
                    length = Decimal(snapshot["raw_bar_length_m"])
                    coefficient = Decimal("0.464")
                    weights = {"long_material_unit_weight_kg": length * coefficient,
                               "tube_unit_weight_kg": Decimal(snapshot["cutting_length_mm"]) * snapshot["pieces_per_product"] * coefficient / 1000,
                               "long_material_total_weight_kg": length * snapshot["suggested_bar_count"] * coefficient}
                    line.raw_values.update({key: format(value.quantize(Decimal("0.0001")), "f").rstrip("0").rstrip(".") or "0" for key, value in weights.items()})
            else:
                line.raw_values.update({key: "" for key in ("long_material_unit_weight_kg", "tube_unit_weight_kg", "long_material_total_weight_kg")})
            line.unit = "根"
        else:
            for field in PIPE_FIELDS:
                setattr(line, field, None)
            if cutting_plan is not None:
                line.cut_piece_quantity = str(cutting_plan["cutting_pieces_per_set"])
                line.unit = "套"
                # 历史耗米保留供旧单据追溯；裁片数量不再计算或覆盖原料米数。
                line.total_purchase_quantity = ""
            # FABRIC 同时包括辅料和裁片，只有明确的面料类按米计算。
            if is_meter_fabric_section(line.section):
                line.unit = "米"
                if line.unit_consumption.strip():
                    consumption = decimal_quantity(line.unit_consumption, "unit_consumption")
                    with localcontext() as ctx:
                        ctx.prec = 64
                        total = decimal_quantity(consumption * Decimal(order_quantity), "total_purchase_quantity")
                    line.total_consumption = format(total, "f")
                    line.total_purchase_quantity = format(total, "f")
                elif require_complete:
                    raise ValidationError({"sections": f"{label}请填写每个成品的面料耗米。"})
                else:
                    line.total_consumption = line.total_purchase_quantity = ""
    except MaterialFlowValueError as error:
        if not tolerate_legacy:
            raise ValidationError({"sections": f"{label}：{error}"}) from error
        for field in PIPE_FIELDS:
            setattr(line, field, None)
        line.branch_count = line.original_material_length = line.total_purchase_quantity = ""
        line.raw_values = {**(line.raw_values or {}), "tube_cut_length_m": ""}
    if require_complete and line.section.title.strip() != "裁剪明细":
        if line.section.title.strip() == "辅料类" and material is None:
            raise ValidationError({"sections": f"{label}尚未关联库存原料，请保存 BOM 以自动关联原料。"})
        if (expected and (material is None or material.item_type != "MATERIAL")) or not line.unit.strip() or line.unit.strip() in {"-", "—", "/"}:
            if line.section.section_type == "PROFILE" and material is None:
                raise ValidationError({"sections": f"{label}尚未关联有效管材原料，请补齐管材参数并保存，系统会自动关联原料。"})
            if is_meter_fabric_section(line.section) and material is None:
                raise ValidationError({"sections": f"{label}尚未关联有效面料原料，请补齐材质、规格、门幅和颜色并保存，系统会自动关联原料。"})
            raise ValidationError({"sections": f"{label}请关联有效原材料并补齐单位。"})


def validate_fabric_links(lines, *, require_complete=False):
    current = {line.pk: line for line in lines}
    for line in lines:
        if line.section.title.strip() != "裁剪明细":
            if line.fabric_source_line_id:
                raise ValidationError({"sections": "只有裁剪明细可以设置来源面料。"})
            continue
        if line.fabric_source_line_id:
            source = current.get(line.fabric_source_line_id)
            if (source is None or source.section.bom_id != line.section.bom_id
                    or not is_meter_fabric_section(source.section)):
                raise ValidationError({"sections": f"裁剪第 {line.line_number} 行须选择本 BOM 保留的面料行。"})
            line.fabric_source_line = source
            material, error = resolve_cutting_fabric_material(line)
            if error or material is None:
                source_values = source.raw_values or {}
                # 草稿允许尚未建立库存映射；已填但失效的原料、错误来源及正式确认仍须拦截。
                unmapped_draft = (not require_complete and not source.fabric_source_line_id
                                  and not any(source_values.get(key) for key in DIRECT_RAW_MATERIAL_SOURCE_KEYS)
                                  and not source_values.get("source_accessory_material_id"))
                if unmapped_draft and source_values.get("source_fabric_material_id"):
                    try:
                        unmapped_draft = FabricMaterial.objects.filter(
                            pk=source_values["source_fabric_material_id"], archived_at__isnull=True,
                            inventory_raw_material_id__isnull=True,
                        ).exists()
                    except (DjangoValidationError, TypeError, ValueError):
                        unmapped_draft = False
                if not unmapped_draft:
                    raise ValidationError({"sections": f"裁剪第 {line.line_number} 行的来源面料第 {source.line_number} 行未关联有效米制面料原料，请补齐该面料行的材质、规格、门幅和颜色后保存。"})
        if require_complete and not line.fabric_source_line_id:
            raise ValidationError({"sections": f"裁剪第 {line.line_number} 行请关联来源面料。"})


def validate_used_components(bom, lines):
    """确认只检查已使用额度，不提前建账；即使删除全部管材也必须检查谱系。"""
    from apps.material_issues.models import OrderMaterialRequirement
    components = {line.component_identity: line for line in lines if line.section.section_type == "PROFILE"}
    if len(components) != sum(line.section.section_type == "PROFILE" for line in lines):
        raise ValidationError({"sections": "当前 BOM 存在重复部位编号。"})
    for requirement in OrderMaterialRequirement.objects.select_for_update().filter(production_task_id=bom.production_task_id).order_by("pk"):
        used = requirement.internal_issued_quantity + requirement.outsourcing_issued_quantity
        if not used:
            continue
        if requirement.measurement_kind == "OTHER" and requirement.section_code == "PROFILE":
            raise ValidationError({"sections": "存在旧口径管材发料，无法自动继承部位，请先处理历史来源。"})
        if requirement.measurement_kind != "PIPE" or requirement.product_line_id != bom.product_line_id:
            continue
        line = components.get(requirement.component_identity)
        if line is None:
            raise ValidationError({"sections": "不能删除已经发料的管材部位，也不能用新部位替代其历史额度。"})
        material, _ = resolve_bom_line_raw_material(line)
        previous = requirement.contributions.order_by("-created_at").first()
        old_length = (previous.calculation_basis or {}).get("cutting_length_mm") if previous else None
        if (material is None or material.pk != requirement.raw_material_id
                or line.pieces_per_bar != requirement.pieces_per_bar
                or Decimal(line.raw_bar_length_m) != requirement.raw_bar_length_m
                or old_length != line.cutting_length_mm
                or line.suggested_bar_count * line.pieces_per_bar < used):
            raise ValidationError({"sections": "该部位已经发料，不能修改原料、切割参数或将额度减至已发支数以下。"})
