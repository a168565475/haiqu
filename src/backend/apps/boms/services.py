from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from uuid import uuid4

from django.db import IntegrityError, transaction
from django.db.models.deletion import ProtectedError
from django.db.models import Max, Sum
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.audit.models import AuditLog
from apps.core.api.concurrency import require_matching_etag
from apps.core.api.exceptions import Conflict
from apps.core.audit import write_audit_log
from apps.core.numbering import next_business_number

from apps.production_tasks.models import ProductionTask
from apps.sales_orders.models import SalesOrder, SalesOrderLine
from apps.quotations.product_writeback import save_bom_product_information
from apps.products.material_identity import lock_bom_line_material_identities
from apps.products.lineage import resolve_production_task_product_lineage
from .material_flow_bom import apply_line_quantities, is_meter_fabric_section, validate_fabric_links, validate_used_components
from .material_flow_calculations import CUTTING_USAGE_FIELDS, pipe_plan, MaterialFlowValueError

from .image_files import delete_business_file_if_unreferenced
from .maintenance import match_maintenance_configuration
from .material_save_plan import (build_material_save_plan, lock_material_references,
                                persist_material_plan, require_save_permissions)
from .models import (
    Bom,
    BomCreationMethod,
    BomLine,
    BomLineImage,
    BomLineImageDraft,
    BomSection,
    BomSectionType,
    BomStatus,
)
from .selectors import boms_with_context
from .uploads import persist_prepared_bom_upload, prepare_bom_upload
from .workbook_import import BomWorkbookError, parse_bom_workbook, validate_workbook_identity


EDITABLE_LINE_FIELDS = [
    "category",
    "material",
    "part_name",
    "specification",
    "raw_material",
    "length_value",
    "unit_consumption",
    "total_consumption",
    "unit",
    "hardness",
    "original_material_length",
    "branch_count",
    "budget_quantity",
    "inventory_quantity",
    "weight_grams",
    "cut_piece_quantity",
    "purchase_consumption",
    "source_order_quantity",
    "total_purchase_quantity",
    "notes",
]


def get_bom_product_lineage(bom):
    """BOM 只沿生产任务产品的真实外键读取来源链，不按产品名称猜测。"""
    return resolve_production_task_product_lineage(bom.product_line)

TUBE_DETAIL_FIELDS = [
    "tube_shape",
    "tube_diameter",
    "tube_thickness",
    "tube_coating_color",
    "coating_unit_area_sqm",
    "purchase_unit_weight_kg",
    "tube_cut_piece_count",
]

TUBE_CALCULATED_FIELDS = [
    "tube_cut_length_m",
    "long_material_unit_weight_kg",
    "tube_unit_weight_kg",
    "long_material_total_weight_kg",
]

HARDWARE_DETAIL_FIELDS = [
    "source_raw_material_id",
    "hardware_material_number",
    "hardware_color",
    "hardware_flow_unit",
    "unit_material_weight_kg",
    "powder_coating_color",
    "powder_coating_unit_area_sqm",
]

PLASTIC_DETAIL_FIELDS = [
    "source_raw_material_id",
    "plastic_material_number",
    "plastic_color",
]

PACKAGING_DETAIL_FIELDS = [
    "source_packaging_material_id",
    "packaging_material_number",
    "packaging_color",
    "units_per_box",
]

CUTTING_DETAIL_FIELDS = [
    "source_cutting_material_id",
    "cutting_material_number",
    "cutting_item_type",
    "cutting_item_type_display",
    "cutting_category",
    "cutting_color",
]

AUXILIARY_DETAIL_FIELDS = [
    "source_accessory_product_name_id",
    "source_accessory_specification_id",
    "source_accessory_color_id",
    "source_accessory_material_id",
    "accessory_color",
]

FABRIC_DETAIL_FIELDS = [
    "source_fabric_material_id",
    "source_fabric_specification_id",
    "source_fabric_width_id",
    "source_product_color_id",
    "fabric_width",
    "fabric_color_card",
    "fabric_color_code",
    "fabric_color_name",
]

REFERENCE_ID_FIELDS = {
    "source_inventory_material_id",
    "source_raw_material_id",
    "source_accessory_product_name_id",
    "source_accessory_specification_id",
    "source_accessory_color_id",
    "source_accessory_material_id",
    "source_fabric_material_id",
    "source_fabric_specification_id",
    "source_fabric_width_id",
    "source_product_color_id",
    "source_packaging_material_id",
    "source_cutting_material_id",
}

CALCULATION_PRECISION = Decimal("0.0001")
CUT_LENGTH_PRECISION = Decimal("0.01")
WHOLE_NUMBER_PRECISION = Decimal("1")
TUBE_WEIGHT_COEFFICIENT = Decimal("0.464")
TUBE_LOSS_FACTOR = Decimal("1.01")


def _tube_specification(line_data):
    shape = line_data.get("tube_shape", "")
    diameter = line_data.get("tube_diameter", "")
    thickness = line_data.get("tube_thickness", "")
    if shape == "圆管" and diameter:
        base = f"Φ{diameter}"
    else:
        base = " ".join(value for value in (shape, diameter) if value)
    return f"{base} × {thickness} mm" if base and thickness else base or thickness


def _decimal_value(value):
    text = str(value or "").strip()
    if not text:
        return None
    try:
        result = Decimal(text)
    except (InvalidOperation, ValueError):
        return None
    return result if result.is_finite() else None


def _rounded_integer_value(value):
    parsed = _decimal_value(value)
    if parsed is None:
        return None
    try:
        return parsed.quantize(WHOLE_NUMBER_PRECISION, rounding=ROUND_HALF_UP)
    except InvalidOperation:
        return None


def _rounded_integer_text(value):
    rounded = _rounded_integer_value(value)
    if rounded is None:
        return str(value or "").strip()
    return format(rounded, "f")


def _calculation_text(value, precision=CALCULATION_PRECISION, keep_trailing_zeros=False):
    if value is None:
        return ""
    try:
        rounded = value.quantize(precision, rounding=ROUND_HALF_UP)
    except InvalidOperation:
        return ""
    text = format(rounded, "f")
    return text if keep_trailing_zeros else text.rstrip("0").rstrip(".") or "0"


def _tube_calculations(line_data, product_quantity):
    length = _decimal_value(line_data.get("length_value"))
    unit_consumption = _decimal_value(line_data.get("unit_consumption"))
    total_consumption = cut_length = branch_count = None
    try:
        plan = pipe_plan(cutting_length_mm=line_data.get("length_value"),
                         pieces_per_product=line_data.get("unit_consumption"),
                         pieces_per_bar=line_data.get("tube_cut_piece_count"), order_quantity=product_quantity)
        total_consumption = Decimal(plan["demand_pieces"])
        cut_length = Decimal(plan["raw_bar_length_m"])
        branch_count = Decimal(plan["suggested_bar_count"])
    except MaterialFlowValueError:
        # 导入/旧草稿缺参时留空，保存和确认由统一校验报告具体错误。
        length = unit_consumption = None

    long_material_unit_weight = cut_length * TUBE_WEIGHT_COEFFICIENT if cut_length is not None else None
    unit_weight = None
    if length is not None and unit_consumption is not None:
        unit_weight = TUBE_WEIGHT_COEFFICIENT * length * unit_consumption / Decimal("1000")
    long_material_total_weight = None
    if branch_count is not None and long_material_unit_weight is not None:
        long_material_total_weight = branch_count * long_material_unit_weight

    return {
        "total_consumption": _calculation_text(total_consumption),
        "branch_count": _calculation_text(branch_count),
    }, {
        "tube_cut_length_m": _calculation_text(
            cut_length,
            precision=CUT_LENGTH_PRECISION,
            keep_trailing_zeros=True,
        ),
        "long_material_unit_weight_kg": _calculation_text(long_material_unit_weight),
        "tube_unit_weight_kg": _calculation_text(unit_weight),
        "long_material_total_weight_kg": _calculation_text(long_material_total_weight),
    }


def _editable_model_values(line_data, section_type, product_quantity, *, existing_line=None):
    values = {field: line_data[field] for field in EDITABLE_LINE_FIELDS if field in line_data}
    tube_fields = ("tube_shape", "tube_diameter", "tube_thickness")
    source_id = line_data.get("source_inventory_material_id")
    # 当前完整参数决定显示规格；仅传来源 ID 的历史调用仍保留原快照。
    if section_type == "PROFILE" and any(field in line_data for field in tube_fields) and (
        not source_id or all(line_data.get(field) for field in tube_fields)
    ):
        values["specification"] = _tube_specification(line_data)
    calculated_raw_values = {}
    if section_type == "PROFILE":
        values["unit"] = "根"
        calculated_values, calculated_raw_values = _tube_calculations(line_data, product_quantity)
        values.update(calculated_values)
    return values, calculated_raw_values


def _merged_raw_values(existing_values, line_data, section_type, section_title, calculated_values):
    values = dict(existing_values or {})
    if "source_inventory_material_id" in line_data:
        source_id = line_data["source_inventory_material_id"]
        values["source_inventory_material_id"] = str(source_id) if source_id else ""
    if section_type == "PROFILE":
        if line_data.get("pipe_source_sync_pending"):
            values["pipe_source_sync_pending"] = True
        for field in TUBE_DETAIL_FIELDS:
            if field in line_data:
                values[field] = (
                    str(line_data[field]).strip()
                    if field == "tube_cut_piece_count"
                    else line_data[field]
                )
        for field in TUBE_CALCULATED_FIELDS:
            values[field] = calculated_values.get(field, "")
    if section_type == BomSectionType.ACCESSORY and section_title.strip() == "五金件":
        for field in HARDWARE_DETAIL_FIELDS:
            if field in line_data:
                value = line_data[field]
                values[field] = str(value) if field == "source_raw_material_id" and value else (value or "")
    elif section_type == BomSectionType.ACCESSORY and section_title.strip() == "塑料件类":
        detail_fields = PLASTIC_DETAIL_FIELDS
        for field in detail_fields:
            if field in line_data:
                value = line_data[field]
                values[field] = str(value) if field in REFERENCE_ID_FIELDS and value else (value or "")
    elif section_type == BomSectionType.ACCESSORY and section_title.strip() == "包材类":
        for field in PACKAGING_DETAIL_FIELDS:
            if field in line_data:
                value = line_data[field]
                values[field] = str(value) if field in REFERENCE_ID_FIELDS and value else (value or "")
    elif section_type == BomSectionType.FABRIC and section_title.strip() == "辅料类":
        for field in AUXILIARY_DETAIL_FIELDS:
            if field in line_data:
                value = line_data[field]
                values[field] = str(value) if field in REFERENCE_ID_FIELDS and value else (value or "")
    elif section_type == BomSectionType.FABRIC and section_title.strip() == "面料类":
        if line_data.get("fabric_source_sync_pending"):
            values["fabric_source_sync_pending"] = True
        for field in FABRIC_DETAIL_FIELDS:
            if field in line_data:
                value = line_data[field]
                values[field] = str(value) if field in REFERENCE_ID_FIELDS and value else (value or "")
    elif section_type == BomSectionType.FABRIC and section_title.strip() == "裁剪明细":
        for field in CUTTING_DETAIL_FIELDS:
            if field in line_data:
                value = line_data[field]
                values[field] = str(value) if field in REFERENCE_ID_FIELDS and value else (value or "")
    return values


def _display_quantity(value):
    text = format(Decimal(value), ",f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def _quantity_snapshot(product_line, source_quantity):
    order_quantity = Decimal(product_line.quantity)
    batch_quantity = product_line.production_task.delivery_batches.aggregate(total=Sum("quantity"))["total"]
    difference = Decimal("0")
    if batch_quantity is not None:
        difference = Decimal(batch_quantity) - order_quantity
    elif source_quantity is not None:
        difference = Decimal(source_quantity) - order_quantity
    return order_quantity, batch_quantity, difference


PREVIEW_LINE_LIMIT = 10


def _normalized_header(value):
    return str(value or "").replace("\n", "").replace(" ", "").replace("（", "(").replace("）", ")").lower()


def _source_value_by_header(section, line, aliases):
    normalized_aliases = tuple(_normalized_header(alias) for alias in aliases)
    for column, header in (section.get("headers") or {}).items():
        normalized = _normalized_header(header)
        if normalized and any(alias == normalized or alias in normalized for alias in normalized_aliases):
            return str((line.get("raw_values") or {}).get(column, "") or "")
    return ""


def _safe_preview_sections(plan):
    """只返回新建页需要的白名单字段，避免原始单元格和公式进入预览接口。"""
    remaining = PREVIEW_LINE_LIMIT
    display_line_number = 0
    sections = []
    for section in plan["sections"]:
        preview_rows = []
        for line in section["lines"]:
            if remaining <= 0:
                break
            display_line_number += 1
            remaining -= 1
            material_name = _source_value_by_header(
                section,
                line,
                ("物料名称", "材料名称", "配件名称", "裁片名称"),
            ) or str(line.get("part_name") or line.get("raw_material") or line.get("material") or "")
            preview_rows.append(
                {
                    "line_number": display_line_number,
                    "source_row_number": line.get("source_row_number"),
                    "material_category": str(line.get("category") or section["title"] or ""),
                    "material_code": _source_value_by_header(
                        section,
                        line,
                        ("物料编码", "物料编号", "材料编码", "材料编号", "配件编号", "原料编号"),
                    ),
                    "material_name": material_name,
                    "specification": str(line.get("specification") or ""),
                    "unit": str(line.get("unit") or ""),
                    "unit_consumption": str(
                        line.get("unit_consumption") or line.get("purchase_consumption") or ""
                    ),
                    "section": str(section["title"] or ""),
                    "notes": str(line.get("notes") or ""),
                }
            )
        sections.append(
            {
                "section_type": section["section_type"],
                "title": section["title"],
                "line_count": section["line_count"],
                "preview_rows": preview_rows,
            }
        )
    return sections


def preview_imported_bom(uploaded_file, actor_employee, product_line):
    prepared = prepare_bom_upload(uploaded_file)
    try:
        plan = parse_bom_workbook(prepared.temporary_path, prepared.original_name)
        identity_errors = validate_workbook_identity(plan, product_line)
        maintenance = match_maintenance_configuration(plan)
        order_quantity, batch_quantity, quantity_difference = _quantity_snapshot(product_line, plan["source_quantity"])
        return {
            "file_name": plan["original_name"],
            "sheet_name": plan["sheet_name"],
            "sheet_number": plan["sheet_number"],
            "metadata": plan["metadata"],
            "section_count": plan["section_count"],
            "line_count": plan["line_count"],
            "preview_limit": PREVIEW_LINE_LIMIT,
            "preview_row_count": min(plan["line_count"], PREVIEW_LINE_LIMIT),
            "has_more_preview_rows": plan["line_count"] > PREVIEW_LINE_LIMIT,
            "sections": _safe_preview_sections(plan),
            "calculation_summary": plan["calculation_summary"],
            "maintenance": maintenance,
            "identity_errors": identity_errors,
            "quantity": {
                "order_quantity": order_quantity,
                "source_quantity": plan["source_quantity"],
                "batch_quantity": batch_quantity,
                "difference": quantity_difference,
                "requires_confirmation": any(
                    value is not None and Decimal(value) != order_quantity
                    for value in (plan["source_quantity"], batch_quantity)
                ),
            },
        }
    except BomWorkbookError as exc:
        raise ValidationError({"workbook": str(exc)}) from exc
    finally:
        prepared.cleanup()


def _next_version(product_line):
    latest = (
        Bom.objects.select_for_update()
        .filter(product_line=product_line)
        .aggregate(latest=Max("version_number"))["latest"]
    )
    return (latest or 0) + 1


def _bom_number():
    return next_business_number("BOM")


def _create_sections(bom, plan):
    for section_index, section_data in enumerate(plan["sections"], start=1):
        section = BomSection.objects.create(
            bom=bom,
            line_number=section_index,
            section_type=section_data["section_type"],
            title=section_data["title"],
            source_title_row=section_data["source_title_row"],
            source_header_row=section_data["source_header_row"],
            headers=section_data["headers"],
            calculation_rows=section_data["calculation_rows"],
        )
        BomLine.objects.bulk_create(
            [
                BomLine(section=section, line_number=line_index, **line_data)
                for line_index, line_data in enumerate(section_data["lines"], start=1)
            ]
        )

    for line in BomLine.objects.filter(section__bom=bom).select_related("section"):
        if is_meter_fabric_section(line.section) and not line.unit_consumption:
            line.unit_consumption = line.purchase_consumption
        apply_line_quantities(line, bom.order_quantity, tolerate_legacy=True)
        line.save()


def _copy_sections(bom, source_bom):
    copied_by_source = {}
    links = []
    for section_data in source_bom.sections.prefetch_related("lines__images").all():
        section = BomSection.objects.create(
            bom=bom,
            line_number=section_data.line_number,
            section_type=section_data.section_type,
            title=section_data.title,
            source_title_row=section_data.source_title_row,
            source_header_row=section_data.source_header_row,
            headers=section_data.headers,
            calculation_rows=section_data.calculation_rows,
        )
        fields = [
            field.name for field in BomLine._meta.fields
            if field.name not in {"id", "section", "created_at", "updated_at", "component_identity", "fabric_source_line"}
        ]
        source_lines = list(section_data.lines.all())
        copied_lines = BomLine.objects.bulk_create(
            [BomLine(section=section, component_identity=line.component_identity if bom.product_line_id == source_bom.product_line_id else uuid4(),
                     **{field: getattr(line, field) for field in fields}) for line in source_lines]
        )
        for source_line, copied_line in zip(source_lines, copied_lines):
            copied_by_source[source_line.pk] = copied_line
            links.append((source_line.fabric_source_line_id, copied_line))
            apply_line_quantities(copied_line, bom.order_quantity, tolerate_legacy=True)
            copied_line.save()
        BomLineImage.objects.bulk_create(
            [
                BomLineImage(
                    bom_line=copied_line,
                    business_file_id=image.business_file_id,
                    position=image.position,
                )
                for source_line, copied_line in zip(source_lines, copied_lines)
                for image in source_line.images.all()
            ]
        )

    for source_id, line in links:
        if source_id:
            if source_id not in copied_by_source:
                raise ValidationError({"source_bom_id": "来源 BOM 的裁片面料关联不完整，请先修正。"})
            line.fabric_source_line = copied_by_source[source_id]
            line.save(update_fields=["fabric_source_line"])



def create_bom(
    *,
    product_line,
    creation_method,
    actor_employee,
    uploaded_file=None,
    source_bom=None,
    quantity_difference_reason="",
    request=None,
    link_source=False,
):
    prepared = None
    persisted_path = None
    plan = None
    maintenance = {"matched_count": 0, "unmatched_count": 0, "unmatched_values": []}
    source_quantity = None
    source_file = None
    try:
        if creation_method == BomCreationMethod.IMPORT:
            if uploaded_file is None:
                raise ValidationError({"workbook": "请选择 BOM Excel 文件。"})
            prepared = prepare_bom_upload(uploaded_file)
            try:
                plan = parse_bom_workbook(prepared.temporary_path, prepared.original_name)
            except BomWorkbookError as exc:
                raise ValidationError({"workbook": str(exc)}) from exc
            identity_errors = validate_workbook_identity(plan, product_line)
            if identity_errors:
                raise ValidationError({"workbook": identity_errors})
            maintenance = match_maintenance_configuration(plan)
            source_quantity = plan["source_quantity"]
        elif creation_method == BomCreationMethod.COPY:
            if source_bom is None:
                raise ValidationError({"source_bom_id": "请选择要复制的历史 BOM。"})
            source_quantity = source_bom.source_quantity
            maintenance = {
                "matched_count": source_bom.maintenance_match_count,
                "unmatched_count": source_bom.maintenance_unmatched_count,
                "unmatched_values": source_bom.maintenance_unmatched_values,
            }
        elif creation_method != BomCreationMethod.BLANK:
            raise ValidationError({"creation_method": "BOM 建立方式不正确。"})

        with transaction.atomic():
            locked_product_line = (
                product_line.__class__.objects.select_for_update()
                .select_related("production_task")
                .get(pk=product_line.pk)
            )
            version_number = _next_version(locked_product_line)
            order_quantity, batch_quantity, quantity_difference = _quantity_snapshot(locked_product_line, source_quantity)
            if prepared is not None:
                source_file, persisted_path = persist_prepared_bom_upload(prepared, actor_employee)
                prepared = None

            section_count = plan["section_count"] if plan else (source_bom.section_count if source_bom else 1)
            line_count = plan["line_count"] if plan else (source_bom.line_count if source_bom else 0)
            bom = Bom.objects.create(
                bom_number=_bom_number(),
                production_task=locked_product_line.production_task,
                product_line=locked_product_line,
                version_number=version_number,
                creation_method=creation_method,
                status=BomStatus.PENDING_CONFIRMATION,
                copied_from=source_bom if creation_method == BomCreationMethod.COPY or link_source else None,
                product=locked_product_line.product,
                product_category=(
                    locked_product_line.product_category
                    or (locked_product_line.product.category if locked_product_line.product_id else None)
                ),
                product_unit=locked_product_line.unit,
                product_color=locked_product_line.product_color,
                product_unit_code_snapshot=locked_product_line.unit.unit_code,
                product_unit_name_snapshot=locked_product_line.unit.unit_name,
                product_color_name_snapshot=locked_product_line.color_name_snapshot,
                product_color_code_snapshot=locked_product_line.color_code_snapshot,
                product_color_card_snapshot=locked_product_line.color_card_snapshot,
                product_number_snapshot=locked_product_line.product_number_snapshot,
                product_code_snapshot=locked_product_line.product_code_snapshot,
                item_number_snapshot=locked_product_line.item_number_snapshot,
                product_name_snapshot=locked_product_line.product_name_snapshot,
                specification_snapshot=locked_product_line.specification_snapshot,
                material_snapshot=locked_product_line.material_snapshot,
                product_category_snapshot=(
                    locked_product_line.product.category.category_name
                    if locked_product_line.product_id and locked_product_line.product and locked_product_line.product.category_id
                    else ""
                ),
                order_quantity=order_quantity,
                source_quantity=source_quantity,
                batch_quantity=batch_quantity,
                quantity_difference=quantity_difference,
                quantity_difference_reason=(quantity_difference_reason or "").strip(),
                source_file=source_file,
                source_sheet_name=plan["sheet_name"] if plan else (source_bom.source_sheet_name if source_bom else ""),
                source_original_name=plan["original_name"] if plan else (source_bom.source_original_name if source_bom else ""),
                source_metadata=plan["metadata"] if plan else (source_bom.source_metadata if source_bom else {}),
                calculation_summary=plan["calculation_summary"] if plan else (source_bom.calculation_summary if source_bom else {}),
                maintenance_match_count=maintenance["matched_count"],
                maintenance_unmatched_count=maintenance["unmatched_count"],
                maintenance_unmatched_values=maintenance["unmatched_values"],
                section_count=section_count,
                line_count=line_count,
                created_by_employee=actor_employee,
                updated_by_employee=actor_employee,
            )
            _reuse_confirmed_product_review(bom, actor_employee=actor_employee, request=request)
            if plan:
                _create_sections(bom, plan)
            elif source_bom:
                _copy_sections(bom, source_bom)
            else:
                BomSection.objects.create(
                    bom=bom,
                    line_number=1,
                    section_type="PROFILE",
                    title="管材类",
                )
            AuditLog.objects.create(
                actor_employee=actor_employee,
                actor_employee_code_snapshot=getattr(actor_employee, "employee_code", "") if actor_employee else "",
                actor_name_snapshot=getattr(actor_employee, "display_name", "") if actor_employee else "",
                object_type="BOM",
                object_id=bom.pk,
                context_type="PRODUCTION_TASK",
                context_id=bom.production_task_id,
                action="CREATE",
                before_data={},
                after_data={
                    "bom_number": bom.bom_number,
                    "creation_method": bom.creation_method,
                    "section_count": bom.section_count,
                    "line_count": bom.line_count,
                    "quantity_difference_reason": bom.quantity_difference_reason,
                },
                request_id=getattr(request, "request_id", None) if request else None,
                ip_address=request.META.get("REMOTE_ADDR") if request else None,
                user_agent=(request.META.get("HTTP_USER_AGENT", "")[:500] if request else ""),
                occurred_at=timezone.now(),
            )
            return bom
    except Exception:
        if persisted_path and Path(persisted_path).exists():
            Path(persisted_path).unlink()
        raise
    finally:
        if prepared is not None:
            prepared.cleanup()


def _product_writeback_snapshot(instance, fields):
    result = {"id": str(instance.pk)}
    for name in fields:
        value = getattr(instance, name)
        result[name] = str(value) if name.endswith("_id") and value is not None else value
    return result


def _reuse_confirmed_product_review(bom, *, actor_employee, request):
    """同一销售明细的后续批次只复用完全一致的首次确认信息，不按产品 ID 跨单匹配。"""
    line = bom.product_line
    if not line.sales_order_delivery_batch_line_id or not bom.product_id or not bom.product_color_id:
        return
    sales_line_id = line.sales_order_delivery_batch_line.sales_order_line_id
    previous = AuditLog.objects.filter(
        object_type="BOM", action="CONFIRM_PRODUCT",
        after_data__sales_order_line_id=str(sales_line_id),
        after_data__writeback_scope="FIRST_CONFIRMATION",
    ).order_by("occurred_at", "id").first()
    if previous is None:
        return
    confirmed = previous.after_data.get("targets", {}).get("sales_order_line", {})
    fields = {
        "product_id": "product_id", "product_category_id": "product_category_id",
        "product_unit_id": "product_unit_id", "product_color_id": "product_color_id",
        "product_number_snapshot": "product_number_snapshot", "product_code_snapshot": "product_code_snapshot",
        "item_number_snapshot": "item_number_snapshot", "product_name_snapshot": "product_name_snapshot",
        "specification_snapshot": "specification_snapshot", "material_snapshot": "material_snapshot",
        "product_unit_code_snapshot": "unit_code_snapshot", "product_color_name_snapshot": "customer_color_snapshot",
    }
    current = _product_writeback_snapshot(bom, fields)
    if any(source not in confirmed or current[target] != confirmed[source] for target, source in fields.items()):
        return
    bom.product_information_confirmed_at = previous.occurred_at
    bom.product_information_confirmed_by_employee_id = previous.actor_employee_id
    bom.save(update_fields=["product_information_confirmed_at", "product_information_confirmed_by_employee"])
    write_audit_log(
        object_type="BOM", object_id=bom.pk, action="REUSE_PRODUCT_REVIEW",
        context_type="PRODUCTION_TASK", context_id=bom.production_task_id,
        actor_employee=actor_employee,
        after_data={"sales_order_line_id": str(sales_line_id), "confirmation_log_id": str(previous.pk)},
        request=request,
    )


@transaction.atomic
def confirm_bom_product(*, bom, product, product_color, color_code, actor_employee, material=None, new_product=None, request=None):
    """保存当前 BOM 的产品核对；上游回写只由确认 BOM 触发。"""
    ProductionTask.objects.select_for_update().get(pk=bom.production_task_id)
    locked_bom = (
        Bom.objects.select_for_update(of=("self",))
        .get(pk=bom.pk)
    )
    if request is not None:
        require_matching_etag(request, locked_bom)
    if new_product is not None:
        if product is not None:
            raise ValidationError({"product": "选择已有产品与新建产品不能同时提交。"})
        if request is None or not request.user.has_perm("products.add_productinformation"):
            raise PermissionDenied("当前账号没有新增产品信息的权限。")
        from apps.products.models import ProductInformation

        try:
            with transaction.atomic():
                product = ProductInformation.objects.create(**new_product)
        except IntegrityError as exc:
            if getattr(exc.__cause__, "sqlstate", None) != "23505":
                raise
            raise ValidationError({"new_product": "品号或产品编码已存在，请核对后重新提交。"}) from exc
        write_audit_log(
            object_type="PRODUCT_INFORMATION", object_id=product.pk, action="CREATED",
            actor_employee=actor_employee,
            after_data={"bom_id": str(locked_bom.pk), "product_number": product.product_number,
                        "product_name": product.product_name, "specification": product.specification},
            request=request,
        )
    if not product or not product_color:
        raise ValidationError({"product": "必须选择正式产品和颜色。"})
    if product.status != "ACTIVE" or product.archived_at or product_color.status != "ACTIVE" or product_color.archived_at:
        raise ValidationError({"product": "产品和颜色必须为有效的维护记录。"})
    normalized_color_code = str(color_code or product_color.color_code or "").strip()
    if normalized_color_code != str(product_color.color_code or "").strip():
        raise ValidationError({"color_code": "颜色色号与所选颜色主数据不一致。"})
    values = {
        "product": product, "product_category": product.category,
        "product_unit": product.unit, "product_color": product_color,
        "product_number_snapshot": product.product_number,
        "product_code_snapshot": product.product_code,
        "item_number_snapshot": product.product_item.item_number,
        "product_name_snapshot": product.product_name,
        "specification_snapshot": product.specification,
        "product_category_snapshot": product.category.category_name,
        "material_snapshot": locked_bom.material_snapshot if material is None else material,
        "product_unit_code_snapshot": product.unit.unit_code,
        "product_unit_name_snapshot": product.unit.unit_name,
        "product_color_name_snapshot": product_color.color_name,
        "product_color_code_snapshot": normalized_color_code,
        "product_color_card_snapshot": product_color.color_card,
    }
    snapshot_fields = [f"{key}_id" if key in {"product", "product_category", "product_unit", "product_color"} else key for key in values]
    before = _product_writeback_snapshot(locked_bom, snapshot_fields)
    for key, value in values.items():
        setattr(locked_bom, key, value)
    locked_bom.product_information_confirmed_at = timezone.now()
    locked_bom.product_information_confirmed_by_employee = actor_employee
    locked_bom.updated_by_employee = actor_employee
    locked_bom.save(update_fields=[*values, "product_information_confirmed_at", "product_information_confirmed_by_employee", "updated_by_employee", "updated_at"])
    write_audit_log(
        object_type="BOM", object_id=locked_bom.pk,
        context_type="PRODUCTION_TASK", context_id=locked_bom.production_task_id,
        action="REVIEW_PRODUCT", actor_employee=actor_employee, before_data=before,
        after_data=_product_writeback_snapshot(locked_bom, snapshot_fields), request=request,
    )
    return locked_bom


def _writeback_confirmed_bom_product(*, locked_bom, actor_employee, request):
    """仅在 verify_bom 的事务内使用已核对快照回写具体来源明细。"""
    from apps.production_tasks.models import ProductionTaskProduct

    if AuditLog.objects.filter(object_type="BOM", object_id=locked_bom.pk, action="CONFIRM_PRODUCT").exists():
        return locked_bom
    task = locked_bom.production_task
    product = locked_bom.product
    product_color = locked_bom.product_color
    normalized_color_code = locked_bom.product_color_code_snapshot
    locked_line = (
        ProductionTaskProduct.objects.select_for_update(of=("self",))
        .select_related(
            "production_task",
            "unit",
            "currency",
        )
        .get(pk=locked_bom.product_line_id)
    )

    # 同一生产任务产品只允许第一份已确认 BOM 回写上游；后续 BOM 仍保存自身确认结果，
    # 但不能覆盖已经确认过的销售、报价和询盘信息。
    has_prior_confirmed_bom = Bom.objects.filter(
        product_line_id=locked_line.pk,
        status=BomStatus.VERIFIED,
    ).exclude(pk=locked_bom.pk).exists()
    has_prior_confirmed_bom = has_prior_confirmed_bom or AuditLog.objects.filter(
        object_type="BOM",
        action="CONFIRM_PRODUCT",
        after_data__product_line_id=str(locked_line.pk),
    ).exists()

    before = {
        "product_id": str(locked_line.product_id) if locked_line.product_id else None,
        "product_name": locked_line.product_name_snapshot,
        "specification": locked_line.specification_snapshot,
        "color": locked_line.color_name_snapshot,
        "color_code": locked_line.color_code_snapshot,
    }
    source_line = getattr(locked_line.sales_order_delivery_batch_line, "sales_order_line", None)
    sales_line = None
    quotation_line = None
    inquiry_item = None
    quotation_version = None
    write_quotation = False
    write_inquiry = False
    before_targets = {}
    after_targets = {}
    identity_fields = [
        "product_id", "product_category_id", "product_color_id", "product_number_snapshot",
        "product_code_snapshot", "item_number_snapshot", "product_name_snapshot",
        "specification_snapshot", "material_snapshot",
    ]
    task_fields = identity_fields + [
        "unit_id", "customer_product_name_snapshot", "customer_specification_snapshot",
        "customer_color_snapshot", "color_card_snapshot", "color_name_snapshot", "color_code_snapshot",
    ]
    sales_fields = identity_fields + [
        "product_unit_id", "unit_code_snapshot", "customer_product_name_snapshot",
        "customer_specification_snapshot", "customer_color_snapshot",
    ]
    quotation_fields = [
        "product_id", "product_category_id", "product_unit_id", "product_color_id",
        "product_number_snapshot", "product_code_snapshot", "item_number_snapshot",
        "product_description_snapshot", "specification_snapshot", "color_snapshot", "material_snapshot", "unit_code",
    ]
    inquiry_fields = [
        "product_id", "product_category_id", "product_unit_id", "product_color_id",
        "product_number_snapshot", "product_code_snapshot", "item_number_snapshot",
        "product_description", "specification", "color", "material", "unit_code",
    ]
    bom_fields = identity_fields + ["product_unit_id", "product_category_snapshot", "product_unit_code_snapshot", "product_unit_name_snapshot", "product_color_name_snapshot", "product_color_code_snapshot", "product_color_card_snapshot"]
    before_targets["bom"] = _product_writeback_snapshot(locked_bom, bom_fields)
    if source_line is not None and not has_prior_confirmed_bom:
        # 先锁定并更新销售来源行，再校验生产任务产品行；否则产品替换时
        # ProductionTaskProduct.clean 会看到旧的销售产品 ID 而误判为非法替换。
        SalesOrder.objects.select_for_update().get(pk=source_line.sales_order_id)
        sales_line = (
            SalesOrderLine.objects.select_for_update(of=("self",))
            .select_related("sales_order", "source_quotation_line__quotation_version", "source_quotation_line__source_inquiry_item__inquiry")
            .get(pk=source_line.pk)
        )
        # 不同任务可能来自同一销售明细；在共享来源行锁内决定首次回写权。
        has_prior_confirmed_bom = AuditLog.objects.filter(
            object_type="BOM", action="CONFIRM_PRODUCT",
            after_data__sales_order_line_id=str(sales_line.pk),
            after_data__writeback_scope="FIRST_CONFIRMATION",
        ).exists()
        if has_prior_confirmed_bom:
            sales_line = None

    if sales_line is not None:
        before_targets["sales_order_line"] = _product_writeback_snapshot(sales_line, sales_fields)
        quotation_line = sales_line.source_quotation_line
        if quotation_line is not None:
            from apps.quotations.models import QuotationLine, QuotationVersion

            quotation_version = QuotationVersion.objects.select_for_update().get(pk=quotation_line.quotation_version_id)
            quotation_line = QuotationLine.objects.select_for_update().get(pk=quotation_line.pk)
            write_quotation = not AuditLog.objects.filter(
                object_type="BOM", action="CONFIRM_PRODUCT",
                after_data__quotation_line_id=str(quotation_line.pk),
                after_data__writeback_scope="FIRST_CONFIRMATION",
            ).exists()
            if write_quotation:
                before_targets["quotation_line"] = _product_writeback_snapshot(quotation_line, quotation_fields)
                if quotation_line.source_inquiry_item_id:
                    from apps.inquiries.models import Inquiry, InquiryItem

                    source_item = quotation_line.source_inquiry_item
                    Inquiry.objects.select_for_update().get(pk=source_item.inquiry_id)
                    inquiry_item = InquiryItem.objects.select_for_update().get(pk=source_item.pk)
                    write_inquiry = not AuditLog.objects.filter(
                        object_type="BOM", action="CONFIRM_PRODUCT",
                        after_data__inquiry_item_id=str(inquiry_item.pk),
                        after_data__writeback_scope="FIRST_CONFIRMATION",
                    ).exists()
                    if write_inquiry:
                        before_targets["inquiry_item"] = _product_writeback_snapshot(inquiry_item, inquiry_fields)
        sales_line.product = product
        sales_line.product_category = locked_bom.product_category
        sales_line.product_unit = locked_bom.product_unit
        sales_line.product_color = product_color
        sales_line.product_number_snapshot = locked_bom.product_number_snapshot
        sales_line.product_code_snapshot = locked_bom.product_code_snapshot
        sales_line.item_number_snapshot = locked_bom.item_number_snapshot
        sales_line.product_name_snapshot = locked_bom.product_name_snapshot
        sales_line.specification_snapshot = locked_bom.specification_snapshot
        sales_line.material_snapshot = locked_bom.material_snapshot
        sales_line.unit_code_snapshot = locked_bom.product_unit_code_snapshot
        sales_line.customer_product_name_snapshot = locked_bom.product_name_snapshot
        sales_line.customer_specification_snapshot = locked_bom.specification_snapshot
        sales_line.customer_color_snapshot = locked_bom.product_color_name_snapshot
        sales_line.full_clean()
        sales_line.save(update_fields=[
            "product", "product_category", "product_unit", "product_color", "product_number_snapshot",
            "product_code_snapshot", "item_number_snapshot", "product_name_snapshot", "specification_snapshot",
            "material_snapshot", "unit_code_snapshot",
            "customer_product_name_snapshot", "customer_specification_snapshot", "customer_color_snapshot", "updated_at",
        ])
        sales_line.sales_order.updated_at = timezone.now()
        sales_line.sales_order.save(update_fields=["updated_at"])
        after_targets["sales_order_line"] = _product_writeback_snapshot(sales_line, sales_fields)
        locked_line.sales_order_delivery_batch_line.sales_order_line = sales_line

    line_values = {
        "product": product,
        "product_category": locked_bom.product_category,
        "unit": locked_bom.product_unit,
        "product_number_snapshot": locked_bom.product_number_snapshot,
        "product_code_snapshot": locked_bom.product_code_snapshot,
        "item_number_snapshot": locked_bom.item_number_snapshot,
        "material_snapshot": locked_bom.material_snapshot,
        "product_name_snapshot": locked_bom.product_name_snapshot,
        "specification_snapshot": locked_bom.specification_snapshot,
        "customer_product_name_snapshot": locked_bom.product_name_snapshot,
        "customer_specification_snapshot": locked_bom.specification_snapshot,
        "customer_color_snapshot": locked_bom.product_color_name_snapshot,
        "product_color": product_color,
        "color_card_snapshot": locked_bom.product_color_card_snapshot,
        "color_name_snapshot": locked_bom.product_color_name_snapshot,
        "color_code_snapshot": normalized_color_code,
    }
    if not has_prior_confirmed_bom:
        before_targets["production_task_product"] = _product_writeback_snapshot(locked_line, task_fields)
        for field_name, value in line_values.items():
            setattr(locked_line, field_name, value)
        locked_line.full_clean()
        locked_line.save(update_fields=[*line_values.keys(), "updated_at"])
        task.save(update_fields=["updated_at"])
        after_targets["production_task_product"] = _product_writeback_snapshot(locked_line, task_fields)

    after_targets["bom"] = _product_writeback_snapshot(locked_bom, bom_fields)

    if write_quotation:
        quotation_line.product = product
        quotation_line.product_category = locked_bom.product_category
        quotation_line.product_unit = locked_bom.product_unit
        quotation_line.product_color = product_color
        quotation_line.product_number_snapshot = locked_bom.product_number_snapshot
        quotation_line.product_code_snapshot = locked_bom.product_code_snapshot
        quotation_line.item_number_snapshot = locked_bom.item_number_snapshot
        quotation_line.product_description_snapshot = locked_bom.product_name_snapshot
        quotation_line.specification_snapshot = locked_bom.specification_snapshot
        quotation_line.color_snapshot = locked_bom.product_color_name_snapshot
        quotation_line.material_snapshot = locked_bom.material_snapshot
        quotation_line.unit_code = locked_bom.product_unit_code_snapshot
        save_bom_product_information(quotation_line)
        quotation_version.save(update_fields=["updated_at"])
        after_targets["quotation_line"] = _product_writeback_snapshot(quotation_line, quotation_fields)

        if write_inquiry:
            inquiry_item.product = product
            inquiry_item.product_category = locked_bom.product_category
            inquiry_item.product_unit = locked_bom.product_unit
            inquiry_item.product_color = product_color
            inquiry_item.product_number_snapshot = locked_bom.product_number_snapshot
            inquiry_item.product_code_snapshot = locked_bom.product_code_snapshot
            inquiry_item.item_number_snapshot = locked_bom.item_number_snapshot
            inquiry_item.product_description = locked_bom.product_name_snapshot
            inquiry_item.specification = locked_bom.specification_snapshot
            inquiry_item.color = locked_bom.product_color_name_snapshot
            inquiry_item.material = locked_bom.material_snapshot
            inquiry_item.unit_code = locked_bom.product_unit_code_snapshot
            inquiry_item.save(update_fields=[
                "product", "product_category", "product_unit", "product_color", "product_number_snapshot",
                "product_code_snapshot", "item_number_snapshot", "product_description", "specification",
                "color", "material", "unit_code", "updated_at",
            ])
            inquiry_item.inquiry.updated_at = timezone.now()
            inquiry_item.inquiry.save(update_fields=["updated_at"])
            after_targets["inquiry_item"] = _product_writeback_snapshot(inquiry_item, inquiry_fields)

    write_audit_log(
        object_type="BOM",
        object_id=locked_bom.pk,
        context_type="PRODUCTION_TASK",
        context_id=locked_bom.production_task_id,
        action="CONFIRM_PRODUCT",
        actor_employee=actor_employee,
        before_data={**before, "targets": before_targets},
        after_data={
            "product_id": str(product.pk),
            "bom_id": str(locked_bom.pk),
            "bom_version": locked_bom.version_number,
            "product_line_id": str(locked_line.pk),
            "sales_order_line_id": str(sales_line.pk) if sales_line else None,
            "quotation_line_id": str(quotation_line.pk) if write_quotation else None,
            "inquiry_item_id": str(inquiry_item.pk) if write_inquiry else None,
            "writeback_scope": "FIRST_CONFIRMATION" if not has_prior_confirmed_bom else "BOM_ONLY",
            "product_name": locked_bom.product_name_snapshot,
            "specification": locked_bom.specification_snapshot,
            "color": locked_bom.product_color_name_snapshot,
            "color_code": normalized_color_code,
            "targets": after_targets,
        },
        request=request,
    )
    return locked_bom


def _sync_profile_lines_to_order_quantity(bom, *, previous_order_quantity=None):
    for line in BomLine.objects.select_for_update().filter(section__bom=bom).select_related("section"):
        apply_line_quantities(line, bom.order_quantity, tolerate_legacy=True)
        if line.section.section_type == "PROFILE":
            _, raw = _tube_calculations({"length_value": line.length_value, "unit_consumption": line.unit_consumption,
                                        "tube_cut_piece_count": (line.raw_values or {}).get("tube_cut_piece_count", "")}, bom.order_quantity)
            line.raw_values = {**line.raw_values, **raw}
        line.save()


@transaction.atomic
def sync_latest_boms_from_order(*, product_line_ids, actor_employee, request):
    """同步发生产品或数量变更的产品行；已校验 BOM 复制为新版本以保留历史。"""
    from apps.production_tasks.models import ProductionTaskProduct

    product_lines = (
        ProductionTaskProduct.objects.select_for_update()
        .select_related("production_task")
        .filter(pk__in=product_line_ids)
        .order_by("production_task_id", "line_number", "id")
    )
    synced_boms = []
    for product_line in product_lines:
        latest = (
            Bom.objects.select_for_update()
            .filter(product_line=product_line, archived_at__isnull=True)
            .order_by("-version_number", "-id")
            .first()
        )
        if latest is None:
            continue

        if latest.status == BomStatus.VERIFIED:
            if request is not None and not request.user.has_perm("boms.add_bom"):
                raise PermissionDenied("已校验 BOM 需要建立新版本，当前账号没有新建 BOM 的权限。")
            target = create_bom(
                product_line=product_line,
                creation_method=BomCreationMethod.COPY,
                source_bom=latest,
                actor_employee=actor_employee,
                request=request,
                link_source=True,
            )
        else:
            target = latest

        before_data = {
            "bom_number": latest.bom_number,
            "order_quantity": str(latest.order_quantity),
            "status": latest.status,
        }
        order_quantity, batch_quantity, quantity_difference = _quantity_snapshot(
            product_line,
            target.source_quantity,
        )
        previous_order_quantity = Decimal(target.order_quantity)
        product_values = {
            "product_id": product_line.product_id,
            "product_category_id": product_line.product_category_id,
            "product_unit_id": product_line.unit_id,
            "product_color_id": product_line.product_color_id,
            "product_number_snapshot": product_line.product_number_snapshot,
            "product_code_snapshot": product_line.product_code_snapshot,
            "item_number_snapshot": product_line.item_number_snapshot,
            "product_name_snapshot": product_line.product_name_snapshot,
            "specification_snapshot": product_line.specification_snapshot,
            "material_snapshot": product_line.material_snapshot,
            "product_category_snapshot": product_line.product_category.category_name if product_line.product_category_id else "",
            "product_unit_code_snapshot": product_line.unit.unit_code,
            "product_unit_name_snapshot": product_line.unit.unit_name,
            "product_color_name_snapshot": product_line.color_name_snapshot,
            "product_color_code_snapshot": product_line.color_code_snapshot,
            "product_color_card_snapshot": product_line.color_card_snapshot,
        }
        if any(getattr(target, field) != value for field, value in product_values.items()):
            # 从任务重新同步身份时，必须重新核对，不能保留旧身份的确认标记。
            target.product_information_confirmed_at = None
            target.product_information_confirmed_by_employee = None
        for field, value in product_values.items():
            setattr(target, field, value)
        target.order_quantity = order_quantity
        target.batch_quantity = batch_quantity
        target.quantity_difference = quantity_difference
        target.status = BomStatus.PENDING_CONFIRMATION
        target.updated_by_employee = actor_employee
        target.save(
            update_fields=[
                *product_values,
                "product_information_confirmed_at",
                "product_information_confirmed_by_employee",
                "order_quantity",
                "batch_quantity",
                "quantity_difference",
                "status",
                "updated_by_employee",
                "updated_at",
            ]
        )
        _sync_profile_lines_to_order_quantity(target, previous_order_quantity=previous_order_quantity)
        write_audit_log(
            object_type="BOM",
            object_id=target.pk,
            context_type="PRODUCTION_TASK",
            context_id=target.production_task_id,
            action="SYNC_FROM_PRODUCTION_TASK",
            actor_employee=actor_employee,
            before_data=before_data,
            after_data={
                "bom_number": target.bom_number,
                "order_quantity": str(target.order_quantity),
                "status": target.status,
                "copied_from": latest.bom_number if target.pk != latest.pk else None,
            },
            request=request,
        )
        synced_boms.append(target)
    return synced_boms


def _edit_snapshot(bom):
    return {
        "status": bom.status,
        "section_count": bom.section_count,
        "line_count": bom.line_count,
        "sections": [
            {
                "id": section.id,
                "section_type": section.section_type,
                "title": section.title,
                "line_count": section.lines.count(),
            }
            for section in bom.sections.all()
        ],
    }


@transaction.atomic
def update_bom_lines(*, bom, sections, actor_employee, request, intent="draft", confirmation_token="",
                     quantity_confirmation_reason=""):
    ProductionTask.objects.select_for_update().get(pk=bom.production_task_id)
    locked = Bom.objects.select_for_update().get(pk=bom.pk)
    require_matching_etag(request, locked)
    require_save_permissions(request, intent)
    lock_material_references(sections, bom=locked)
    # 字典/版本在等待锁期间可能改变；事务内重新验证，预检凭据会对比实际建档内容。
    from .api.serializers import BomUpdateInputSerializer
    if hasattr(request, "data"):
        validated = BomUpdateInputSerializer(data=request.data, context={"bom": locked})
        validated.is_valid(raise_exception=True)
        sections = validated.validated_data["sections"]
    before_data = _edit_snapshot(locked)
    existing_sections = {
        section.id: section
        for section in locked.sections.prefetch_related("lines").all()
    }

    submitted_section_ids = {item["id"] for item in sections if item.get("id")}
    unknown_section_ids = submitted_section_ids - set(existing_sections)
    if unknown_section_ids:
        raise ValidationError({"sections": "存在不属于当前 BOM 的用料分区，请刷新后重试。"})

    existing_lines = {
        line.id: (section.id, line)
        for section in existing_sections.values()
        for line in section.lines.all()
    }
    submitted_line_ids = [
        line["id"]
        for section_data in sections
        for line in section_data["lines"]
        if line.get("id")
    ]
    if len(submitted_line_ids) != len(set(submitted_line_ids)):
        raise ValidationError({"sections": "同一条用料明细不能重复出现在多个分区。"})
    unknown_line_ids = set(submitted_line_ids) - set(existing_lines)
    if unknown_line_ids:
        raise ValidationError({"sections": "存在不属于当前 BOM 的用料明细，请刷新后重试。"})

    client_keys = [
        line["client_key"]
        for section_data in sections
        for line in section_data["lines"]
        if line.get("client_key")
    ]
    if len(client_keys) != len(set(client_keys)):
        raise ValidationError({"sections": "用料明细的临时标识不能重复。"})

    draft_image_ids = []
    draft_line_payloads = []
    for section_data in sections:
        for line_data in section_data["lines"]:
            line_draft_ids = line_data.get("draft_image_ids", [])
            if len(line_draft_ids) != len(set(line_draft_ids)):
                raise ValidationError({"sections": "同一条用料明细不能重复绑定草稿图片。"})
            if line_draft_ids:
                draft_line_payloads.append((line_data, line_draft_ids))
                draft_image_ids.extend(line_draft_ids)

    if len(draft_image_ids) != len(set(draft_image_ids)):
        raise ValidationError({"sections": "同一张草稿图片不能绑定到多条用料明细。"})

    drafts_for_payload_line = {}
    if draft_image_ids:
        owner_user = getattr(request, "user", None)
        if owner_user is None or not owner_user.is_authenticated:
            raise PermissionDenied("当前账号无法绑定用料明细草稿图片。")
        locked_drafts = list(
            BomLineImageDraft.objects.select_for_update()
            .filter(
                pk__in=draft_image_ids,
                bom=locked,
                owner_user=owner_user,
                expires_at__gt=timezone.now(),
            )
            .select_related("business_file")
        )
        drafts_by_id = {str(draft.pk): draft for draft in locked_drafts}
        if {str(draft_id) for draft_id in draft_image_ids} != set(drafts_by_id):
            raise ValidationError(
                {"sections": "草稿图片不存在、已过期，或不属于当前账号和 BOM，请重新上传。"}
            )

        active_drafts_by_key = {}
        active_drafts = BomLineImageDraft.objects.select_for_update().filter(
            bom=locked,
            owner_user=owner_user,
            draft_key__in={draft.draft_key for draft in locked_drafts},
            expires_at__gt=timezone.now(),
        )
        for draft in active_drafts:
            active_drafts_by_key.setdefault(draft.draft_key, set()).add(draft.pk)

        used_draft_keys = set()
        for line_data, line_draft_ids in draft_line_payloads:
            ordered_drafts = [drafts_by_id[str(draft_id)] for draft_id in line_draft_ids]
            draft_keys = {draft.draft_key for draft in ordered_drafts}
            if len(draft_keys) != 1:
                raise ValidationError({"sections": "同一条用料明细的草稿图片必须来自同一组上传。"})
            draft_key = next(iter(draft_keys))
            if {str(draft_id) for draft_id in line_draft_ids} != {
                str(draft_id) for draft_id in active_drafts_by_key.get(draft_key, set())
            }:
                raise ValidationError({"sections": "同一组草稿图片必须一次完整绑定到同一条用料明细。"})
            if draft_key in used_draft_keys:
                raise ValidationError({"sections": "同一组草稿图片不能拆分绑定到多条用料明细。"})
            used_draft_keys.add(draft_key)
            existing_image_count = 0
            if line_data.get("id"):
                existing_image_count = BomLineImage.objects.filter(bom_line_id=line_data["id"]).count()
            if existing_image_count + len(ordered_drafts) > 20:
                raise ValidationError({"sections": "每条用料明细最多保留 20 张图片。"})
            drafts_for_payload_line[id(line_data)] = ordered_drafts

    material_plan = build_material_save_plan(bom=locked, sections=sections, request=request, for_update=True)
    persist_material_plan(plan=material_plan, bom=locked, request=request, actor_employee=actor_employee,
                          intent=intent, confirmation_token=confirmation_token)

    for section in existing_sections.values():
        section.line_number += 100000
        section.save(update_fields=["line_number", "updated_at"])
        for line in section.lines.all():
            line.line_number += 100000
            line.save(update_fields=["line_number", "updated_at"])

    saved_lines = []
    saved_lines_by_client_key = {}
    fabric_links = []
    kept_section_ids = set()
    kept_line_ids = set()
    for section_number, section_data in enumerate(sections, start=1):
        section_id = section_data.get("id")
        if section_id:
            section = existing_sections[section_id]
            kept_section_ids.add(section_id)
            section.section_type = section_data["section_type"]
            section.title = section_data["title"]
            section.line_number = section_number
            section.save(update_fields=["section_type", "title", "line_number", "updated_at"])
        else:
            section = BomSection.objects.create(
                bom=locked,
                line_number=section_number,
                section_type=section_data["section_type"],
                title=section_data["title"],
            )

        for line_number, line_data in enumerate(section_data["lines"], start=1):
            line_id = line_data.get("id")
            if line_id:
                line = existing_lines[line_id][1]
                kept_line_ids.add(line_id)
                moved_to_section = line.section_id != section.id
                model_values, calculated_values = _editable_model_values(
                    line_data,
                    section.section_type,
                    Decimal(locked.order_quantity),
                    existing_line=line,
                )
                for field, value in model_values.items():
                    setattr(line, field, value)
                line.raw_values = _merged_raw_values(
                    line.raw_values,
                    line_data,
                    section.section_type,
                    section.title,
                    calculated_values,
                )
                line.line_number = line_number
                if moved_to_section:
                    line.section = section
                update_fields = [*model_values, "raw_values", "line_number", "updated_at"]
                if moved_to_section:
                    update_fields.append("section")
                line.save(update_fields=update_fields)
            else:
                model_values, calculated_values = _editable_model_values(
                    line_data,
                    section.section_type,
                    Decimal(locked.order_quantity),
                )
                line = BomLine.objects.create(
                    section=section,
                    line_number=line_number,
                    **model_values,
                    raw_values=_merged_raw_values(
                        {},
                        line_data,
                        section.section_type,
                        section.title,
                        calculated_values,
                    ),
                )

            if line_data.get("client_key"):
                saved_lines_by_client_key[line_data["client_key"]] = line
            if "fabric_source_line_id" in line_data or line_data.get("fabric_source_client_key"):
                fabric_links.append((line, line_data))
            if "fabric_meters_per_set" in line_data:
                line.fabric_meters_per_set = line_data["fabric_meters_per_set"]
            was_piece_usage = any(getattr(line, field) is not None for field in CUTTING_USAGE_FIELDS)
            for field in CUTTING_USAGE_FIELDS:
                if field in line_data:
                    setattr(line, field, line_data[field])
            if was_piece_usage and all(getattr(line, field) is None for field in CUTTING_USAGE_FIELDS):
                raise ValidationError({"sections": "已采用每片用量的裁剪明细不能清空三个参数退回旧口径。"})
            planned_line = material_plan["lines"][(section_number - 1, line_number)]
            line.raw_values = planned_line.raw_values
            line.raw_material, line.category, line.unit = planned_line.raw_material, planned_line.category, planned_line.unit
            line.specification = planned_line.specification
            apply_line_quantities(line, locked.order_quantity)
            line.save()
            saved_lines.append(line)

            line_drafts = drafts_for_payload_line.get(id(line_data), [])
            if line_drafts:
                last_position = BomLineImage.objects.filter(bom_line=line).aggregate(value=Max("position"))["value"] or 0
                BomLineImage.objects.bulk_create(
                    [
                        BomLineImage(
                            bom_line=line,
                            business_file_id=draft.business_file_id,
                            position=last_position + offset,
                        )
                        for offset, draft in enumerate(line_drafts, start=1)
                    ]
                )
                BomLineImageDraft.objects.filter(pk__in=[draft.pk for draft in line_drafts]).delete()

    # 所有行取得真实 ID 后再建立来源关联，支持同次保存新增面料和裁片，且不依赖提交顺序。
    for line, line_data in fabric_links:
        source_key = line_data.get("fabric_source_client_key")
        source_id = line_data.get("fabric_source_line_id")
        if source_key:
            if source_id:
                raise ValidationError({"sections": "来源面料不能同时指定已保存行和未保存行。"})
            source = saved_lines_by_client_key.get(source_key)
            if source is None:
                raise ValidationError({"sections": "来源面料已移除或不存在，请重新选择。"})
            source_id = source.pk
        elif source_id and source_id not in existing_lines:
            raise ValidationError({"sections": "来源面料必须是本 BOM 保留的面料行，请重新选择。"})
        line.fabric_source_line_id = source_id
        line.save(update_fields=["fabric_source_line"])

    validate_fabric_links(saved_lines)
    for line in saved_lines:
        if line.section.title.strip() != "裁剪明细":
            continue
        original_material = line.material
        if original_material.strip() in {"", "/"} and line.fabric_source_line_id:
            line.raw_values["cutting_material_original"] = original_material
            line.material = line.fabric_source_line.material
        else:
            line.raw_values.pop("cutting_material_original", None)
        line.save(update_fields=["material", "raw_values"])
    stale_line_ids = set(existing_lines) - kept_line_ids
    stale_image_file_ids = []
    if stale_line_ids:
        stale_image_file_ids = list(
            BomLineImage.objects.filter(bom_line_id__in=stale_line_ids)
            .values_list("business_file_id", flat=True)
            .distinct()
        )
        BomLine.objects.filter(id__in=stale_line_ids).update(fabric_source_line=None)
        try:
            BomLine.objects.filter(id__in=stale_line_ids).delete()
        except ProtectedError as error:
            raise ValidationError({"sections": "用料已被采购或生产记录引用，不能直接删除，请保留历史来源并建立修订版本。"}) from error
    stale_section_ids = set(existing_sections) - kept_section_ids
    if stale_section_ids:
        BomSection.objects.filter(id__in=stale_section_ids).delete()

    locked.section_count = len(sections)
    locked.line_count = sum(len(section["lines"]) for section in sections)
    locked.status = BomStatus.PENDING_CONFIRMATION
    locked.updated_by_employee = actor_employee
    locked.confirmed_by_employee = None
    locked.confirmed_at = None
    locked.confirmation_reason = ""
    locked.save(
        update_fields=[
            "section_count",
            "line_count",
            "status",
            "updated_by_employee",
            "confirmed_by_employee",
            "confirmed_at",
            "confirmation_reason",
            "updated_at",
        ]
    )
    for file_id in stale_image_file_ids:
        transaction.on_commit(lambda file_id=file_id: delete_business_file_if_unreferenced(file_id))
    refreshed = boms_with_context(Bom.objects.all(), include_lines=True).get(pk=locked.pk)
    write_audit_log(
        object_type="BOM",
        object_id=locked.pk,
        context_type="PRODUCTION_TASK",
        context_id=locked.production_task_id,
        action="UPDATE",
        actor_employee=actor_employee,
        before_data=before_data,
        after_data=_edit_snapshot(refreshed),
        request=request,
    )
    if intent == "verify":
        _verify_locked_bom(locked=refreshed, quantity_confirmation_reason=quantity_confirmation_reason,
                           actor_employee=actor_employee, request=request)
        return boms_with_context(Bom.objects.all(), include_lines=True).get(pk=locked.pk)
    return refreshed


@transaction.atomic
def verify_bom(*, bom, quantity_confirmation_reason, actor_employee, request):
    ProductionTask.objects.select_for_update().get(pk=bom.production_task_id)
    locked = Bom.objects.select_for_update().get(pk=bom.pk)
    require_matching_etag(request, locked)
    return _verify_locked_bom(locked=locked, quantity_confirmation_reason=quantity_confirmation_reason,
                              actor_employee=actor_employee, request=request)


def _verify_locked_bom(*, locked, quantity_confirmation_reason, actor_employee, request):
    """仅由已锁定并完成 ETag 校验的事务入口调用，避免保存后二次使用旧 ETag。"""
    if locked.status == BomStatus.VERIFIED:
        raise Conflict("该 BOM 版本已经确认。")
    if not locked.product_information_confirmed_at or not locked.product_id or not locked.product_color_id:
        raise ValidationError({"product": "请先核对并保存本 BOM 的产品信息，再确认 BOM。"})
    if locked.line_count <= 0:
        raise ValidationError({"sections": "至少需要一条用料明细才能提交校验。"})

    quantity_mismatch = (
        locked.product_line.quantity != locked.order_quantity
        or (locked.source_quantity is not None and locked.source_quantity != locked.order_quantity)
        or (locked.batch_quantity is not None and locked.batch_quantity != locked.order_quantity)
    )
    reason = (quantity_confirmation_reason or locked.quantity_difference_reason or "").strip()
    if quantity_mismatch and not reason:
        baseline = locked.order_quantity
        comparisons = [
            ("当前订单最新产品数量", locked.product_line.quantity),
            ("Excel 原表数量", locked.source_quantity),
            ("生产批次合计数量", locked.batch_quantity),
        ]
        mismatch_details = []
        for label, value in comparisons:
            if value is None or Decimal(value) == baseline:
                continue
            difference = Decimal(value) - baseline
            difference_prefix = "+" if difference > 0 else ""
            mismatch_details.append(
                f"{label}为 {_display_quantity(value)}，"
                f"与本 BOM 保存的订单数量相差 {difference_prefix}{_display_quantity(difference)}"
            )
        detail_text = "；".join(mismatch_details)
        message = f"本 BOM 保存的订单数量为 {_display_quantity(baseline)}"
        if detail_text:
            message = f"{message}；{detail_text}"
        raise ValidationError({"quantity_confirmation_reason": f"{message}。请填写确认原因。"})

    lines = list(BomLine.objects.select_for_update(of=("self",)).filter(section__bom=locked).select_related("section").order_by("pk"))
    lock_bom_line_material_identities(lines)
    for line in lines:
        apply_line_quantities(line, locked.order_quantity, require_complete=True)
        line.save()
    validate_fabric_links(lines, require_complete=True)
    validate_used_components(locked, lines)

    _writeback_confirmed_bom_product(locked_bom=locked, actor_employee=actor_employee, request=request)
    before_status = locked.status
    locked.status = BomStatus.VERIFIED
    locked.updated_by_employee = actor_employee
    locked.confirmed_by_employee = actor_employee
    locked.confirmed_at = timezone.now()
    locked.confirmation_reason = reason
    locked.save(
        update_fields=[
            "status",
            "updated_by_employee",
            "confirmed_by_employee",
            "confirmed_at",
            "confirmation_reason",
            "updated_at",
        ]
    )
    write_audit_log(
        object_type="BOM",
        object_id=locked.pk,
        context_type="PRODUCTION_TASK",
        context_id=locked.production_task_id,
        action="VERIFY",
        actor_employee=actor_employee,
        before_data={"status": before_status},
        after_data={"status": locked.status, "quantity_confirmation_reason": reason},
        request=request,
    )
    return locked
