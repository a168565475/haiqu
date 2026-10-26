from .pipe_purchase import PIPE_PURCHASE_FIELDS, is_sample_total_meter_snapshot, pipe_source_snapshot, purchase_pipe_values, validate_pipe_purchase_source
import hashlib
import json
import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP, localcontext
from pathlib import Path

from django.conf import settings
from django.db import transaction
from django.db.models.deletion import ProtectedError
from django.utils import timezone
from rest_framework.exceptions import NotFound, ValidationError

from apps.boms.models import Bom, BomLine, BomSectionType, BomStatus
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


def _source_quantity(line, bom):
    section_type = line.section.section_type
    if section_type == BomSectionType.PROFILE:
        try:
            snapshot = pipe_source_snapshot(line)
        except (ValidationError, Conflict):
            return None, "suggested_purchase_meters", "", "米", PurchaseQuantityParseStatus.MISSING
        value = Decimal(snapshot["suggested_purchase_meters"])
        return value, "suggested_purchase_meters", str(value), "米", PurchaseQuantityParseStatus.READY

    if section_type == BomSectionType.ACCESSORY:
        value, field_name, text, status = _first_direct_quantity(
            line,
            ["budget_quantity", "total_consumption"],
        )
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
    return {
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
        **({key: pipe_source_snapshot(line)[key] for key in ("raw_bar_length_m", "suggested_bar_count", "suggested_purchase_meters")} if section.section_type == "PROFILE" and parse_status == "READY" else {}),
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
                source_line = _source_line(bom, section, line, product)
                source_lines.append(source_line)
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
                if source_unit not in valid_units:
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
        "unit_name": product.unit.unit_name,
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
        unavailable_blockers.extend(bom_blockers)
        option = _bom_option(product, latest_bom, bom_blockers, len(bom_lines), global_blockers)
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
        "has_creatable_bom": any(option["can_create"] for option in bom_options),
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
        "order_number": order.order_number,
        "production_task_id": str(order.production_task_id) if order.production_task_id else None,
        "source_type": order.source_type,
        "sample_procurement_request_id": str(order.sample_procurement_request_id) if order.sample_procurement_request_id else None,
        "sample_number": order.sample_number_snapshot,
        "production_task_number": order.production_task_number_snapshot,
        "source_revision": order.source_revision,
        "currency_code": order.currency_code_snapshot,
        "is_mailed": order.is_mailed,
        "status": order.status,
        "total_amount": str(order.total_amount) if order.total_amount is not None else None,
        "lines": [
            {
                "purchase_order_line_id": str(line.pk),
                'raw_bar_length_m': str(line.raw_bar_length_m) if line.raw_bar_length_m else None,
                'actual_bar_count': line.actual_bar_count,
                'actual_purchase_meters': str(line.actual_purchase_meters) if line.actual_purchase_meters is not None else None,
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
        is_mailed=validated_data.get("is_mailed"),
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
            quantity = pipe_values["actual_purchase_meters"]
        else:
            pipe_values["calculation_snapshot"] = build_purchase_material_snapshot(source_line["_bom_line"])
        unit_price = input_line.get("unit_price")
        amount = _money(quantity * unit_price) if quantity is not None and unit_price is not None else None
        amounts.append(amount)
        PurchaseOrderLine.objects.create(
            purchase_order=order,
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
    errors = []
    for line in lines:
        validate_pipe_purchase_source(line)
        if is_sample_total_meter_snapshot(line.calculation_snapshot):
            if line.raw_bar_length_m is None or line.actual_bar_count is None or line.actual_purchase_meters is None:
                errors.append(f'第 {line.line_number} 行缺少打样管材采购根数或单根长度')
            elif line.actual_purchase_meters != line.actual_bar_count * line.raw_bar_length_m:
                errors.append(f'第 {line.line_number} 行打样管材米数与根数、单根长度不一致')
        if line.raw_bar_length_m and (line.actual_bar_count is None or line.actual_purchase_meters != line.actual_purchase_quantity):
            errors.append(f"第 {line.line_number} 行缺少有效管材根米数量")
        if line.actual_purchase_quantity is None or line.actual_purchase_quantity <= 0:
            errors.append(f"第 {line.line_number} 行缺少有效采购数量")
        if not line.source_unit_text.strip():
            errors.append(f"第 {line.line_number} 行缺少单位")
        if line.supplier_id is None:
            errors.append(f"第 {line.line_number} 行缺少供应商")
        if line.delivery_date is None:
            errors.append(f"第 {line.line_number} 行缺少采购交期")
        if line.unit_price is None or line.unit_price < 0:
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
    lock_bom_line_material_identities([line.bom_line for line in lines if line.bom_line_id and line.raw_bar_length_m],
                                      extra_raw_material_ids=[line.calculation_snapshot.get('raw_material_id') for line in lines if line.calculation_snapshot])
    if set(submitted_by_id) != {str(line.pk) for line in lines}:
        raise ValidationError({"lines": "采购明细归属已锁定，不能新增、删除或跨采购订单移动。"})

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
        reset_source_fields = refresh_reset_purchase_source(line)
        validate_pipe_purchase_source(line)
        if line.raw_bar_length_m or is_sample_total_meter_snapshot(line.calculation_snapshot):
            pipe_input = {**submitted, 'quantity_difference_reason': submitted.get('quantity_difference_reason', line.quantity_difference_reason)}
            pipe_values = purchase_pipe_values(line.calculation_snapshot, pipe_input)
            for key, value in pipe_values.items():
                setattr(line, key, value)
            quantity = pipe_values["actual_purchase_meters"]
        unit_price = submitted.get("unit_price")
        amount = _money(quantity * unit_price) if quantity is not None and unit_price is not None else None
        line.supplier = supplier
        line.supplier_number_snapshot = supplier.supplier_number if supplier else ""
        line.supplier_name_snapshot = supplier.supplier_name if supplier else ""
        line.supplier_type_snapshot = supplier.supplier_type if supplier else ""
        line.supplier_categories_snapshot = list(supplier.supplier_categories) if supplier else []
        line.delivery_date = submitted.get("delivery_date")
        line.actual_purchase_quantity = quantity
        line.unit_price = unit_price
        line.amount = amount
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
        amounts.append(amount)

    if "is_mailed" in validated_data:
        order.is_mailed = validated_data["is_mailed"]
    order.total_amount = (
        _money(sum(amounts, Decimal("0")))
        if order.currency_id and amounts and all(amount is not None for amount in amounts)
        else None
    )
    if order.status == PurchaseOrderStatus.SUBMITTED:
        errors = _purchase_order_confirmation_errors(order, lines)
        if errors:
            raise ValidationError({"lines": errors})
    order.save(update_fields=["is_mailed", "total_amount", "updated_at"])
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
