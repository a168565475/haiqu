from django.db.models import Case, Q, Value, When
from django.db.models.functions import Trim
from rest_framework.exceptions import ValidationError

from apps.access_control.module_operations import PACKAGING_PURCHASE as PACKAGING_PERMISSION
from apps.inventory.bom_inventory_sections import RAW_SECTIONS

from .models import PurchaseScope


def is_packaging_material(selection, section_type, section_title, category):
    section_title = (section_title or "").strip()
    saved = selection.get("category_key") if isinstance(selection, dict) else None
    if saved in RAW_SECTIONS:
        return saved == "PACKAGING"
    if section_type == "PROFILE":
        return False
    for value in (section_title, category):
        for key, (_, aliases) in RAW_SECTIONS.items():
            if value in aliases:
                return key == "PACKAGING"
    return False


def is_packaging_bom_line(line):
    return is_packaging_material(line.material_selection_snapshot, line.section.section_type, line.section.title, line.category)


def is_packaging_snapshot(snapshot):
    if not isinstance(snapshot, dict):
        return False
    return is_packaging_material(
        snapshot.get("material_selection_snapshot"), snapshot.get("section_type_snapshot"),
        snapshot.get("section_title_snapshot"), snapshot.get("category_snapshot"),
    )


def packaging_order_filter(prefix=""):
    return Q(**{f"{prefix}purchase_group__purchase_scope": PurchaseScope.PACKAGING})


def _with_packaging_flag(queryset, section_type, title, category):
    saved_key = "material_selection_snapshot__category_key"
    return queryset.alias(is_packaging=Case(
        When(**{saved_key: "PACKAGING"}, then=Value(True)),
        When(**{f"{saved_key}__in": list(RAW_SECTIONS)}, then=Value(False)),
        When(**{section_type: "PROFILE"}, then=Value(False)),
        *(When(**{f"{field}__in": aliases}, then=Value(key == "PACKAGING"))
          for field in (title, category) for key, (_, aliases) in RAW_SECTIONS.items()),
        default=Value(False),
    ))


def packaging_bom_lines(queryset):
    return _with_packaging_flag(queryset, "section__section_type", "section__title", "category").filter(is_packaging=True)


def standard_order_lines(queryset):
    queryset = queryset.exclude(packaging_order_filter("purchase_order__")).alias(trimmed_title=Trim("section_title_snapshot"))
    return _with_packaging_flag(queryset, "section_type_snapshot", "trimmed_title", "category_snapshot").filter(is_packaging=False)


def validate_source_scope(packaging, purchase_scope, number):
    if packaging != (purchase_scope == PurchaseScope.PACKAGING):
        raise ValidationError({"lines": f"第{number}行材料属于{'包材' if packaging else '普通'}采购，请从对应入口办理。"})
