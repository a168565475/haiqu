from .catalog_materials import bom_catalog_fields, purchase_catalog_selection, physical_pipe_quantity, priced_quantity
from .pipe_purchase import PIPE_PURCHASE_FIELDS, is_sample_total_meter_snapshot, is_sample_weight_snapshot, pipe_source_snapshot, purchase_pipe_values, validate_pipe_purchase_source
import hashlib
import json
import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP, localcontext
from pathlib import Path

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.db.models.deletion import ProtectedError
from django.utils import timezone
from rest_framework.exceptions import NotFound, ValidationError

from apps.boms.models import Bom, BomLine, BomSectionType, BomStatus
from apps.boms.material_flow_calculations import MaterialFlowValueError, packaging_quantity
from apps.core.api.concurrency import require_matching_etag
from apps.core.api.exceptions import Conflict
from apps.core.audit import write_audit_log
from apps.core.numbering import next_business_number
from apps.files.models import BusinessFile
from apps.production_tasks.models import ProductionTask, ProductionTaskProduct, ProductionTaskStatus
from apps.products.material_identity import resolve_bom_line_raw_material, lock_bom_line_material_identities
from apps.reference_data.models import Currency, ReferenceStatus

from .models import (
    PurchaseOrder,
    PurchaseOrderLine,
    PurchaseOrderStatus,
    PurchaseQuantityParseStatus,
    Supplier,
    SupplierCategory,
    SupplierPurchaseSheet,
    SupplierPurchaseSheetLineImage,
    SupplierPurchaseSheetSealImage,
)
from .material_attribute_snapshot import build_material_attribute_snapshot
from .material_receipt_identity import build_purchase_material_snapshot
from .selectors import (
    production_tasks_with_purchase_sources, purchase_orders_with_context,
    purchase_orders_by_product, purchase_orders_with_product_ids,
)
from .source_access import purchase_order_access
from .set_pricing import apply_set_pricing, line_set_pricing, validate_set_members


MONEY_QUANT = Decimal("0.0001")
MAX_MONEY_VALUE = Decimal("999999999999999999.9999")
PURCHASABLE_TASK_STATUSES = {
    # 新建采购订单（包括草稿）必须以 PMC 已确认的生产任务为来源。
    ProductionTaskStatus.READY,
    ProductionTaskStatus.IN_PRODUCTION,
}
PLAIN_DECIMAL_PATTERN = re.compile(r"^(?:[0-9]+(?:\.[0-9]+)?|\.[0-9]+)$")
GROUPED_DECIMAL_PATTERN = re.compile(r"^[0-9]{1,3}(?:,[0-9]{3})+(?:\.[0-9]+)?$")


def next_purchase_order_number(business_date=None):
    """采购订单与供应商采购表共用 CGDD + YYMMDD + 至少三位日流水。"""
    return next_business_number("PURCHASE_ORDER", business_date)


def supplier_snapshot(supplier):
    return {
        "supplier_number": supplier.supplier_number,
        "supplier_type": supplier.supplier_type,
        "supplier_categories": list(supplier.supplier_categories),
        "supplier_name": supplier.supplier_name,
        "payment_cycle": supplier.payment_cycle,
        "remark": supplier.remark,
        "phone": supplier.phone,
        "is_disabled": supplier.is_disabled,
    }


@transaction.atomic
def create_supplier(*, validated_data, actor_employee, request=None):
    submitted_by_name = getattr(actor_employee, "display_name", "") if actor_employee else ""
    supplier = Supplier(
        supplier_number=next_business_number("SUPPLIER"),
        submitted_by_employee=actor_employee,
        submitted_by_name=submitted_by_name,
        submitted_at=timezone.now(),
        created_by_employee=actor_employee,
        updated_by_employee=actor_employee,
        **validated_data,
    )
    supplier.full_clean()
    supplier.save()
    write_audit_log(
        object_type="SUPPLIER",
        object_id=supplier.pk,
        action="CREATED",
        actor_employee=actor_employee,
        after_data=supplier_snapshot(supplier),
        request=request,
    )
    return supplier


@transaction.atomic
def update_supplier(*, supplier_id, validated_data, actor_employee, request):
    supplier = Supplier.objects.select_for_update().get(
        pk=supplier_id,
        archived_at__isnull=True,
    )
    require_matching_etag(request, supplier)
    before_data = supplier_snapshot(supplier)
    for field_name, value in validated_data.items():
        setattr(supplier, field_name, value)
    supplier.updated_by_employee = actor_employee
    supplier.full_clean()
    supplier.save()
    write_audit_log(
        object_type="SUPPLIER",
        object_id=supplier.pk,
        action="UPDATED",
        actor_employee=actor_employee,
        before_data=before_data,
        after_data=supplier_snapshot(supplier),
        request=request,
    )
    return supplier


class PurchaseSourceUnavailable(Conflict):
    api_error_code = "PURCHASE_SOURCE_UNAVAILABLE"

    def __init__(self, blockers):
        self.error_meta = {"can_create": False, "blockers": blockers}
        super().__init__("当前采购来源不满足采购条件，请根据阻塞原因处理后重试。")


class PurchaseSourceChanged(Conflict):
    api_error_code = "PURCHASE_SOURCE_CHANGED"

    def __init__(self, current_revision):
        self.error_meta = {"current_source_revision": current_revision}
        super().__init__("采购来源已更新，请刷新采购明细后重试。")


def _blocker(code, message, *, product=None, bom=None, **extra):
    result = {"code": code, "message": message}
    if product is not None:
        result.update(
            {
                "product_line_id": str(product.pk),
                "product_line_number": product.line_number,
                "product_number": product.product_number_snapshot,
                "product_name": product.product_name_snapshot,
                "product_color": product.color_name_snapshot,
            }
        )
    if bom is not None:
        result.update({"bom_id": str(bom.pk), "bom_number": bom.bom_number})
    result.update(extra)
    return result


def _parsed_decimal(raw_value):
    text = str("" if raw_value is None else raw_value).strip()
    if not text:
        return None, PurchaseQuantityParseStatus.MISSING
    comma_normalized = text.replace("，", ",")
    if not (
        PLAIN_DECIMAL_PATTERN.fullmatch(comma_normalized)
        or GROUPED_DECIMAL_PATTERN.fullmatch(comma_normalized)
    ):
        return None, PurchaseQuantityParseStatus.INVALID
    normalized = comma_normalized.replace(",", "")
    try:
        value = Decimal(normalized)
    except (InvalidOperation, ValueError):
        return None, PurchaseQuantityParseStatus.INVALID
    if not value.is_finite() or value < 0:
        return None, PurchaseQuantityParseStatus.INVALID
    return value, PurchaseQuantityParseStatus.READY


def _normalized_decimal(raw_value):
    value, status = _parsed_decimal(raw_value)
    if status != PurchaseQuantityParseStatus.READY:
        return value, status
    try:
        value = value.quantize(MONEY_QUANT, rounding=ROUND_HALF_UP)
    except InvalidOperation:
        return None, PurchaseQuantityParseStatus.INVALID
    if value > MAX_MONEY_VALUE:
        return None, PurchaseQuantityParseStatus.INVALID
    return value, PurchaseQuantityParseStatus.READY


def _first_direct_quantity(line, field_names):
    for field_name in field_names:
        raw_value = getattr(line, field_name, "")
        text = str(raw_value or "").strip()
        if not text:
            continue
        value, status = _normalized_decimal(text)
        return value, field_name, text, status
    return None, "", "", PurchaseQuantityParseStatus.MISSING


def _derived_quantity(line, bom, field_name):
    text = str(getattr(line, field_name, "") or "").strip()
    value, status = _parsed_decimal(text)
    source_field = f"{field_name}*order_quantity"
    source_text = f"{text} × {bom.order_quantity}" if text else ""
    if status != PurchaseQuantityParseStatus.READY:
        return None, source_field, source_text, status
    try:
        order_quantity = Decimal(bom.order_quantity)
        precision = max(
            50,
            len(value.as_tuple().digits) + len(order_quantity.as_tuple().digits) + 8,
        )
        with localcontext() as context:
            context.prec = precision
            result = (value * order_quantity).quantize(MONEY_QUANT, rounding=ROUND_HALF_UP)
    except InvalidOperation:
        return None, source_field, source_text, PurchaseQuantityParseStatus.INVALID
    if result > MAX_MONEY_VALUE:
        return None, source_field, source_text, PurchaseQuantityParseStatus.INVALID
    return result, source_field, source_text, PurchaseQuantityParseStatus.READY


def _hardware_weight_data(line, bom):
    """返回五金按重量采购所需的快照；未启用重量规则时返回 None。"""
    if line.section.title.strip() != "五金件":
        return None
    # 普通五金可以记录单重，采购时仍沿用选料单位；铆钉套也按普通配件处理。
    name = re.split(r"[-（(]", line.part_name, maxsplit=1)[0].strip()
    if not name.endswith(("铆钉", "平垫", "垫片", "垫圈")):
        return None
    raw = line.raw_values or {}
    mode = raw.get("hardware_weight_mode") or "MANUAL"
    unit_weight, unit_status = _parsed_decimal(raw.get("unit_material_weight_kg"))
    source_unit = str(line.unit or "").strip()
    weight_source = source_unit.upper() in {"KG", "公斤", "千克"}
    piece_source = source_unit.upper() in {"个", "片", "件", "只", "颗", "粒", "枚", "支", "PCS", "PC", "PIECE", "PIECES"}
    piece_quantity, source_field, source_text, piece_status = _first_direct_quantity(
        line, ["budget_quantity", "total_consumption"]
    )
    if not source_field:
        piece_quantity, source_field, source_text, piece_status = _derived_quantity(line, bom, "unit_consumption")
    if unit_status == PurchaseQuantityParseStatus.READY:
        try:
            unit_weight = unit_weight.quantize(Decimal("0.00000001"), rounding=ROUND_HALF_UP)
        except InvalidOperation:
            unit_weight, unit_status = None, PurchaseQuantityParseStatus.INVALID
        if unit_weight is not None and unit_weight <= 0:
            unit_status = PurchaseQuantityParseStatus.INVALID
    if not weight_source and not piece_source:
        piece_status = PurchaseQuantityParseStatus.INVALID
    if weight_source:
        return {
            "mode": mode, "piece_quantity": None, "piece_source_field": source_field,
            "piece_source_text": source_text, "piece_status": piece_status,
            "source_unit": source_unit, "weight_source": True,
            "unit_weight_kg": unit_weight, "unit_status": unit_status,
            **({"total_weight_kg": piece_quantity} if piece_status == PurchaseQuantityParseStatus.READY
               and piece_quantity is not None and piece_quantity > 0 else {}),
        }
    if piece_status != PurchaseQuantityParseStatus.READY:
        return {
            "mode": mode, "piece_quantity": None, "piece_source_field": source_field,
            "piece_source_text": source_text, "piece_status": piece_status,
            "unit_weight_kg": unit_weight, "unit_status": unit_status,
        }
    if unit_status != PurchaseQuantityParseStatus.READY or unit_weight is None or unit_weight <= 0:
        return {
            "mode": mode, "piece_quantity": piece_quantity, "piece_source_field": source_field,
            "piece_source_text": source_text, "piece_status": piece_status,
            "unit_weight_kg": unit_weight, "unit_status": unit_status,
        }
    with localcontext() as context:
        context.prec = 64
        total_weight = (piece_quantity * unit_weight).quantize(MONEY_QUANT, rounding=ROUND_HALF_UP)
    if total_weight <= 0 or total_weight > MAX_MONEY_VALUE:
        return {
            "mode": mode, "piece_quantity": piece_quantity, "piece_source_field": source_field,
            "piece_source_text": source_text, "piece_status": PurchaseQuantityParseStatus.INVALID,
            "unit_weight_kg": unit_weight, "unit_status": PurchaseQuantityParseStatus.INVALID,
        }
    return {
        "mode": mode, "piece_quantity": piece_quantity, "piece_source_field": source_field,
        "piece_source_text": source_text, "piece_status": piece_status,
        "unit_weight_kg": unit_weight, "unit_status": unit_status,
        "total_weight_kg": total_weight,
    }


def _hardware_calculation_snapshot(line, bom, data):
    snapshot = build_purchase_material_snapshot(line)
    unit_weight = data.get("unit_weight_kg")
    piece_quantity = data.get("piece_quantity")
    total_weight = data.get("total_weight_kg")
    snapshot.update({
        "hardware_weight_mode": data["mode"],
        "measurement_kind": "HARDWARE_WEIGHT",
        "measurement_unit": "kg",
        "hardware_quantity_unit": line.unit or "个",
        "hardware_weight_unit": "KG",
        "hardware_unit_weight_kg": str(unit_weight) if unit_weight is not None else "",
        "hardware_piece_quantity": str(piece_quantity) if piece_quantity is not None else "",
        "hardware_suggested_weight_kg": str(total_weight) if total_weight is not None else "",
        "hardware_weight_snapshot": (line.raw_values or {}).get("hardware_weight_snapshot") or {},
    })
    return snapshot


def is_hardware_weight_snapshot(snapshot):
    return isinstance(snapshot, dict) and snapshot.get("measurement_kind") == "HARDWARE_WEIGHT"


def _validate_hardware_actual_weight(snapshot, submitted, quantity):
    if not is_hardware_weight_snapshot(snapshot):
        return
    submitted_weight = submitted.get("actual_purchase_weight_kg")
    if submitted_weight is not None and quantity is not None and Decimal(submitted_weight) != Decimal(quantity):
        raise ValidationError({"lines": "五金重量采购的实际采购重量必须与实际采购数量（KG）一致。"})


def _source_quantity(line, bom):
    section_type = line.section.section_type
    if line.section.title.strip() == "包材类":
        units_per_box = str((line.raw_values or {}).get("units_per_box", "")).strip()
        try:
            quantity = packaging_quantity(units_per_box=units_per_box, order_quantity=bom.order_quantity)
        except MaterialFlowValueError:
            status = PurchaseQuantityParseStatus.INVALID if units_per_box else PurchaseQuantityParseStatus.MISSING
            return None, "units_per_box", units_per_box, line.unit, status
        return Decimal(quantity), "units_per_box", units_per_box, line.unit, PurchaseQuantityParseStatus.READY
    if line.material_catalog_id and line.section.title.strip() == "面料类" and line.unit != "米":
        return None, "unit_consumption", "", line.unit, PurchaseQuantityParseStatus.MISSING
    if section_type == BomSectionType.PROFILE:
        try:
            snapshot = pipe_source_snapshot(line)
        except (ValidationError, Conflict):
            return None, "suggested_purchase_weight_kg", "", "KG", PurchaseQuantityParseStatus.MISSING
        if snapshot.get("measurement_unit") == "kg":
            value = Decimal(snapshot["suggested_purchase_weight_kg"])
            return value, "suggested_purchase_weight_kg", str(value), "KG", PurchaseQuantityParseStatus.READY
        # 新采购只接受已确认的长料单重；旧采购继续使用自身保存的米制快照履约。
        return None, "suggested_purchase_weight_kg", "", "KG", PurchaseQuantityParseStatus.MISSING

    if section_type == BomSectionType.ACCESSORY:
        hardware = _hardware_weight_data(line, bom)
        if hardware is not None:
            source_unit = str(line.unit or "").strip()
            if hardware.get("total_weight_kg") is not None:
                text = (f"{hardware['piece_source_text']} KG" if hardware.get("weight_source") else
                        f"{hardware['piece_source_text']} {source_unit} × {hardware['unit_weight_kg']} kg/{source_unit}")
                return hardware["total_weight_kg"], "hardware_weight_kg", text, "KG", PurchaseQuantityParseStatus.READY
            status = hardware["piece_status"] if hardware["piece_status"] != PurchaseQuantityParseStatus.READY else hardware["unit_status"]
            text = (f"{hardware['piece_source_text']} KG" if hardware.get("weight_source") else
                    f"{hardware['piece_source_text']} {source_unit} × 单个材料重量" if hardware["piece_source_text"] else "单个材料重量")
            if status == PurchaseQuantityParseStatus.READY:
                status = PurchaseQuantityParseStatus.INVALID
            return None, "hardware_weight_kg", text, "KG", status
        value, field_name, text, status = _first_direct_quantity(line, ["budget_quantity", "total_consumption"])
        if field_name:
            return value, field_name, text, line.unit, status
        value, field_name, text, status = _derived_quantity(line, bom, "unit_consumption")
        return value, field_name, text, line.unit, status

    value, field_name, text, status = _first_direct_quantity(
        line,
        ["total_purchase_quantity", "total_consumption"],
    )
    if field_name:
        return value, field_name, text, line.unit, status
    consumption_field = "purchase_consumption"
    # 面料与辅料共用 FABRIC 类型；辅料编辑页保存的是单个用量，空值保留旧数据的取数规则。
    if section_type == BomSectionType.FABRIC and line.section.title.strip() == "辅料类" and line.unit_consumption.strip():
        consumption_field = "unit_consumption"
    value, field_name, text, status = _derived_quantity(line, bom, consumption_field)
    return value, field_name, text, line.unit, status


def _supplier_category_suggestion(line):
    if line.section.section_type == BomSectionType.PROFILE:
        return SupplierCategory.TUBE, "SECTION"

    text = " ".join(
        str(value or "").lower()
        for value in (
            line.section.title,
            line.category,
            line.material,
            line.part_name,
            line.raw_material,
        )
    )
    rules = [
        (SupplierCategory.PACKAGING, ("包材", "包装", "纸箱", "纸盒", "塑料袋", "编织袋")),
        (SupplierCategory.PLASTIC_PART, ("塑料", "塑胶", "尼龙件", "注塑")),
        (SupplierCategory.HARDWARE, ("五金", "螺丝", "螺母", "铆钉", "垫片", "铁件")),
        (SupplierCategory.AUXILIARY, ("辅料", "织带", "松紧", "拉链", "魔术贴", "绳", "线")),
        (SupplierCategory.FABRIC, ("面料", "布", "牛津", "涤纶", "帆布", "网布")),
    ]
    for category, keywords in rules:
        if any(keyword in text for keyword in keywords):
            return category, "HEURISTIC"
    return None, "UNKNOWN"


def _source_line(bom, section, line, product):
    required_quantity, source_field, source_text, source_unit, parse_status = _source_quantity(line, bom)
    suggested_category, confidence = _supplier_category_suggestion(line)
    pipe_snapshot = pipe_source_snapshot(line) if section.section_type == "PROFILE" and parse_status == "READY" else {}
    hardware_data = _hardware_weight_data(line, bom) if section.section_type == BomSectionType.ACCESSORY else None
    hardware_snapshot = None
    if hardware_data is not None:
        try:
            hardware_snapshot = _hardware_calculation_snapshot(line, bom, hardware_data)
        except (ValidationError, Conflict):
            # 来源详情仍需返回阻塞行，材料身份问题由后续来源校验统一报告。
            hardware_snapshot = None
    return {
        **bom_catalog_fields(line),
        "bom_id": str(bom.pk),
        "bom_number": bom.bom_number,
        "bom_status": bom.status,
        "bom_status_display": bom.get_status_display(),
        "bom_line_id": str(line.pk),
        "source_bom_line_id_snapshot": str(line.pk),
        "product_line_id": str(bom.product_line_id),
        "product_line_number": product.line_number,
        "product_number": bom.product_number_snapshot,
        "product_code": bom.product_code_snapshot,
        "product_name": bom.product_name_snapshot,
        "product_specification": bom.specification_snapshot,
        "product_color": product.color_name_snapshot,
        "section_type": section.section_type,
        "section_title": section.title,
        "category": line.category,
        "material": line.material,
        "part_name": line.part_name,
        "specification": line.specification,
        "raw_material": line.raw_material,
        "material_attributes_snapshot": build_material_attribute_snapshot(line, section),
        "required_quantity": required_quantity,
        "source_quantity_field": source_field,
        "source_quantity_text": source_text,
        "source_unit_text": source_unit,
        "quantity_parse_status": parse_status,
        "suggested_supplier_category": suggested_category,
        "category_source": confidence,
        **({key: pipe_snapshot[key] for key in ("raw_bar_length_m", "suggested_bar_count", "suggested_purchase_meters") if key in pipe_snapshot}),
        **({key: pipe_snapshot[key] for key in ("measurement_unit", "raw_bar_weight_kg", "suggested_purchase_weight_kg") if key in pipe_snapshot}
           if pipe_snapshot.get("measurement_unit") == "kg" else {}),
        **({"suggested_purchase_weight_kg": str(hardware_data["total_weight_kg"])}
           if hardware_data is not None and hardware_data.get("total_weight_kg") is not None else {}),
        **({"calculation_snapshot": hardware_snapshot} if hardware_snapshot is not None else {}),
        "_bom": bom,
        "_bom_line": line,
    }


NON_PURCHASABLE_BOM_SECTION_TITLES = {"裁剪明细"}


def _is_purchasable_bom_section(section):
    return section.title.strip() not in NON_PURCHASABLE_BOM_SECTION_TITLES


def _purchase_source_revision(task, products):
    payload = {
        "task": {
            "id": str(task.pk),
            "status": task.status,
            "updated_at": task.updated_at.isoformat(),
        },
        "products": [],
    }
    for product in products:
        boms = getattr(product, "purchase_source_boms", None)
        if boms is None:
            boms = list(product.boms.filter(archived_at__isnull=True).order_by("-version_number", "-id"))
        latest_bom = boms[0] if boms else None
        product_payload = {
            "id": str(product.pk),
            "quantity": str(product.quantity),
            "updated_at": product.updated_at.isoformat(),
            "latest_bom": None,
        }
        if latest_bom is not None:
            line_revisions = []
            for section in latest_bom.sections.all():
                if not _is_purchasable_bom_section(section):
                    continue
                for line in section.lines.all():
                    if not line.purchase_required:
                        continue
                    line_revisions.append(
                        {
                            "section_id": str(section.pk),
                            "section_type": section.section_type,
                            "section_title": section.title,
                            "section_updated_at": section.updated_at.isoformat(),
                            "line_id": str(line.pk),
                            "line_updated_at": line.updated_at.isoformat(),
                            "category": line.category,
                            "material": line.material,
                            "part_name": line.part_name,
                            "specification": line.specification,
                            "raw_material": line.raw_material,
                            "material_attributes": build_material_attribute_snapshot(line, section),
                            "unit": line.unit,
                            "branch_count": line.branch_count,
                            "budget_quantity": line.budget_quantity,
                            "total_consumption": line.total_consumption,
                            "unit_consumption": line.unit_consumption,
                            "total_purchase_quantity": line.total_purchase_quantity,
                            "purchase_consumption": line.purchase_consumption,
                            "hardware_weight_mode": (line.raw_values or {}).get("hardware_weight_mode", ""),
                            "hardware_weight_input": (line.raw_values or {}).get("hardware_weight_input", {}),
                            "hardware_weight_snapshot": (line.raw_values or {}).get("hardware_weight_snapshot", {}),
                            "unit_material_weight_kg": (line.raw_values or {}).get("unit_material_weight_kg", ""),
                            "material_identity_sources": {
                                key: str((line.raw_values or {}).get(key) or "")
                                for key in (
                                    "source_inventory_material_id",
                                    "source_raw_material_id",
                                    "source_cutting_material_id",
                                    "source_packaging_material_id",
                                    "source_fabric_material_id",
                                    "source_accessory_material_id",
                                )
                            },
                        }
                    )
            product_payload["latest_bom"] = {
                "id": str(latest_bom.pk),
                "version_number": latest_bom.version_number,
                "status": latest_bom.status,
                "order_quantity": str(latest_bom.order_quantity),
                "updated_at": latest_bom.updated_at.isoformat(),
                "lines": line_revisions,
            }
        payload["products"].append(product_payload)
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _latest_bom_for_product(product):
    boms = getattr(product, "purchase_source_boms", None)
    if boms is None:
        boms = list(product.boms.filter(archived_at__isnull=True).order_by("-version_number", "-id"))
    return boms[0] if boms else None


def _hardware_quantity_blocker(product, bom, section, line, source):
    weight = _hardware_weight_data(line, bom)
    if weight.get("weight_source"):
        detail = "请核对按公斤填写的采购数量。"
    elif weight["piece_status"] == PurchaseQuantityParseStatus.READY and weight["unit_status"] != PurchaseQuantityParseStatus.READY:
        detail = "按公斤采购，请填写有效的单个材料重量（kg），以便从件数换算。"
    else:
        detail = "按公斤采购，请核对五金用量、数量单位和计算出的总重量。"
    name = (line.material_selection_snapshot or {}).get("name") or line.part_name or line.raw_material
    return _blocker(
        "BOM_PURCHASE_QUANTITY_INVALID", f"{section.title}第{line.line_number}行「{name}」：{detail}",
        product=product, bom=bom, bom_line_id=str(line.pk), line_number=line.line_number,
        section_title=section.title, source_quantity_field=source["source_quantity_field"],
    )


def _bom_source_details(product, bom):
    blockers = []
    source_lines = []
    if bom is None:
        blockers.append(_blocker("BOM_MISSING", "该产品没有有效 BOM。", product=product))
    else:
        if bom.status != BomStatus.VERIFIED:
            blockers.append(
                _blocker(
                    "BOM_NOT_VERIFIED",
                    "该产品最新 BOM 尚未校验，不能回退使用旧版本。",
                    product=product,
                    bom=bom,
                    bom_status=bom.status,
                )
            )
        if Decimal(bom.order_quantity) != Decimal(product.quantity):
            blockers.append(
                _blocker(
                    "BOM_QUANTITY_STALE",
                    "该产品最新 BOM 数量与生产订单数量不一致。",
                    product=product,
                    bom=bom,
                    bom_order_quantity=str(bom.order_quantity),
                    production_order_quantity=str(product.quantity),
                )
            )
        identity_errors = []
        identity_cache = {}
        for section in bom.sections.all():
            if not _is_purchasable_bom_section(section):
                continue
            for line in section.lines.all():
                if not line.purchase_required:
                    continue
                source_line = _source_line(bom, section, line, product)
                source_lines.append(source_line)
                if line.material_catalog_id:
                    if source_line["quantity_parse_status"] != "READY":
                        if source_line["source_quantity_field"] == "hardware_weight_kg":
                            blockers.append(_hardware_quantity_blocker(product, bom, section, line, source_line))
                        else:
                            identity_errors.append({"bom_line_id": str(line.pk), "reason": "MATERIAL_QUANTITY_REQUIRED"})
                    continue
                material, source_key = resolve_bom_line_raw_material(
                    line,
                    cache=identity_cache,
                )
                if material is None:
                    identity_errors.append(
                        {
                            "bom_line_id": str(line.pk),
                            "line_number": line.line_number,
                            "section_title": section.title,
                            "part_name": line.part_name,
                            "reason": "MATERIAL_IDENTITY_UNRESOLVED",
                        }
                    )
                    continue
                if section.section_type == "PROFILE":
                    if source_line["quantity_parse_status"] != "READY":
                        identity_errors.append({"bom_line_id": str(line.pk), "reason": "PIPE_PARAMETERS_REQUIRED"})
                    continue
                source_unit = str(source_line["source_unit_text"] or "").strip()
                valid_units = {
                    material.unit.unit_name.strip(),
                    material.unit.unit_code.strip(),
                }
                hardware_weighted = (
                    section.section_type == BomSectionType.ACCESSORY
                    and source_unit == "KG"
                    and is_hardware_weight_snapshot(source_line.get("calculation_snapshot"))
                )
                if hardware_weighted and source_line["quantity_parse_status"] != "READY":
                    blockers.append(_hardware_quantity_blocker(product, bom, section, line, source_line))
                if source_unit not in valid_units and not hardware_weighted:
                    identity_errors.append(
                        {
                            "bom_line_id": str(line.pk),
                            "line_number": line.line_number,
                            "section_title": section.title,
                            "part_name": line.part_name,
                            "reason": "UNIT_MISMATCH",
                            "source_key": source_key,
                            "source_unit": source_unit,
                            "inventory_unit": material.unit.unit_name,
                        }
                    )
        if identity_errors:
            blockers.append(
                _blocker(
                    "BOM_MATERIAL_IDENTITY_INVALID",
                    "BOM 存在未绑定具体库存原料或采购单位不一致的明细，请先修正 BOM。",
                    product=product,
                    bom=bom,
                    invalid_line_count=len(identity_errors),
                    invalid_lines=identity_errors[:20],
                )
            )
        if not source_lines:
            blockers.append(
                _blocker(
                    "BOM_EMPTY",
                    "该产品最新 BOM 没有可采购的用料明细。",
                    product=product,
                    bom=bom,
                )
            )
    return blockers, source_lines


def _bom_option(product, bom, blockers, line_count, global_blockers):
    return {
        "product_line_id": str(product.pk),
        "product_line_number": product.line_number,
        "product_number": product.product_number_snapshot,
        "product_code": product.product_code_snapshot,
        "product_name": product.product_name_snapshot,
        "product_color": product.color_name_snapshot,
        "order_quantity": str(product.quantity),
        "unit_name": product.unit_name,
        "bom_id": str(bom.pk) if bom else None,
        "bom_number": bom.bom_number if bom else "",
        "bom_status": bom.status if bom else "MISSING",
        "bom_status_display": bom.get_status_display() if bom else "未建立 BOM",
        "line_count": line_count,
        "can_create": not global_blockers and not blockers,
        "blockers": [*global_blockers, *blockers],
    }


def evaluate_purchase_source(task, bom_id=None):
    global_blockers = []
    if task.status not in PURCHASABLE_TASK_STATUSES:
        global_blockers.append(
            _blocker(
                "TASK_NOT_READY",
                "生产任务单必须经 PMC 确认后，才能创建采购订单。",
                task_status=task.status,
                task_status_display=task.get_status_display(),
            )
        )

    orders = getattr(task, "purchase_source_orders", None)
    if orders is None:
        orders = purchase_orders_with_product_ids(PurchaseOrder.objects.filter(production_task=task))
    existing_by_product = purchase_orders_by_product(orders)
    from .models import PurchaseGroup
    existing_groups = {}
    groups = PurchaseGroup.objects.filter(production_task=task, archived_at__isnull=True).prefetch_related(
        "bom_sources", "combined_into_sources",
    )
    for group in groups:
        if group.combined_into_sources.all():
            continue
        if group.product_line_id_snapshot:
            existing_groups[group.product_line_id_snapshot] = group
        else:
            for membership in group.bom_sources.all():
                existing_groups[membership.product_line_id_snapshot] = group
    if None in existing_by_product:
        global_blockers.append(
            _blocker(
                "PURCHASE_PRODUCT_UNKNOWN",
                "已有采购单缺少可核实的产品明细，请先核实原单据。",
            )
        )

    products = getattr(task, "purchase_source_products", None)
    if products is None:
        products = list(task.products.order_by("line_number", "id"))
    product_missing_blocker = None
    if not products:
        product_missing_blocker = _blocker("BOM_MISSING", "生产订单没有产品明细，无法读取 BOM。")

    bom_options = []
    source_by_bom_id = {}
    product_by_bom_id = {}
    unavailable_blockers = []
    for product in products:
        latest_bom = _latest_bom_for_product(product)
        bom_blockers, bom_lines = _bom_source_details(product, latest_bom)
        existing = existing_by_product.get(product.pk)
        if existing is not None:
            bom_blockers.append(_blocker(
                "PURCHASE_ORDER_EXISTS", "该产品已建立采购订单。", product=product, bom=latest_bom,
                existing_purchase_order_id=str(existing.pk),
                existing_purchase_order_number=existing.order_number,
            ))
        elif product.pk in existing_groups:
            group = existing_groups[product.pk]
            # 旧第一批无下游删除后，来源完全未变时沿用原总单重建，不生成第二份建议量。
            can_reconnect = (
                latest_bom is not None and group.source_bom_id_snapshot == latest_bom.pk
                and group.source_revision == _purchase_source_revision(task, [product])
                and not group.compatibility_issues and not group.batches.exists()
                and not group.lines.exclude(compatibility_issues=[]).exists()
            )
            if not can_reconnect:
                bom_blockers.append(_blocker(
                    "PURCHASE_GROUP_EXISTS", "该产品已有采购需求，请在该需求中新增批次。", product=product, bom=latest_bom,
                    existing_purchase_group_id=str(group.pk), existing_purchase_group_number=group.group_number,
                ))
        unavailable_blockers.extend(bom_blockers)
        option = _bom_option(product, latest_bom, bom_blockers, len(bom_lines), global_blockers)
        if option["can_create"]:
            option["source_revision"] = _purchase_source_revision(task, [product])
        group = existing_groups.get(product.pk)
        if group:
            option["existing_purchase_group_id"] = str(group.pk)
            if (not global_blockers and latest_bom and latest_bom.status == BomStatus.VERIFIED
                    and group.product_line_id_snapshot == product.pk and group.source_bom_id_snapshot
                    and not group.manual_completed_at and not group.compatibility_issues):
                option["can_combine"] = True
                option["combine_source_revision"] = group.source_revision
        bom_options.append(option)
        if latest_bom is not None:
            source_by_bom_id[str(latest_bom.pk)] = (bom_blockers, bom_lines)
            product_by_bom_id[str(latest_bom.pk)] = product

    requested_bom_id = str(bom_id) if bom_id else None
    available_bom_ids = list(source_by_bom_id)
    if requested_bom_id and requested_bom_id not in source_by_bom_id:
        raise ValidationError({"bom_id": "所选 BOM 不属于该生产订单，或不是该产品的最新版本。"})

    selected_bom_id = requested_bom_id
    if selected_bom_id is None and len(available_bom_ids) == 1:
        selected_bom_id = available_bom_ids[0]

    selected_product = product_by_bom_id.get(selected_bom_id)
    existing = existing_by_product.get(selected_product.pk) if selected_product is not None else None
    selected_blockers = []
    selected_lines = []
    if selected_bom_id:
        selected_blockers, selected_lines = source_by_bom_id[selected_bom_id]

    requires_bom_selection = selected_bom_id is None and len(available_bom_ids) > 1
    blockers = [*global_blockers, *selected_blockers]
    if product_missing_blocker:
        blockers.append(product_missing_blocker)
    if not selected_bom_id and not available_bom_ids:
        blockers.extend(unavailable_blockers)
    if requires_bom_selection:
        blockers.append(_blocker("BOM_SELECTION_REQUIRED", "请选择本次要采购的产品 BOM。"))

    can_create = bool(selected_bom_id and selected_lines and not blockers)
    revision_products = [selected_product] if selected_product is not None else products
    return {
        "can_create": can_create,
        "blockers": blockers,
        "lines": selected_lines if can_create else [],
        "preview_lines": selected_lines if selected_bom_id and not can_create else [],
        "bom_options": bom_options,
        "selected_bom_id": selected_bom_id,
        "requires_bom_selection": requires_bom_selection,
        "has_creatable_bom": (any(option["can_create"] for option in bom_options) or
                              sum(bool(option.get("can_combine")) for option in bom_options) >= 2),
        "existing_purchase_order_id": str(existing.pk) if existing else None,
        "existing_purchase_order_number": existing.order_number if existing else None,
        "product_count": len(products),
        "remaining_product_count": sum(product.pk not in existing_by_product for product in products),
        "source_revision": _purchase_source_revision(task, revision_products),
    }


def public_purchase_source(task, bom_id=None):
    result = evaluate_purchase_source(task, bom_id=bom_id)
    for field_name in ("lines", "preview_lines"):
        public_lines = []
        for line in result[field_name]:
            public_line = {key: value for key, value in line.items() if not key.startswith("_")}
            if public_line["required_quantity"] is not None:
                public_line["required_quantity"] = format(public_line["required_quantity"], "f")
            public_lines.append(public_line)
        result[field_name] = public_lines
    return result


def refresh_batch_demand_version(group_id):
    if group_id:
        from .models import PurchaseGroup, PurchaseGroupBomSource
        combined_ids = PurchaseGroupBomSource.objects.filter(previous_group_id=group_id).values("purchase_group_id")
        PurchaseGroup.objects.filter(Q(pk=group_id) | Q(pk__in=combined_ids)).update(updated_at=timezone.now())


def _money(value):
    try:
        decimal_value = Decimal(value)
        if not decimal_value.is_finite() or decimal_value < 0:
            raise InvalidOperation
        result = decimal_value.quantize(MONEY_QUANT, rounding=ROUND_HALF_UP)
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValidationError({"lines": "采购金额不是可保存的有限非负数。"}) from exc
    if result > MAX_MONEY_VALUE:
        raise ValidationError({"lines": "采购金额超出系统可保存范围。"})
    return result


def purchase_order_audit_context(order):
    if order.sample_procurement_request_id:
        return {"context_type": "SAMPLE_REQUEST", "context_id": order.sample_procurement_request.material_request.sample_request_id}
    return {"context_type": "PRODUCTION_TASK", "context_id": order.production_task_id}


def purchase_order_snapshot(order):
    return {
        "purchase_group_id": str(order.purchase_group_id) if order.purchase_group_id else None,
        "batch_number": order.batch_number,
        "batch_type": order.batch_type,
        "order_number": order.order_number,
        "production_task_id": str(order.production_task_id) if order.production_task_id else None,
        "source_type": order.source_type,
        "sample_procurement_request_id": str(order.sample_procurement_request_id) if order.sample_procurement_request_id else None,
        "sample_number": order.sample_number_snapshot,
        "production_task_number": order.production_task_number_snapshot,
        "source_revision": order.source_revision,
        "currency_code": order.currency_code_snapshot,
        "status": order.status,
        "total_amount": str(order.total_amount) if order.total_amount is not None else None,
        "lines": [
            {
                "purchase_order_line_id": str(line.pk),
                'raw_bar_length_m': str(line.raw_bar_length_m) if line.raw_bar_length_m else None,
                'raw_bar_weight_kg': str(line.raw_bar_weight_kg) if line.raw_bar_weight_kg is not None else None,
                'actual_bar_count': line.actual_bar_count,
                'actual_purchase_meters': str(line.actual_purchase_meters) if line.actual_purchase_meters is not None else None,
                'actual_purchase_weight_kg': str(line.actual_purchase_weight_kg) if line.actual_purchase_weight_kg is not None else None,
                'suggested_purchase_weight_kg': str(line.suggested_purchase_weight_kg) if line.suggested_purchase_weight_kg is not None else None,
                'quantity_difference_reason': line.quantity_difference_reason,
                'calculation_snapshot': line.calculation_snapshot,
                "sample_line_key": str(line.sample_material_source.line_key) if hasattr(line, "sample_material_source") else None,
                "source_bom_line_id": str(line.source_bom_line_id_snapshot) if line.source_bom_line_id_snapshot else None,
                "supplier_id": str(line.supplier_id) if line.supplier_id else None,
                "delivery_date": line.delivery_date,
                "actual_purchase_quantity": (
                    str(line.actual_purchase_quantity) if line.actual_purchase_quantity is not None else None
                ),
                "unit_price": str(line.unit_price) if line.unit_price is not None else None,
                "amount": str(line.amount) if line.amount is not None else None,
                "material_attributes_snapshot": line.material_attributes_snapshot,
            }
            for line in order.lines.order_by("line_number", "id")
        ],
    }


@transaction.atomic
def create_purchase_order(*, validated_data, allowed_task_ids, actor_employee, request=None):
    if validated_data.get("source_type") == "SAMPLE":
        from .sample_purchase_services import create_sample_purchase_order
        return create_sample_purchase_order(validated_data=validated_data, actor_employee=actor_employee, request=request)
    task_id = validated_data["production_task_id"]
    try:
        locked_task = ProductionTask.objects.select_for_update().get(
            pk=task_id,
            pk__in=allowed_task_ids,
            archived_at__isnull=True,
        )
    except ProductionTask.DoesNotExist as exc:
        raise NotFound("生产订单不存在、已归档或不在当前账号的数据范围内。") from exc

    # BOM 编辑会删除旧行；先锁定当前来源，再生成采购快照。
    list(
        ProductionTaskProduct.objects.select_for_update()
        .filter(production_task=locked_task)
        .order_by("id")
    )
    list(Bom.objects.select_for_update().filter(production_task=locked_task).order_by("id"))
    locked_source_lines = list(
        BomLine.objects.select_for_update()
        .filter(section__bom__production_task=locked_task)
        .order_by("id")
    )
    lock_bom_line_material_identities(locked_source_lines)
    task = production_tasks_with_purchase_sources(
        ProductionTask.objects.filter(pk=locked_task.pk)
    ).get()
    source = evaluate_purchase_source(task, bom_id=validated_data["bom_id"])
    if not source["can_create"]:
        raise PurchaseSourceUnavailable(source["blockers"])
    if validated_data["source_revision"] != source["source_revision"]:
        raise PurchaseSourceChanged(source["source_revision"])

    submitted_lines = validated_data["lines"]
    submitted_ids = [str(item["bom_line_id"]) for item in submitted_lines]
    if len(submitted_ids) != len(set(submitted_ids)):
        raise ValidationError({"lines": "同一条 BOM 明细不能重复提交。"})
    source_by_id = {line["bom_line_id"]: line for line in source["lines"]}
    if set(submitted_ids) != set(source_by_id):
        raise ValidationError({"lines": "采购明细必须完整对应当前所选的最新 BOM，请刷新后重试。"})

    currency = None
    currency_id = validated_data.get("currency_id")
    if currency_id:
        try:
            currency = Currency.objects.select_for_update().get(
                pk=currency_id,
                status=ReferenceStatus.ACTIVE,
                archived_at__isnull=True,
            )
        except Currency.DoesNotExist as exc:
            raise ValidationError({"currency_id": "采购币种不存在或已停用。"}) from exc

    supplier_ids = {item.get("supplier_id") for item in submitted_lines if item.get("supplier_id")}
    # 保持供应商状态校验与编辑互斥，同时允许已持 CGDD 流水锁的采购表提交外键。
    suppliers = {
        str(item.pk): item
        for item in Supplier.objects.select_for_update(no_key=True).filter(
            pk__in=supplier_ids,
            archived_at__isnull=True,
            is_disabled=False,
        )
    }
    missing_supplier_ids = {str(item) for item in supplier_ids} - set(suppliers)
    if missing_supplier_ids:
        raise ValidationError({"lines": "采购明细包含不存在、已禁用或已归档的供应商。"})

    order = PurchaseOrder.objects.create(
        order_number=next_purchase_order_number(),
        production_task=task,
        production_task_number_snapshot=task.task_number,
        sales_order_number_snapshot=task.order_number,
        customer_name_snapshot=task.customer_account.account_name if task.customer_account_id else "",
        source_revision=source["source_revision"],
        currency=currency,
        currency_code_snapshot=currency.code if currency else "",
        currency_name_snapshot=currency.chinese_name if currency else "",
        currency_symbol_snapshot=currency.symbol if currency else "",
        status=PurchaseOrderStatus.DRAFT,
        total_amount=None,
        created_by_employee=actor_employee,
    )

    amounts = []
    input_by_id = {str(item["bom_line_id"]): item for item in submitted_lines}
    for line_number, source_line in enumerate(source["lines"], start=1):
        input_line = input_by_id[source_line["bom_line_id"]]
        supplier_id = input_line.get("supplier_id")
        supplier = suppliers.get(str(supplier_id)) if supplier_id else None
        quantity = input_line.get("actual_purchase_quantity")
        pipe_values = {}
        if source_line["section_type"] == "PROFILE":
            pipe_values = purchase_pipe_values(pipe_source_snapshot(source_line["_bom_line"]), input_line)
            quantity = physical_pipe_quantity(pipe_values["calculation_snapshot"], input_line, pipe_values)
        else:
            pipe_values["calculation_snapshot"] = build_purchase_material_snapshot(source_line["_bom_line"])
            if source_line["section_type"] == BomSectionType.ACCESSORY:
                hardware_data = _hardware_weight_data(source_line["_bom_line"], source_line["_bom"])
                if hardware_data is not None:
                    pipe_values["calculation_snapshot"] = _hardware_calculation_snapshot(source_line["_bom_line"], source_line["_bom"], hardware_data)
        _validate_hardware_actual_weight(pipe_values["calculation_snapshot"], input_line, quantity)
        unit_price = input_line.get("unit_price")
        price_quantity = priced_quantity(section_type=source_line["section_type"], material_catalog_id=source_line["material_catalog_id"], physical_quantity=quantity, pipe_values=pipe_values)
        amount = _money(price_quantity * unit_price) if price_quantity is not None and quantity is not None and unit_price is not None else None
        amounts.append(amount)
        PurchaseOrderLine.objects.create(
            purchase_order=order,
            **bom_catalog_fields(source_line["_bom_line"]),
            **pipe_values,
            line_number=line_number,
            bom=source_line["_bom"],
            bom_line=source_line["_bom_line"],
            source_bom_line_id_snapshot=source_line["source_bom_line_id_snapshot"],
            product_line_id_snapshot=source_line["product_line_id"],
            bom_number_snapshot=source_line["bom_number"],
            product_number_snapshot=source_line["product_number"],
            product_code_snapshot=source_line["product_code"],
            product_name_snapshot=source_line["product_name"],
            product_specification_snapshot=source_line["product_specification"],
            section_type_snapshot=source_line["section_type"],
            section_title_snapshot=source_line["section_title"],
            category_snapshot=source_line["category"],
            material_snapshot=source_line["material"],
            part_name_snapshot=source_line["part_name"],
            specification_snapshot=source_line["specification"],
            raw_material_snapshot=source_line["raw_material"],
            material_attributes_snapshot=source_line["material_attributes_snapshot"],
            required_quantity=source_line["required_quantity"],
            source_quantity_field=source_line["source_quantity_field"],
            source_quantity_text=source_line["source_quantity_text"],
            source_unit_text=source_line["source_unit_text"],
            quantity_parse_status=source_line["quantity_parse_status"],
            supplier=supplier,
            supplier_number_snapshot=supplier.supplier_number if supplier else "",
            supplier_name_snapshot=supplier.supplier_name if supplier else "",
            supplier_type_snapshot=supplier.supplier_type if supplier else "",
            supplier_categories_snapshot=list(supplier.supplier_categories) if supplier else [],
            delivery_date=input_line.get("delivery_date"),
            actual_purchase_quantity=quantity,
            unit_price=unit_price,
            amount=amount,
        )

    if currency is not None and amounts and all(amount is not None for amount in amounts):
        order.total_amount = _money(sum(amounts, Decimal("0")))
        order.save(update_fields=["total_amount", "updated_at"])

    from .group_services import attach_purchase_order_group
    attach_purchase_order_group(order)
    order = purchase_orders_with_context().get(pk=order.pk)
    write_audit_log(
        object_type="PURCHASE_ORDER",
        object_id=order.pk,
        **purchase_order_audit_context(order),
        action="CREATED",
        actor_employee=actor_employee,
        after_data=purchase_order_snapshot(order),
        request=request,
    )
    return order


def _purchase_order_confirmation_errors(order, lines):
    validate_set_members(lines)
    errors = []
    for line in lines:
        validate_pipe_purchase_source(line)
        if is_sample_total_meter_snapshot(line.calculation_snapshot):
            if line.raw_bar_length_m is None or line.actual_bar_count is None or line.actual_purchase_meters is None:
                errors.append(f'第 {line.line_number} 行缺少打样管材采购根数或单根长度')
            elif line.actual_purchase_meters != line.actual_bar_count * line.raw_bar_length_m:
                errors.append(f'第 {line.line_number} 行打样管材米数与根数、单根长度不一致')
        if line.section_type_snapshot == "PROFILE" and line.source_unit_text == "KG":
            if (line.raw_bar_length_m is None or line.raw_bar_weight_kg is None or line.actual_bar_count is None
                    or line.actual_purchase_weight_kg is None or line.actual_purchase_quantity != line.actual_purchase_weight_kg):
                errors.append(f"第 {line.line_number} 行缺少有效管材重量或换算根数")
        elif line.raw_bar_length_m and (line.actual_bar_count is None or line.actual_purchase_meters != line.actual_purchase_quantity):
            errors.append(f"第 {line.line_number} 行缺少有效管材根米数量")
        if line.actual_purchase_quantity is None or line.actual_purchase_quantity <= 0:
            errors.append(f"第 {line.line_number} 行缺少有效采购数量")
        if not line.source_unit_text.strip():
            errors.append(f"第 {line.line_number} 行缺少单位")
        if line.supplier_id is None:
            errors.append(f"第 {line.line_number} 行缺少供应商")
        if line.delivery_date is None:
            errors.append(f"第 {line.line_number} 行缺少采购交期")
        if not line_set_pricing(line) and (line.unit_price is None or line.unit_price < 0):
            errors.append(f"第 {line.line_number} 行缺少有效采购单价")
        if line.amount is None:
            errors.append(f"第 {line.line_number} 行缺少采购金额")
    if order.currency_code_snapshot != "CNY":
        errors.append("供应商采购表金额单位固定为元，采购单必须使用人民币 CNY")
    return errors


def _lock_purchase_task(order_id):
    from apps.samples.models import SampleRequest
    source = PurchaseOrder.objects.filter(pk=order_id).values('production_task_id', 'sample_procurement_request__material_request__sample_request_id').first()
    task_id = source['production_task_id'] if source else None
    if task_id:
        ProductionTask.objects.select_for_update().get(pk=task_id)
    sample_id = source['sample_procurement_request__material_request__sample_request_id'] if source else None
    if sample_id:
        SampleRequest.objects.select_for_update().get(pk=sample_id)


@transaction.atomic
def update_purchase_order(*, order_id, validated_data, allowed_task_ids, actor_employee, request=None):
    _lock_purchase_task(order_id)
    order = (
        PurchaseOrder.objects.select_for_update(of=("self",))
        .filter(
            purchase_order_access(allowed_task_ids, request),
            pk=order_id,
            archived_at__isnull=True,
        )
        .first()
    )
    if order is None:
        raise NotFound("采购订单不存在或不在当前账号的数据范围内。")
    if order.status not in {PurchaseOrderStatus.DRAFT, PurchaseOrderStatus.SUBMITTED}:
        raise Conflict("当前采购订单状态不允许编辑。")
    if SupplierPurchaseSheet.objects.filter(purchase_order=order, archived_at__isnull=True).exists():
        raise Conflict("该采购订单已生成供应商采购表。为避免上下游内容不一致，请先删除采购表后再修改采购订单。")
    require_matching_etag(request, order)

    lines = list(
        PurchaseOrderLine.objects.select_for_update()
        .filter(purchase_order=order)
        .order_by("line_number", "id")
    )
    submitted_lines = validated_data["lines"]
    submitted_by_id = {str(item["id"]): item for item in submitted_lines}
    skipped_ids = {str(item) for item in validated_data.get("skipped_line_ids", [])}
    if skipped_ids and (order.status != PurchaseOrderStatus.DRAFT or not order.purchase_group_id):
        raise Conflict("只有生产采购批次草稿可以跳过材料。")
    if skipped_ids.intersection(submitted_by_id) or (set(submitted_by_id) | skipped_ids) != {str(line.pk) for line in lines}:
        raise ValidationError({"lines": "采购明细必须对应本单的材料，每行只能保留或跳过一次。"})

    lines = [line for line in lines if str(line.pk) in submitted_by_id]
    lock_bom_line_material_identities([line.bom_line for line in lines if line.bom_line_id and line.raw_bar_length_m],
                                      extra_raw_material_ids=[line.calculation_snapshot.get('raw_material_id') for line in lines if line.calculation_snapshot])

    supplier_ids = {item.get("supplier_id") for item in submitted_lines if item.get("supplier_id")}
    suppliers = {
        str(item.pk): item
        for item in Supplier.objects.select_for_update().filter(
            pk__in=supplier_ids,
            archived_at__isnull=True,
            is_disabled=False,
        )
    }
    if {str(item) for item in supplier_ids} - set(suppliers):
        raise ValidationError({"lines": "采购明细包含不存在、已禁用或已归档的供应商。"})

    before = purchase_order_snapshot(purchase_orders_with_context().get(pk=order.pk))
    amounts = []
    for line in lines:
        submitted = submitted_by_id[str(line.pk)]
        supplier_id = submitted.get("supplier_id")
        supplier = suppliers.get(str(supplier_id)) if supplier_id else None
        quantity = submitted.get("actual_purchase_quantity")
        from .reset_sources import refresh_reset_purchase_source
        reset_source_fields = [] if order.batch_request_id else refresh_reset_purchase_source(line)
        validate_pipe_purchase_source(line)
        if line.raw_bar_length_m or is_sample_total_meter_snapshot(line.calculation_snapshot) or is_sample_weight_snapshot(line.calculation_snapshot):
            pipe_input = {**submitted, 'quantity_difference_reason': submitted.get('quantity_difference_reason', line.quantity_difference_reason)}
            pipe_values = purchase_pipe_values(line.calculation_snapshot, pipe_input)
            for key, value in pipe_values.items():
                setattr(line, key, value)
            quantity = physical_pipe_quantity(line.calculation_snapshot, submitted, pipe_values)
            if is_sample_weight_snapshot(line.calculation_snapshot):
                line.required_quantity = line.suggested_purchase_weight_kg
                line.source_quantity_text = str(line.required_quantity) if line.required_quantity is not None else ''
                line.quantity_parse_status = 'READY' if line.required_quantity is not None else 'MISSING'
                reset_source_fields.extend(['required_quantity', 'source_quantity_text', 'quantity_parse_status'])
        _validate_hardware_actual_weight(line.calculation_snapshot, submitted, quantity)
        unit_price = submitted.get("unit_price")
        price_quantity = quantity
        amount = _money(price_quantity * unit_price) if price_quantity is not None and quantity is not None and unit_price is not None else None
        line.supplier = supplier
        line.supplier_number_snapshot = supplier.supplier_number if supplier else ""
        line.supplier_name_snapshot = supplier.supplier_name if supplier else ""
        line.supplier_type_snapshot = supplier.supplier_type if supplier else ""
        line.supplier_categories_snapshot = list(supplier.supplier_categories) if supplier else []
        line.delivery_date = submitted.get("delivery_date")
        line.actual_purchase_quantity = quantity
        line.unit_price = unit_price
        line.amount = amount
        apply_set_pricing(line, submitted)
        line.save(update_fields=[
            *reset_source_fields,
            *PIPE_PURCHASE_FIELDS,
            "supplier",
            "supplier_number_snapshot",
            "supplier_name_snapshot",
            "supplier_type_snapshot",
            "supplier_categories_snapshot",
            "delivery_date",
            "actual_purchase_quantity",
            "unit_price",
            "amount",
            "updated_at",
        ])
        amounts.append(line.amount)

    validate_set_members(lines)
    if skipped_ids:
        order.lines.filter(pk__in=skipped_ids).delete()
    if "batch_type" in validated_data:
        if not order.purchase_group_id or order.source_type != "PRODUCTION":
            raise ValidationError({"batch_type": "只有生产采购需求的批次可以设置采购类型。"})
        order.batch_type = validated_data["batch_type"]
    order.total_amount = (
        _money(sum(amounts, Decimal("0")))
        if order.currency_id and amounts and all(amount is not None for amount in amounts)
        else None
    )
    if order.status == PurchaseOrderStatus.SUBMITTED:
        errors = _purchase_order_confirmation_errors(order, lines)
        if errors:
            raise ValidationError({"lines": errors})
    order.save(update_fields=["batch_type", "total_amount", "updated_at"])
    refresh_batch_demand_version(order.purchase_group_id)
    updated = purchase_orders_with_context().get(pk=order.pk)
    write_audit_log(
        object_type="PURCHASE_ORDER",
        object_id=order.pk,
        **purchase_order_audit_context(order),
        action="UPDATED_AFTER_CONFIRMATION" if order.status == PurchaseOrderStatus.SUBMITTED else "UPDATED",
        actor_employee=actor_employee,
        before_data=before,
        after_data=purchase_order_snapshot(updated),
        request=request,
    )
    return updated


@transaction.atomic
def confirm_purchase_order(*, order_id, allowed_task_ids, actor_employee, request=None):
    _lock_purchase_task(order_id)
    order = (
        PurchaseOrder.objects.select_for_update(of=("self",))
        .prefetch_related("lines")
        .filter(
            purchase_order_access(allowed_task_ids, request),
            pk=order_id,
            archived_at__isnull=True,
        )
        .first()
    )
    if order is None:
        raise NotFound("采购单不存在。")
    if order.status != PurchaseOrderStatus.DRAFT:
        raise Conflict("只有草稿采购单可以确认。")
    lines = list(order.lines.all())
    if not lines:
        raise ValidationError({"lines": "采购单没有明细，不能确认。"})
    lock_bom_line_material_identities([line.bom_line for line in lines if line.bom_line_id and line.raw_bar_length_m],
                                      extra_raw_material_ids=[line.calculation_snapshot.get('raw_material_id') for line in lines if line.calculation_snapshot])
    errors = _purchase_order_confirmation_errors(order, lines)
    if errors:
        raise ValidationError({"lines": errors})
    before = purchase_order_snapshot(order)
    order.status = PurchaseOrderStatus.SUBMITTED
    order.save(update_fields=["status", "updated_at"])
    write_audit_log(
        object_type="PURCHASE_ORDER",
        object_id=order.pk,
        **purchase_order_audit_context(order),
        action="CONFIRMED",
        actor_employee=actor_employee,
        before_data=before,
        after_data=purchase_order_snapshot(order),
        request=request,
    )
    return purchase_orders_with_context().get(pk=order.pk)


@transaction.atomic
def delete_purchase_order(*, order_id, allowed_task_ids, actor_employee, request=None):
    _lock_purchase_task(order_id)
    order = (
        PurchaseOrder.objects.select_for_update(of=("self",))
        .filter(
            purchase_order_access(allowed_task_ids, request),
            pk=order_id,
            archived_at__isnull=True,
        )
        .first()
    )
    if order is None:
        raise NotFound("采购订单不存在或不在当前账号的数据范围内。")

    # 锁定采购明细，避免删除检查与材料入库同时发生。
    list(
        PurchaseOrderLine.objects.select_for_update()
        .filter(purchase_order=order)
        .values_list("id", flat=True)
    )
    if PurchaseOrderLine.objects.filter(
        purchase_order=order,
        material_inbound_lines__isnull=False,
    ).exists():
        raise Conflict("该采购订单已经产生材料入库记录，不能删除。")

    order_with_lines = purchase_orders_with_context().get(pk=order.pk)
    before = purchase_order_snapshot(order_with_lines)
    order_id_value = order.pk
    production_task_id = order.production_task_id

    sheets = list(
        SupplierPurchaseSheet.objects.select_for_update()
        .filter(purchase_order=order)
        .order_by("id")
    )
    if any(sheet.purchase_request_allocations.exists() for sheet in sheets):
        raise Conflict("该采购订单生成的供应商采购表已关联采购申请分配，不能删除。")

    if order.batch_request_id:
        # 新批次保留幂等请求和序号，避免删除后重放同一请求重新下单。
        require_matching_etag(request, order)
        now = timezone.now()
        order.archived_at = now
        order.archived_by_employee = actor_employee
        order.archive_reason = "删除未入库采购批次"
        order.save(update_fields=["archived_at", "archived_by_employee", "archive_reason", "updated_at"])
        SupplierPurchaseSheet.objects.filter(pk__in=[sheet.pk for sheet in sheets]).update(
            archived_at=now, archived_by_employee=actor_employee, archive_reason="采购批次已删除", updated_at=now,
        )
        refresh_batch_demand_version(order.purchase_group_id)
        write_audit_log(object_type="PURCHASE_ORDER", object_id=order.pk, **purchase_order_audit_context(order),
                        action="ARCHIVED", actor_employee=actor_employee, before_data=before, request=request)
        return

    sheet_ids = [sheet.pk for sheet in sheets]
    business_file_ids = {sheet.pdf_file_id for sheet in sheets if sheet.pdf_file_id}
    if sheet_ids:
        business_file_ids.update(
            SupplierPurchaseSheetLineImage.objects.filter(sheet_id__in=sheet_ids)
            .values_list("image_file_id", flat=True)
        )
        business_file_ids.update(
            SupplierPurchaseSheetSealImage.objects.filter(sheet_id__in=sheet_ids)
            .values_list("image_file_id", flat=True)
        )

    sheet_snapshots = [
        {
            "sheet_number": sheet.sheet_number,
            "version_number": sheet.version_number,
            "is_current": sheet.is_current,
            "status": sheet.status,
            "purchase_order_id": str(sheet.purchase_order_id),
            "supplier_id": str(sheet.supplier_id),
            "template_version_id": str(sheet.template_version_id),
            "total_amount": str(sheet.total_amount) if sheet.total_amount is not None else None,
            "pdf_file_id": str(sheet.pdf_file_id) if sheet.pdf_file_id else None,
        }
        for sheet in sheets
    ]
    for sheet, snapshot in zip(sheets, sheet_snapshots):
        write_audit_log(
            object_type="SUPPLIER_PURCHASE_SHEET",
            object_id=sheet.pk,
            context_type="PURCHASE_ORDER",
            context_id=order_id_value,
            action="DELETED",
            actor_employee=actor_employee,
            before_data=snapshot,
            request=request,
        )

    if sheet_ids:
        SupplierPurchaseSheet.objects.filter(pk__in=sheet_ids).delete()

    storage_paths = []
    for business_file in BusinessFile.objects.select_for_update().filter(pk__in=business_file_ids):
        has_references = any(
            relation.related_model._base_manager.filter(
                **{relation.field.name: business_file.pk}
            ).exists()
            for relation in business_file._meta.related_objects
        )
        if has_references:
            continue
        media_root = Path(settings.MEDIA_ROOT).resolve()
        storage_path = (media_root / business_file.storage_key).resolve()
        try:
            storage_path.relative_to(media_root)
        except ValueError:
            storage_path = None
        if storage_path == media_root:
            storage_path = None
        try:
            business_file.delete()
        except ProtectedError:
            continue
        if storage_path is not None:
            storage_paths.append(storage_path)

    before["deleted_supplier_purchase_sheets"] = sheet_snapshots
    from apps.samples.models import SampleMaterialPurchaseSource
    SampleMaterialPurchaseSource.objects.filter(purchase_order_line__purchase_order=order).delete()
    order.delete()
    refresh_batch_demand_version(order.purchase_group_id)
    write_audit_log(
        object_type="PURCHASE_ORDER",
        object_id=order_id_value,
        **purchase_order_audit_context(order),
        action="DELETED",
        actor_employee=actor_employee,
        before_data=before,
        request=request,
    )

    def remove_files_after_commit():
        for storage_path in storage_paths:
            try:
                storage_path.unlink(missing_ok=True)
            except OSError:
                # 数据库删除已经提交；磁盘清理失败交由运维处理，避免返回假失败。
                pass

    transaction.on_commit(remove_files_after_commit)


# 兼容已经使用旧函数名的内部调用；新页面和新接口统一使用“确认”。
submit_purchase_order = confirm_purchase_order
