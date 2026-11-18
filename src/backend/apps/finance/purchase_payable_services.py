from decimal import Decimal, ROUND_HALF_UP

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from rest_framework.generics import get_object_or_404

from apps.core.api.concurrency import require_matching_etag
from apps.core.audit import write_audit_log
from apps.core.daily_numbering import next_daily_business_number
from apps.inventory.models import MaterialInbound, MaterialInboundLine, MaterialInboundStatus
from .exceptions import FinanceConflict
from .purchase_payable_models import PurchasePayable, PurchasePayableLine, PurchasePayableStatus


MONEY_QUANTUM = Decimal("0.01")


def payable_quantity(line):
    """返回与采购计价单位一致的合格数量；KG仅使用已有重量，不做其他单位换算。"""
    unit = (line.source_unit_text_snapshot or "").strip().upper()
    if unit in {"KG", "千克"} and line.accepted_weight_kg is not None:
        return line.accepted_weight_kg
    return line.accepted_quantity


def line_amount(quantity, unit_price):
    return (Decimal(quantity) * Decimal(unit_price)).quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP)


def _source_snapshot(line):
    purchase_line = line.purchase_order_line
    return {
        "material_snapshot": line.material_snapshot,
        "specification_snapshot": line.specification_snapshot,
        "part_name_snapshot": line.part_name_snapshot,
        "material_attributes_snapshot": line.material_attributes_snapshot or {},
        "source_unit_text_snapshot": line.source_unit_text_snapshot,
        "accepted_quantity": payable_quantity(line),
        "accepted_weight_kg": line.accepted_weight_kg,
        "accepted_bar_count": line.accepted_bar_count,
        "reference_unit_price": purchase_line.unit_price,
        "reference_amount": purchase_line.amount,
        "currency_code_snapshot": purchase_line.purchase_order.currency_code_snapshot,
    }


def _audit_snapshot(payable):
    return {
        "number": payable.number,
        "status": payable.status,
        "amount": payable.amount,
        "material_inbound_id": str(payable.material_inbound_id),
        "supplier_id": str(payable.supplier_id) if payable.supplier_id else None,
        "tax_mode": payable.tax_mode,
        "freight_mode": payable.freight_mode,
        "lines": list(payable.lines.values("id", "material_inbound_line_id", "accepted_quantity", "unit_price", "amount")),
    }


def _audit(payable, *, action, actor=None, before=None, request=None):
    write_audit_log(
        object_type="PURCHASE_PAYABLE",
        object_id=payable.pk,
        action=action,
        actor_employee=actor,
        before_data=before,
        after_data=_audit_snapshot(payable),
        context_type="MATERIAL_INBOUND",
        context_id=payable.material_inbound_id,
        request=request,
    )


@transaction.atomic
def create_payables_for_inbound(*, inbound_id, actor_employee=None, request=None):
    """在品质确认事务中生成采购应付来源；重复调用只返回既有结果。"""
    inbound = get_object_or_404(
        # 采购来源允许为空；只锁入库本表，避免 PostgreSQL 锁可空外连接时报错。
        MaterialInbound.objects.select_for_update(of=("self",)).select_related("purchase_order"), pk=inbound_id,
    )
    if inbound.status != MaterialInboundStatus.CONFIRMED:
        raise FinanceConflict("INBOUND_NOT_CONFIRMED", "只有已完成品质确认的采购入库才能生成应付来源。")
    if inbound.purchase_order_id is None:
        return []

    lines = list(
        MaterialInboundLine.objects.select_for_update(of=("self",))
        .select_related("purchase_order_line", "purchase_order_line__supplier", "purchase_order_line__purchase_order")
        .filter(inbound_id=inbound.pk, purchase_order_line__isnull=False)
        .order_by("id")
    )
    grouped = {}
    for line in lines:
        if payable_quantity(line) <= 0:
            continue
        supplier = line.purchase_order_line.supplier
        if supplier is None:
            raise FinanceConflict("SUPPLIER_REQUIRED", "采购入库明细缺少供应商，不能生成应付来源。")
        grouped.setdefault(supplier.pk, []).append(line)

    result = []
    for group_lines in grouped.values():
        supplier = group_lines[0].purchase_order_line.supplier
        supplier_number_snapshot = (
            group_lines[0].purchase_order_line.supplier_number_snapshot or supplier.supplier_number
        )
        supplier_name_snapshot = (
            group_lines[0].purchase_order_line.supplier_name_snapshot or supplier.supplier_name
        )
        payable, created = PurchasePayable.objects.select_for_update().get_or_create(
            material_inbound=inbound,
            supplier=supplier,
            defaults={
                "number": next_daily_business_number("PURCHASE_PAYABLE"),
                "supplier_number_snapshot": supplier_number_snapshot,
                "supplier_name_snapshot": supplier_name_snapshot,
                "purchase_order_number_snapshot": inbound.purchase_order.order_number,
                "inbound_number_snapshot": inbound.inbound_number,
                "currency_code_snapshot": inbound.purchase_order.currency_code_snapshot,
                "currency_name_snapshot": inbound.purchase_order.currency_name_snapshot,
                "status": PurchasePayableStatus.WAITING_PRICE,
            },
        )
        added = False
        for inbound_line in group_lines:
            existing = PurchasePayableLine.objects.filter(material_inbound_line_id=inbound_line.pk).first()
            if existing is not None:
                if existing.payable_id != payable.pk:
                    raise FinanceConflict("PAYABLE_SOURCE_CONFLICT", "同一入库明细已归属其他采购应付单。")
                continue
            PurchasePayableLine.objects.create(payable=payable, material_inbound_line=inbound_line,
                                                purchase_order_line=inbound_line.purchase_order_line,
                                                **_source_snapshot(inbound_line))
            added = True
        if added:
            payable.amount = None
            payable.status = PurchasePayableStatus.WAITING_PRICE
            payable.save(update_fields=["amount", "status", "updated_at"])
            _audit(payable, action="CREATE" if created else "SOURCE_APPEND", actor=actor_employee, request=request)
        result.append(payable)
    return result


@transaction.atomic
def update_payable_pricing(request, payable_id, data):
    payable = get_object_or_404(
        PurchasePayable.objects.select_for_update().prefetch_related("lines"), pk=payable_id,
    )
    require_matching_etag(request, payable)
    if payable.status not in {PurchasePayableStatus.WAITING_PRICE, PurchasePayableStatus.WAITING_FINANCE_CONFIRM}:
        raise FinanceConflict("PAYABLE_NOT_EDITABLE", "当前应付状态不能修改价格。")
    before = _audit_snapshot(payable)
    lines = {str(line.pk): line for line in payable.lines.all()}
    for item in data["lines"]:
        line = lines.get(str(item.get("id") or item.get("line_id")))
        if line is None:
            raise ValidationError({"lines": "价格明细不属于当前应付单。"})
        price_unit = (item.get("price_unit") or item.get("price_unit_text") or "").strip()
        if not price_unit:
            raise ValidationError({"price_unit": "请填写计价单位。"})
        source_unit = line.source_unit_text_snapshot.strip()
        if source_unit and price_unit.upper() != source_unit.upper():
            raise FinanceConflict("PRICE_UNIT_MISMATCH", "计价单位必须与入库来源单位一致。")
        line.unit_price = item["unit_price"]
        line.price_unit_text = price_unit
        line.price_source = item.get("price_source", "").strip()
        line.price_confirmed_by_name = request.employee.display_name
        line.price_remark = (item.get("price_confirmation_remark") or item.get("price_remark") or "").strip()
        line.tax_mode = item.get("tax_mode")
        line.freight_mode = item.get("freight_mode")
        line.price_confirmed_at = timezone.now()
        line.amount = line_amount(payable_quantity(line.material_inbound_line), line.unit_price)
        line.save(update_fields=["unit_price", "price_unit_text", "price_source", "price_confirmed_by_name",
                                 "price_remark", "tax_mode", "freight_mode", "price_confirmed_at", "amount", "updated_at"])

    current_lines = list(PurchasePayableLine.objects.filter(payable=payable).order_by("id"))
    tax_modes = {line.tax_mode for line in current_lines if line.tax_mode not in (None, "")}
    freight_modes = {line.freight_mode for line in current_lines if line.freight_mode not in (None, "")}
    payable.tax_mode = data.get("tax_mode") if "tax_mode" in data else (
        tax_modes.pop() if len(tax_modes) == 1 and len(tax_modes) == len(current_lines) else None
    )
    payable.freight_mode = data.get("freight_mode") if "freight_mode" in data else (
        freight_modes.pop() if len(freight_modes) == 1 and len(freight_modes) == len(current_lines) else None
    )
    if any(line.unit_price is None or line.amount is None for line in current_lines):
        payable.status = PurchasePayableStatus.WAITING_PRICE
        payable.amount = None
    else:
        payable.status = PurchasePayableStatus.WAITING_FINANCE_CONFIRM
        payable.amount = sum((line.amount for line in current_lines), Decimal("0.00"))
    payable.save(update_fields=["status", "amount", "tax_mode", "freight_mode", "updated_at"])
    _audit(payable, action="PRICE_UPDATE", actor=request.employee, before=before, request=request)
    return payable


@transaction.atomic
def confirm_payable(request, payable_id):
    payable = get_object_or_404(PurchasePayable.objects.select_for_update().prefetch_related("lines"), pk=payable_id)
    require_matching_etag(request, payable)
    if payable.status != PurchasePayableStatus.WAITING_FINANCE_CONFIRM:
        raise FinanceConflict("PAYABLE_NOT_READY", "应付单尚未完成核价，不能确认。")
    lines = list(payable.lines.all())
    if not lines or any(line.unit_price is None or line.amount is None for line in lines):
        raise FinanceConflict("PRICE_REQUIRED", "请先完成全部明细核价。")
    if not (payable.tax_mode or "").strip() or not (payable.freight_mode or "").strip():
        raise FinanceConflict("TAX_FREIGHT_REQUIRED", "请先确认含税和运费口径。")
    before = _audit_snapshot(payable)
    payable.amount = sum((line.amount for line in lines), Decimal("0.00"))
    payable.status = PurchasePayableStatus.WAITING_PAYMENT
    payable.confirmed_by_employee = request.employee
    payable.confirmed_at = timezone.now()
    payable.save(update_fields=["amount", "status", "confirmed_by_employee", "confirmed_at", "updated_at"])
    _audit(payable, action="CONFIRM", actor=request.employee, before=before, request=request)
    return payable


@transaction.atomic
def void_payable(request, payable_id, reason):
    payable = get_object_or_404(PurchasePayable.objects.select_for_update(), pk=payable_id)
    require_matching_etag(request, payable)
    if payable.status == PurchasePayableStatus.VOID:
        return payable
    if payable.status == PurchasePayableStatus.WAITING_PAYMENT:
        raise FinanceConflict("PAYABLE_NOT_VOIDABLE", "待付款采购应付不能再作废。")
    before = _audit_snapshot(payable)
    payable.status = PurchasePayableStatus.VOID
    payable.void_reason = reason.strip()
    payable.voided_by_employee = request.employee
    payable.voided_at = timezone.now()
    payable.save(update_fields=["status", "void_reason", "voided_by_employee", "voided_at", "updated_at"])
    _audit(payable, action="VOID", actor=request.employee, before=before, request=request)
    return payable
