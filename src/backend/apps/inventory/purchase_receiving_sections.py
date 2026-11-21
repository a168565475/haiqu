"""Classify purchase and receipt lines using the saved material identity."""
from django.db.models import Case, CharField, F, Q, Value, When
from django.db.models.fields.json import KeyTextTransform
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.access_control.sales_policy import access_for

from .models import PURCHASE_INBOUND_SECTION_NAMES, PurchaseInboundSection

RAW_SECTIONS = {
    "TUBE": ("管材", ("管材", "管材类", "型材", "型材明细")),
    "HARDWARE": ("五金", ("五金", "五金件", "五金件类")),
    "PLASTIC": ("塑料", ("塑料", "塑料件", "塑料件类")),
    "FABRIC": ("面料", ("面料", "面料类")),
    "AUXILIARY": ("辅料", ("辅料", "辅料类")),
    "PACKAGING": ("包材", ("包材", "包材类")),
}
MATERIAL_SECTIONS = {key: label for key, (label, _) in RAW_SECTIONS.items()}
OTHER_SECTION = "OTHER"
SECTION_CATEGORIES = {
    PurchaseInboundSection.A: {"TUBE"},
    PurchaseInboundSection.B: {"HARDWARE", "PLASTIC", "PACKAGING"},
    PurchaseInboundSection.C: {"FABRIC", "AUXILIARY"},
}
SECTION_BY_CATEGORY = {category: section for section, categories in SECTION_CATEGORIES.items() for category in categories}
# Existing links and clients may still pass a single material category.
RECEIVING_SELECTIONS = {**PURCHASE_INBOUND_SECTION_NAMES, **MATERIAL_SECTIONS, OTHER_SECTION: "其他材料"}


def with_receiving_section(queryset):
    saved_category = Q(material_selection_snapshot__category_key__in=list(MATERIAL_SECTIONS))
    return queryset.annotate(receiving_section=Case(
        When(saved_category, then=KeyTextTransform("category_key", F("material_selection_snapshot"))),
        When(section_type_snapshot="PROFILE", then=Value("TUBE")),
        *(When(Q(**{f"{field}__in": aliases}), then=Value(key))
          for field in ("section_title_snapshot", "category_snapshot")
          for key, (_, aliases) in RAW_SECTIONS.items()),
        default=Value(OTHER_SECTION),
        output_field=CharField(),
    ))


def assigned_receiving_sections(request):
    """None means the current receiving grant has no material restriction."""
    if request.user.is_superuser:
        return None
    entry = access_for(request)["actions"].get("inventory.receive_material", {})
    scopes = set(entry.get("scopes", ()))
    if "MATERIAL" not in scopes or scopes & {"MODULE", "ALL"}:
        return None
    return {key for source in entry["sources"] if source.get("scope") == "MATERIAL"
            for key in source.get("resource_ids", ())}


def receiving_lines_in_scope(queryset, sections, *, order_field="purchase_order"):
    if sections is None:
        return queryset
    return with_receiving_section(queryset).filter(
        Q(receiving_section__in=sections) | Q(**{f"{order_field}__source_type": "SAMPLE"}),
    )


def receiving_categories(allowed, selection):
    if not selection:
        return allowed
    categories = SECTION_CATEGORIES.get(selection, {selection})
    visible = categories if allowed is None else categories & allowed
    if not visible:
        raise PermissionDenied("当前账号无权办理该材料分区的入库。")
    return visible


def resolve_receiving_section(request, lines, selected_section):
    allowed = assigned_receiving_sections(request)
    submitted = {line.receiving_section for line in lines}
    if allowed is not None and not submitted <= allowed:
        raise PermissionDenied("本次收货包含未授权材料分区。")
    sections = {SECTION_BY_CATEGORY.get(category) for category in submitted}
    if None in sections:
        raise ValidationError({"items": "本次收货含未能识别分区的材料，请核对采购明细的材料分类。"})
    if len(sections) != 1 or (
        selected_section and not submitted <= receiving_categories(allowed, selected_section)
    ):
        raise ValidationError({"items": "每次收货只能提交当前分区的材料。"})
    return next(iter(sections))
