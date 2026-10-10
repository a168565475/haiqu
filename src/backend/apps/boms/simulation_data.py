"""真实流程模拟数据使用的 BOM 明细构造器。

只复用已经启用的生产维护/原料资料，不创建新的主数据。
"""

from collections import Counter, defaultdict

from django.core.exceptions import ValidationError

from apps.products.models import RawMaterialInformation
from apps.reference_data.models import ProductItemType, ReferenceStatus

from .models import BomSectionType


BOM_SIMULATION_COUNT_RANGES = {
    "管材类": (5, 8),
    "五金件": (10, 15),
    "塑料件类": (7, 9),
    "裁剪明细": (3, 9),
    "面料类": (1, 3),
    "辅料类": (5, 9),
    "包材类": (1, 1),
}

BOM_SIMULATION_SECTION_TYPES = {
    "管材类": BomSectionType.PROFILE,
    "五金件": BomSectionType.ACCESSORY,
    "塑料件类": BomSectionType.ACCESSORY,
    "裁剪明细": BomSectionType.FABRIC,
    "面料类": BomSectionType.FABRIC,
    "辅料类": BomSectionType.FABRIC,
    "包材类": BomSectionType.ACCESSORY,
}


def summarize_bom_simulation_sections(boms, *, expected_bom_count):
    """逐份校验七个分区的标题、类型、唯一性和明细数量。"""
    counts_by_title = defaultdict(list)
    expected_pairs = set(BOM_SIMULATION_SECTION_TYPES.items())
    all_boms_have_unique_sections = True
    for bom in boms:
        sections = list(bom.sections.all())
        section_counts = Counter(
            (section.title.strip(), section.section_type) for section in sections
        )
        if set(section_counts) != expected_pairs or any(
            count != 1 for count in section_counts.values()
        ):
            all_boms_have_unique_sections = False
        for title, section_type in BOM_SIMULATION_SECTION_TYPES.items():
            matching = [
                section
                for section in sections
                if section.title.strip() == title and section.section_type == section_type
            ]
            if len(matching) == 1:
                counts_by_title[title].append(matching[0].lines.count())

    ranges = {
        title: {
            "minimum": min(values) if values else 0,
            "maximum": max(values) if values else 0,
            "bom_count": len(values),
            "expected_minimum": expected[0],
            "expected_maximum": expected[1],
        }
        for title, expected in BOM_SIMULATION_COUNT_RANGES.items()
        for values in [counts_by_title.get(title, [])]
    }
    ranges_valid = all(
        data["bom_count"] == expected_bom_count
        and data["minimum"] >= data["expected_minimum"]
        and data["maximum"] <= data["expected_maximum"]
        for data in ranges.values()
    )
    return {
        "counts_by_title": counts_by_title,
        "ranges": ranges,
        "all_valid": all_boms_have_unique_sections and ranges_valid,
    }


def bom_simulation_counts(index):
    """用固定轮转生成可复核且覆盖完整区间的明细数量。"""
    offset = index - 1
    return {
        title: minimum + offset % (maximum - minimum + 1)
        for title, (minimum, maximum) in BOM_SIMULATION_COUNT_RANGES.items()
    }


def _active_raw_materials(category_name, *, item_type=ProductItemType.MATERIAL):
    return list(
        RawMaterialInformation.objects.filter(
            item_type=item_type,
            category__category_name=category_name,
            category__item_type=item_type,
            category__status=ReferenceStatus.ACTIVE,
            category__archived_at__isnull=True,
            unit__status=ReferenceStatus.ACTIVE,
            unit__archived_at__isnull=True,
            archived_at__isnull=True,
        ).exclude(unit__unit_name__in=("", "-", "—", "/"))
        .select_related("category", "unit", "color")
        .order_by("material_number", "id")
    )


def load_bom_simulation_catalog():
    fabric_materials = [
        material
        for material in _active_raw_materials("面料")
        if material.unit.unit_name == "米"
    ]
    catalog = {
        "profile": _active_raw_materials("管材"),
        "hardware": _active_raw_materials("五金"),
        "plastic": _active_raw_materials("塑料件"),
        "auxiliary": _active_raw_materials("辅料"),
        # “面料类”按米采购；“裁片”等套/张单位资料只能用于裁剪明细，
        # 不能作为面料采购行，否则 BOM 保存会被单位门禁拒绝。
        "fabric": fabric_materials,
        "packaging": _active_raw_materials("包材"),
        "cutting": list(
            RawMaterialInformation.objects.filter(
                item_type=ProductItemType.SEMI_FINISHED,
                category__item_type=ProductItemType.SEMI_FINISHED,
                category__status=ReferenceStatus.ACTIVE,
                category__archived_at__isnull=True,
                unit__status=ReferenceStatus.ACTIVE,
                unit__archived_at__isnull=True,
                archived_at__isnull=True,
            ).exclude(unit__unit_name__in=("", "-", "—", "/"))
            .select_related("category", "unit", "color")
            .order_by("category__sort_order", "material_number", "id")
        ),
    }
    missing = [key for key, rows in catalog.items() if not rows]
    if missing:
        raise ValidationError(f"BOM 模拟数据缺少可用主数据：{', '.join(missing)}。")
    return catalog


def _pick(rows, index, line_number):
    return rows[((index - 1) * 17 + line_number - 1) % len(rows)]


def build_bom_simulation_sections(*, bom, index, catalog):
    counts = bom_simulation_counts(index)
    existing_sections = {
        (section.title.strip(), section.section_type): section
        for section in bom.sections.all()
    }

    def section_identity(title, section_type):
        existing = existing_sections.get((title, section_type))
        return {"id": existing.pk} if existing else {}

    profile_lines = []
    for line_number in range(1, counts["管材类"] + 1):
        source = _pick(catalog["profile"], index, line_number)
        diameter = source.diameter.strip()
        tube_shape = "矩形管" if "*" in diameter else "圆管"
        profile_lines.append(
            {
                "category": source.category.category_name,
                "material": source.material,
                "part_name": source.material_name,
                "specification": source.specification,
                "raw_material": source.material_number,
                "source_inventory_material_id": source.pk,
                "length_value": str(360 + line_number * 45 + index % 5 * 10),
                "unit_consumption": str(1 + line_number % 3),
                "unit": source.unit.unit_name,
                "tube_shape": tube_shape,
                "tube_diameter": diameter,
                "tube_thickness": source.thickness,
                "tube_coating_color": (
                    source.color.color_name if source.color_id else source.color_snapshot
                ),
                "coating_unit_area_sqm": "0.12",
                "purchase_unit_weight_kg": source.weight_kg,
                "tube_cut_piece_count": str(6 + line_number % 5),
                "notes": (
                    f"流程模拟 BOM 第 {index:03d} 套型材；"
                    f"来源于管材原料档案。"
                ),
            }
        )

    hardware_lines = []
    for line_number in range(1, counts["五金件"] + 1):
        source = _pick(catalog["hardware"], index, line_number)
        hardware_lines.append(
            {
                "part_name": source.material_name,
                "source_raw_material_id": source.pk,
                "unit_consumption": str(2 + line_number % 4),
                "unit_material_weight_kg": source.weight_kg or "0.10",
                "powder_coating_color": "黑色" if line_number % 2 else "白色",
                "powder_coating_unit_area_sqm": "0.03",
                "notes": "来源于五金原料资料。",
            }
        )

    plastic_lines = []
    for line_number in range(1, counts["塑料件类"] + 1):
        source = _pick(catalog["plastic"], index, line_number)
        plastic_lines.append(
            {
                "part_name": source.material_name,
                "source_raw_material_id": source.pk,
                "unit_consumption": str(1 + line_number % 3),
                "notes": "来源于塑料件原料资料。",
            }
        )

    auxiliary_lines = []
    for line_number in range(1, counts["辅料类"] + 1):
        source = _pick(catalog["auxiliary"], index, line_number)
        auxiliary_lines.append(
            {
                "part_name": source.material_name,
                "source_inventory_material_id": source.pk,
                "source_accessory_product_name_id": None,
                "source_accessory_specification_id": None,
                "source_accessory_color_id": None,
                "source_accessory_material_id": None,
                "purchase_consumption": f"{0.2 + (line_number % 4) * 0.1:.1f}",
                "notes": "来源于辅料原料档案。",
            }
        )

    fabric_lines = []
    for line_number in range(1, counts["面料类"] + 1):
        source = _pick(catalog["fabric"], index, line_number)
        fabric_lines.append(
            {
                "part_name": source.material_name,
                "source_inventory_material_id": source.pk,
                "source_fabric_material_id": None,
                "source_fabric_specification_id": None,
                "source_fabric_width_id": None,
                "source_product_color_id": None,
                "unit_consumption": f"{0.6 + line_number * 0.15:.2f}",
                "purchase_consumption": f"{0.6 + line_number * 0.15:.2f}",
                "notes": "来源于面料原料档案。",
            }
        )

    packaging_source = _pick(catalog["packaging"], index, 1)
    packaging_lines = [
        {
            "part_name": packaging_source.material_name,
            "source_packaging_material_id": packaging_source.pk,
            "units_per_box": str(4 + index % 5),
            "unit_consumption": "1",
            "notes": "每个 BOM 固定一项包材。",
        }
    ]

    cutting_lines = []
    for line_number in range(1, counts["裁剪明细"] + 1):
        source = _pick(catalog["cutting"], index, line_number)
        cutting_lines.append(
            {
                "part_name": source.material_name,
                "source_cutting_material_id": source.pk,
                "cut_piece_quantity": str(1 + line_number % 3),
                "purchase_consumption": f"{0.3 + line_number * 0.1:.1f}",
                "notes": "裁剪工艺明细，不作为采购来源。",
            }
        )

    return [
        {
            **section_identity("管材类", BomSectionType.PROFILE),
            "section_type": BomSectionType.PROFILE,
            "title": "管材类",
            "lines": profile_lines,
        },
        {
            **section_identity("五金件", BomSectionType.ACCESSORY),
            "section_type": BomSectionType.ACCESSORY,
            "title": "五金件",
            "lines": hardware_lines,
        },
        {
            **section_identity("塑料件类", BomSectionType.ACCESSORY),
            "section_type": BomSectionType.ACCESSORY,
            "title": "塑料件类",
            "lines": plastic_lines,
        },
        {
            **section_identity("辅料类", BomSectionType.FABRIC),
            "section_type": BomSectionType.FABRIC,
            "title": "辅料类",
            "lines": auxiliary_lines,
        },
        {
            **section_identity("面料类", BomSectionType.FABRIC),
            "section_type": BomSectionType.FABRIC,
            "title": "面料类",
            "lines": fabric_lines,
        },
        {
            **section_identity("包材类", BomSectionType.ACCESSORY),
            "section_type": BomSectionType.ACCESSORY,
            "title": "包材类",
            "lines": packaging_lines,
        },
        {
            **section_identity("裁剪明细", BomSectionType.FABRIC),
            "section_type": BomSectionType.FABRIC,
            "title": "裁剪明细",
            "lines": cutting_lines,
        },
    ]
