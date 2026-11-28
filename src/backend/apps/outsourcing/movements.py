"""车缝、丝印按有效收发凭证显示实际物品和数量。"""
from itertools import chain

from django.conf import settings
from django.db.models import Q
from rest_framework.exceptions import PermissionDenied

from apps.access_control.module_operations import CUT_PIECE_PRINTING
from apps.access_control.module_policy import has_permission
from apps.access_control.resource_scopes import filter_crafts
from apps.inventory.public_stock_mode import public_flow_enabled

from .models import (
    OutsourcingDispatchLine, OutsourcingOrder, OutsourcingReturnLine, TubeOutsourcingAction,
    TubeOutsourcingOrder, TubeOutsourcingReceiptLine, TubePlanReceiptLine,
)
from .selectors import accessible_outsourcing_orders
from .sewing_tracking import TRACKED_CRAFTS
from .tube_selectors import DISPATCH_PERMISSION, RETURN_PERMISSION, VIEW_PERMISSION, saved_orders_for_permission
from .unified_selectors import workshop_list_access
from .warehouse_access import warehouse_regular_orders, warehouse_tube_orders


def _row(key, record, task_number, process, business_date, voucher_number, *,
         name, factory, quantity, unit, direct_transfer=False):
    return {
        "id": str(key), "created_at": record.created_at, "task_number": task_number,
        "process": process, "business_date": business_date, "voucher_number": voucher_number,
        "item_name": name, "factory_name": factory, "quantity": quantity, "unit": unit,
        "direct_transfer": direct_transfer,
    }


def _tube_dispatches(roots):
    # 实发批次由原计划单的查看权限覆盖，独立单则检查自身权限。
    actions = TubeOutsourcingAction.objects.filter(
        Q(order__plan_id__in=roots.filter(is_plan=True).values("pk"))
        | Q(order_id__in=roots.filter(is_plan=False).values("pk")),
        kind="DISPATCH", order__is_plan=False, order__status__in=("PROCESSING", "COMPLETED"),
    ).select_related("order__product_line__production_task", "order__craft").prefetch_related(
        "order__inputs__factory", "order__lines__factory", "order__materials__factory", "order__materials__unit",
    ).order_by()
    for action in actions.iterator(chunk_size=200):
        order = action.order
        process = order.craft.outsourcing_code
        facts = (action, order.product_line.production_task.task_number, process,
                 action.actual_dispatch_date, order.order_number)
        uses_inputs = order.source_snapshot.get("sewing_inputs")
        for line in (order.inputs if uses_inputs else order.lines).all():
            yield _row(line.pk, *facts, name=line.snapshot.get("part_name") or "",
                       factory=line.snapshot.get("factory_name") or line.factory.name,
                       quantity=line.quantity, unit=line.snapshot.get("unit") or "",
                       direct_transfer=bool(uses_inputs and line.print_order_line_id))
        if process == "SEWING":
            for material in order.materials.all():
                snap = material.snapshot
                unit = snap.get("unit") or material.unit.unit_name
                key = f"{order.pk}:{material.bom_line_id}:{material.factory_id}:{unit}"
                yield _row(key, *facts, name=snap.get("name") or snap.get("part_name") or snap.get("material") or "",
                           factory=snap.get("factory_name") or material.factory.name,
                           quantity=material.quantity, unit=unit)


def _tube_receipts(roots):
    plans = TubePlanReceiptLine.objects.filter(receipt__order_id__in=roots.filter(is_plan=True).values("pk"),
                                               receipt__voided_at__isnull=True)
    final = TubeOutsourcingReceiptLine.objects.filter(
        receipt__order_id__in=roots.filter(is_plan=False, status="COMPLETED").values("pk"))
    for queryset in (plans, final):
        lines = queryset.filter(received_quantity__gt=0).select_related(
            "receipt__order__product_line__production_task", "receipt__order__craft", "order_line__factory",
        ).order_by()
        for line in lines.iterator(chunk_size=500):
            receipt, ordered = line.receipt, line.order_line
            order = receipt.order
            yield _row(line.pk, receipt, order.product_line.production_task.task_number,
                       order.craft.outsourcing_code, receipt.receipt_date, receipt.receipt_number,
                       name=line.snapshot.get("part_name") or ordered.snapshot.get("part_name") or "",
                       unit=line.snapshot.get("unit") or ordered.snapshot.get("unit") or "",
                       factory=line.snapshot.get("factory_name") or ordered.snapshot.get("factory_name") or ordered.factory.name,
                       quantity=line.received_quantity)


def _regular_dispatches(orders):
    lines = OutsourcingDispatchLine.objects.filter(dispatch__order_id__in=orders.values("pk")).select_related(
        "dispatch__order__schedule__production_task", "dispatch__order__craft", "material_item__allocation__factory",
        "raw_material", "unit",
    ).order_by()
    for line in lines.iterator(chunk_size=500):
        dispatch, item = line.dispatch, line.material_item
        order, allocation = dispatch.order, item.allocation
        snap = item.material_snapshot
        unit = line.source_unit_snapshot or line.unit.unit_name
        key = f"{dispatch.pk}:{item.pk}:{line.raw_material_id}:{unit}"
        yield _row(key, dispatch, order.schedule.production_task.task_number,
                   order.craft_code_snapshot or order.craft.outsourcing_code, dispatch.dispatch_date,
                   dispatch.dispatch_number or order.order_number,
                   name=snap.get("part_name") or snap.get("material") or line.raw_material.material_name,
                   factory=line.snapshot.get("factory") or allocation.factory_snapshot.get("name") or allocation.factory.name,
                   quantity=line.source_quantity or line.issued_quantity, unit=unit)


def _regular_receipts(orders):
    lines = OutsourcingReturnLine.objects.filter(return_record__order_id__in=orders.values("pk")).select_related(
        "return_record__order__schedule__production_task", "return_record__order__craft",
        "return_record__factory", "allocation__processing_item",
    ).order_by()
    for line in lines.iterator(chunk_size=500):
        receipt, item = line.return_record, line.allocation.processing_item
        order, snap = receipt.order, line.snapshot
        unit = snap.get("unit") or item.unit_snapshot
        key = f"{receipt.pk}:{line.allocation_id}:{unit}"
        yield _row(key, receipt, order.schedule.production_task.task_number,
                   order.craft_code_snapshot or order.craft.outsourcing_code, receipt.return_date, receipt.return_number,
                   name=snap.get("component") or item.component_snapshot.get("part_name") or "",
                   factory=snap.get("factory") or receipt.factory_snapshot.get("name") or receipt.factory.name,
                   quantity=line.returned_quantity, unit=unit)


def movement_rows(request, *, task_number, direction, process):
    warehouse_code = DISPATCH_PERMISSION if direction == "dispatch" else RETURN_PERMISSION
    regular = workshop_list_access(request, VIEW_PERMISSION)
    printing = has_permission(request, CUT_PIECE_PRINTING)
    warehouse = workshop_list_access(request, warehouse_code)
    if not (regular or printing or warehouse):
        raise PermissionDenied("当前账号没有此方向的外协收发查看权限。")

    processes = (process,) if process else TRACKED_CRAFTS
    regular_scope = Q(pk__in=[])
    tube_scope = Q(pk__in=[])
    if regular:
        orders = filter_crafts(accessible_outsourcing_orders(request, VIEW_PERMISSION), request, VIEW_PERMISSION)
        regular_scope |= Q(pk__in=orders.values("pk"))
        orders = filter_crafts(saved_orders_for_permission(request), request, VIEW_PERMISSION)
        tube_scope |= Q(pk__in=orders.values("pk"))
    if printing:
        tube_scope |= Q(pk__in=saved_orders_for_permission(request, CUT_PIECE_PRINTING).values("pk"))
    if warehouse:
        regular_scope |= Q(pk__in=warehouse_regular_orders(request, warehouse_code).values("pk"))
        tube_scope |= Q(pk__in=warehouse_tube_orders(request, warehouse_code).values("pk"))
    orders = OutsourcingOrder.objects.filter(
        regular_scope, Q(craft_code_snapshot__in=processes) | Q(craft_code_snapshot="", craft__outsourcing_code__in=processes),
        schedule__production_task__task_number__icontains=task_number,
    ).exclude(status="CANCELLED").order_by()
    legacy = _regular_dispatches(orders) if direction == "dispatch" else _regular_receipts(orders)
    current = ()
    if settings.TUBE_OUTSOURCING_ENABLED and public_flow_enabled():
        roots = TubeOutsourcingOrder.objects.filter(
            tube_scope, plan__isnull=True, craft__outsourcing_code__in=processes,
            product_line__production_task__task_number__icontains=task_number,
        ).exclude(status="CANCELLED").order_by()
        current = _tube_dispatches(roots) if direction == "dispatch" else _tube_receipts(roots)
    # 同一凭证的同一物品可能分库区或品质保存；不同凭证始终分行。
    rows = {}
    for row in chain(legacy, current):
        key = row["id"]
        if key in rows:
            rows[key]["quantity"] += row["quantity"]
        else:
            rows[key] = row
    return sorted(rows.values(), key=lambda row: (row["business_date"], row["created_at"], row["id"]), reverse=True)
