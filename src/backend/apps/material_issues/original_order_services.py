from apps.access_control.resource_scopes import current_permission, can_order
from apps.inventory.public_stock_cutover import stock_write_transaction
"""直接交接原单收尾：按分配核账，显式取消待交余量，冻结差额结清历史。"""

from decimal import Decimal

from django.db import connection, transaction
from django.db.migrations.recorder import MigrationRecorder
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.audit.models import AuditLog
from apps.core.api.concurrency import PreconditionFailed, PreconditionRequired
from apps.core.api.exceptions import Conflict
from apps.core.audit import write_audit_log
from apps.core.auth import active_employee_for
from apps.outsourcing.material_flow import lock_request
from apps.outsourcing.models import (
    OutsourcingDispatch, OutsourcingFactoryAllocation, OutsourcingOrderStatus, OutsourcingReturnLine,
)
from apps.outsourcing.selectors import accessible_outsourcing_orders
from apps.outsourcing.services import order_audit_snapshot

from .models import MetalProcessingOriginalHandoff, MetalProcessingUnsprayedReturn
from .processing_selectors import digest, processing_lines


CLOSURE_ACTION = "DIRECT_HANDOFF_CLOSED"
CANCEL_PENDING_ACTION = "DIRECT_HANDOFF_PENDING_CANCELLED"
QUANTITY_FIELDS = ("planned_pieces", "cancelled_pending_pieces", "effective_planned_pieces", "pending_handoff_pieces",
                   "handoff_pieces", "returned_good_pieces", "returned_unsprayed_pieces", "remaining_return_pieces")
OPEN_STATUSES = {OutsourcingOrderStatus.PENDING_DISPATCH, OutsourcingOrderStatus.PROCESSING,
                 OutsourcingOrderStatus.PARTIAL_RETURN}


def original_closure_schema_ready():
    return MigrationRecorder(connection).migration_qs.filter(
        app="outsourcing", name="0006_direct_handoff_closed_status").exists()


def original_order_for_request(request, order_id, *, lock=False, permission=None):
    from .p4_services import p4_schema_ready
    if not p4_schema_ready():
        raise Conflict("管材直接交接数据库升级尚未完成，暂不能读取或操作原单收尾。")
    from apps.outsourcing.warehouse_access import warehouse_stage, warehouse_original_handoffs
    warehouse_read = not lock and permission is None and request.method == 'GET' and warehouse_stage(request)
    if warehouse_read:
        permission = 'outsourcing.confirm_return_outsourcingorder'
    queryset = accessible_outsourcing_orders(request, permission=permission or current_permission(request, "material_issues.view_metalprocessingsource"))
    if lock:
        queryset = queryset.select_for_update(of=("self",))
    order = get_object_or_404(queryset.select_related("schedule", "craft"), pk=order_id)
    handoffs = MetalProcessingOriginalHandoff.objects.filter(original_order=order)
    # 原单级操作不得借单一可见来源处理同单中超出本人范围的其他来源。
    outside_scope = handoffs.exclude(pk__in=warehouse_original_handoffs(request)) if warehouse_read else handoffs.exclude(source__issue_line__in=processing_lines(request))
    if outside_scope.exists():
        from django.http import Http404
        raise Http404
    return order


def _audit_rows(order, action):
    return AuditLog.objects.filter(object_type="OUTSOURCING_ORDER", object_id=order.pk, action=action)


def original_closure_data(order):
    row = _audit_rows(order, CLOSURE_ACTION).order_by("occurred_at", "id").first()
    if row is None:
        return None
    return {"id": str(row.pk), "remark": row.after_data["remark"],
            "actor_employee_id": str(row.actor_employee_id) if row.actor_employee_id else None,
            "actor_name": row.actor_name_snapshot, "created_at": row.occurred_at.isoformat(),
            "quantity_snapshot": row.after_data["quantity_snapshot"]}


def cancelled_pending_pieces(allocation):
    return sum(row.after_data["cancelled_pieces"] for row in _audit_rows(
        allocation.processing_item.order_product.order, CANCEL_PENDING_ACTION,
    ).filter(after_data__allocation_id=str(allocation.pk)))


def _order_quantities(order):
    from .p4_services import original_handoff_totals
    parts, blockers = [], []
    allocations = OutsourcingFactoryAllocation.objects.filter(processing_item__order_product__order=order).select_related(
        "factory", "processing_item__order_product__schedule_product", "processing_item__order_product__order",
    ).order_by("processing_item__order_product__line_number", "processing_item__line_number", "id")
    for allocation in allocations:
        item = allocation.processing_item
        product = item.order_product
        totals = original_handoff_totals(allocation)
        plan = allocation.allocated_quantity
        returned = Decimal(str(totals["returned_pieces"]))
        if plan < 0 or plan != plan.to_integral_value() or returned != returned.to_integral_value():
            blockers.append("原单存在非整数计划或回货数量，请先核对。")
        planned = int(plan)
        cancelled = cancelled_pending_pieces(allocation)
        effective = planned - cancelled
        pending = effective - totals["handoff_pieces"]
        remaining = totals["handoff_pieces"] - int(returned) - totals["returned_unsprayed_pieces"]
        if effective < 0 or pending < 0 or remaining < 0:
            blockers.append("原单分配、已交和回货数量存在冲突，请先核对。")
        if item.component_snapshot.get("flow", {}).get("kind") != "PIPE":
            blockers.append("原单含非管材加工分配，不能按直接交接管材支数收尾。")
        product_snapshot = product.product_snapshot
        parts.append({"allocation_id": str(allocation.pk),
            "product_line_id": str(product.schedule_product.product_line_id),
            "product_name": product_snapshot.get("product_name", ""),
            "product_number": product_snapshot.get("product_number", ""),
            "specification": item.component_snapshot.get("specification", ""),
            "part_name": item.component_snapshot.get("part_name", ""),
            "factory_id": str(allocation.factory_id),
            "factory_name": allocation.factory_snapshot.get("name", allocation.factory.name),
            "planned_pieces": planned, "cancelled_pending_pieces": cancelled,
            "effective_planned_pieces": effective, "pending_handoff_pieces": max(pending, 0),
            "handoff_pieces": totals["handoff_pieces"], "returned_good_pieces": int(returned),
            "returned_unsprayed_pieces": totals["returned_unsprayed_pieces"],
            "remaining_return_pieces": max(remaining, 0)})
    if not parts:
        blockers.append("原单没有有效加工分配。")
    if OutsourcingDispatch.objects.filter(order=order).exists():
        blockers.append("原单同时存在仓库原料发料记录，不能混合来源收尾。")
    if OutsourcingReturnLine.objects.filter(return_record__order=order).exclude(quality="AVAILABLE").exists():
        blockers.append("原单包含非合格回货记录，不能按当前直接交接流程收尾。")
    return parts, {field: sum(row[field] for row in parts) for field in QUANTITY_FIELDS}, list(dict.fromkeys(blockers))


def _post_closure_returns(order, closure, parts):
    if closure is None:
        return []
    part_map = {row["allocation_id"]: row for row in parts}
    result = []
    for line in OutsourcingReturnLine.objects.filter(return_record__order=order, snapshot__post_closure=True).select_related(
            "return_record__confirmed_by_employee"):
        record = line.return_record
        part = part_map.get(str(line.allocation_id), {})
        result.append({"id": str(record.pk), "kind": "GOOD", "allocation_id": str(line.allocation_id),
            "part_name": part.get("part_name", ""), "factory_name": part.get("factory_name", ""),
            "pieces": int(line.returned_quantity), "return_date": record.return_date.isoformat(), "remark": record.remark,
            "actor_name": line.snapshot.get("actor_name", record.confirmed_by_employee.display_name),
            "created_at": record.created_at.isoformat()})
    for record in MetalProcessingUnsprayedReturn.objects.filter(original_handoff__original_order=order, snapshot__post_closure=True):
        allocation_id = record.snapshot.get("allocation_id", "")
        part = part_map.get(allocation_id, {})
        result.append({"id": str(record.pk), "kind": "UNSPRAYED", "allocation_id": allocation_id,
            "part_name": part.get("part_name", ""), "factory_name": part.get("factory_name", ""),
            "pieces": record.returned_pieces, "return_date": record.return_date.isoformat(), "remark": record.remark,
            "actor_name": record.snapshot.get("actor_name", ""), "created_at": record.created_at.isoformat()})
    return sorted(result, key=lambda row: (row["created_at"], row["id"]), reverse=True)


def original_order_context(order, request=None):
    parts, totals, structural_blockers = _order_quantities(order)
    closure = original_closure_data(order)
    blockers = list(structural_blockers)
    schema_ready = original_closure_schema_ready()
    if not schema_ready:
        blockers.append("原单收尾数据库升级尚未完成，暂不能结清或取消待交余量。")
    if order.status not in OPEN_STATUSES:
        blockers.append("原单已结清、已完成或已取消，不能再次备注结清。")
    if not totals["handoff_pieces"]:
        blockers.append("原单尚无实际交接，不能备注结清。")
    if totals["pending_handoff_pieces"]:
        blockers.append("存在待交接分配，请先完成交接或明确取消对应待交余量。")
    if not totals["remaining_return_pieces"]:
        blockers.append("原单没有未回差额，无需备注结清。")
    if request is not None and not can_order(request, "outsourcing.complete_outsourcingorder", order):
        blockers.append("当前账号没有原单备注结清权限。")
    can_cancel = (schema_ready and not structural_blockers and totals["handoff_pieces"] > 0
                  and order.status in OPEN_STATUSES and request is not None
                  and can_order(request, "outsourcing.change_outsourcingorder", order))
    for part in parts:
        part["can_cancel_pending"] = bool(can_cancel and part["pending_handoff_pieces"] > 0)
    pending_cancellations = []
    for row in _audit_rows(order, CANCEL_PENDING_ACTION).order_by("-occurred_at", "-id"):
        pending_cancellations.append({"id": str(row.pk), "allocation_id": row.after_data["allocation_id"],
            "part_name": row.after_data["part_name"], "factory_name": row.after_data["factory_name"],
            "cancelled_pieces": row.after_data["cancelled_pieces"], "remark": row.after_data["remark"],
            "actor_employee_id": str(row.actor_employee_id) if row.actor_employee_id else None,
            "actor_name": row.actor_name_snapshot, "created_at": row.occurred_at.isoformat()})
    return {"original_order_id": str(order.pk), "original_order_number": order.order_number,
        "original_order_status": order.status, "etag": '"' + digest({"order_id": str(order.pk), "version": order.version, "status": order.status,
            "parts": [{key: value for key, value in row.items() if key != "can_cancel_pending"} for row in parts]}) + '"',
        "parts": parts, "totals": totals, "schema_ready": schema_ready, "can_close": not blockers, "blockers": blockers,
        "closure": closure, "pending_cancellations": pending_cancellations,
        "post_closure_returns": _post_closure_returns(order, closure, parts)}


def update_original_return_status(order):
    """调用方已锁原单，状态与当前写入在同一事务提交，不自动取消任何计划。"""
    parts, totals, blockers = _order_quantities(order)
    if not blockers and totals["handoff_pieces"] > 0 and all(
            row["remaining_return_pieces"] == 0 and row["pending_handoff_pieces"] == 0 for row in parts):
        order.status = OutsourcingOrderStatus.COMPLETED
        order.completed_at = timezone.now()
    elif order.status != OutsourcingOrderStatus.CLOSED and (totals["returned_good_pieces"] or totals["returned_unsprayed_pieces"]):
        order.status = OutsourcingOrderStatus.PARTIAL_RETURN


def _require_context_etag(request, context):
    expected = request.headers.get("If-Match")
    if not expected:
        raise PreconditionRequired()
    if expected != context["etag"]:
        raise PreconditionFailed()


@stock_write_transaction
def write_original_order_closure(*, request, order_id, request_id, remark, allocation_id=None):
    cancelling = allocation_id is not None
    permission = "change_outsourcingorder" if cancelling else "complete_outsourcingorder"
    actor = active_employee_for(request.user)
    if actor is None or not request.user.has_perm(f"outsourcing.{permission}"):
        raise PermissionDenied("当前账号没有执行此原单操作的权限。")
    if not original_closure_schema_ready():
        raise Conflict("原单收尾数据库升级尚未完成，暂不能结清或取消待交余量。")
    remark = remark.strip()
    if not remark:
        raise ValidationError({"remark": "原因备注去除空格后不能为空。"})
    lock_request("metal-original-closure", request_id)
    order = original_order_for_request(request, order_id, lock=True, permission=f"outsourcing.{permission}")
    action = CANCEL_PENDING_ACTION if cancelling else CLOSURE_ACTION
    payload_hash = digest({"order_id": str(order_id), "actor_id": str(actor.pk), "action": action,
                           "remark": remark, "allocation_id": str(allocation_id) if allocation_id else None})
    existing = AuditLog.objects.filter(object_type="OUTSOURCING_ORDER", action__in=[CLOSURE_ACTION, CANCEL_PENDING_ACTION],
                                      after_data__client_request_id=str(request_id)).first()
    if existing:
        if existing.object_id != order.pk or existing.after_data.get("request_payload_hash") != payload_hash:
            raise Conflict("相同请求标识不能用于不同原单、操作人或提交内容。")
        return original_order_context(order, request)
    context = original_order_context(order, request)
    _require_context_etag(request, context)
    before = order_audit_snapshot(order)
    if cancelling:
        part = next((row for row in context["parts"] if row["allocation_id"] == str(allocation_id)), None)
        if part is None:
            raise ValidationError({"allocation_id": "所选分配不属于当前原单。"})
        if not part["can_cancel_pending"]:
            raise Conflict("当前分配没有可取消的待交余量，或原单状态不允许取消。")
        detail = {"allocation_id": str(allocation_id), "part_name": part["part_name"], "factory_name": part["factory_name"],
                  "cancelled_pieces": part["pending_handoff_pieces"], "quantity_snapshot": dict(part)}
    else:
        if not context["can_close"]:
            raise Conflict("；".join(context["blockers"]))
        detail = {"quantity_snapshot": {"parts": [{key: value for key, value in row.items() if key != "can_cancel_pending"}
                                                    for row in context["parts"]], "totals": context["totals"]}}
        order.status = OutsourcingOrderStatus.CLOSED
    write_audit_log(object_type="OUTSOURCING_ORDER", object_id=order.pk, action=action, actor_employee=actor,
        before_data=before, after_data={**detail, "remark": remark, "client_request_id": str(request_id),
                                       "request_payload_hash": payload_hash},
        context_type="PRODUCTION_SCHEDULE", context_id=order.schedule_id, request=request)
    if cancelling:
        update_original_return_status(order)
    from .p4_services import _bump_original_order
    _bump_original_order(order, actor, request, "DIRECT_HANDOFF_STATE_UPDATED", before)
    return original_order_context(order, request)
