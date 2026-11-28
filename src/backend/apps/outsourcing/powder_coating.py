"""按业务凭证列出管件喷塑收发。库存流水只负责记账。"""
from collections import Counter, defaultdict
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.db.models import Exists, F, OuterRef, Q

from apps.access_control.resource_scopes import filter_crafts
from apps.boms.material_attributes import spray_color_value
from apps.core.delivery_reminders import business_today, delivery_reminder, reminder_matches, reminder_order
from apps.inventory.public_stock_mode import public_flow_enabled
from apps.material_issues.models import (
    MetalProcessingExternalGoodReturn, MetalProcessingExternalHandoff, MetalProcessingExternalOrder,
    MetalProcessingOriginalHandoff, MetalProcessingUnsprayedReturn,
)
from apps.material_issues.p4_access import scoped_records
from apps.material_issues.processing_selectors import processing_lines
from apps.workshop_config.models import OutsourcingCode

from .legacy_raw_returns import raw_returns_by_dispatch
from .models import (
    OutsourcingDispatchLine, OutsourcingFactoryAllocation, OutsourcingOrder, OutsourcingReturnLine,
    TubeOutsourcingLine, TubeOutsourcingOrder, TubeOutsourcingReceiptLine, TubePlanReceiptLine,
)
from .selectors import accessible_outsourcing_orders
from .sewing_workbench import RETURN_REMINDER_DAYS
from .tube_selectors import VIEW_PERMISSION, saved_orders_for_permission
from .unified_selectors import VIEW_PERMISSIONS


POWDER = OutsourcingCode.POWDER_COATING
TUBE_SOURCES = ("METAL", "RAW_PIPE", "PUBLIC_SEMI")
METAL_PERMISSION = VIEW_PERMISSIONS[1]
ENDED = ("COMPLETED", "CLOSED", "CANCELLED")


def _movement(record, *, line_id, order, task_number, source, business_date, voucher_number, quantity, unit, factory_name,
              part, responsibility, unreliable=False):
    return {
        "id": str(line_id), "order_id": order.pk, "task_number": task_number, "source": source,
        "business_date": business_date, "created_at": record.created_at,
        "voucher_number": voucher_number or order.order_number,
        "quantity": quantity, "unit": unit, "factory_name": factory_name,
        "part_name": part.get("part_name") or "", "specification": part.get("specification") or "",
        "spray_color": part.get("spray_color") or "",
        "_responsibility": responsibility, "_unreliable": unreliable, "_order_number": order.order_number,
        "_deadline": getattr(order, "expected_return_date", None) or getattr(order, "delivery_date", None),
        "_open": order.status not in ENDED,
    }


def _tube_movements(orders, direction):
    plans = orders.filter(is_plan=True)
    independent = orders.filter(is_plan=False, plan__isnull=True)
    if direction == "dispatch":
        # A plan's detail owns its batches. A standalone order must itself be readable.
        lines = TubeOutsourcingLine.objects.filter(
            Q(order__plan_id__in=plans.values("pk")) | Q(order_id__in=independent.values("pk")),
            order__is_plan=False, order__craft__outsourcing_code=POWDER, order__source_kind__in=TUBE_SOURCES,
            order__status__in=("PROCESSING", "COMPLETED"), order__actions__kind="DISPATCH",
        ).select_related("order__plan", "order__product_line__production_task", "factory").annotate(
            business_date=F("order__actions__actual_dispatch_date"), dispatched_at=F("order__actions__created_at"),
        )
        for line in lines:
            batch = line.order
            row = _movement(batch, line_id=line.pk, order=batch.plan or batch, source="TUBE",
                            task_number=batch.product_line.production_task.task_number,
                            business_date=line.business_date, voucher_number=batch.order_number,
                            quantity=line.quantity, unit=line.snapshot.get("unit") or "支",
                            factory_name=line.snapshot.get("factory_name") or line.factory.name, part=line.snapshot,
                            responsibility=(batch.plan_id or batch.pk, line.factory_id, line.component_identity))
            row["created_at"] = line.dispatched_at
            yield row
        return

    plan_lines = TubePlanReceiptLine.objects.filter(
        receipt__order_id__in=plans.values("pk"), receipt__voided_at__isnull=True,
    )
    final_lines = TubeOutsourcingReceiptLine.objects.filter(
        receipt__order_id__in=independent.filter(status="COMPLETED").values("pk"), received_quantity__gt=0,
    )
    for queryset in (plan_lines, final_lines):
        for line in queryset.select_related("receipt__order__product_line__production_task", "order_line__factory"):
            receipt, ordered = line.receipt, line.order_line
            part = {**ordered.snapshot, **line.snapshot}
            yield _movement(receipt, line_id=line.pk, order=receipt.order, source="TUBE",
                            task_number=receipt.order.product_line.production_task.task_number,
                            business_date=receipt.receipt_date, voucher_number=receipt.receipt_number,
                            quantity=line.received_quantity, unit=part.get("unit") or "支",
                            factory_name=ordered.snapshot.get("factory_name") or ordered.factory.name, part=part,
                            responsibility=(receipt.order_id, ordered.factory_id, ordered.component_identity))


def _legacy_part(allocation):
    snapshot = allocation.processing_item.component_snapshot
    color = next((field["value"] for field in (snapshot.get("bom_attributes") or [])
                  if field.get("key") == "spray_color" and field.get("value")), "")
    output = (snapshot.get("public_output_identity") or {}).get("identity_snapshot", {})
    return {**snapshot, "spray_color": snapshot.get("spray_color") or color or output.get("color") or snapshot.get("color")}


def _legacy_dispatches(orders, *, net_of_raw_returns=False):
    rows = {}
    lines = OutsourcingDispatchLine.objects.filter(
        Q(issued_piece_count__gt=0) | Q(snapshot__kind="PIPE") | Q(material_item__conversion_snapshot__kind="PIPE"),
        dispatch__order_id__in=orders.values("pk"),
    ).select_related("dispatch__order__schedule__production_task", "material_item__allocation__factory",
                     "material_item__allocation__processing_item__order_product__schedule_product", "unit").order_by("pk")
    raw_returns = raw_returns_by_dispatch(lines) if net_of_raw_returns else {}
    for line in lines:
        dispatch, allocation = line.dispatch, line.material_item.allocation
        if line.issued_piece_count:
            quantity, unit = line.issued_piece_count, "支"
        else:
            quantity, unit = line.material_quantity or line.issued_quantity, line.unit.unit_name
        unreliable = False
        if returned := raw_returns.get(line.pk):
            returned_pieces = _returned_pipe_pieces(line, returned) if unit == "支" else None
            unreliable = returned_pieces is None or returned_pieces > quantity
            if not unreliable:
                quantity -= returned_pieces
        # Each stock location can have its own detail line on the same voucher.
        key = f"{dispatch.pk}:{allocation.pk}:{unit}"
        if key in rows:
            rows[key]["quantity"] += quantity
            rows[key]["_unreliable"] |= unreliable
        else:
            rows[key] = _movement(dispatch, line_id=key, order=dispatch.order, source="REGULAR",
                                  task_number=dispatch.order.schedule.production_task.task_number,
                                  business_date=dispatch.dispatch_date, voucher_number=dispatch.dispatch_number,
                                  quantity=quantity, unit=unit,
                                  factory_name=line.snapshot.get("factory") or allocation.factory_snapshot.get("name") or allocation.factory.name,
                                  part=_legacy_part(allocation), responsibility=_allocation_key(allocation), unreliable=unreliable)
    return rows.values()


def _returned_pipe_pieces(line, returns):
    pieces = 0
    for quantity, _, equivalent in returns:
        if equivalent is None:
            if line.unit.unit_name == "支":
                equivalent = quantity
            else:
                try:
                    ratio = Decimal(str(line.snapshot.get("pieces_per_bar")))
                except InvalidOperation:
                    return None
                if not ratio.is_finite() or ratio <= 0 or ratio * line.issued_quantity != line.issued_piece_count:
                    return None
                equivalent = quantity * ratio
        if equivalent <= 0 or int(equivalent) != equivalent:
            return None
        pieces += int(equivalent)
    return pieces


def _allocation_key(allocation):
    item = allocation.processing_item
    return (item.order_product.order_id, allocation.factory_id,
            str(item.order_product.schedule_product.product_line_id), str(item.bom_line_id))


def _handoff_key(handoff):
    snapshot = handoff.source.source_snapshot
    return (handoff.original_order_id, handoff.factory_id,
            snapshot.get("product_line_id"), snapshot.get("conversion_snapshot", {}).get("bom_line_id"))


def _handoff_responsibility(handoff):
    key = _handoff_key(handoff)
    return key if all(key) else (handoff.original_order_id, handoff.factory_id, handoff.source_id)


def _metal_part(source, event, component=None):
    frozen = (source.source_snapshot.get("conversion_snapshot", {}).get("public_bom_snapshot") or {}).get("line", {})
    output = (event.get("public_output_identity") or {}).get("identity_snapshot", {})
    part = component or {}
    return {
        "part_name": event.get("part_name") or source.source_snapshot.get("part_name") or part.get("part_name"),
        "specification": frozen.get("specification") or part.get("specification") or source.issue_line.specification_snapshot,
        "spray_color": output.get("color") or spray_color_value(frozen.get("raw_values")) or part.get("spray_color"),
    }


def _original_handoff_dispatches(handoffs):
    allocations = OutsourcingFactoryAllocation.objects.filter(
        processing_item__order_product__order_id__in={handoff.original_order_id for handoff in handoffs},
    ).select_related("processing_item__order_product__schedule_product")
    by_part = {_allocation_key(allocation): allocation for allocation in allocations}
    for handoff in handoffs:
        allocation = by_part.get(_handoff_key(handoff))
        yield _movement(
            handoff, line_id=handoff.pk, order=handoff.original_order, source="METAL",
            task_number=handoff.original_order.schedule.production_task.task_number,
            business_date=handoff.handoff_date, voucher_number=handoff.original_order.order_number,
            quantity=handoff.handoff_pieces, unit="支",
            factory_name=handoff.snapshot.get("factory_name") or handoff.factory.name,
            part=_metal_part(handoff.source, handoff.snapshot, _legacy_part(allocation) if allocation else None),
            responsibility=_handoff_responsibility(handoff), unreliable=allocation is None,
        )


def _legacy_receipts(orders, handoffs):
    rows = {}
    handoffs_by_part = defaultdict(set)
    for handoff in handoffs:
        key = _handoff_key(handoff)
        handoffs_by_part[key].update((str(handoff.pk), str(handoff.source_id)))
    legacy_orders = orders.filter(pk=OuterRef("return_record__order_id"))
    lines = OutsourcingReturnLine.objects.annotate(can_read_order=Exists(legacy_orders)).filter(
        Q(can_read_order=True) | Q(return_record__order_id__in={row.original_order_id for row in handoffs}),
        Q(allocation__conversion_snapshot__kind="PIPE")
        | Q(allocation__processing_item__component_snapshot__section_title="管材类")
        | Q(snapshot__route="METAL_ORIGINAL_GOOD_RETURN"),
    ).select_related("return_record__order__schedule__production_task", "allocation__factory",
                     "allocation__processing_item__order_product__schedule_product").order_by("pk")
    for line in lines:
        receipt, allocation = line.return_record, line.allocation
        saved = line.snapshot
        visible_ids = handoffs_by_part.get(_allocation_key(allocation), set())
        origin = saved.get("handoff_id") or saved.get("source_id")
        metal_access = line.quality == "AVAILABLE" and bool(visible_ids) and (not origin or origin in visible_ids)
        if not line.can_read_order and not metal_access:
            continue
        # 金工合格回货就是这条委外入库记录。同一凭证的合格与不良部分共用一行。
        unit = saved.get("unit") or allocation.processing_item.unit_snapshot
        key = f"{receipt.pk}:{allocation.pk}:{unit}"
        if key in rows:
            rows[key]["quantity"] += line.returned_quantity
            continue
        part = _legacy_part(allocation)
        part["part_name"] = saved.get("component") or part.get("part_name")
        output = (saved.get("public_output_identity") or {}).get("identity_snapshot", {})
        part["spray_color"] = output.get("color") or part["spray_color"]
        if saved.get("route") != "METAL_ORIGINAL_GOOD_RETURN":
            part["spray_color"] = saved.get("color") or part["spray_color"]
        rows[key] = _movement(
            receipt, line_id=key, order=receipt.order, source="METAL" if metal_access else "REGULAR",
            task_number=receipt.order.schedule.production_task.task_number,
            business_date=receipt.return_date, voucher_number=receipt.return_number, quantity=line.returned_quantity,
            unit=unit, responsibility=_allocation_key(allocation),
            unreliable=bool(receipt.factory_id and receipt.factory_id != allocation.factory_id),
            factory_name=saved.get("factory") or allocation.factory_snapshot.get("name") or allocation.factory.name, part=part,
        )
    return rows.values()


def _rework_movements(orders, direction):
    if direction == "dispatch":
        records = MetalProcessingExternalHandoff.objects.filter(order_id__in=orders.values("pk"))
    else:
        records = MetalProcessingExternalGoodReturn.objects.filter(order_id__in=orders.values("pk"))
    for record in records.select_related("order__source__issue_line__issue__production_task", "order__factory"):
        order = record.order
        yield _movement(
            record, line_id=record.pk, order=order, source="REWORK",
            task_number=order.source.issue_line.issue.production_task.task_number,
            business_date=record.handoff_date if direction == "dispatch" else record.return_date,
            voucher_number=order.order_number if direction == "dispatch" else record.return_number,
            quantity=record.handoff_pieces if direction == "dispatch" else record.good_pieces,
            unit="支", factory_name=record.snapshot.get("factory_name") or order.factory.name,
            part=_metal_part(order.source, record.snapshot), responsibility=(order.pk,),
        )


def _powder_sources(request, task_number, *, regular, metal, active_only=False):
    excluded = ENDED if active_only else ("CANCELLED",)
    old_orders = OutsourcingOrder.objects.filter(
        Q(craft_code_snapshot=POWDER) | Q(craft_code_snapshot="", craft__outsourcing_code=POWDER),
    ).exclude(status__in=excluded)
    if task_number:
        old_orders = old_orders.filter(schedule__production_task__task_number__iexact=task_number)
    tube_orders = TubeOutsourcingOrder.objects.none()
    if regular:
        if settings.TUBE_OUTSOURCING_ENABLED and public_flow_enabled():
            tube_orders = filter_crafts(saved_orders_for_permission(request), request, VIEW_PERMISSION).filter(
                craft__outsourcing_code=POWDER, source_kind__in=TUBE_SOURCES,
            ).exclude(status__in=excluded)
            if task_number:
                tube_orders = tube_orders.filter(product_line__production_task__task_number__iexact=task_number)
    regular_orders = (old_orders.filter(pk__in=accessible_outsourcing_orders(request, VIEW_PERMISSION).values("pk"))
                      if regular else old_orders.none())
    handoffs, rework_orders = [], MetalProcessingExternalOrder.objects.none()
    if metal:
        lines = processing_lines(request)
        if task_number:
            lines = lines.filter(issue__production_task__task_number__iexact=task_number)
        handoffs = list(scoped_records(
            MetalProcessingOriginalHandoff.objects.filter(source__issue_line__in=lines.values("pk"),
                original_order_id__in=old_orders.filter(
                    pk__in=accessible_outsourcing_orders(request, METAL_PERMISSION).values("pk")).values("pk"),
            ), request, METAL_PERMISSION, "original_order__craft_id",
        ).select_related("original_order__schedule__production_task", "factory", "source__issue_line"))
        rework_orders = scoped_records(MetalProcessingExternalOrder.objects.filter(
            source__issue_line__in=lines.values("pk"), craft__outsourcing_code=POWDER,
        ), request, METAL_PERMISSION)
        if active_only:
            rework_orders = rework_orders.exclude(status__in=ENDED)
    return tube_orders, regular_orders, handoffs, rework_orders


def _powder_movements(sources, direction, *, net_of_raw_returns=False):
    tube_orders, regular_orders, handoffs, rework_orders = sources
    yield from _tube_movements(tube_orders, direction)
    yield from _rework_movements(rework_orders, direction)
    if direction == "dispatch":
        yield from _legacy_dispatches(regular_orders, net_of_raw_returns=net_of_raw_returns)
        yield from _original_handoff_dispatches(handoffs)
    else:
        yield from _legacy_receipts(regular_orders, handoffs)


def powder_coating_rows(request, task_number, direction, *, regular, metal, follow_up, owner, order_id=None):
    sources = _powder_sources(request, task_number, regular=regular, metal=metal)
    factory = owner.casefold()
    rows = [
        row for row in _powder_movements(sources, direction)
        if (order_id is None or row["order_id"] == order_id) and factory in row["factory_name"].casefold()
    ]
    order_ids = {row["order_id"] for row in rows if row["_open"]}
    current = {}
    if order_ids:
        tube, regular_orders, handoffs, rework = sources
        current = _powder_reminders((
            tube.filter(pk__in=order_ids).exclude(status__in=ENDED),
            regular_orders.filter(pk__in=order_ids).exclude(status__in=ENDED),
            [handoff for handoff in handoffs
             if handoff.original_order_id in order_ids and handoff.original_order.status not in ENDED],
            rework.filter(pk__in=order_ids).exclude(status__in=ENDED),
        ))
    matches = []
    for row in rows:
        reminder_row = current.get(row["_responsibility"]) if row["_open"] else None
        reminder = reminder_row["reminder"] if reminder_row is not None else None
        if reminder_matches(reminder, follow_up, ""):
            row["reminder"] = reminder
            matches.append(row)
    matches.sort(key=lambda row: (row["business_date"], row["created_at"], row["id"]), reverse=True)
    if follow_up == "FOLLOW_UP":
        matches.sort(key=lambda row: reminder_order(row["reminder"]))
    return matches


def _powder_reminders(sources):
    sent, received = defaultdict(Counter), defaultdict(Counter)
    origins, uncertain = {}, set()
    for row in _powder_movements(sources, "dispatch", net_of_raw_returns=True):
        key = row["_responsibility"]
        origins.setdefault(key, row)
        sent[key][row["unit"]] += row["quantity"]
        if row["_unreliable"]:
            uncertain.add(key)
    for row in _powder_movements(sources, "receipt"):
        key = row["_responsibility"]
        if key in origins and row["quantity"] > 0:
            received[key][row["unit"]] += row["quantity"]
            if row["_unreliable"]:
                uncertain.add(key)
    handoff_keys = {row.pk: _handoff_responsibility(row) for row in sources[2]}
    for handoff, quantity in MetalProcessingUnsprayedReturn.objects.filter(
        original_handoff_id__in=handoff_keys,
    ).values_list("original_handoff_id", "returned_pieces"):
        # 未喷塑退回已离开加工点，仍按原业务展示在金工原单。
        received[handoff_keys[handoff]]["支"] += quantity

    today = business_today()
    rows = {}
    for key, row in origins.items():
        units = sent[key].keys() | received[key].keys()
        comparable = key not in uncertain and units == {"支"}
        unit = "支" if comparable else ""
        remaining = max(sent[key][unit] - received[key][unit], 0) if comparable else None
        reminder = delivery_reminder(
            today=today, window=RETURN_REMINDER_DAYS, due=row["_deadline"], quantity=remaining,
            unit=unit, action="催回厂", owner=row["factory_name"], reference=row["_order_number"],
            reason="未约定交期" if row["_deadline"] is None and not comparable else "",
        )
        if reminder is not None:
            rows[key] = {**row, "id": ":".join(str(value) for value in key), "reminder": reminder}
    return rows


def powder_coating_reminders(request, task_number, *, regular, metal, follow_up, owner):
    sources = _powder_sources(request, task_number, regular=regular, metal=metal, active_only=True)
    rows = (row for row in _powder_reminders(sources).values() if reminder_matches(row["reminder"], follow_up, owner))
    return sorted(rows, key=lambda row: (*reminder_order(row["reminder"]), row["task_number"], row["part_name"], row["id"]))
