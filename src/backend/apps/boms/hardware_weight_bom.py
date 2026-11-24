"""在选料快照确定后核算五金单重，保留未启用及未变更的历史结果。"""
from copy import deepcopy

from rest_framework.exceptions import ValidationError

from .hardware_weight import calculate_hardware_weight


def apply_hardware_weight(line, data, *, old=None):
    previous = (old.raw_values or {}) if old is not None else {}
    mode = data.get("hardware_weight_mode", previous.get("hardware_weight_mode"))
    if line.section.section_type != "ACCESSORY" or line.section.title.strip() != "五金件":
        if data.get("hardware_weight_mode") == "AUTO" or data.get("hardware_weight_input"):
            raise ValidationError({"hardware_weight_mode": "自动单重仅用于五金件。"})
        return
    if mode is None:
        if data.get("hardware_weight_input"):
            raise ValidationError({"hardware_weight_mode": "请先选择自动计算或手工填写。"})
        return

    raw = line.raw_values
    raw["hardware_weight_mode"] = mode
    if mode == "MANUAL":
        raw.pop("hardware_weight_input", None)
        raw["hardware_weight_snapshot"] = {
            "method": "MANUAL", "material": line.material, "specification": line.specification,
            "unit_material_weight_kg": raw.get("unit_material_weight_kg", ""),
        }
        return

    if (old is not None and "hardware_weight_input" not in data
            and (old.material.strip(), old.specification.strip()) != (line.material.strip(), line.specification.strip())):
        raise ValidationError({"hardware_weight_input": "材质或规格已变更，请重新确认单重计算参数。"})
    supplied = data.get("hardware_weight_input", previous.get("hardware_weight_input"))
    if not supplied:
        raise ValidationError({"hardware_weight_input": "请补齐五金单重计算参数，或切换为手工填写。"})
    # 选料产生的真实材质、规格是权威，不能用预览请求中的旧值覆盖。
    inputs = {key: str(value).strip() for key, value in supplied.items() if value not in (None, "")}
    inputs.update(material=line.material.strip(), specification=line.specification.strip())
    snapshot = previous.get("hardware_weight_snapshot")
    if (previous.get("hardware_weight_mode") == "AUTO" and previous.get("hardware_weight_input") == inputs
            and snapshot and snapshot.get("unit_material_weight_kg")):
        raw["unit_material_weight_kg"] = snapshot["unit_material_weight_kg"]
        raw["hardware_weight_snapshot"] = deepcopy(snapshot)
    else:
        result = calculate_hardware_weight(inputs)
        raw["unit_material_weight_kg"] = result["unit_material_weight_kg"]
        raw["hardware_weight_snapshot"] = result["calculation_snapshot"]
    raw["hardware_weight_input"] = inputs
