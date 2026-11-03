"""BOM 管材单支指标及公式快照；普通保存不刷新历史公式。"""
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP, localcontext
import re

from django.db import connection
from rest_framework.exceptions import ValidationError

from apps.core.api.exceptions import Conflict
from apps.reference_data.tube_formulas import calculate_tube_metrics, get_tube_formula_group, parse_tube_dimensions
from .pipe_material_sync import pipe_parameter_values


METRIC_FIELDS = ("coating_unit_area_sqm", "purchase_unit_weight_kg", "tube_unit_weight_kg",
                 "long_material_unit_weight_kg", "long_material_total_weight_kg")
MANUAL_METRIC_PATTERN = re.compile(r"(?:[0-9]+(?:\.[0-9]{1,4})?|\.[0-9]{1,4})\Z")


def _manual_metric_value(raw_value, field):
    label = "喷塑面积" if field == "coating_unit_area_sqm" else "单支重量"
    text = str(raw_value).strip() if raw_value is not None else ""
    if len(text) > 100 or not MANUAL_METRIC_PATTERN.fullmatch(text):
        raise ValidationError({field: f"请填写非负十进制{label}，最多保留 4 位小数。"})
    value = Decimal(text)
    if not value.is_finite() or value < 0 or value > Decimal("999999999999.9999"):
        raise ValidationError({field: f"{label}必须介于 0 和 999999999999.9999 之间。"})
    return format(value, ".4f")


def tube_metric_inputs(line):
    values = pipe_parameter_values(line.raw_values or {})
    return {**values, "length_value": str(line.length_value or "").strip()}


def supports_tube_metrics(shape):
    if isinstance(shape, str) and shape in {"Φ", "Ф", "φ"}:
        shape = "圆管"
    try:
        get_tube_formula_group(shape)
    except ValidationError:
        return False
    return True


def _current_formula_snapshot(shape):
    from apps.reference_data.models import TubeCalculationFormula

    group = get_tube_formula_group(shape)
    queryset = TubeCalculationFormula.objects.order_by("group_key")
    if connection.in_atomic_block:
        # 三组公式按固定顺序锁定，同一保存事务里的各行使用同一组配置。
        queryset = queryset.select_for_update()
    record = next((record for record in queryset if record.group_key == group), None)
    if record is None:
        raise ValidationError({"tube_shape": "管材计算公式缺失，请先完成生产维护配置。"})
    return {"group_key": record.group_key, "area_expression": record.area_expression,
            "weight_expression": record.weight_expression, "updated_at": record.updated_at.isoformat()}


def _formula_arguments(inputs):
    return {"shape": inputs["tube_shape"], "specification": inputs["tube_diameter"],
            "thickness": inputs["tube_thickness"], "length_mm": inputs["length_value"]}


def apply_tube_metrics(line, *, recalculate=False, require_complete=False, recalculate_total=False,
                       expected_formula_version=None):
    raw = line.raw_values
    if raw.get("tube_metrics_manual") is True:
        for field in ("coating_unit_area_sqm", "purchase_unit_weight_kg"):
            raw[field] = _manual_metric_value(raw.get(field), field)
        raw["tube_unit_weight_kg"] = raw["purchase_unit_weight_kg"]
        raw["long_material_unit_weight_kg"] = ""
        raw["long_material_total_weight_kg"] = ""
        for field in ("tube_formula_snapshot", "tube_formula_inputs", "tube_formula_pending"):
            raw.pop(field, None)
        return
    inputs = tube_metric_inputs(line)
    if inputs["tube_shape"] and not supports_tube_metrics(inputs["tube_shape"]):
        # D 形等本次未覆盖的形状继续沿用原手填流程，不能套用其他形状公式。
        raw.pop("tube_formula_snapshot", None)
        raw.pop("tube_formula_inputs", None)
        raw.pop("tube_formula_pending", None)
        return
    complete = all(inputs.values())
    if not complete:
        if require_complete and raw.get("tube_formula_pending"):
            raise ValidationError({"sections": f"管材类第 {line.line_number} 行请补齐形状、截面、厚度及切割长度后再确认。"})
        if recalculate:
            raw.update({field: "" for field in METRIC_FIELDS})
            raw.pop("tube_formula_snapshot", None)
            raw.pop("tube_formula_inputs", None)
            raw["tube_formula_pending"] = True
        return

    snapshot = raw.get("tube_formula_snapshot")
    if require_complete and raw.get("tube_formula_pending") and not recalculate:
        raise ValidationError({"sections": f"管材类第 {line.line_number} 行请重新应用管材计算后再确认。"})
    if recalculate or snapshot:
        # 几何校验不读取当前配置，旧公式停用或调整不会刷新已保存结果。
        parse_tube_dimensions(**_formula_arguments(inputs))
    if recalculate:
        formula = _current_formula_snapshot(inputs["tube_shape"])
        if expected_formula_version and expected_formula_version != formula["updated_at"]:
            raise Conflict("管材计算公式已更新，请重新打开该管材行，检查计算结果后再应用修改。")
        result = calculate_tube_metrics(**_formula_arguments(inputs), formula=formula)
        raw["coating_unit_area_sqm"] = result["coating_unit_area_sqm"]
        raw["purchase_unit_weight_kg"] = result["purchase_unit_weight_kg"]
        raw["tube_unit_weight_kg"] = result["purchase_unit_weight_kg"]
        raw["tube_formula_snapshot"] = result["formula_snapshot"]
        raw["tube_formula_inputs"] = inputs
        raw.pop("tube_formula_pending", None)
        snapshot = result["formula_snapshot"]

    if snapshot:
        if line.raw_bar_length_m is None:
            raw["long_material_unit_weight_kg"] = ""
            raw["long_material_total_weight_kg"] = ""
            return
        arguments = _formula_arguments(inputs)
        arguments["length_mm"] = Decimal(line.raw_bar_length_m) * 1000
        long_result = calculate_tube_metrics(**arguments, formula=snapshot)
        raw["long_material_unit_weight_kg"] = long_result["purchase_unit_weight_kg"]
    # 无公式快照的旧行只沿用已保存长料单重计算汇总，禁止退回固定 kg/m 系数。
    if (snapshot or recalculate_total) and line.suggested_bar_count is not None and raw.get("long_material_unit_weight_kg"):
        try:
            unit_weight = Decimal(raw["long_material_unit_weight_kg"])
        except (InvalidOperation, TypeError, ValueError) as error:
            raise ValidationError({"sections": f"管材类第 {line.line_number} 行原有长料单重无效，请重新应用管材计算。"}) from error
        if not unit_weight.is_finite() or unit_weight < 0:
            raise ValidationError({"sections": f"管材类第 {line.line_number} 行原有长料单重无效，请重新应用管材计算。"})
        with localcontext() as context:
            context.prec = 64
            total = (unit_weight * line.suggested_bar_count).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
        raw["long_material_total_weight_kg"] = format(total, ".4f")


def tube_calculation_preview(values):
    from .material_flow_calculations import MaterialFlowValueError, pipe_plan, positive_integer

    try:
        positive_integer(values["length_value"], "length_value")
    except MaterialFlowValueError as error:
        raise ValidationError({error.field: str(error)}) from error
    arguments = {"shape": values["tube_shape"], "specification": values["tube_diameter"],
                 "thickness": values["tube_thickness"], "length_mm": values["length_value"]}
    result = calculate_tube_metrics(**arguments)
    result["formula_version"] = result["formula_snapshot"]["updated_at"]
    result["long_material_unit_weight_kg"] = ""
    if values.get("tube_cut_piece_count"):
        try:
            plan = pipe_plan(cutting_length_mm=values["length_value"], pieces_per_product=1,
                             pieces_per_bar=values["tube_cut_piece_count"], order_quantity=1)
        except MaterialFlowValueError as error:
            raise ValidationError({error.field: str(error)}) from error
        arguments["length_mm"] = Decimal(plan["raw_bar_length_m"]) * 1000
        long_result = calculate_tube_metrics(**arguments, formula=result["formula_snapshot"])
        result["long_material_unit_weight_kg"] = long_result["purchase_unit_weight_kg"]
    return {key: result[key] for key in ("coating_unit_area_sqm", "purchase_unit_weight_kg", "long_material_unit_weight_kg", "formula_version")}
