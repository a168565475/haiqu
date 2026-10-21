from decimal import Decimal

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import NotFound, ValidationError

from apps.core.audit import write_audit_log
from apps.core.api.concurrency import require_matching_etag
from apps.core.api.exceptions import Conflict
from apps.core.numbering import next_business_number

from .models import PurchaseOrder, PurchaseOrderStatus, PurchaseReturn, PurchaseReturnLine, PurchaseReturnStatus
from .selectors import purchase_orders_with_context


def purchase_completion_summary(order):
    # 采购完成核对已发起的到货流程；未到货数量允许由采购人员手动关闭。
    from apps.inventory.models import MaterialInboundStatus

    from apps.inventory.workflow import purchase_inbound_workflow_status

    lines = list(order.lines.all())
    has_inbound = False
    pending_quality = False
    received_quantity = Decimal("0")
    remaining_line_count = 0
    return_orders = {}
    missing_return = False
    for line in lines:
        line_received_quantity = Decimal("0")
        for inbound_line in line.material_inbound_lines.all():
            has_inbound = True
            received_quantity += Decimal(inbound_line.received_quantity or 0)
            if inbound_line.inbound.status != MaterialInboundStatus.CONFIRMED:
                pending_quality = True
                line_received_quantity += Decimal(inbound_line.received_quantity or 0)
                continue
            line_received_quantity += Decimal(inbound_line.accepted_quantity or 0)
            if inbound_line.return_quantity > 0:
                try:
                    return_line = inbound_line.purchase_return_line
                except PurchaseReturnLine.DoesNotExist:
                    missing_return = True
                else:
                    if return_line.quantity != inbound_line.return_quantity:
                        missing_return = True
                    return_orders[return_line.return_order_id] = return_line.return_order.status
        if line.actual_purchase_quantity is not None and Decimal(line.actual_purchase_quantity) - line_received_quantity > 0:
            remaining_line_count += 1
    return_statuses = set(return_orders.values())
    return_total = len(return_orders)
    return_completed_count = sum(status == PurchaseReturnStatus.COMPLETED for status in return_orders.values())
    return_pending_confirmation_count = sum(status == PurchaseReturnStatus.QUALITY_GENERATED for status in return_orders.values())
    return_pending_completion_count = sum(status == PurchaseReturnStatus.PROCUREMENT_CONFIRMED for status in return_orders.values())
    return_status = "NONE"
    if missing_return:
        return_status = "MISSING"
    elif PurchaseReturnStatus.QUALITY_GENERATED in return_statuses:
        return_status = PurchaseReturnStatus.QUALITY_GENERATED
    elif PurchaseReturnStatus.PROCUREMENT_CONFIRMED in return_statuses:
        return_status = PurchaseReturnStatus.PROCUREMENT_CONFIRMED
    elif return_statuses:
        return_status = PurchaseReturnStatus.COMPLETED
    has_returns = missing_return or bool(return_statuses)
    reason = ""
    if order.status not in {PurchaseOrderStatus.SUBMITTED, PurchaseOrderStatus.PURCHASING}:
        reason = "仅已确认或采购中的采购单可以完成采购。"
    elif not has_inbound:
        reason = "至少需要完成一批到货流程后才能完成采购。"
    elif pending_quality:
        reason = "仍有到货批次待品质确认，请先完成相应流程。"
    elif missing_return:
        reason = "存在尚未关联退货单的品质退货记录，请先核对退货明细。"
    elif has_returns and return_status != PurchaseReturnStatus.COMPLETED:
        reason = "请先在退货明细中完成全部退货。"
    return_status_display = {"NONE": "无退货", "MISSING": "退货记录待核对", **dict(PurchaseReturnStatus.choices)}[return_status]
    if return_completed_count and return_completed_count < return_total:
        if return_pending_confirmation_count and return_pending_completion_count:
            pending_text = f"{return_total - return_completed_count}单待处理"
        elif return_pending_confirmation_count:
            pending_text = f"{return_pending_confirmation_count}单待确认"
        else:
            pending_text = f"{return_pending_completion_count}单待完成"
        return_status_display = f"已完成{return_completed_count}/{return_total} · {pending_text}"
    elif return_total > 1 and return_pending_confirmation_count == return_total:
        return_status_display = f"品质生成 · {return_total}单待确认退货"
    elif return_total > 1 and return_pending_completion_count == return_total:
        return_status_display = f"已确认退货 · {return_total}单待完成"
    elif return_pending_confirmation_count and return_pending_completion_count:
        return_status_display = f"退货处理中 · {return_pending_confirmation_count}单待确认 / {return_pending_completion_count}单待完成"

    inbound_status, inbound_status_display = purchase_inbound_workflow_status(
        order_status=order.status,
        has_lines=any(line.actual_purchase_quantity is not None for line in lines),
        has_remaining_lines=remaining_line_count > 0,
        pending_quality_count=int(pending_quality),
        received_quantity=received_quantity,
        return_status=return_status,
    )

    return {
        "can_complete": not reason,
        "blocked_reason": reason,
        "inbound_status": inbound_status,
        "inbound_status_display": inbound_status_display,
        "has_returns": has_returns,
        "return_status": return_status,
        "return_status_display": return_status_display,
        "return_total": return_total,
        "return_completed_count": return_completed_count,
        "return_pending_confirmation_count": return_pending_confirmation_count,
        "return_pending_completion_count": return_pending_completion_count,
    }


@transaction.atomic
def complete_purchase_order(*, order_id, remark, allowed_task_ids, actor_employee, request):
    from .source_access import purchase_order_access
    order = PurchaseOrder.objects.select_for_update(of=("self",)).filter(
        purchase_order_access(allowed_task_ids, request), pk=order_id, archived_at__isnull=True,
    ).first()
    if order is None:
        raise NotFound("采购单不存在或无权访问。")
    require_matching_etag(request, order)
    summary = purchase_completion_summary(purchase_orders_with_context().get(pk=order.pk))
    if not summary["can_complete"]:
        raise Conflict(summary["blocked_reason"])
    remark = remark.strip()
    if len(remark) > 2000:
        raise ValidationError({"remark": "完成备注不能超过2000字。"})
    if summary["has_returns"] and not remark:
        raise ValidationError({"remark": "有退货的采购单完成时必须填写备注。"})
    previous_status = order.status
    order.status = PurchaseOrderStatus.COMPLETED
    order.completed_at = timezone.now()
    order.completed_by_employee = actor_employee
    order.completion_remark = remark
    order.save(update_fields=["status", "completed_at", "completed_by_employee", "completion_remark", "updated_at"])
    write_audit_log(
        object_type="PURCHASE_ORDER", object_id=order.pk, action="COMPLETED",
        actor_employee=actor_employee, before_data={"status": previous_status},
        after_data={"status": order.status, "completion_remark": remark}, request=request,
    )
    from apps.wecom.notification_services import register_business_event
    register_business_event(
        event_code="PURCHASE_ORDER_COMPLETED", idempotency_key=f"PURCHASE_ORDER_COMPLETED:{order.pk}:1",
        object_type="procurement.PurchaseOrder", object_id=order.pk, object_version=1,
        context={"document_no": order.order_number, "operator": actor_employee.display_name,
                 "occurred_at": order.completed_at.isoformat(), "status": order.get_status_display()},
    )
    return purchase_orders_with_context().get(pk=order.pk)


def generate_quality_returns(*, inbound, lines, actor_employee, request):
    """由品质确认事务调用；唯一约束保护同一批次、同一明细不重复生成。"""
    grouped = {}
    for line in lines:
        if line.return_quantity <= 0:
            continue
        supplier_id = line.purchase_order_line.supplier_id
        if not supplier_id:
            raise ValidationError({"items": "退货明细缺少供应商，请先核对采购单。"})
        grouped.setdefault(supplier_id, []).append(line)
    for supplier_id, supplier_lines in grouped.items():
        first = supplier_lines[0]
        return_order = PurchaseReturn.objects.create(
            return_number=next_business_number("PURCHASE_RETURN"),
            purchase_order_id=first.purchase_order_line.purchase_order_id,
            inbound=inbound, supplier_id=supplier_id,
            supplier_number_snapshot=first.supplier_number_snapshot,
            supplier_name_snapshot=first.supplier_name_snapshot,
            generated_by_employee=actor_employee,
        )
        PurchaseReturnLine.objects.bulk_create([
            PurchaseReturnLine(return_order=return_order, inbound_line=line, quantity=line.return_quantity)
            for line in supplier_lines
        ])
        write_audit_log(
            object_type="PURCHASE_RETURN", object_id=return_order.pk, action="QUALITY_GENERATED",
            context_type="PURCHASE_ORDER", context_id=return_order.purchase_order_id,
            actor_employee=actor_employee,
            after_data={"return_number": return_order.return_number, "line_count": len(supplier_lines)}, request=request,
        )


@transaction.atomic
def advance_purchase_return(*, return_id, target_status, allowed_task_ids, actor_employee, request):
    from .source_access import purchase_order_access
    record = PurchaseReturn.objects.select_for_update(of=("self",)).filter(
        purchase_order_access(allowed_task_ids, request, "purchase_order__"),
        pk=return_id, purchase_order__archived_at__isnull=True,
    ).first()
    if record is None:
        raise NotFound("退货单不存在或无权访问。")
    require_matching_etag(request, record)
    expected = {
        PurchaseReturnStatus.PROCUREMENT_CONFIRMED: PurchaseReturnStatus.QUALITY_GENERATED,
        PurchaseReturnStatus.COMPLETED: PurchaseReturnStatus.PROCUREMENT_CONFIRMED,
    }.get(target_status)
    if expected is None or record.status != expected:
        raise Conflict("退货状态已变化，请刷新；须先确认退货，再完成退货。")
    before = record.status
    record.status = target_status
    if target_status == PurchaseReturnStatus.PROCUREMENT_CONFIRMED:
        record.confirmed_by_employee = actor_employee
        record.confirmed_at = timezone.now()
        fields = ["confirmed_by_employee", "confirmed_at"]
    else:
        record.completed_by_employee = actor_employee
        record.completed_at = timezone.now()
        fields = ["completed_by_employee", "completed_at"]
    record.save(update_fields=["status", "updated_at", *fields])
    write_audit_log(
        object_type="PURCHASE_RETURN", object_id=record.pk, action=target_status,
        context_type="PURCHASE_ORDER", context_id=record.purchase_order_id,
        actor_employee=actor_employee, before_data={"status": before}, after_data={"status": target_status}, request=request,
    )
    return record
