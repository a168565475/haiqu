import re
from decimal import Decimal

from django.db.models import Count, OuterRef, Prefetch, Q, Subquery

from apps.products.models import RawMaterialInformation
from apps.production_tasks.selectors import accessible_production_tasks

from .models import Bom, BomSection


def accessible_boms(request):
    queryset = Bom.objects.filter(archived_at__isnull=True)
    if request.user.is_superuser or request.user.has_perm("boms.view_all_bom"):
        return queryset
    accessible_task_ids = accessible_production_tasks(request).values("id")
    return queryset.filter(production_task_id__in=accessible_task_ids)


def boms_with_context(queryset=None, *, include_lines=False, read_optimized=False):
    if queryset is None:
        queryset = Bom.objects.all()
    latest_active_bom = (
        Bom.objects.filter(
            product_line_id=OuterRef("product_line_id"),
            archived_at__isnull=True,
        )
        .order_by("-version_number", "-id")
        .values("id")[:1]
    )
    related = [
        "production_task",
        "production_task__customer_account",
        "production_task__sales_order",
        "product_line",
        "product_line__unit",
        "created_by_employee",
        "updated_by_employee",
        "confirmed_by_employee",
        "product_information_confirmed_by_employee",
    ]
    # 读取接口只加载序列化真正使用的关联，避免无用 JOIN 增加规划时间。
    if not read_optimized:
        related.extend(["product_line__product", "product_line__product__category", "source_file"])
    if not read_optimized or include_lines:
        related.append("copied_from")
    if include_lines:
        related.extend(["product__category", "product__unit", "product__product_item__category"])
    queryset = queryset.annotate(
        latest_active_bom_id=Subquery(latest_active_bom),
    ).select_related(*related).prefetch_related(
        "production_task__delivery_batches",
        Prefetch(
            "sections",
            queryset=BomSection.objects.annotate(prefetched_line_count=Count("lines")).order_by(
                "bom_id",
                "line_number",
                "id",
            ),
        ),
    )
    if include_lines:
        queryset = queryset.prefetch_related("sections__lines__images__business_file")
    return queryset


def search_boms(queryset, search_text):
    if not search_text:
        return queryset
    return queryset.filter(
        Q(bom_number__icontains=search_text)
        | Q(production_task__task_number__icontains=search_text)
        | Q(production_task__order_number__icontains=search_text)
        | Q(product_code_snapshot__icontains=search_text)
        | Q(product_name_snapshot__icontains=search_text)
    )


def pipe_dimension_numbers(value):
    """仅统一明确的数值与毫米写法，不把任意文字规格猜成尺寸。"""
    text = re.sub(r"\s+", "", str(value or "")).lower()
    text = re.sub(r"(?:mm|毫米)$", "", text).lstrip("φø")
    parts = re.split(r"[x×*]", text)
    if not parts or any(not re.fullmatch(r"\d+(?:\.\d+)?", item) for item in parts):
        return None
    numbers = tuple(Decimal(item) for item in parts)
    return numbers if all(0 < number < 10 ** 12 for number in numbers) else None


def pipe_material_dimensions(source):
    specification = str(source.specification or "").strip()
    shape = ""
    for prefix in ("椭圆管", "扁圆管", "矩形管", "方管", "圆管", "Φ", "φ", "Ø", "ø"):
        if specification.startswith(prefix):
            shape = "圆管" if prefix in {"Φ", "φ", "Ø", "ø"} else prefix
            specification = specification[len(prefix):].strip()
            break
    specification_numbers = pipe_dimension_numbers(specification)
    if not specification_numbers or len(specification_numbers) not in {3, 4}:
        specification_numbers = None
    diameter = pipe_dimension_numbers(source.diameter)
    thickness = pipe_dimension_numbers(source.thickness)
    length = pipe_dimension_numbers(source.length)
    if not str(source.diameter or "").strip() or str(source.diameter).strip() in {"/", "-", "—"}:
        diameter = specification_numbers[:-2] if specification_numbers else None
    if not str(source.thickness or "").strip() or str(source.thickness).strip() in {"/", "-", "—"}:
        thickness = specification_numbers[-2:-1] if specification_numbers else None
    if shape == "圆管" and (not diameter or len(diameter) != 1):
        shape = ""
    if specification_numbers and (diameter != specification_numbers[:-2] or thickness != specification_numbers[-2:-1]):
        shape = ""
    # 历史管材规范为截面×厚度×长度(mm)；缺失或不一致的长度不得自动换算猜测。
    explicit_mm = bool(re.search(r"(?:mm|毫米)\s*$", str(source.length or ""), re.IGNORECASE))
    length_mm = length[0] if length and len(length) == 1 and explicit_mm else None
    if specification_numbers:
        if not str(source.length or "").strip() or str(source.length).strip() in {"/", "-", "—"}:
            length_mm = specification_numbers[-1]
        elif length == specification_numbers[-1:]:
            length_mm = length[0]
    return diameter, thickness, length_mm, shape


def match_pipe_material_candidates(materials, *, material="", diameter="", thickness="",
                                   tube_shape="", raw_bar_length_m=None):
    result = {"candidates": [], "automatic_source_id": None, "reason": "incomplete"}
    expected_diameter = pipe_dimension_numbers(diameter)
    expected_thickness = pipe_dimension_numbers(thickness)
    if not material.strip() or not expected_diameter or len(expected_diameter) > 2 or not expected_thickness or len(expected_thickness) != 1:
        return result
    for source in materials:
        source_diameter, source_thickness, _, source_shape = pipe_material_dimensions(source)
        if (str(source.material or "").strip() == material.strip()
                and source_diameter == expected_diameter and source_thickness == expected_thickness
                and not (source_shape and tube_shape.strip() and source_shape != tube_shape.strip())):
            result["candidates"].append(source)
    candidates = result["candidates"]
    if not candidates:
        result["reason"] = "no_match"
    elif len(candidates) > 1:
        result["reason"] = "multiple"
    else:
        _, _, length_mm, shape = pipe_material_dimensions(candidates[0])
        expected_length = pipe_dimension_numbers(raw_bar_length_m)
        if shape and shape == tube_shape.strip() and length_mm is not None and expected_length == (length_mm / 1000,):
            result.update(automatic_source_id=candidates[0].pk, reason="unique")
        else:
            result["reason"] = "needs_review"
    return result


def pipe_material_matches(**parameters):
    materials = RawMaterialInformation.objects.filter(
        item_type="MATERIAL", category__item_type="MATERIAL", category__category_name="管材",
        category__status="ACTIVE", category__archived_at__isnull=True, archived_at__isnull=True,
        unit__unit_name="根", unit__status="ACTIVE", unit__archived_at__isnull=True,
    ).select_related("category", "unit", "color").order_by("material_number", "id")
    return match_pipe_material_candidates(materials, **parameters)
