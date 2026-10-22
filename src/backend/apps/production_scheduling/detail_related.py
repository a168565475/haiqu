"""排产产品下的外发与领料摘要；只读冻结单据，并保留各来源权限。"""
from collections import defaultdict
from copy import copy
from decimal import Decimal, localcontext
from types import SimpleNamespace

from django.conf import settings
from django.db.models import Case, CharField, Count, Prefetch, Q, Value, When

from apps.material_issues.models import MetalProcessingExternalOrder, MetalProcessingOriginalHandoff
from apps.material_issues.p4_access import scoped_records
from apps.material_issues.processing_selectors import processing_lines
from apps.material_issues.selectors import accessible_material_issues
from apps.outsourcing.models import (
    OutsourcingDispatchLine, OutsourcingFactoryAllocation, OutsourcingOrder, OutsourcingReturnLine,
    TubeOutsourcingAction, TubeOutsourcingLine, TubeOutsourcingOrder, TubeOutsourcingReceipt,
)
from apps.outsourcing.selectors import accessible_outsourcing_orders
from apps.outsourcing.tube_kinds import output_unit
from apps.outsourcing.tube_prices import line_price_data
from apps.outsourcing.tube_selectors import saved_orders_for_permission
from apps.outsourcing.unified_selectors import TUBE_STATUS_LABELS


OUTSOURCING_PERMISSION = "outsourcing.view_outsourcingorder"
METAL_PERMISSION = "material_issues.view_metalprocessingsource"
ISSUE_PERMISSION = "material_issues.view_materialissue"


def _read_request(request, permission):
    # 各来源 selector 按自己的 view 权限取范围，不借用排产接口的 action。
    result = copy(request)
    view = SimpleNamespace(action="retrieve", action_permission_map={"retrieve": permission})
    result.parser_context = {**(getattr(request, "parser_context", None) or {}), "view": view}
    return result


def _sources_for_tasks(request, task_ids, product_ids):
    external_request = _read_request(request, OUTSOURCING_PERMISSION)
    metal_request = _read_request(request, METAL_PERMISSION)
    regular = accessible_outsourcing_orders(external_request, permission=OUTSOURCING_PERMISSION).filter(
        schedule__production_task_id__in=task_ids,
        products__schedule_product__product_line_id__in=product_ids,
    ) if request.user.has_perm(OUTSOURCING_PERMISSION) else OutsourcingOrder.objects.none()
    if request.user.has_perm(METAL_PERMISSION):
        lines = processing_lines(metal_request, permission=METAL_PERMISSION).filter(
            issue__production_task_id__in=task_ids, issue__product_line_id__in=product_ids)
        handoffs = scoped_records(MetalProcessingOriginalHandoff.objects.filter(source__issue_line__in=lines),
            metal_request, METAL_PERMISSION, "original_order__craft_id")
        reworks = scoped_records(MetalProcessingExternalOrder.objects.filter(source__issue_line__in=lines),
            metal_request, METAL_PERMISSION)
    else:
        handoffs, reworks = MetalProcessingOriginalHandoff.objects.none(), MetalProcessingExternalOrder.objects.none()
    originals = OutsourcingOrder.objects.filter(
        Q(pk__in=regular.values("pk")) | Q(pk__in=handoffs.values("original_order_id")),
    ).annotate(unified_access=Case(When(pk__in=regular.values("pk"), then=Value("REGULAR")),
        default=Value("METAL"), output_field=CharField()))
    tubes = saved_orders_for_permission(external_request, permission=OUTSOURCING_PERMISSION).filter(
        schedule_product__schedule__production_task_id__in=task_ids,
    ) if request.user.has_perm(OUTSOURCING_PERMISSION) and getattr(settings, "TUBE_OUTSOURCING_ENABLED", False) else TubeOutsourcingOrder.objects.none()
    return originals, reworks, tubes, metal_request


def _quantity(value):
    return format(Decimal(value).normalize(), "f") if value is not None else None


def _amount(quantity, price, *, decimal_places=2):
    if quantity is None or price is None:
        return None
    with localcontext() as context:
        context.prec = 48
        return format(Decimal(quantity) * price, f".{decimal_places}f")


def _record(order, kind, *, identity, part_name, factory_name, unit, quantity, price, access):
    return {
        "id": f"{kind}:{identity}", "order_id": str(order.pk), "order_kind": kind,
        "order_number": order.order_number, "craft_name": getattr(order, "craft_name_snapshot", order.craft.name),
        "craft_code": getattr(order, "craft_code_snapshot", "") or order.craft.outsourcing_code or "",
        "part_name": part_name, "factory_name": factory_name,
        "planned_quantity": _quantity(quantity), "quantity_unit": unit,
        "dispatched_quantity": None, "dispatched_unit": None,
        "received_quantity": "0", "received_unit": unit, "shortage_quantity": None,
        "unit_price": _quantity(price), "price_unit": f"元/{unit}" if unit else "",
        # 普通外发沿用详情的四位金额，避免历史四位单价被逐行舍入到分后再汇总。
        "planned_amount": _amount(quantity, price, decimal_places=4 if kind == "REGULAR" else 2),
        "expected_return_date": None,
        "status": order.status,
        "status_display": TUBE_STATUS_LABELS.get(order.status, order.status) if kind == "TUBE" else order.get_status_display(),
        "detail_access": access, "reason": "", "_updated_at": order.updated_at,
    }


def _set_dispatched(record, quantities):
    if not quantities:
        record["reason"] = "尚无可核对的发出凭证。"
    elif len(quantities) == 1:
        unit, quantity = next(iter(quantities.items()))
        record.update(dispatched_quantity=_quantity(quantity), dispatched_unit=unit)
    else:
        record.update(dispatched_unit="多种单位", reason="实发包含不同材料单位，请到外发详情逐项核对。")


def _regular_records(orders, product_ids):
    allocations = list(OutsourcingFactoryAllocation.objects.filter(
        processing_item__order_product__order__in=orders.filter(unified_access="REGULAR"),
        processing_item__order_product__schedule_product__product_line_id__in=product_ids,
    ).select_related("factory", "processing_item__order_product__order__craft",
                     "processing_item__order_product__schedule_product"))
    if not allocations:
        return []
    by_id = {str(row.pk): row for row in allocations}
    by_source = {
        (str(row.processing_item.order_product.order_id), str(row.factory_id),
         str(row.processing_item.order_product.schedule_product.product_line_id), str(row.processing_item.bom_line_id)): row
        for row in allocations
    }
    sent, returned = defaultdict(lambda: defaultdict(Decimal)), defaultdict(Decimal)
    dispatches = OutsourcingDispatchLine.objects.filter(material_item__allocation_id__in=by_id).select_related("unit", "material_item")
    for line in dispatches:
        quantity = line.issued_piece_count if line.issued_piece_count is not None else (
            line.material_quantity if line.material_quantity is not None else line.issued_quantity)
        unit = "支" if line.issued_piece_count is not None else line.unit.unit_name
        sent[str(line.material_item.allocation_id)][unit] += quantity
    handoffs = MetalProcessingOriginalHandoff.objects.filter(
        original_order_id__in={row.processing_item.order_product.order_id for row in allocations},
        source__issue_line__issue__product_line_id__in=product_ids,
    ).select_related("source")
    for handoff in handoffs:
        source = handoff.source.source_snapshot
        key = (str(handoff.original_order_id), str(handoff.factory_id), source.get("product_line_id"),
               source.get("conversion_snapshot", {}).get("bom_line_id"))
        allocation = by_source.get(key)
        if allocation is not None:
            sent[str(allocation.pk)]["支"] += handoff.handoff_pieces
    for line in OutsourcingReturnLine.objects.filter(allocation_id__in=by_id, quality="AVAILABLE"):
        returned[str(line.allocation_id)] += line.returned_quantity
    result = []
    for allocation in allocations:
        item, product = allocation.processing_item, allocation.processing_item.order_product
        record = _record(product.order, "REGULAR", identity=allocation.pk,
            part_name=item.component_snapshot.get("part_name", ""),
            factory_name=allocation.factory_snapshot.get("name") or allocation.factory.name,
            unit=item.unit_snapshot, quantity=allocation.allocated_quantity, price=allocation.unit_price, access="REGULAR")
        _set_dispatched(record, sent[str(allocation.pk)])
        record.update(received_quantity=_quantity(returned[str(allocation.pk)]), expected_return_date=product.order.delivery_date)
        result.append((product.schedule_product.product_line_id, record))
    return result


def _projected_records(request, orders, task_ids, product_ids):
    sources = processing_lines(request, permission=METAL_PERMISSION).filter(
        issue__production_task_id__in=task_ids, issue__product_line_id__in=product_ids)
    handoffs = scoped_records(MetalProcessingOriginalHandoff.objects.filter(
        original_order__in=orders.filter(unified_access="METAL"), source__issue_line__in=sources,
    ), request, METAL_PERMISSION, "original_order__craft_id").select_related(
        "source__issue_line__issue", "original_order__craft", "factory")
    groups, source_keys = {}, {}
    for handoff in handoffs:
        source = handoff.source.source_snapshot
        product_id = handoff.source.issue_line.issue.product_line_id
        key = (handoff.original_order_id, source.get("component_identity") or str(handoff.source_id), handoff.factory_id, product_id)
        if key not in groups:
            record = _record(handoff.original_order, "REGULAR", identity=f"source:{':'.join(map(str, key))}",
                part_name=source.get("part_name", ""), factory_name=handoff.factory.name,
                unit="支", quantity=None, price=None, access="METAL")
            record.update(dispatched_quantity="0", dispatched_unit="支", reason="仅展示授权金工来源；计划数量、价格和交期不可见。")
            groups[key] = record
        groups[key]["dispatched_quantity"] = _quantity(Decimal(groups[key]["dispatched_quantity"]) + handoff.handoff_pieces)
        source_keys[(str(handoff.original_order_id), str(handoff.factory_id), str(handoff.source_id))] = key
    returns = OutsourcingReturnLine.objects.filter(
        return_record__order_id__in={key[0] for key in groups}, quality="AVAILABLE",
        snapshot__source_id__in={key[2] for key in source_keys},
    ).select_related("allocation", "return_record")
    for line in returns:
        key = source_keys.get((str(line.return_record.order_id), str(line.allocation.factory_id), line.snapshot.get("source_id")))
        if key is not None:
            groups[key]["received_quantity"] = _quantity(Decimal(groups[key]["received_quantity"]) + line.returned_quantity)
    return [(key[3], record) for key, record in groups.items()]


def _tube_records(orders, product_ids):
    orders = list(orders.filter(product_line_id__in=product_ids).select_related("craft").prefetch_related(
        Prefetch("lines", queryset=TubeOutsourcingLine.objects.order_by("created_at", "id"), to_attr="detail_lines"),
        Prefetch("actions", queryset=TubeOutsourcingAction.objects.all(), to_attr="detail_actions")))
    receipts = {row.order_id: row for row in TubeOutsourcingReceipt.objects.filter(order__in=orders).prefetch_related("lines")}
    result = []
    for order in orders:
        actions = {row.kind: row for row in order.detail_actions}
        dispatch = actions.get("DISPATCH")
        valid_dispatch = (bool(order.detail_lines) and dispatch is not None and "CANCEL" not in actions
            and isinstance(dispatch.snapshot, dict)
            and dispatch.snapshot.get("quantity") == sum(line.quantity for line in order.detail_lines))
        receipt = receipts.get(order.pk)
        receipt_lines = {row.order_line_id: row for row in receipt.lines.all()} if receipt else {}
        valid_receipt = (valid_dispatch and order.status == "COMPLETED" and len(receipt_lines) == len(order.detail_lines)
            and all(line.pk in receipt_lines and receipt_lines[line.pk].dispatched_quantity == line.quantity
                and 0 <= receipt_lines[line.pk].received_quantity <= line.quantity
                and receipt_lines[line.pk].shortage_quantity == line.quantity - receipt_lines[line.pk].received_quantity
                for line in order.detail_lines))
        for line in order.detail_lines:
            unit = output_unit(order.source_kind)
            record = _record(order, "TUBE", identity=line.pk, part_name=line.snapshot.get("part_name", ""),
                factory_name=line.snapshot.get("factory_name", ""), unit=unit, quantity=line.quantity,
                price=line.unit_price, access="TUBE")
            record.update(**line_price_data(line), expected_return_date=order.expected_return_date)
            if valid_dispatch:
                record.update(dispatched_quantity=str(line.quantity), dispatched_unit=unit)
            else:
                record["reason"] = "尚无可核对的完整发出凭证。"
            if valid_receipt:
                returned = receipt_lines[line.pk]
                record.update(received_quantity=str(returned.received_quantity), shortage_quantity=str(returned.shortage_quantity))
            elif receipt is not None or order.status == "COMPLETED":
                record.update(received_quantity=None, reason="缺少完整有效的回货凭证，不能按零回货计算。")
            result.append((order.product_line_id, record))
    return result


def _p4_records(orders, product_ids):
    result = []
    for order in orders.filter(source__issue_line__issue__product_line_id__in=product_ids).distinct().select_related(
        "source__issue_line__issue", "factory", "craft"):
        record = _record(order, "P4", identity=order.pk, part_name=order.source.source_snapshot.get("part_name", ""),
            factory_name=order.factory.name, unit="支", quantity=order.allocated_pieces,
            price=order.unit_price, access="METAL")
        record.update(dispatched_quantity=str(order.handoff_pieces), dispatched_unit="支",
                      received_quantity=str(order.returned_good_pieces))
        result.append((order.source.issue_line.issue.product_line_id, record))
    return result


def related_summary(request, schedule, products):
    """products 必须由调用方按排产权限筛选；关联记录再独立核查来源权限。"""
    products = list(products)
    outsourcing_allowed = request.user.has_perm(OUTSOURCING_PERMISSION) or request.user.has_perm(METAL_PERMISSION)
    issues_allowed = request.user.has_perm(ISSUE_PERMISSION)
    result = {str(product.pk): {
        "outsourcing": {"allowed": outsourcing_allowed, "records": [], "planned_amount": "0.00" if outsourcing_allowed else None},
        "material_issues": {"allowed": issues_allowed, "records": []},
    } for product in products}
    if not products or not (outsourcing_allowed or issues_allowed):
        return result
    product_ids = {product.product_line_id: str(product.pk) for product in products}
    if outsourcing_allowed:
        originals, reworks, tubes, metal_request = _sources_for_tasks(request, [schedule.production_task_id], product_ids)
        rows = [*_regular_records(originals, product_ids), *_tube_records(tubes, product_ids), *_p4_records(reworks, product_ids)]
        if request.user.has_perm(METAL_PERMISSION):
            rows.extend(_projected_records(metal_request, originals, [schedule.production_task_id], product_ids))
        rows.sort(key=lambda item: (item[1]["_updated_at"], item[1]["id"]), reverse=True)
        for product_id, row in rows:
            row.pop("_updated_at")
            result[product_ids[product_id]]["outsourcing"]["records"].append(row)
        for summary in result.values():
            records = summary["outsourcing"]["records"]
            with localcontext() as context:
                context.prec = 48
                summary["outsourcing"]["planned_amount"] = (None if any(row["planned_amount"] is None for row in records)
                    else format(sum((Decimal(row["planned_amount"]) for row in records), Decimal(0)), ".2f"))
    if issues_allowed:
        issues = accessible_material_issues(_read_request(request, ISSUE_PERMISSION)).filter(
            production_task_id=schedule.production_task_id, product_line_id__in=product_ids,
        ).select_related("workshop", "recipient_workshop_employee").annotate(detail_line_count=Count("lines", distinct=True)).order_by("-created_at", "-id")
        for issue in issues:
            result[product_ids[issue.product_line_id]]["material_issues"]["records"].append({
                "id": str(issue.pk), "issue_number": issue.issue_number,
                "workshop_name": issue.workshop.name if issue.workshop_id else "",
                "recipient_name": issue.recipient_workshop_employee.name if issue.recipient_workshop_employee_id else "",
                "line_count": issue.detail_line_count, "issue_at": issue.issue_at, "issued_at": issue.issued_at,
                "status": issue.status, "status_display": issue.get_status_display(),
            })
    return result
