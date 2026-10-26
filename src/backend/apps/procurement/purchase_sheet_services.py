import uuid
from copy import deepcopy
from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from django.db import models, transaction
from django.utils import timezone
from rest_framework.exceptions import NotFound, ValidationError

from apps.core.api.concurrency import require_matching_etag
from apps.core.api.exceptions import Conflict
from apps.core.audit import write_audit_log
from apps.files.uploads import save_scanned_image

from .models import (
    PurchaseAllocationStatus,
    PurchaseContractTemplate,
    PurchaseContractTemplateStatus,
    PurchaseContractTemplateVersion,
    PurchaseOrder,
    PurchaseOrderStatus,
    PurchaseRequest,
    PurchaseRequestAllocation,
    PurchaseRequestStatus,
    SupplierPurchaseSheet,
    SupplierPurchaseSheetLineImage,
    SupplierPurchaseSheetSealImage,
    SupplierPurchaseSheetStatus,
)
from .services import MAX_MONEY_VALUE, MONEY_QUANT, next_purchase_order_number


DEFAULT_BUYER = {
    "name": "浙江嗨趣休闲用品有限公司",
    "address": "",
    "contact": "",
    "phone": "",
}
ALLOWED_SETTLEMENT_MODES = {"NORMAL", "ACTUAL_WEIGHT"}
DEFAULT_CONTRACT_SECTIONS = {
    "payment_and_delivery": "乙方应在{{采购交期}}前将货物送达甲方指定地点；付款方式以双方最终确认内容为准。",
    "quality_standards": [
        "乙方供应的产品应符合双方确认的规格、样品及质量要求，不得侵犯第三方知识产权。",
        "产品材质、尺寸、颜色、外观和单位应与确认样或双方书面确认内容一致；不合格品由乙方负责退换并承担相关费用。",
    ],
    "delivery_handover": "乙方送货至甲方指定地点，送货前通知甲方采购人员验收；验收不合格时，甲方有权拒收或要求退换。",
    "special_instructions": "价格及技术要求以本采购表和双方书面确认内容为准；未经甲方书面确认，不得擅自变更。",
    "dispute_resolution": "履行过程中发生争议，双方应先友好协商；协商不成，向甲方所在地有管辖权的人民法院起诉。",
    "effectiveness": "本采购表一式两份，甲乙双方各执一份，自双方签字或盖章之日起生效；扫描件、电子邮件确认件具有同等效力。",
}


def _structured_sections(config):
    config = config if isinstance(config, dict) else {}
    legacy_terms = [str(item).strip() for item in config.get("terms") or [] if str(item).strip()]
    quality = config.get("quality_standards")
    if not isinstance(quality, list) or not quality:
        quality = legacy_terms[:2] or DEFAULT_CONTRACT_SECTIONS["quality_standards"]
    return {
        "payment_and_delivery": str(config.get("payment_and_delivery") or DEFAULT_CONTRACT_SECTIONS["payment_and_delivery"]),
        "quality_standards": list(quality),
        "delivery_handover": str(config.get("delivery_handover") or DEFAULT_CONTRACT_SECTIONS["delivery_handover"]),
        "special_instructions": str(config.get("special_instructions") or DEFAULT_CONTRACT_SECTIONS["special_instructions"]),
        "dispute_resolution": str(config.get("dispute_resolution") or DEFAULT_CONTRACT_SECTIONS["dispute_resolution"]),
        "effectiveness": str(config.get("effectiveness") or DEFAULT_CONTRACT_SECTIONS["effectiveness"]),
    }


def _delivery_date_text(lines):
    values = sorted({
        str(item.get("delivery_date") or "").strip()
        for item in lines
        if str(item.get("delivery_date") or "").strip()
    })
    formatted = []
    for value in values:
        try:
            parsed = date.fromisoformat(value)
        except ValueError:
            formatted.append(value)
        else:
            formatted.append(f"{parsed.year}年{parsed.month}月{parsed.day}日")
    return "、".join(formatted) if formatted else "约定采购交期"


def _resolve_section_variables(sections, lines):
    delivery_text = _delivery_date_text(lines)

    def replace(value):
        return str(value).replace("{{采购交期}}", delivery_text)

    return {
        **sections,
        "payment_and_delivery": replace(sections["payment_and_delivery"]),
        "quality_standards": [replace(item) for item in sections["quality_standards"]],
        "delivery_handover": replace(sections["delivery_handover"]),
        "special_instructions": replace(sections["special_instructions"]),
        "dispute_resolution": replace(sections["dispute_resolution"]),
        "effectiveness": replace(sections["effectiveness"]),
    }


def _string(value, *, field_name, max_length, allow_blank=True):
    normalized = str(value or "").strip()
    if not allow_blank and not normalized:
        raise ValidationError({field_name: "该字段不能为空。"})
    if len(normalized) > max_length:
        raise ValidationError({field_name: f"该字段不能超过 {max_length} 个字符。"})
    return normalized


def _decimal(value, *, field_name, allow_null=True, positive=False, maximum=MAX_MONEY_VALUE):
    if value in (None, ""):
        if allow_null:
            return None
        raise ValidationError({field_name: "该字段不能为空。"})
    try:
        result = Decimal(str(value)).quantize(MONEY_QUANT, rounding=ROUND_HALF_UP)
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValidationError({field_name: "请输入有效数字。"}) from exc
    if not result.is_finite() or result < 0 or (positive and result <= 0):
        message = "请输入大于 0 的数字。" if positive else "请输入非负数字。"
        raise ValidationError({field_name: message})
    if result > maximum:
        raise ValidationError({field_name: "数值超出系统可保存范围。"})
    return result


def _date_text(value, *, field_name, allow_blank=True):
    normalized = str(value or "").strip()
    if not normalized and allow_blank:
        return ""
    try:
        return date.fromisoformat(normalized).isoformat()
    except ValueError as exc:
        raise ValidationError({field_name: "日期必须为 YYYY-MM-DD 格式。"}) from exc


def sheet_snapshot(sheet):
    return {
        "sheet_number": sheet.sheet_number,
        "version_number": sheet.version_number,
        "is_current": sheet.is_current,
        "status": sheet.status,
        "purchase_order_id": str(sheet.purchase_order_id) if sheet.purchase_order_id else None,
        "purchase_request_id": str(sheet.purchase_request_id) if sheet.purchase_request_id else None,
        "supplier_id": str(sheet.supplier_id),
        "template_version_id": str(sheet.template_version_id),
        "total_amount": str(sheet.total_amount) if sheet.total_amount is not None else None,
        "pdf_file_id": str(sheet.pdf_file_id) if sheet.pdf_file_id else None,
    }


def _sheet_access_filter(allowed_task_ids, request=None):
    from .source_access import purchase_order_access
    return (
        purchase_order_access(allowed_task_ids, request, "purchase_order__")
        | models.Q(purchase_request__production_task_id__in=allowed_task_ids)
    )


def _sheet_context(sheet):
    if sheet.purchase_request_id:
        return "PURCHASE_REQUEST", sheet.purchase_request_id
    return "PURCHASE_ORDER", sheet.purchase_order_id


def _default_content(order, supplier, lines, template_version, sheet_number):
    from .pipe_purchase import pipe_sheet_fields
    config = deepcopy(template_version.content_config) if isinstance(template_version.content_config, dict) else {}
    settlement_mode = config.get("settlement_mode")
    if settlement_mode not in ALLOWED_SETTLEMENT_MODES:
        settlement_mode = "NORMAL"
    content_lines = []
    for line in lines:
        pipe_fields = pipe_sheet_fields(line)
        if pipe_fields and settlement_mode == 'ACTUAL_WEIGHT':
            raise ValidationError({'template_version_id': '管材按米计价，请改选按米模板，不能使用按重量结算模板。'})
        content_lines.append(
            {
                **pipe_fields,
                "source_purchase_order_line_id": str(line.pk),
                "product_name": line.product_name_snapshot,
                "product_specification": line.product_specification_snapshot,
                "part_name": line.part_name_snapshot,
                "specification": line.specification_snapshot,
                "material": line.raw_material_snapshot if order.source_type == "SAMPLE" else line.material_snapshot,
                "section_type": line.section_type_snapshot,
                "section_title": line.section_title_snapshot,
                "material_attributes_snapshot": deepcopy(line.material_attributes_snapshot) if isinstance(line.material_attributes_snapshot, dict) else {},
                "quantity": format(line.actual_purchase_quantity, "f") if line.actual_purchase_quantity is not None else "",
                "unit": line.source_unit_text,
                "unit_price": format(line.unit_price, "f") if line.unit_price is not None else "",
                "amount": format(line.amount, "f") if line.amount is not None else "",
                "delivery_date": line.delivery_date.isoformat() if line.delivery_date else "",
                "remark": line.color_snapshot if order.source_type == "SAMPLE" else "",
            }
        )
    total = None
    if settlement_mode != "ACTUAL_WEIGHT" and content_lines and all(item["amount"] != "" for item in content_lines):
        total = sum((Decimal(item["amount"]) for item in content_lines), Decimal("0")).quantize(MONEY_QUANT)
    buyer = deepcopy(config.get("buyer")) if isinstance(config.get("buyer"), dict) else deepcopy(DEFAULT_BUYER)
    sections = _resolve_section_variables(_structured_sections(config), content_lines)
    return {
        "title": str(config.get("title") or "采购合同"),
        "sheet_number": sheet_number,
        "purchase_date": timezone.localdate().isoformat(),
        "order": {
            "sales_order_number": order.sales_order_number_snapshot,
            "production_task_number": order.production_task_number_snapshot,
            "source_type": order.source_type,
            "source_number": order.sample_number_snapshot if order.source_type == "SAMPLE" else order.production_task_number_snapshot,
        },
        "buyer": {**DEFAULT_BUYER, **buyer},
        "seller": {
            "name": supplier.supplier_name,
            "address": "",
            "contact": "",
            "phone": supplier.phone,
        },
        "settlement_mode": settlement_mode,
        "tax_rate": str(config.get("tax_rate") or "13"),
        "freight_bearer": str(config.get("freight_bearer") or "乙方"),
        "remark": "",
        **sections,
        "show_image": bool(config.get("show_image", True)),
        "seal_status": "NOT_UPLOADED",
        "lines": content_lines,
        "total_amount": format(total, "f") if total is not None else None,
        'schema_version': 2 if any(row.get('measurement_kind') == 'PIPE' for row in content_lines) else 1,
    }


def _purchase_request_content(purchase_request, supplier, allocations, template_version, sheet_number):
    from .material_attribute_snapshot import build_material_attribute_snapshot

    config = deepcopy(template_version.content_config) if isinstance(template_version.content_config, dict) else {}
    settlement_mode = config.get("settlement_mode")
    if settlement_mode not in ALLOWED_SETTLEMENT_MODES:
        settlement_mode = "NORMAL"
    product_line = purchase_request.bom.product_line
    content_lines = []
    for allocation in allocations:
        request_line = allocation.purchase_request_line
        if request_line.bom_line and request_line.bom_line.section.section_type == 'PROFILE':
            raise Conflict('旧管材采购申请不能生成供应商表，请先从采购汇总单建立根米采购。')
        content_lines.append(
            {
                # 兼容既有采购表编辑器；新链路中该字段保存采购分配行 ID。
                "source_purchase_order_line_id": str(allocation.pk),
                "product_name": product_line.product_name_snapshot,
                "product_specification": product_line.specification_snapshot,
                "part_name": request_line.material_snapshot,
                "specification": request_line.specification_snapshot,
                "material": request_line.material_snapshot,
                "section_type": request_line.bom_line.section.section_type,
                "section_title": request_line.bom_line.section.title,
                "material_attributes_snapshot": build_material_attribute_snapshot(
                    request_line.bom_line,
                    request_line.bom_line.section,
                ),
                "quantity": format(allocation.quantity, "f"),
                "unit": request_line.unit_snapshot,
                "unit_price": "",
                "amount": "",
                "delivery_date": allocation.expected_arrival_date.isoformat(),
                "remark": f"来源采购申请 {purchase_request.request_number} 第 {request_line.line_number} 行",
            }
        )
    buyer = deepcopy(config.get("buyer")) if isinstance(config.get("buyer"), dict) else deepcopy(DEFAULT_BUYER)
    sales_order = purchase_request.production_task.sales_order
    sections = _resolve_section_variables(_structured_sections(config), content_lines)
    return {
        "title": str(config.get("title") or "采购合同"),
        "sheet_number": sheet_number,
        "purchase_date": timezone.localdate().isoformat(),
        "order": {
            "sales_order_number": sales_order.order_number if sales_order else purchase_request.production_task.order_number,
            "production_task_number": purchase_request.production_task.task_number,
            "purchase_request_number": purchase_request.request_number,
        },
        "buyer": {**DEFAULT_BUYER, **buyer},
        "seller": {
            "name": supplier.supplier_name,
            "address": "",
            "contact": "",
            "phone": supplier.phone,
        },
        "settlement_mode": settlement_mode,
        "tax_rate": str(config.get("tax_rate") or "13"),
        "freight_bearer": str(config.get("freight_bearer") or "乙方"),
        "remark": "",
        **sections,
        "show_image": bool(config.get("show_image", True)),
        "seal_status": "NOT_UPLOADED",
        "lines": content_lines,
        "total_amount": None,
    }


def _inherit_bom_line_images(sheet, source_rows, actor_employee):
    """每条来源明细只沿用 BOM 中排序第一的图片，后续仍可在采购表中替换。"""
    inherited = []
    for source_line_id, bom_line in source_rows:
        if bom_line is None:
            continue
        source_image = next(iter(bom_line.images.all()), None)
        if source_image is None:
            continue
        inherited.append(
            SupplierPurchaseSheetLineImage(
                sheet=sheet,
                source_purchase_order_line_id=source_line_id,
                image_file=source_image.business_file,
                created_by_employee=actor_employee,
            )
        )
    if inherited:
        SupplierPurchaseSheetLineImage.objects.bulk_create(inherited, ignore_conflicts=True)


@transaction.atomic
def generate_supplier_purchase_sheet_from_request(
    *, purchase_request, supplier, procurement_batch_number, template_version, allowed_task_ids, actor_employee, request=None
):
    purchase_request = (
        PurchaseRequest.objects.select_for_update(of=("self",))
        .select_related(
            "production_task__sales_order",
            "bom__product_line",
        )
        .filter(pk=purchase_request.pk, production_task_id__in=allowed_task_ids, archived_at__isnull=True)
        .first()
    )
    if purchase_request is None:
        raise NotFound("采购申请不存在或不在当前账号的数据范围内。")
    require_matching_etag(request, purchase_request)
    if purchase_request.status not in {
        PurchaseRequestStatus.SUBMITTED,
        PurchaseRequestStatus.ALLOCATING,
        PurchaseRequestStatus.FULLY_ALLOCATED,
    }:
        raise Conflict("采购申请提交后才能生成供应商采购单。")
    batch_number = str(procurement_batch_number or "").strip()
    if not batch_number:
        raise ValidationError({"procurement_batch_number": "采购批次不能为空。"})
    if supplier.archived_at or supplier.is_disabled:
        raise ValidationError({"supplier_id": "供应商已禁用或归档。"})
    if template_version.template.archived_at or template_version.template.status != PurchaseContractTemplateStatus.ACTIVE:
        raise ValidationError({"template_version_id": "采购模板不存在、已停用或已归档。"})

    allocations = list(
        PurchaseRequestAllocation.objects.select_for_update()
        .select_related("purchase_request_line__bom_line__section")
        .prefetch_related("purchase_request_line__bom_line__images__business_file")
        .filter(
            purchase_request_line__purchase_request=purchase_request,
            supplier=supplier,
            procurement_batch_number=batch_number,
            status=PurchaseAllocationStatus.DRAFT,
            supplier_purchase_sheet__isnull=True,
        )
        .order_by("purchase_request_line__line_number", "created_at", "id")
    )
    if not allocations:
        raise ValidationError({"allocations": "该供应商和采购批次没有待下单的分配明细。"})
    if SupplierPurchaseSheet.objects.filter(
        purchase_request=purchase_request,
        supplier=supplier,
        procurement_batch_number=batch_number,
        is_current=True,
        archived_at__isnull=True,
    ).exists():
        raise Conflict("该供应商和采购批次已经生成正式采购单。")

    sheet_number = next_purchase_order_number()
    content = _purchase_request_content(
        purchase_request,
        supplier,
        allocations,
        template_version,
        sheet_number,
    )
    sheet = SupplierPurchaseSheet.objects.create(
        purchase_request=purchase_request,
        supplier=supplier,
        supplier_number_snapshot=supplier.supplier_number,
        supplier_name_snapshot=supplier.supplier_name,
        supplier_phone_snapshot=supplier.phone,
        sheet_number=sheet_number,
        version_number=1,
        procurement_batch_number=batch_number,
        is_current=True,
        template_version=template_version,
        status=SupplierPurchaseSheetStatus.DRAFT,
        content_snapshot=content,
        created_by_employee=actor_employee,
        updated_by_employee=actor_employee,
    )
    _inherit_bom_line_images(
        sheet,
        (
            (allocation.pk, allocation.purchase_request_line.bom_line)
            for allocation in allocations
        ),
        actor_employee,
    )
    PurchaseRequestAllocation.objects.filter(pk__in=[item.pk for item in allocations]).update(
        status=PurchaseAllocationStatus.ORDERED,
        supplier_purchase_sheet=sheet,
        updated_at=timezone.now(),
    )
    write_audit_log(
        object_type="SUPPLIER_PURCHASE_SHEET",
        object_id=sheet.pk,
        context_type="PURCHASE_REQUEST",
        context_id=purchase_request.pk,
        action="CREATED_FROM_PURCHASE_REQUEST",
        actor_employee=actor_employee,
        after_data={
            **sheet_snapshot(sheet),
            "allocation_ids": [str(item.pk) for item in allocations],
        },
        request=request,
    )
    return sheet


def _normalize_party(raw_value, field_name):
    value = raw_value if isinstance(raw_value, dict) else {}
    return {
        "name": _string(value.get("name"), field_name=f"{field_name}.name", max_length=255),
        "address": _string(value.get("address"), field_name=f"{field_name}.address", max_length=500),
        "contact": _string(value.get("contact"), field_name=f"{field_name}.contact", max_length=100),
        "phone": _string(value.get("phone"), field_name=f"{field_name}.phone", max_length=100),
    }


def normalize_sheet_content(sheet, raw_content, *, for_publish=False):
    from .pipe_purchase import normalize_pipe_sheet_line
    if not isinstance(raw_content, dict):
        raise ValidationError({"content": "采购表内容必须是对象。"})
    current = sheet.content_snapshot if isinstance(sheet.content_snapshot, dict) else {}
    settlement_mode = str(raw_content.get("settlement_mode") or current.get("settlement_mode") or "NORMAL")
    if settlement_mode not in ALLOWED_SETTLEMENT_MODES:
        raise ValidationError({"settlement_mode": "结算方式选项不正确。"})
    tax_rate = _decimal(raw_content.get("tax_rate"), field_name="tax_rate", allow_null=False)
    if tax_rate > Decimal("100"):
        raise ValidationError({"tax_rate": "税率不能大于 100%。"})

    original_lines = current.get("lines") if isinstance(current.get("lines"), list) else []
    original_by_id = {
        str(item.get("source_purchase_order_line_id")): item
        for item in original_lines
        if isinstance(item, dict) and item.get("source_purchase_order_line_id")
    }
    submitted_lines = raw_content.get("lines")
    if not isinstance(submitted_lines, list) or not submitted_lines:
        raise ValidationError({"lines": "采购表至少需要一条采购明细。"})
    if len(submitted_lines) > 5000:
        raise ValidationError({"lines": "采购明细不能超过 5000 行。"})
    submitted_ids = [str(item.get("source_purchase_order_line_id") or "") for item in submitted_lines if isinstance(item, dict)]
    if len(submitted_ids) != len(submitted_lines) or set(submitted_ids) != set(original_by_id) or len(submitted_ids) != len(set(submitted_ids)):
        raise ValidationError({"lines": "采购明细归属已锁定，不能新增、删除、重复或跨供应商移动。"})

    normalized_lines = []
    amounts = []
    for index, item in enumerate(submitted_lines, start=1):
        source_id = str(item.get("source_purchase_order_line_id"))
        source_line = original_by_id[source_id]
        pipe_fields = normalize_pipe_sheet_line(original_by_id[source_id], item, settlement_mode)
        if pipe_fields:
            item = {**item, **{key: original_by_id[source_id][key] for key in ('quantity', 'unit', 'unit_price')}}
        quantity = _decimal(item.get("quantity"), field_name=f"lines.{index}.quantity", allow_null=not for_publish, positive=True)
        unit_price = _decimal(item.get("unit_price"), field_name=f"lines.{index}.unit_price", allow_null=not for_publish)
        amount = None
        if settlement_mode != "ACTUAL_WEIGHT" and quantity is not None and unit_price is not None:
            try:
                amount = (quantity * unit_price).quantize(MONEY_QUANT, rounding=ROUND_HALF_UP)
            except InvalidOperation as exc:
                raise ValidationError({"lines": f"第 {index} 行金额超出系统范围。"}) from exc
            if amount > MAX_MONEY_VALUE:
                raise ValidationError({"lines": f"第 {index} 行金额超出系统范围。"})
        if for_publish and not _string(item.get("unit"), field_name=f"lines.{index}.unit", max_length=50):
            raise ValidationError({"lines": f"第 {index} 行缺少单位。"})
        normalized_lines.append(
            {
                **pipe_fields,
                "source_purchase_order_line_id": source_id,
                "product_name": _string(item.get("product_name"), field_name=f"lines.{index}.product_name", max_length=200),
                "product_specification": _string(item.get("product_specification"), field_name=f"lines.{index}.product_specification", max_length=300),
                "part_name": _string(item.get("part_name"), field_name=f"lines.{index}.part_name", max_length=300, allow_blank=not for_publish),
                "specification": _string(item.get("specification"), field_name=f"lines.{index}.specification", max_length=500),
                "material": _string(item.get("material"), field_name=f"lines.{index}.material", max_length=500 if (current.get("order") or {}).get("source_type") == "SAMPLE" else 200),
                "section_type": str(source_line.get("section_type") or "").strip(),
                "section_title": str(source_line.get("section_title") or "").strip(),
                "material_attributes_snapshot": deepcopy(source_line.get("material_attributes_snapshot")) if isinstance(source_line.get("material_attributes_snapshot"), dict) else {},
                "quantity": format(quantity, "f") if quantity is not None else "",
                "unit": _string(item.get("unit"), field_name=f"lines.{index}.unit", max_length=50),
                "unit_price": format(unit_price, "f") if unit_price is not None else "",
                "amount": format(amount, "f") if amount is not None else "",
                "delivery_date": _date_text(item.get("delivery_date"), field_name=f"lines.{index}.delivery_date", allow_blank=not for_publish),
                "remark": _string(item.get("remark"), field_name=f"lines.{index}.remark", max_length=500),
            }
        )
        amounts.append(amount)

    section_defaults = _structured_sections(current)
    quality_standards = raw_content.get("quality_standards", section_defaults["quality_standards"])
    if not isinstance(quality_standards, list) or not quality_standards or len(quality_standards) > 20:
        raise ValidationError({"quality_standards": "产品质量标准必须有 1 至 20 条。"})
    normalized_quality_standards = [
        _string(item, field_name=f"quality_standards.{index}", max_length=2000, allow_blank=False)
        for index, item in enumerate(quality_standards, start=1)
    ]

    payment_and_delivery = _string(
        raw_content.get("payment_and_delivery", section_defaults["payment_and_delivery"]),
        field_name="payment_and_delivery",
        max_length=4000,
        allow_blank=not for_publish,
    )
    delivery_handover = _string(
        raw_content.get("delivery_handover", section_defaults["delivery_handover"]),
        field_name="delivery_handover",
        max_length=4000,
        allow_blank=not for_publish,
    )
    special_instructions = _string(
        raw_content.get("special_instructions", section_defaults["special_instructions"]),
        field_name="special_instructions",
        max_length=4000,
    )
    dispute_resolution = _string(
        raw_content.get("dispute_resolution", section_defaults["dispute_resolution"]),
        field_name="dispute_resolution",
        max_length=4000,
        allow_blank=not for_publish,
    )
    effectiveness = _string(
        raw_content.get("effectiveness", section_defaults["effectiveness"]),
        field_name="effectiveness",
        max_length=4000,
        allow_blank=not for_publish,
    )
    total = None
    if settlement_mode != "ACTUAL_WEIGHT" and amounts and all(value is not None for value in amounts):
        total = sum(amounts, Decimal("0")).quantize(MONEY_QUANT, rounding=ROUND_HALF_UP)
    buyer = _normalize_party(raw_content.get("buyer"), "buyer")
    seller = _normalize_party(raw_content.get("seller"), "seller")
    if for_publish and (not buyer["name"] or not seller["name"]):
        raise ValidationError({"parties": "正式发布前必须填写甲方和乙方名称。"})
    from .purchase_sheet_template_edits import EDITABLE_TEMPLATE_FIELDS
    template_edits = raw_content.get("original_template_edits", current.get("original_template_edits", []))
    if not isinstance(template_edits, list) or any(not isinstance(key, str) or key not in EDITABLE_TEMPLATE_FIELDS for key in template_edits):
        raise ValidationError({"original_template_edits": "原版合同编辑字段不正确。"})
    return {
        "original_template_edits": list(dict.fromkeys(template_edits)),
        "title": _string(raw_content.get("title"), field_name="title", max_length=150, allow_blank=not for_publish),
        "sheet_number": sheet.sheet_number,
        "purchase_date": _date_text(raw_content.get("purchase_date"), field_name="purchase_date", allow_blank=not for_publish),
        "order": deepcopy(current.get("order") or {}),
        "buyer": buyer,
        "seller": seller,
        "settlement_mode": settlement_mode,
        "tax_rate": format(tax_rate, "f"),
        "freight_bearer": _string(raw_content.get("freight_bearer"), field_name="freight_bearer", max_length=50, allow_blank=not for_publish),
        "remark": _string(raw_content.get("remark"), field_name="remark", max_length=2000),
        "payment_and_delivery": payment_and_delivery,
        "quality_standards": normalized_quality_standards,
        "delivery_handover": delivery_handover,
        "special_instructions": special_instructions,
        "dispute_resolution": dispute_resolution,
        "effectiveness": effectiveness,
        "show_image": bool(raw_content.get("show_image", current.get("show_image", True))),
        "seal_status": "UPLOADED" if hasattr(sheet, "seal_image") else "NOT_UPLOADED",
        "lines": normalized_lines,
        'schema_version': 2 if any(row.get('measurement_kind') == 'PIPE' for row in normalized_lines) else 1,
        "total_amount": format(total, "f") if total is not None else None,
    }, total


@transaction.atomic
def generate_supplier_purchase_sheets(*, order_id, assignments, allowed_task_ids, actor_employee, request=None):
    from .source_access import purchase_order_access
    order = (
        PurchaseOrder.objects.select_for_update(of=("self",))
        .select_related("production_task")
        .prefetch_related(
            "lines__supplier",
            "lines__bom_line__images__business_file",
        )
        .filter(purchase_order_access(allowed_task_ids, request), pk=order_id, archived_at__isnull=True)
        .first()
    )
    if order is None:
        raise NotFound("采购单不存在或不在当前账号的数据范围内。")
    if order.status != PurchaseOrderStatus.SUBMITTED:
        raise Conflict("请先确认采购汇总单，再生成供应商采购表。")
    lines = list(order.lines.all())
    supplier_ids = {line.supplier_id for line in lines if line.supplier_id}
    if not supplier_ids or len(supplier_ids) != len({line.supplier_id for line in lines}):
        raise ValidationError({"lines": "采购明细存在未选择供应商的行。"})
    assignment_by_supplier = {item["supplier_id"]: item["template_version_id"] for item in assignments}
    if len(assignment_by_supplier) != len(assignments) or set(assignment_by_supplier) != supplier_ids:
        raise ValidationError({"assignments": "必须为每家供应商且仅为每家供应商选择一个模板。"})
    existing = SupplierPurchaseSheet.objects.filter(
        purchase_order=order,
        supplier_id__in=supplier_ids,
        is_current=True,
        archived_at__isnull=True,
    )
    if existing.exists():
        raise Conflict("当前采购单已经生成供应商采购表，请到采购表工作台继续处理。")

    versions = {
        item.pk: item
        for item in PurchaseContractTemplateVersion.objects.select_related("template").filter(
            pk__in=set(assignment_by_supplier.values()),
            template__status=PurchaseContractTemplateStatus.ACTIVE,
            template__archived_at__isnull=True,
        )
    }
    if len(versions) != len(set(assignment_by_supplier.values())):
        raise ValidationError({"assignments": "包含不存在、已停用或已归档的采购模板版本。"})

    grouped = {}
    for line in lines:
        grouped.setdefault(line.supplier_id, []).append(line)
    created = []
    for supplier_id in sorted(
        grouped,
        key=lambda item: (
            grouped[item][0].supplier_number_snapshot,
            grouped[item][0].supplier_name_snapshot,
        ),
    ):
        supplier = grouped[supplier_id][0].supplier
        template_version = versions[assignment_by_supplier[supplier_id]]
        sheet_number = next_purchase_order_number()
        content = _default_content(order, supplier, grouped[supplier_id], template_version, sheet_number)
        total = Decimal(content["total_amount"]) if content["total_amount"] is not None else None
        sheet = SupplierPurchaseSheet.objects.create(
            purchase_order=order,
            supplier=supplier,
            supplier_number_snapshot=supplier.supplier_number,
            supplier_name_snapshot=supplier.supplier_name,
            supplier_phone_snapshot=supplier.phone,
            sheet_number=sheet_number,
            version_number=1,
            is_current=True,
            template_version=template_version,
            status=SupplierPurchaseSheetStatus.DRAFT,
            content_snapshot=content,
            total_amount=total,
            created_by_employee=actor_employee,
            updated_by_employee=actor_employee,
        )
        _inherit_bom_line_images(
            sheet,
            ((line.pk, line.bom_line) for line in grouped[supplier_id]),
            actor_employee,
        )
        write_audit_log(
            object_type="SUPPLIER_PURCHASE_SHEET",
            object_id=sheet.pk,
            context_type="PURCHASE_ORDER",
            context_id=order.pk,
            action="CREATED",
            actor_employee=actor_employee,
            after_data=sheet_snapshot(sheet),
            request=request,
        )
        created.append(sheet)
    return created


@transaction.atomic
def update_supplier_purchase_sheet(*, sheet_id, content, allowed_task_ids, actor_employee, request):
    sheet = (
        SupplierPurchaseSheet.objects.select_for_update(of=("self",))
        .filter(_sheet_access_filter(allowed_task_ids, request), pk=sheet_id, archived_at__isnull=True, is_current=True)
        .first()
    )
    if sheet is None:
        raise NotFound("采购表不存在或不在当前账号的数据范围内。")
    if sheet.status != SupplierPurchaseSheetStatus.DRAFT:
        raise Conflict("已发布采购表只读；如需修改，请先创建新版本。")
    require_matching_etag(request, sheet)
    before = sheet_snapshot(sheet)
    normalized, total = normalize_sheet_content(sheet, content, for_publish=False)
    sheet.content_snapshot = normalized
    sheet.total_amount = total
    sheet.updated_by_employee = actor_employee
    sheet.save(update_fields=["content_snapshot", "total_amount", "updated_by_employee", "updated_at"])
    context_type, context_id = _sheet_context(sheet)
    write_audit_log(
        object_type="SUPPLIER_PURCHASE_SHEET",
        object_id=sheet.pk,
        context_type=context_type,
        context_id=context_id,
        action="UPDATED",
        actor_employee=actor_employee,
        before_data=before,
        after_data=sheet_snapshot(sheet),
        request=request,
    )
    return sheet


def _has_source_line(sheet, source_line_id):
    content = sheet.content_snapshot if isinstance(sheet.content_snapshot, dict) else {}
    return any(
        isinstance(item, dict)
        and str(item.get("source_purchase_order_line_id") or "") == str(source_line_id)
        for item in content.get("lines") or []
    )


@transaction.atomic
def replace_supplier_purchase_sheet_line_image(
    *, sheet_id, source_line_id, uploaded_file, allowed_task_ids, actor_employee, request
):
    sheet = (
        SupplierPurchaseSheet.objects.select_for_update(of=("self",))
        .filter(_sheet_access_filter(allowed_task_ids, request), pk=sheet_id, archived_at__isnull=True, is_current=True)
        .first()
    )
    if sheet is None:
        raise NotFound("采购表不存在或不在当前账号的数据范围内。")
    if sheet.status != SupplierPurchaseSheetStatus.DRAFT:
        raise Conflict("已发布采购表只读；如需替换图片，请先创建新版本。")
    require_matching_etag(request, sheet)
    if not _has_source_line(sheet, source_line_id):
        raise ValidationError({"line_id": "该采购明细不属于当前供应商采购表。"})
    image_file = save_scanned_image(
        uploaded_file,
        actor_employee,
        storage_folder="purchase-sheet-images",
        field_label="采购表图片",
    )
    SupplierPurchaseSheetLineImage.objects.update_or_create(
        sheet=sheet,
        source_purchase_order_line_id=source_line_id,
        defaults={"image_file": image_file, "created_by_employee": actor_employee},
    )
    sheet.updated_by_employee = actor_employee
    sheet.save(update_fields=["updated_by_employee", "updated_at"])
    context_type, context_id = _sheet_context(sheet)
    write_audit_log(
        object_type="SUPPLIER_PURCHASE_SHEET",
        object_id=sheet.pk,
        context_type=context_type,
        context_id=context_id,
        action="LINE_IMAGE_REPLACED",
        actor_employee=actor_employee,
        after_data={"source_purchase_order_line_id": str(source_line_id), "image_file_id": str(image_file.pk)},
        request=request,
    )
    return sheet


@transaction.atomic
def remove_supplier_purchase_sheet_line_image(
    *, sheet_id, source_line_id, allowed_task_ids, actor_employee, request
):
    sheet = (
        SupplierPurchaseSheet.objects.select_for_update(of=("self",))
        .filter(_sheet_access_filter(allowed_task_ids, request), pk=sheet_id, archived_at__isnull=True, is_current=True)
        .first()
    )
    if sheet is None:
        raise NotFound("采购表不存在或不在当前账号的数据范围内。")
    if sheet.status != SupplierPurchaseSheetStatus.DRAFT:
        raise Conflict("已发布采购表只读；如需删除图片，请先创建新版本。")
    require_matching_etag(request, sheet)
    deleted_count, _ = SupplierPurchaseSheetLineImage.objects.filter(
        sheet=sheet,
        source_purchase_order_line_id=source_line_id,
    ).delete()
    if not deleted_count:
        raise NotFound("该采购明细没有可删除的图片。")
    sheet.updated_by_employee = actor_employee
    sheet.save(update_fields=["updated_by_employee", "updated_at"])
    context_type, context_id = _sheet_context(sheet)
    write_audit_log(
        object_type="SUPPLIER_PURCHASE_SHEET",
        object_id=sheet.pk,
        context_type=context_type,
        context_id=context_id,
        action="LINE_IMAGE_REMOVED",
        actor_employee=actor_employee,
        after_data={"source_purchase_order_line_id": str(source_line_id)},
        request=request,
    )
    return sheet


@transaction.atomic
def replace_supplier_purchase_sheet_seal_image(
    *, sheet_id, uploaded_file, allowed_task_ids, actor_employee, request
):
    sheet = (
        SupplierPurchaseSheet.objects.select_for_update(of=("self",))
        .filter(_sheet_access_filter(allowed_task_ids, request), pk=sheet_id, archived_at__isnull=True, is_current=True)
        .first()
    )
    if sheet is None:
        raise NotFound("采购表不存在或不在当前账号的数据范围内。")
    if sheet.status != SupplierPurchaseSheetStatus.DRAFT:
        raise Conflict("已发布采购表只读；如需替换盖章图片，请先创建新版本。")
    require_matching_etag(request, sheet)
    image_file = save_scanned_image(
        uploaded_file,
        actor_employee,
        storage_folder="purchase-sheet-seals",
        field_label="采购表盖章图片",
    )
    SupplierPurchaseSheetSealImage.objects.update_or_create(
        sheet=sheet,
        defaults={"image_file": image_file, "created_by_employee": actor_employee},
    )
    sheet.updated_by_employee = actor_employee
    sheet.save(update_fields=["updated_by_employee", "updated_at"])
    context_type, context_id = _sheet_context(sheet)
    write_audit_log(
        object_type="SUPPLIER_PURCHASE_SHEET",
        object_id=sheet.pk,
        context_type=context_type,
        context_id=context_id,
        action="SEAL_IMAGE_REPLACED",
        actor_employee=actor_employee,
        after_data={"image_file_id": str(image_file.pk)},
        request=request,
    )
    return sheet


@transaction.atomic
def remove_supplier_purchase_sheet_seal_image(
    *, sheet_id, allowed_task_ids, actor_employee, request
):
    sheet = (
        SupplierPurchaseSheet.objects.select_for_update(of=("self",))
        .filter(_sheet_access_filter(allowed_task_ids, request), pk=sheet_id, archived_at__isnull=True, is_current=True)
        .first()
    )
    if sheet is None:
        raise NotFound("采购表不存在或不在当前账号的数据范围内。")
    if sheet.status != SupplierPurchaseSheetStatus.DRAFT:
        raise Conflict("已发布采购表只读；如需删除盖章图片，请先创建新版本。")
    require_matching_etag(request, sheet)
    deleted_count, _ = SupplierPurchaseSheetSealImage.objects.filter(sheet=sheet).delete()
    if not deleted_count:
        raise NotFound("当前采购表没有可删除的盖章图片。")
    sheet.updated_by_employee = actor_employee
    sheet.save(update_fields=["updated_by_employee", "updated_at"])
    context_type, context_id = _sheet_context(sheet)
    write_audit_log(
        object_type="SUPPLIER_PURCHASE_SHEET",
        object_id=sheet.pk,
        context_type=context_type,
        context_id=context_id,
        action="SEAL_IMAGE_REMOVED",
        actor_employee=actor_employee,
        request=request,
    )
    return sheet


def _lock_sheet_purchase_orders(sheet_ids, allowed_task_ids, request):
    # 与生成、删除保持相同锁顺序，串行化同一采购单的发布和修订，避免最后两张同时发布时漏转状态。
    order_ids = SupplierPurchaseSheet.objects.filter(
        _sheet_access_filter(allowed_task_ids, request),
        pk__in=sheet_ids, archived_at__isnull=True, is_current=True,
        purchase_order__isnull=False,
    ).values_list("purchase_order_id", flat=True)
    return list(PurchaseOrder.objects.select_for_update().filter(pk__in=order_ids).order_by("id"))


def _start_purchasing_if_all_published(sheet, actor_employee, request):
    if not sheet.purchase_order_id:
        return
    order = PurchaseOrder.objects.get(pk=sheet.purchase_order_id)
    if order.status != PurchaseOrderStatus.SUBMITTED or order.archived_at is not None:
        return
    supplier_ids = set(order.lines.values_list("supplier_id", flat=True))
    current_sheets = list(SupplierPurchaseSheet.objects.filter(
        purchase_order=order, archived_at__isnull=True, is_current=True,
    ).values_list("supplier_id", "status"))
    if (not supplier_ids or None in supplier_ids
            or supplier_ids != {supplier_id for supplier_id, _ in current_sheets}
            or any(status != SupplierPurchaseSheetStatus.PUBLISHED for _, status in current_sheets)):
        return
    order.status = PurchaseOrderStatus.PURCHASING
    order.save(update_fields=["status", "updated_at"])
    write_audit_log(
        object_type="PURCHASE_ORDER", object_id=order.pk, action="PURCHASING",
        actor_employee=actor_employee, before_data={"status": PurchaseOrderStatus.SUBMITTED},
        after_data={"status": order.status}, request=request,
    )


def _publish_prepared_sheet(sheet, actor_employee, request):
    sheet.status = SupplierPurchaseSheetStatus.PUBLISHED
    sheet.published_at = timezone.now()
    sheet.published_by_employee = actor_employee
    sheet.updated_by_employee = actor_employee
    sheet.save(update_fields=[
        "content_snapshot",
        "total_amount",
        "status",
        "published_at",
        "published_by_employee",
        "updated_by_employee",
        "updated_at",
    ])
    _start_purchasing_if_all_published(sheet, actor_employee, request)
    context_type, context_id = _sheet_context(sheet)
    write_audit_log(
        object_type="SUPPLIER_PURCHASE_SHEET",
        object_id=sheet.pk,
        context_type=context_type,
        context_id=context_id,
        action="PUBLISHED",
        actor_employee=actor_employee,
        after_data=sheet_snapshot(sheet),
        request=request,
    )
    return sheet


def _first_validation_message(detail):
    if isinstance(detail, dict):
        for value in detail.values():
            message = _first_validation_message(value)
            if message:
                return message
        return "采购表内容不完整。"
    if isinstance(detail, (list, tuple)):
        for value in detail:
            message = _first_validation_message(value)
            if message:
                return message
        return "采购表内容不完整。"
    return str(detail or "采购表内容不完整。")


def _prepare_sheet_for_publish(sheet, *, include_sheet_number_in_error=False):
    try:
        from .pipe_purchase import validate_pipe_sheet_source
        validate_pipe_sheet_source(sheet)
        normalized, total = normalize_sheet_content(sheet, sheet.content_snapshot, for_publish=True)
    except ValidationError as exc:
        if not include_sheet_number_in_error:
            raise
        raise ValidationError({
            "ids": f"{sheet.sheet_number} 无法发布：{_first_validation_message(exc.detail)}"
        }) from exc
    sheet.content_snapshot = normalized
    sheet.total_amount = total


@transaction.atomic
def publish_supplier_purchase_sheet(*, sheet_id, allowed_task_ids, actor_employee, request):
    _lock_sheet_purchase_orders([sheet_id], allowed_task_ids, request)
    sheet = (
        SupplierPurchaseSheet.objects.select_for_update(of=("self",))
        .select_related("purchase_order", "purchase_request")
        .filter(_sheet_access_filter(allowed_task_ids, request), pk=sheet_id, archived_at__isnull=True, is_current=True)
        .first()
    )
    if sheet is None:
        raise NotFound("采购表不存在或不在当前账号的数据范围内。")
    if sheet.status != SupplierPurchaseSheetStatus.DRAFT:
        raise Conflict("只有草稿采购表可以发布。")
    require_matching_etag(request, sheet)
    _prepare_sheet_for_publish(sheet)
    return _publish_prepared_sheet(sheet, actor_employee, request)


@transaction.atomic
def publish_supplier_purchase_sheets(*, sheet_ids, allowed_task_ids, actor_employee, request):
    """批量发布采用全有或全无：任一采购表校验失败时，整批都不发布。"""
    requested_ids = list(sheet_ids)
    _lock_sheet_purchase_orders(requested_ids, allowed_task_ids, request)
    locked = list(
        SupplierPurchaseSheet.objects.select_for_update(of=("self",))
        .select_related("purchase_order", "purchase_request")
        .filter(
            _sheet_access_filter(allowed_task_ids, request),
            pk__in=requested_ids,
            archived_at__isnull=True,
            is_current=True,
        )
        .order_by("id")
    )
    if len(locked) != len(requested_ids):
        raise ValidationError({"ids": "选择中包含不存在、无权限、非当前版本或已删除的采购表。"})
    by_id = {sheet.pk: sheet for sheet in locked}
    ordered = [by_id[sheet_id] for sheet_id in requested_ids]
    non_draft = [sheet.sheet_number for sheet in ordered if sheet.status != SupplierPurchaseSheetStatus.DRAFT]
    if non_draft:
        raise ValidationError({"ids": f"只有草稿采购表可以批量发布：{', '.join(non_draft)}。"})

    for sheet in ordered:
        _prepare_sheet_for_publish(sheet, include_sheet_number_in_error=True)
    return [
        _publish_prepared_sheet(sheet, actor_employee, request)
        for sheet in ordered
    ]


@transaction.atomic
def create_supplier_purchase_sheet_version(*, sheet_id, allowed_task_ids, actor_employee, request):
    _lock_sheet_purchase_orders([sheet_id], allowed_task_ids, request)
    current = (
        SupplierPurchaseSheet.objects.select_for_update(of=("self",))
        .filter(_sheet_access_filter(allowed_task_ids, request), pk=sheet_id, archived_at__isnull=True, is_current=True)
        .first()
    )
    if current is None:
        raise NotFound("采购表不存在或不在当前账号的数据范围内。")
    if current.status != SupplierPurchaseSheetStatus.PUBLISHED:
        raise Conflict("只有已发布采购表可以创建新版本。")
    require_matching_etag(request, current)
    current.is_current = False
    current.save(update_fields=["is_current", "updated_at"])
    next_sheet = SupplierPurchaseSheet.objects.create(
        series_id=current.series_id,
        purchase_order=current.purchase_order,
        purchase_request=current.purchase_request,
        supplier=current.supplier,
        supplier_number_snapshot=current.supplier_number_snapshot,
        supplier_name_snapshot=current.supplier_name_snapshot,
        supplier_phone_snapshot=current.supplier_phone_snapshot,
        sheet_number=current.sheet_number,
        version_number=current.version_number + 1,
        procurement_batch_number=current.procurement_batch_number,
        is_current=True,
        template_version=current.template_version,
        status=SupplierPurchaseSheetStatus.DRAFT,
        content_snapshot=deepcopy(current.content_snapshot),
        total_amount=current.total_amount,
        created_by_employee=actor_employee,
        updated_by_employee=actor_employee,
    )
    SupplierPurchaseSheetLineImage.objects.bulk_create([
        SupplierPurchaseSheetLineImage(
            sheet=next_sheet,
            source_purchase_order_line_id=item.source_purchase_order_line_id,
            image_file=item.image_file,
            created_by_employee=actor_employee,
        )
        for item in current.line_images.select_related("image_file").all()
    ])
    current_seal = SupplierPurchaseSheetSealImage.objects.filter(sheet=current).first()
    if current_seal:
        SupplierPurchaseSheetSealImage.objects.create(
            sheet=next_sheet,
            image_file=current_seal.image_file,
            created_by_employee=actor_employee,
        )
    context_type, context_id = _sheet_context(next_sheet)
    write_audit_log(
        object_type="SUPPLIER_PURCHASE_SHEET",
        object_id=next_sheet.pk,
        context_type=context_type,
        context_id=context_id,
        action="VERSION_CREATED",
        actor_employee=actor_employee,
        before_data=sheet_snapshot(current),
        after_data=sheet_snapshot(next_sheet),
        request=request,
    )
    return next_sheet


@transaction.atomic
def create_purchase_contract_template(*, validated_data, actor_employee, request=None):
    code = str(validated_data.get("template_code") or f"TPL_{uuid.uuid4().hex[:12]}").strip().upper()
    if PurchaseContractTemplate.objects.filter(template_code=code).exists():
        raise ValidationError({"template_code": "模板编码已存在。"})
    template = PurchaseContractTemplate.objects.create(
        template_code=code,
        template_name=validated_data["template_name"].strip(),
        supplier_categories=validated_data.get("supplier_categories", []),
        status=validated_data.get("status", PurchaseContractTemplateStatus.ACTIVE),
        current_version_number=1,
        created_by_employee=actor_employee,
        updated_by_employee=actor_employee,
    )
    version = PurchaseContractTemplateVersion.objects.create(
        template=template,
        version_number=1,
        version_name=validated_data["version_name"].strip(),
        content_config=validated_data["content_config"],
        change_summary=validated_data.get("change_summary", "建立模板"),
        created_by_employee=actor_employee,
    )
    write_audit_log(
        object_type="PURCHASE_CONTRACT_TEMPLATE",
        object_id=template.pk,
        action="CREATED",
        actor_employee=actor_employee,
        after_data={"template_code": code, "version_number": version.version_number},
        request=request,
    )
    return template


@transaction.atomic
def update_purchase_contract_template(*, template_id, validated_data, actor_employee, request):
    template = PurchaseContractTemplate.objects.select_for_update().filter(
        pk=template_id,
        archived_at__isnull=True,
    ).first()
    if template is None:
        raise NotFound("采购模板不存在或已归档。")
    require_matching_etag(request, template)
    before = {
        "template_name": template.template_name,
        "supplier_categories": list(template.supplier_categories),
        "status": template.status,
        "version_number": template.current_version_number,
    }
    save_mode = validated_data.get("save_mode", "NEW_VERSION")
    template.template_name = validated_data.get("template_name", template.template_name).strip()
    template.supplier_categories = validated_data.get("supplier_categories", template.supplier_categories)
    template.status = validated_data.get("status", template.status)
    template.updated_by_employee = actor_employee
    template_fields = [
        "template_name",
        "supplier_categories",
        "status",
        "updated_by_employee",
        "updated_at",
    ]
    previous = template.versions.select_for_update().filter(
        version_number=template.current_version_number,
    ).first()
    config = validated_data.get("content_config")
    if config is None:
        config = deepcopy(previous.content_config if previous else {})
    if save_mode == "CURRENT":
        if previous is None:
            raise Conflict("当前模板版本不存在，不能覆盖保存。")
        previous.content_config = config
        previous.version_name = validated_data.get("version_name", previous.version_name).strip()
        previous.change_summary = validated_data.get("change_summary", "更新当前模板")
        previous.created_by_employee = actor_employee
        previous.save(update_fields=["version_name", "content_config", "change_summary", "created_by_employee", "updated_at"])
        version = previous
        audit_action = "CURRENT_VERSION_UPDATED"
    else:
        template.current_version_number += 1
        template_fields.append("current_version_number")
        version = PurchaseContractTemplateVersion.objects.create(
            template=template,
            version_number=template.current_version_number,
            version_name=validated_data.get("version_name") or f"版本 {template.current_version_number}",
            content_config=config,
            change_summary=validated_data.get("change_summary", "更新模板"),
            created_by_employee=actor_employee,
        )
        audit_action = "VERSION_CREATED"
    template.save(update_fields=template_fields)
    write_audit_log(
        object_type="PURCHASE_CONTRACT_TEMPLATE",
        object_id=template.pk,
        action=audit_action,
        actor_employee=actor_employee,
        before_data=before,
        after_data={
            "template_name": template.template_name,
            "supplier_categories": list(template.supplier_categories),
            "status": template.status,
            "version_number": version.version_number,
            "version_name": version.version_name,
            "change_summary": version.change_summary,
        },
        request=request,
    )
    return template
