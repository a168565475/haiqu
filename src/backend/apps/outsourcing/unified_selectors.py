"""委外统一列表：先按原权限合并分页，再批量读取当页摘要。"""

from apps.access_control.resource_scopes import can_order
from apps.material_issues.p4_access import scoped_records
from collections import defaultdict
from decimal import Decimal, localcontext

from django.conf import settings
from django.db.models import Case, CharField, Exists, F, OuterRef, Prefetch, Q, Value, When
from rest_framework import serializers

from apps.material_issues.models import (
    MetalProcessingExternalOrder, MetalProcessingOriginalHandoff,
)
from apps.material_issues.processing_selectors import processing_lines

from .models import (
    OutsourcingDispatch, OutsourcingDispatchLine, OutsourcingFactoryAllocation,
    OutsourcingOrder, OutsourcingOrderProduct, OutsourcingOrderStatus,
    OutsourcingProcessingItem, OutsourcingReturnLine,
    TubeOutsourcingAction, TubeOutsourcingLine, TubeOutsourcingMaterial, TubeOutsourcingOrder,
    TubeOutsourcingReceipt, TubeOutsourcingReceiptLine,
)
from .selectors import accessible_outsourcing_orders
from .tube_selectors import saved_orders_for_permission
from .tube_prices import planned_amount
from .warehouse_access import (
    DISPATCH_PERMISSION, RETURN_PERMISSION, RAW_RETURN_PERMISSION, REWORK_HANDOFF_PERMISSION, REWORK_RETURN_PERMISSION,
    warehouse_original_handoffs, warehouse_original_dispatch_orders,
    warehouse_regular_orders, warehouse_rework_orders, warehouse_tube_orders,
)


VIEW_PERMISSIONS = ("outsourcing.view_outsourcingorder", "material_issues.view_metalprocessingsource")
SOURCE_LABELS = {"RAW": "仓库原料", "METAL": "金工加工件", "REWORK": "重加工件", "UNSELECTED": "待选择",
                 "RAW_PIPE": "原材料", "PUBLIC_SEMI": "未喷塑半成品", "TUBE_METAL": "未入库半成品",
                 "PUBLIC_CUTTING": "已入库裁片半成品", "SEWING": "未入库车缝完成件"}
SOURCE_GROUP_LABELS = {"RAW": "原材料", "TUBE_PUBLIC": "未喷塑半成品", "TUBE_METAL": "未入库半成品",
                       "CUTTING_PUBLIC": "已入库裁片半成品", "SEWING": "未入库车缝完成件",
                       "OLD_METAL": "金工加工件（旧流程）", "REWORK": "重加工件（旧流程）", "UNSELECTED": "待选择（旧流程）"}
SOURCE_GROUP_KINDS = {"RAW": ("RAW", "RAW_PIPE"), "TUBE_PUBLIC": ("PUBLIC_SEMI",),
                      "CUTTING_PUBLIC": ("PUBLIC_CUTTING",), "SEWING": ("SEWING",),
                      "TUBE_METAL": ("TUBE_METAL",), "OLD_METAL": ("METAL",),
                      "REWORK": ("REWORK",), "UNSELECTED": ("UNSELECTED",)}
TUBE_STATUS_LABELS = {"PENDING_DISPATCH": "待外发", "PROCESSING": "加工中", "COMPLETED": "已结束", "CANCELLED": "已取消"}


class UnifiedOrderFilters(serializers.Serializer):
    warehouse_stage = serializers.ChoiceField(required=False, choices=['all'])
    search = serializers.CharField(required=False, allow_blank=True, max_length=200)
    status = serializers.ChoiceField(required=False, allow_blank=True,
                                     choices=[*OutsourcingOrderStatus.values, "PENDING_HANDOFF"])
    source_kind = serializers.ChoiceField(required=False, allow_blank=True, choices=list(SOURCE_LABELS))
    source_group = serializers.ChoiceField(required=False, allow_blank=True, choices=list(SOURCE_GROUP_LABELS))
    craft_id = serializers.UUIDField(required=False)
    factory_id = serializers.UUIDField(required=False)
    production_task_id = serializers.UUIDField(required=False)
    product_line_id = serializers.UUIDField(required=False)
    issue_id = serializers.UUIDField(required=False)


def _source_lines(request, filters):
    lines = processing_lines(request)
    for key in ("production_task_id", "product_line_id", "issue_id"):
        if filters.get(key):
            lines = lines.filter(**{key if key == "issue_id" else f"issue__{key}": filters[key]})
    return lines


def unified_order_sources(request, filters):
    """返回统一列表使用的三个授权查询，供列表和只读统计共用。"""
    warehouse = filters.get('warehouse_stage') == 'all'
    regular = warehouse or request.user.has_perm(VIEW_PERMISSIONS[0])
    metal = not warehouse and request.user.has_perm(VIEW_PERMISSIONS[1])
    visible_handoffs = MetalProcessingOriginalHandoff.objects.filter(
        source__issue_line__in=_source_lines(request, filters),
    ) if metal else MetalProcessingOriginalHandoff.objects.none()
    visible_handoffs = scoped_records(visible_handoffs, request, VIEW_PERMISSIONS[1], "original_order__craft_id")
    regular_orders = accessible_outsourcing_orders(request) if regular else OutsourcingOrder.objects.none()
    if warehouse:
        regular_orders = warehouse_regular_orders(request)
        visible_handoffs = warehouse_original_handoffs(request)
        for key in ('production_task_id', 'product_line_id', 'issue_id'):
            if filters.get(key):
                path = 'source__issue_line__issue_id' if key == 'issue_id' else f'source__issue_line__issue__{key}'
                visible_handoffs = visible_handoffs.filter(**{path: filters[key]})
    originals = OutsourcingOrder.objects.filter(
        Q(pk__in=regular_orders.values("pk")) | Q(pk__in=visible_handoffs.values("original_order_id")),
    ).annotate(unified_access=Case(
        When(Exists(regular_orders.filter(pk=OuterRef("pk"))), then=Value("REGULAR")),
        default=Value("METAL"), output_field=CharField(),
    ))
    originals = originals.annotate(
        unified_source=Case(
            When(Exists(OutsourcingDispatch.objects.filter(order_id=OuterRef("pk"))), then=Value("RAW")),
            When(Exists(MetalProcessingOriginalHandoff.objects.filter(original_order_id=OuterRef("pk"))),
                 then=Value("METAL")),
            default=Value("UNSELECTED"), output_field=CharField(),
        ), record_type=Value("ORIGINAL", output_field=CharField()),
    )
    reworks = MetalProcessingExternalOrder.objects.filter(
        source__issue_line__in=_source_lines(request, filters),
    ) if metal else MetalProcessingExternalOrder.objects.none()
    reworks = scoped_records(reworks, request, VIEW_PERMISSIONS[1])
    if warehouse:
        reworks = warehouse_rework_orders(request)
        for key in ('production_task_id', 'product_line_id', 'issue_id'):
            if filters.get(key):
                path = 'source__issue_line__issue_id' if key == 'issue_id' else f'source__issue_line__issue__{key}'
                reworks = reworks.filter(**{path: filters[key]})
    reworks = reworks.annotate(record_type=Value("REWORK", output_field=CharField()),
                               unified_source=Value("REWORK", output_field=CharField()),
                               unified_access=Value("METAL", output_field=CharField()))
    tubes = _tube_candidates(request, filters) if regular and getattr(settings, "TUBE_OUTSOURCING_ENABLED", False) else TubeOutsourcingOrder.objects.none().annotate(
        record_type=Value("TUBE", output_field=CharField()), unified_source=Value("", output_field=CharField()),
        unified_access=Value("TUBE", output_field=CharField()))
    for key in ("status", "craft_id"):
        if filters.get(key):
            originals = originals.filter(**{key: filters[key]})
            reworks = reworks.filter(**{key: filters[key]})
    if filters.get("source_kind"):
        originals = originals.filter(unified_source=filters["source_kind"])
        reworks = reworks.filter(unified_source=filters["source_kind"])
    if filters.get("source_group"):
        kinds = SOURCE_GROUP_KINDS[filters["source_group"]]
        originals = originals.filter(unified_source__in=kinds)
        reworks = reworks.filter(unified_source__in=kinds)
    if filters.get("factory_id"):
        factory_id = filters["factory_id"]
        originals = originals.filter(
            Q(unified_access="REGULAR", products__processing_items__allocations__factory_id=factory_id)
            | Q(unified_access="METAL", pk__in=visible_handoffs.filter(factory_id=factory_id).values("original_order_id")),
        )
        reworks = reworks.filter(factory_id=factory_id)
    if regular:
        if filters.get("production_task_id"):
            originals = originals.filter(Q(unified_access="METAL") | Q(schedule__production_task_id=filters["production_task_id"]))
        if filters.get("product_line_id"):
            originals = originals.filter(Q(unified_access="METAL") | Q(products__schedule_product__product_line_id=filters["product_line_id"]))
        if filters.get("issue_id"):
            originals = originals.filter(Q(unified_access="METAL") | Q(metal_processing_original_handoffs__source__issue_line__issue_id=filters["issue_id"]))
    keyword = filters.get("search", "")
    if keyword:
        original_search = Q(order_number__icontains=keyword)
        if regular:
            regular_search = Q(schedule__schedule_number__icontains=keyword) | Q(schedule__production_task__task_number__icontains=keyword)
            for field in ("product_name", "product_number", "product_code", "item_number"):
                regular_search |= Q(**{f"products__product_snapshot__{field}__icontains": keyword})
            original_search |= Q(unified_access="REGULAR") & regular_search
        originals = originals.filter(original_search)
        reworks = reworks.filter(Q(order_number__icontains=keyword)
                                | Q(source__issue_line__issue__production_task__task_number__icontains=keyword))
    return originals, reworks, tubes


def unified_order_candidates(request, filters):
    """UNION 只选择排序和定位列；三个渠道统一计数、排序和分页。"""
    originals, reworks, tubes = unified_order_sources(request, filters)
    fields = ("id", "updated_at", "record_type", "unified_source", "unified_access")
    return originals.order_by().values(*fields).distinct().union(
        reworks.order_by().values(*fields), tubes.order_by().values(*fields).distinct(), all=True,
    ).order_by("-updated_at", "-id", "record_type")


def _tube_candidates(request, filters):
    queryset = warehouse_tube_orders(request) if filters.get('warehouse_stage') == 'all' else saved_orders_for_permission(request)
    tubes = queryset.annotate(
        record_type=Value("TUBE", output_field=CharField()),
        unified_access=Value("TUBE", output_field=CharField()),
        unified_source=Case(When(source_kind="METAL", then=Value("TUBE_METAL")),
                            default=F("source_kind"), output_field=CharField()),
    )
    for key in ("status", "craft_id", "product_line_id"):
        if filters.get(key):
            tubes = tubes.filter(**{key: filters[key]})
    if filters.get("production_task_id"):
        tubes = tubes.filter(schedule_product__schedule__production_task_id=filters["production_task_id"])
    if filters.get("issue_id"):
        # 新管材单不归属旧领料来源；不能按产品扩大旧来源筛选。
        tubes = tubes.none()
    if filters.get("source_kind"):
        tubes = tubes.filter(unified_source=filters["source_kind"])
    if filters.get("source_group"):
        tubes = tubes.filter(unified_source__in=SOURCE_GROUP_KINDS[filters["source_group"]])
    if filters.get("factory_id"):
        tubes = tubes.filter(Q(lines__factory_id=filters["factory_id"])
                             | Q(materials__factory_id=filters["factory_id"])).distinct()
    keyword = filters.get("search", "")
    if keyword:
        search = (Q(order_number__icontains=keyword)
                  | Q(schedule_product__schedule__schedule_number__icontains=keyword)
                  | Q(schedule_product__schedule__production_task__task_number__icontains=keyword))
        for field in ("product_name", "product_number", "item_number", "color_name"):
            search |= Q(**{f"schedule_product__product_snapshot__{field}__icontains": keyword})
        tubes = tubes.filter(search)
    return tubes


def _decimal(value):
    return format(Decimal(value).normalize(), "f")


def _quantities(group):
    return [{"quantity": _decimal(quantity), "unit": unit} for unit, quantity in sorted(group.items())]


def _base_row(order, record_type, source_kind, detail_access):
    return {
        "id": str(order.pk), "row_key": f"{record_type}:{order.pk}", "record_type": record_type,
        "source_kind": source_kind, "source_label": SOURCE_LABELS[source_kind], "detail_access": detail_access,
        "source_group": next(group for group, kinds in SOURCE_GROUP_KINDS.items() if source_kind in kinds),
        "source_issue_line_id": None, "order_number": order.order_number,
        "schedule_id": "", "schedule_number": "", "production_task_number": "", "craft": {"id": "", "name": ""},
        "delivery_date": None, "status": order.status,
        "status_display": TUBE_STATUS_LABELS.get(order.status, order.status) if record_type == "TUBE" else order.get_status_display(),
        "product": {}, "product_count": 0, "processing_count": 0, "returned_processing_count": None,
        "factory_names": [], "factory_count": 0, "planned_amount": None,
        "factory_allocated_quantity": None, "factory_allocated_unit": None, "factory_allocation_count": None,
        "factory_returned_quantity": None, "factory_remaining_quantity": None,
        "direct_handoff": source_kind == "METAL", "direct_handoff_lock_reason": "",
        "can_delete": False, "can_revoke_dispatched": False,
        "dispatched_quantities": [], "returned_quantities": [], "updated_at": order.updated_at,
    }


def _regular_context(ids):
    allocations = OutsourcingFactoryAllocation.objects.select_related("factory").order_by("factory__name", "id")
    items = OutsourcingProcessingItem.objects.prefetch_related(Prefetch("allocations", queryset=allocations, to_attr="list_allocations"))
    products = OutsourcingOrderProduct.objects.select_related("schedule_product__product_line").prefetch_related(Prefetch("processing_items", queryset=items, to_attr="list_items")).order_by("line_number", "id")
    return OutsourcingOrder.objects.filter(pk__in=ids).select_related("schedule__production_task").prefetch_related(
        Prefetch("products", queryset=products, to_attr="list_products"),
    )


def _regular_rows(request, candidates, filters):
    from .reconciliation_services import order_action_candidates

    source_kinds = {row["id"]: row["unified_source"] for row in candidates}
    orders = list(_regular_context(source_kinds))
    actions = order_action_candidates(orders)
    rows = {}
    factory_id = str(filters.get("factory_id", ""))
    for order in orders:
        row = _base_row(order, "ORIGINAL", source_kinds[order.pk], "REGULAR")
        products, entries = [], []
        for product in order.list_products:
            matching = []
            for item in product.list_items:
                matching.extend((item, allocation) for allocation in item.list_allocations
                                if not factory_id or str(allocation.factory_id) == factory_id)
            if matching:
                products.append(product)
                entries.extend(matching)
        factories = {str(allocation.factory_id): allocation.factory_snapshot.get("name") or allocation.factory.name
                     for _item, allocation in entries}
        product = dict(products[0].product_snapshot) if products else {}
        if products:
            # 旧快照缺少产品材质时只补展示，不修改已保存的快照。
            product.setdefault("material", products[0].schedule_product.product_line.material_snapshot)
        row.update(
            schedule_id=str(order.schedule_id), schedule_number=order.schedule.schedule_number,
            production_task_number=order.schedule.production_task.task_number,
            craft={"id": str(order.craft_id), "name": order.craft_name_snapshot}, delivery_date=order.delivery_date,
            product=product, product_count=len(products),
            processing_count=len({item.pk for item, _allocation in entries}),
            factory_names=list(factories.values()), factory_count=len(factories),
            planned_amount=f"{sum((allocation.allocated_quantity * allocation.unit_price for _item, allocation in entries), Decimal(0)):.2f}",
            can_delete=bool(source_kinds[order.pk] != "METAL" and order.pk in actions["delete"]
                            and can_order(request, "outsourcing.delete_outsourcingorder", order)),
            can_revoke_dispatched=bool(source_kinds[order.pk] != "METAL" and order.pk in actions["revoke_dispatched"]
                                       and can_order(request, "outsourcing.cancel_outsourcingorder", order)
                                       and can_order(request, "outsourcing.return_raw_outsourcingorder", order)),
        )
        if factory_id:
            row["factory_allocation_count"] = len(entries)
            if len(entries) == 1:
                item, allocation = entries[0]
                row.update(factory_allocated_quantity=_decimal(allocation.allocated_quantity), factory_allocated_unit=item.unit_snapshot)
        rows[order.pk] = row
    return rows


def _original_quantities(rows, request, filters, regular):
    """来源受限投影只读取可见来源的交接和可归属回货，不借整单汇总跨范围数量。"""
    if not rows:
        return
    dispatch_totals, return_totals = defaultdict(lambda: defaultdict(Decimal)), defaultdict(lambda: defaultdict(Decimal))
    handoffs = MetalProcessingOriginalHandoff.objects.filter(original_order_id__in=rows)
    if not regular:
        if filters.get('warehouse_stage') == 'all':
            handoffs = handoffs.filter(pk__in=warehouse_original_handoffs(request).values('pk'))
        else:
            handoffs = handoffs.filter(source__issue_line__in=_source_lines(request, filters))
    if filters.get("factory_id"):
        handoffs = handoffs.filter(factory_id=filters["factory_id"])
    handoffs = list(handoffs.select_related("source", "factory").order_by("created_at", "id"))
    visible_source_ids = set()
    factories, source_ids = defaultdict(dict), defaultdict(set)
    for handoff in handoffs:
        order_id = handoff.original_order_id
        dispatch_totals[order_id]["支"] += handoff.handoff_pieces
        visible_source_ids.add(str(handoff.source_id))
        source_ids[order_id].add(handoff.source_id)
        factories[order_id][handoff.factory_id] = handoff.factory.name
        if rows[order_id]["source_issue_line_id"] is None:
            rows[order_id]["source_issue_line_id"] = str(handoff.source.issue_line_id)
    if regular:
        dispatches = OutsourcingDispatchLine.objects.filter(dispatch__order_id__in=rows).select_related("dispatch", "unit")
        if filters.get("factory_id"):
            dispatches = dispatches.filter(material_item__allocation__factory_id=filters["factory_id"])
        for line in dispatches:
            # 管材显示加工支数；其他材料显示外发实物量，不能用采购换算扣库量冒充。
            if line.issued_piece_count is not None:
                quantity, unit = line.issued_piece_count, "支"
            else:
                quantity = line.material_quantity if line.material_quantity is not None else line.issued_quantity
                unit = line.unit.unit_name
            dispatch_totals[line.dispatch.order_id][unit] += quantity
    returned = OutsourcingReturnLine.objects.filter(return_record__order_id__in=rows, quality="AVAILABLE")
    if filters.get("factory_id"):
        returned = returned.filter(allocation__factory_id=filters["factory_id"])
    if not regular:
        returned = returned.filter(snapshot__source_id__in=visible_source_ids)
    for line in returned.values("return_record__order_id", "returned_quantity", "allocation__processing_item__unit_snapshot"):
        order_id = line["return_record__order_id"]
        unit = "支" if rows[order_id]["source_kind"] == "METAL" else line["allocation__processing_item__unit_snapshot"]
        return_totals[order_id][unit] += line["returned_quantity"]
    for order_id, row in rows.items():
        row.update(dispatched_quantities=_quantities(dispatch_totals[order_id]), returned_quantities=_quantities(return_totals[order_id]))
        if not regular:
            row.update(factory_names=list(factories[order_id].values()), factory_count=len(factories[order_id]),
                       processing_count=len(source_ids[order_id]))


def _tube_rows(candidates, filters):
    """当页冻结摘要；查询次数不随单数变化，不读取当前BOM、报工或来源额度。"""
    if not candidates:
        return {}
    sources = {row["id"]: row["unified_source"] for row in candidates}
    orders = TubeOutsourcingOrder.objects.filter(pk__in=sources).select_related(
        "schedule_product__schedule__production_task", "product_line", "craft",
    ).prefetch_related(
        Prefetch("lines", queryset=TubeOutsourcingLine.objects.order_by("created_at", "id"), to_attr="list_lines"),
        Prefetch("materials", queryset=TubeOutsourcingMaterial.objects.order_by("created_at", "id"), to_attr="list_materials"),
        Prefetch("actions", queryset=TubeOutsourcingAction.objects.all(), to_attr="list_actions"),
    )
    receipts = {receipt.order_id: receipt for receipt in TubeOutsourcingReceipt.objects.filter(order_id__in=sources)
        .prefetch_related(Prefetch("lines", queryset=TubeOutsourcingReceiptLine.objects.all(), to_attr="list_lines"))}
    factory_id, rows = str(filters.get("factory_id", "")), {}
    for order in orders:
        row = _base_row(order, "TUBE", sources[order.pk], "TUBE")
        from .tube_kinds import output_unit
        unit = output_unit(order.source_kind)
        lines = [line for line in order.list_lines if not factory_id or str(line.factory_id) == factory_id]
        materials = [material for material in order.list_materials
                     if not factory_id or str(material.factory_id) == factory_id]
        factories = {}
        for line in [*lines, *materials]:
            snapshot = line.snapshot if isinstance(line.snapshot, dict) else {}
            factories[str(line.factory_id)] = snapshot.get("factory_name", "")
        product = order.schedule_product.product_snapshot
        product = product if isinstance(product, dict) else {}
        row.update(
            schedule_id=str(order.schedule_product.schedule_id),
            schedule_number=order.schedule_product.schedule.schedule_number,
            production_task_number=order.schedule_product.schedule.production_task.task_number,
            product={**{field: product.get(field, "") for field in ("product_name", "product_number", "item_number", "color_name")},
                     "material": product.get("material", order.product_line.material_snapshot)},
            product_count=1, craft={"id": str(order.craft_id), "name": order.craft.name},
            delivery_date=order.expected_return_date, processing_count=len(lines),
            factory_names=sorted(factories.values()), factory_count=len(factories),
            planned_amount=planned_amount(lines),
            receipt_state="MISSING" if order.status == "COMPLETED" else "NOT_RECEIVED", shortage_quantities=[],
        )
        if factory_id:
            row["factory_allocation_count"] = len(lines) + len(materials)
        actions = {action.kind: action for action in order.list_actions}
        dispatch = actions.get("DISPATCH")
        # 状态或保存数量不能单独证明实发；先核对整单动作，再按厂投影冻结明细。
        valid_dispatch = (bool(order.list_lines) and dispatch is not None and "CANCEL" not in actions
                          and isinstance(dispatch.snapshot, dict)
                          and dispatch.snapshot.get("quantity") == sum(line.quantity for line in order.list_lines))
        if valid_dispatch:
            quantities = defaultdict(Decimal)
            if lines:
                quantities[unit] += sum(line.quantity for line in lines)
            for material in materials:
                quantities[material.snapshot.get('unit', '')] += material.quantity
            row["dispatched_quantities"] = _quantities(quantities)
        receipt = receipts.get(order.pk)
        if receipt is not None:
            receipt_lines = {line.order_line_id: line for line in receipt.list_lines}
            valid_receipt = (valid_dispatch and order.status == "COMPLETED"
                and len(receipt_lines) == len(order.list_lines)
                and all(line.pk in receipt_lines
                    and receipt_lines[line.pk].dispatched_quantity == line.quantity
                    and 0 <= receipt_lines[line.pk].received_quantity <= line.quantity
                    and receipt_lines[line.pk].shortage_quantity == line.quantity - receipt_lines[line.pk].received_quantity
                    for line in order.list_lines))
            row["receipt_state"] = "RECORDED" if valid_receipt else "MISSING"
            if valid_receipt:
                received = sum(receipt_lines[line.pk].received_quantity for line in lines)
                shortage = sum(receipt_lines[line.pk].shortage_quantity for line in lines)
                row.update(returned_quantities=[{"quantity": str(received), "unit": unit}] if lines else [],
                           shortage_quantities=[{"quantity": str(shortage), "unit": unit}] if lines else [])
                if factory_id:
                    row["factory_returned_quantity"] = str(received)
        rows[row["row_key"]] = row
    return rows


def unified_order_rows(request, candidates, filters):
    originals = [row for row in candidates if row["record_type"] == "ORIGINAL"]
    regular_candidates = [row for row in originals if row["unified_access"] == "REGULAR"]
    original_rows = _regular_rows(request, regular_candidates, filters) if regular_candidates else {}
    projected_rows = {order.pk: _base_row(order, "ORIGINAL", "METAL", "METAL") for order in OutsourcingOrder.objects.filter(
        pk__in=[row["id"] for row in originals if row["unified_access"] == "METAL"],
    )}
    _original_quantities(original_rows, request, filters, True)
    _original_quantities(projected_rows, request, filters, False)
    original_rows.update(projected_rows)
    all_rows = {f"ORIGINAL:{key}": row for key, row in original_rows.items()}
    reworks = MetalProcessingExternalOrder.objects.filter(
        pk__in=[row["id"] for row in candidates if row["record_type"] == "REWORK"],
    ).select_related("source__issue_line__issue__production_task", "factory", "craft")
    for order in reworks:
        row = _base_row(order, "REWORK", "REWORK", "METAL")
        with localcontext() as context:
            context.prec = 40
            amount = format(Decimal(order.allocated_pieces) * order.unit_price, '.2f') if order.unit_price is not None else None
        row.update(
            source_issue_line_id=str(order.source.issue_line_id),
            production_task_number=order.source.issue_line.issue.production_task.task_number,
            craft={"id": str(order.craft_id), "name": order.craft.name}, processing_count=1,
            factory_names=[order.factory.name], factory_count=1,
            planned_amount=amount,
            dispatched_quantities=[{"quantity": str(order.handoff_pieces), "unit": "支"}],
            returned_quantities=[{"quantity": str(order.returned_good_pieces), "unit": "支"}],
            factory_allocated_quantity=str(order.allocated_pieces), factory_allocated_unit="支",
            factory_allocation_count=1, factory_returned_quantity=order.returned_good_pieces,
            factory_remaining_quantity=order.handoff_pieces - order.returned_good_pieces,
        )
        all_rows[row["row_key"]] = row
    all_rows.update(_tube_rows([row for row in candidates if row["record_type"] == "TUBE"], filters))
    if filters.get('warehouse_stage') == 'all':
        _warehouse_actions(request, all_rows)
    return [all_rows[f"{row['record_type']}:{row['id']}"] for row in candidates]


def _warehouse_actions(request, rows):
    """按钮同时满足动作的数据范围和当前状态；写接口仍复核库存及并发。"""
    original_ids = [row['id'] for row in rows.values() if row['record_type'] == 'ORIGINAL']
    tube_ids = [row['id'] for row in rows.values() if row['record_type'] == 'TUBE']
    allowed = {}
    for action, permission, statuses in (
        ('dispatch', DISPATCH_PERMISSION, ['PENDING_DISPATCH']),
        ('return', RETURN_PERMISSION, ['PROCESSING', 'PARTIAL_RETURN']),
        ('raw', RAW_RETURN_PERMISSION, ['PROCESSING', 'PARTIAL_RETURN']),
    ):
        allowed[('ORIGINAL', action)] = set(map(str, warehouse_regular_orders(request, permission).filter(
            pk__in=original_ids, status__in=statuses).values_list('pk', flat=True)))
    allowed[('TUBE', 'dispatch')] = set(map(str, warehouse_tube_orders(request, DISPATCH_PERMISSION).filter(
        pk__in=tube_ids, status='PENDING_DISPATCH').values_list('pk', flat=True)))
    receivable = warehouse_tube_orders(request, RETURN_PERMISSION).filter(pk__in=tube_ids, status='PROCESSING').filter(
        Exists(TubeOutsourcingAction.objects.filter(order_id=OuterRef('pk'), kind='DISPATCH')),
        ~Exists(TubeOutsourcingAction.objects.filter(order_id=OuterRef('pk'), kind='CANCEL')),
        ~Exists(TubeOutsourcingReceipt.objects.filter(order_id=OuterRef('pk'))),
    )
    allowed[('TUBE', 'return')] = set(map(str, receivable.values_list('pk', flat=True)))
    rework_ids = [row['id'] for row in rows.values() if row['record_type'] == 'REWORK']
    allowed[('REWORK', 'dispatch')] = set(map(str, warehouse_rework_orders(request, REWORK_HANDOFF_PERMISSION).filter(
        pk__in=rework_ids, status='PENDING_HANDOFF').values_list('pk', flat=True)))
    allowed[('REWORK', 'return')] = set(map(str, warehouse_rework_orders(request, REWORK_RETURN_PERMISSION).filter(
        pk__in=rework_ids, status__in=['PROCESSING', 'CLOSED'], handoff_pieces__gt=F('returned_good_pieces'),
    ).values_list('pk', flat=True)))
    from apps.material_issues.p4_services import original_good_return_context
    from apps.material_issues.original_order_services import original_order_context
    for order in warehouse_original_dispatch_orders(request).filter(pk__in=original_ids).select_related('schedule', 'craft'):
        if original_order_context(order, request)['can_handoff']:
            allowed[('ORIGINAL', 'dispatch')].add(str(order.pk))
    for handoff in warehouse_original_handoffs(request).filter(original_order_id__in=original_ids).select_related('original_order', 'source', 'factory'):
        if original_good_return_context(handoff, request)['can_return']:
            allowed[('ORIGINAL', 'return')].add(str(handoff.original_order_id))
    for row in rows.values():
        row['warehouse_actions'] = [action for action in ('dispatch', 'return', 'raw')
            if row['id'] in allowed.get((row['record_type'], action), set())
            and not (row['record_type'] == 'TUBE' and action == 'return' and row.get('receipt_state') == 'MISSING')]
