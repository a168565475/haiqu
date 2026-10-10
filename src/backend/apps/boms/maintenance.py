import re

from apps.reference_data.models import (
    AccessoryColor,
    AccessoryMaterial,
    AccessoryProductName,
    AccessorySpecification,
    FabricMaterial,
    FabricSpecification,
    FabricWidth,
    ProductionUnit,
    ReferenceStatus,
    TubeCoatingColor,
    TubeDiameter,
    TubeMaterial,
    TubeProductName,
    TubeThickness,
)


CONFIGURED_FIELD_LABELS = [
    "物料分类",
    "材质",
    "规格",
    "单位",
    "产品名称",
    "管材厚度",
    "管材直径",
    "涂层颜色",
    "配件名称",
]


def _normalized(value):
    return re.sub(r"[\s×*／/\-_.，,（）()]", "", str(value or "")).replace("Ф", "Φ").upper()


def _active_values(model, field_name):
    return {
        _normalized(value)
        for value in model.objects.filter(status=ReferenceStatus.ACTIVE, archived_at__isnull=True)
        .values_list(field_name, flat=True)
        if value
    }


def _matches(value, candidates, *, contains=False):
    normalized = _normalized(value)
    if not normalized:
        return None
    if normalized in candidates:
        return True
    if contains and any(candidate and (candidate in normalized or normalized in candidate) for candidate in candidates):
        return True
    return False


def match_maintenance_configuration(plan):
    references = {
        "型材名称": _active_values(TubeProductName, "product_name"),
        "型材材质": _active_values(TubeMaterial, "material_name"),
        "管材厚度": _active_values(TubeThickness, "thickness_value"),
        "管材直径": _active_values(TubeDiameter, "diameter_value"),
        "涂层颜色": _active_values(TubeCoatingColor, "color_name"),
        "配件名称": _active_values(AccessoryProductName, "product_name"),
        "配件材质": _active_values(AccessoryMaterial, "material_name"),
        "配件规格": _active_values(AccessorySpecification, "specification_value"),
        "配件颜色": _active_values(AccessoryColor, "color_name"),
        "面料材质": _active_values(FabricMaterial, "material_name"),
        "面料规格": _active_values(FabricSpecification, "specification_name"),
        "面料门幅": _active_values(FabricWidth, "width_value"),
    }
    units = _active_values(ProductionUnit, "unit_code") | _active_values(ProductionUnit, "unit_name")
    checks = []
    seen = set()
    for section in plan["sections"]:
        for line in section["lines"]:
            candidates = []
            raw = line.get("raw_values") or {}
            if section["section_type"] == "PROFILE":
                candidates.extend(
                    [
                        ("型材名称", line["part_name"], references["型材名称"], False),
                        ("型材材质", line["material"], references["型材材质"], False),
                    ]
                )
                candidates.extend(
                    [
                        ("管材直径", raw.get("F", ""), references["管材直径"], False),
                        ("管材厚度", raw.get("G", ""), references["管材厚度"], False),
                    ]
                )
                if line["part_name"] == "塑粉":
                    candidates.append(("涂层颜色", line["specification"], references["涂层颜色"], True))
            elif section["section_type"] == "FABRIC" and section.get("title", "").strip() == "辅料类":
                candidates.extend(
                    [
                        ("配件名称", line["part_name"], references["配件名称"], False),
                        ("配件材质", line["material"], references["配件材质"], False),
                        ("配件规格", line["specification"], references["配件规格"], True),
                        ("配件颜色", raw.get("accessory_color", ""), references["配件颜色"], False),
                    ]
                )
            elif section["section_type"] == "ACCESSORY":
                candidates.extend(
                    [
                        ("配件名称", line["part_name"], references["配件名称"], False),
                        ("配件材质", line["material"], references["配件材质"], False),
                        ("配件规格", line["specification"], references["配件规格"], True),
                    ]
                )
            else:
                candidates.extend(
                    [
                        ("面料材质", line.get("material") or line["raw_material"], references["面料材质"], True),
                        ("面料规格", line.get("specification") or line["raw_material"], references["面料规格"], True),
                        ("面料门幅", raw.get("fabric_width") or line["raw_material"], references["面料门幅"], True),
                    ]
                )
            candidates.append(("单位", line["unit"], units, False))
            for field, value, options, contains in candidates:
                key = (field, _normalized(value))
                if not key[1] or key in seen:
                    continue
                seen.add(key)
                checks.append({"field": field, "value": str(value), "matched": bool(_matches(value, options, contains=contains))})

    unmatched = [{"field": item["field"], "value": item["value"]} for item in checks if not item["matched"]]
    return {
        "configured_field_labels": CONFIGURED_FIELD_LABELS,
        "matched_count": sum(1 for item in checks if item["matched"]),
        "unmatched_count": len(unmatched),
        "unmatched_values": unmatched[:50],
    }
