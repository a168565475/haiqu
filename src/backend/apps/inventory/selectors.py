from decimal import Decimal, ROUND_FLOOR
from types import SimpleNamespace

from django.contrib.postgres.aggregates import ArrayAgg
from django.db.models import Count, Exists, F, Max, OuterRef, Prefetch, Q, Sum, Value, Subquery
from django.db.models.functions import Coalesce

from apps.procurement.models import (
    PurchaseOrder,
    PurchaseOrderLine,
    PurchaseOrderStatus,
    PurchaseReturnLine,
    PurchaseReturnStatus,
)
from apps.production_tasks.models import ProductionTaskProduct, ProductionTaskStatus
from apps.boms.models import Bom
from apps.sales_orders.presentation import specification_display
from apps.samples.models import SampleItem

from .models import (
    FinishedGoodsOutbound,
    FinishedGoodsOutboundLine,
    FinishedGoodsReceipt,
    MaterialInbound,
    MaterialInboundLine,
    MaterialInboundStatus,
    MaterialStockBalance,
    MaterialStockMovement,
    MaterialStockDirection,
    MaterialStockQuality,
    Warehouse,
    WarehouseLocation,
    WarehouseZone,
)


def finished_goods_outbounds(*, keyword="", warehouse_id=None, production_task_id=None, product_line_id=None):
    lines = FinishedGoodsOutboundLine.objects.select_related(
        "receipt__unit", "receipt__production_task_product", "receipt__location__zone__warehouse",
    )
    queryset = FinishedGoodsOutbound.objects.select_related(
        "outbound_by_employee", "responsible_employee",
    ).prefetch_related(Prefetch("lines", queryset=lines), "attachments__business_file")
    if keyword or warehouse_id or production_task_id or product_line_id:
        # 所有条件必须命中同一条出库明细；命中后仍返回整张单据的全部明细。
        matching_lines = FinishedGoodsOutboundLine.objects.filter(outbound_id=OuterRef("pk"))
        if keyword:
            matching_lines = matching_lines.filter(
                Q(outbound__outbound_number__icontains=keyword)
                | Q(receipt__task_number_snapshot__icontains=keyword)
                | Q(receipt__product_code_snapshot__icontains=keyword)
                | Q(receipt__product_name_snapshot__icontains=keyword)
                | Q(receipt__item_number_snapshot__icontains=keyword)
                | Q(receipt__specification_snapshot__icontains=keyword)
                | Q(receipt__actual_color__icontains=keyword)
            )
        if warehouse_id:
            matching_lines = matching_lines.filter(receipt__location__zone__warehouse_id=warehouse_id)
        if production_task_id:
            matching_lines = matching_lines.filter(receipt__production_task_product__production_task_id=production_task_id)
        if product_line_id:
            matching_lines = matching_lines.filter(receipt__production_task_product_id=product_line_id)
        queryset = queryset.filter(Exists(matching_lines))
    return queryset


def warehouses_with_usage(queryset=None):
    if queryset is None:
        queryset = Warehouse.objects.all()
    return queryset.annotate(
        zone_count=Count("zones", distinct=True),
        location_count=Count("zones__locations", distinct=True),
        capacity_box_slots_total=Sum("zones__locations__capacity_box_slots"),
        occupied_box_slots=Coalesce(
            Sum(
                "zones__locations__finished_goods_receipts__remaining_box_slots",
                filter=Q(zones__locations__finished_goods_receipts__remaining_quantity__gt=0),
            ),
            Value(0),
        ),
    )


def zones_with_usage(queryset=None):
    if queryset is None:
        queryset = WarehouseZone.objects.all()
    return queryset.select_related("warehouse").annotate(
        location_count=Count("locations", distinct=True),
        capacity_box_slots_total=Sum("locations__capacity_box_slots"),
        occupied_box_slots=Coalesce(
            Sum(
                "locations__finished_goods_receipts__remaining_box_slots",
                filter=Q(locations__finished_goods_receipts__remaining_quantity__gt=0),
            ),
            Value(0),
        ),
    )


def locations_with_usage(queryset=None):
    if queryset is None:
        queryset = WarehouseLocation.objects.all()
    return queryset.select_related("zone", "zone__warehouse").annotate(
        occupied_box_slots=Coalesce(
            Sum(
                "finished_goods_receipts__remaining_box_slots",
                filter=Q(finished_goods_receipts__remaining_quantity__gt=0),
            ),
            Value(0),
        )
    )


def finished_goods_inventory_rows(*, keyword="", warehouse_id="", zone_id="", category="", production_task_id="", exclude_sample=False):
    queryset = FinishedGoodsReceipt.objects.filter(remaining_quantity__gt=0)
    if exclude_sample:
        queryset = queryset.exclude(source_type="SAMPLE_INVENTORY")
    if production_task_id:
        queryset = queryset.filter(production_task_product__production_task_id=production_task_id)
    if keyword:
        queryset = queryset.filter(
            Q(product_number_snapshot__icontains=keyword)
            | Q(product_code_snapshot__icontains=keyword)
            | Q(product_name_snapshot__icontains=keyword)
            | Q(task_number_snapshot__icontains=keyword)
            | Q(product_name_pinyin_search__icontains=keyword)
            | Q(item_number_snapshot__icontains=keyword)
            | Q(actual_color__icontains=keyword)
            | Q(specification_snapshot__icontains=keyword)
        )
    if warehouse_id:
        queryset = queryset.filter(location__zone__warehouse_id=warehouse_id)
    if zone_id:
        queryset = queryset.filter(location__zone_id=zone_id)
    if category:
        queryset = queryset.filter(category_snapshot=category)
    return (
        queryset.values(
            "production_task_product__product_id",
            "task_number_snapshot",
            "category_snapshot",
            "product_number_snapshot",
            "product_code_snapshot",
            "product_name_snapshot",
            "item_number_snapshot",
            "specification_snapshot",
            "actual_color",
            "unit_id",
            "unit__unit_code",
            "unit__unit_name",
            "location__zone__warehouse_id",
            "location__zone__warehouse__warehouse_number",
            "location__zone__warehouse__warehouse_name",
            "location__zone_id",
            "location__zone__zone_name",
        )
        .annotate(
            inventory_quantity=Sum("remaining_quantity"),
            batch_count=Count("id"),
            occupied_box_slots=Sum("remaining_box_slots"),
            latest_inbound_time=Max("received_at"),
            receipt_ids=ArrayAgg("id", distinct=True),
        )
        .order_by("-latest_inbound_time", "product_number_snapshot", "product_name_snapshot")
    )


def material_inventory_rows(
    *, keyword="", section_title="", warehouse_id="", zone_id="", location_id="",
):
    queryset = MaterialStockBalance.objects.filter(quality=MaterialStockQuality.AVAILABLE)
    inbound_movements = MaterialStockMovement.objects.filter(
        balance_id=OuterRef('pk'), direction=MaterialStockDirection.IN,
    ).order_by().values('balance_id').annotate(total=Count('source_id', distinct=True), latest=Max('occurred_at'))
    if keyword:
        matching_inbound = MaterialInboundLine.objects.filter(
            raw_material_information_id=OuterRef("raw_material_id"),
            inbound__status=MaterialInboundStatus.CONFIRMED,
            material_pinyin_search__icontains=keyword,
        )
        queryset = queryset.annotate(has_matching_inbound=Exists(matching_inbound)).filter(
            Q(raw_material__material_number__icontains=keyword)
            | Q(raw_material__category__category_name__icontains=keyword)
            | Q(raw_material__material_name__icontains=keyword)
            | Q(raw_material__specification__icontains=keyword)
            | Q(raw_material__material__icontains=keyword)
            | Q(has_matching_inbound=True)
        )
    if section_title:
        matching_section = MaterialInboundLine.objects.filter(
            raw_material_information_id=OuterRef("raw_material_id"),
            inbound__status=MaterialInboundStatus.CONFIRMED,
            section_title_snapshot=section_title,
        )
        queryset = queryset.annotate(has_matching_section=Exists(matching_section)).filter(has_matching_section=True)
    if warehouse_id:
        queryset = queryset.filter(zone__warehouse_id=warehouse_id)
    if zone_id:
        queryset = queryset.filter(zone_id=zone_id)
    if location_id:
        # 净余额当前按库区记账，不能把库位历史入库量冒充成库位净库存。
        queryset = queryset.none()
    return (
        queryset.values(
            'measurement_kind', 'raw_bar_length_m',
            "raw_material_id",
            "raw_material__item_type",
            "raw_material__category__category_name",
            "raw_material__material_number",
            "raw_material__material_name",
            "raw_material__specification",
            "raw_material__material",
            "raw_material__color__color_name",
            "raw_material__color_snapshot",
            "unit__unit_name",
            "zone_id",
            "zone__zone_name",
            "zone__warehouse_id",
            "zone__warehouse__warehouse_number",
            "zone__warehouse__warehouse_name",
        )
        .annotate(
            # 先按余额行计算流水统计，再聚合批次数量，避免流水联表将余额重复累加。
            inventory_quantity=Sum('quantity'),
            meter_quantity=Sum('meter_quantity'),
            inbound_count=Sum(Coalesce(Subquery(inbound_movements.values('total')[:1]), 0)),
            latest_inbound_time=Max(Subquery(inbound_movements.values('latest')[:1])),
        )
        .order_by("-latest_inbound_time", "raw_material__category__category_name", "raw_material__material_number")
    )


def material_received_totals(line_ids=None):
    queryset = MaterialInboundLine.objects.filter(purchase_order_line__isnull=False)
    if line_ids is not None:
        queryset = queryset.filter(purchase_order_line_id__in=line_ids)
    totals = {}
    confirmed = (
        queryset.filter(inbound__status=MaterialInboundStatus.CONFIRMED)
        .values_list("purchase_order_line_id")
        .annotate(total=Sum("accepted_quantity"))
    )
    pending = (
        queryset.filter(inbound__status=MaterialInboundStatus.PENDING_QUALITY)
        .values_list("purchase_order_line_id")
        .annotate(total=Sum("received_quantity"))
    )
    for line_id, total in [*confirmed, *pending]:
        totals[line_id] = totals.get(line_id, Decimal("0")) + Decimal(total or 0)
    return totals


def eligible_material_purchase_orders(queryset=None, *, include_open_returns=False, read_optimized=False):
    if queryset is None:
        queryset = PurchaseOrder.objects.all()
    returns_for_order = PurchaseReturnLine.objects.filter(
        inbound_line__purchase_order_line__purchase_order_id=OuterRef("pk"),
    )
    queryset = queryset.annotate(
            has_completed_material_return=Exists(
                returns_for_order.filter(return_order__status=PurchaseReturnStatus.COMPLETED)
            ),
            has_open_material_return=Exists(
                returns_for_order.exclude(return_order__status=PurchaseReturnStatus.COMPLETED)
            ),
        )
    purchasing_filter = Q(status=PurchaseOrderStatus.PURCHASING)
    if not include_open_returns:
        purchasing_filter &= Q(has_open_material_return=False)
    result = (
        queryset.filter(
            purchasing_filter
            | Q(
                status=PurchaseOrderStatus.COMPLETED,
                has_completed_material_return=True,
                has_open_material_return=False,
            ),
            archived_at__isnull=True,
        )
        .order_by("-created_at", "-id")
    )
    if read_optimized:
        return result.prefetch_related("lines")
    return result.select_related("production_task").prefetch_related("lines__supplier")


def eligible_material_lines(purchase_order_id, *, read_optimized=False):
    returns_for_line = PurchaseReturnLine.objects.filter(
        inbound_line__purchase_order_line_id=OuterRef("pk"),
    )
    open_returns_for_order = PurchaseReturnLine.objects.filter(
        inbound_line__purchase_order_line__purchase_order_id=OuterRef("purchase_order_id"),
    ).exclude(return_order__status=PurchaseReturnStatus.COMPLETED)
    queryset = (
        PurchaseOrderLine.objects.annotate(
            has_completed_material_return=Exists(
                returns_for_line.filter(return_order__status=PurchaseReturnStatus.COMPLETED)
            ),
            has_open_material_return=Exists(
                open_returns_for_order
            ),
        ).filter(
            Q(
                purchase_order__status=PurchaseOrderStatus.PURCHASING,
                has_open_material_return=False,
            )
            | Q(
                purchase_order__status=PurchaseOrderStatus.COMPLETED,
                has_completed_material_return=True,
                has_open_material_return=False,
            ),
            purchase_order_id=purchase_order_id,
            purchase_order__archived_at__isnull=True,
            actual_purchase_quantity__isnull=False,
        )
        .order_by("line_number", "id")
    )
    if not read_optimized:
        queryset = queryset.select_related("purchase_order", "purchase_order__production_task", "supplier")
    lines = list(queryset)
    totals = material_received_totals([line.pk for line in lines])
    return [
        (line, Decimal(line.actual_purchase_quantity) - Decimal(totals.get(line.pk, 0)))
        for line in lines
        if Decimal(line.actual_purchase_quantity) - Decimal(totals.get(line.pk, 0)) > 0
    ]


def procurement_inbound_supplier_summaries(lines):
    """按供应商汇总本单采购金额；未核价的明细不冒充零金额。"""
    grouped = {}
    for line in lines:
        if not line.supplier_id and not line.supplier_name_snapshot:
            continue
        key = line.supplier_id or line.supplier_name_snapshot
        grouped.setdefault(key, []).append(line)
    summaries = []
    for supplier_lines in sorted(grouped.values(), key=lambda rows: rows[0].supplier_number_snapshot):
        first = supplier_lines[0]
        amount = None if any(line.amount is None for line in supplier_lines) else sum(
            (line.amount for line in supplier_lines), Decimal("0")
        )
        summaries.append({
            "supplier_id": str(first.supplier_id) if first.supplier_id else None,
            "supplier_name": first.supplier_name_snapshot,
            "total_amount": format(amount, ".4f") if amount is not None else None,
        })
    return summaries


def procurement_inbound_product_summaries(orders):
    """按采购行保留产品顺序；打样材料无逐产品绑定，展示来源打样明细。"""
    lines_by_order = {
        order.pk: sorted(
            (line for line in order.lines.all() if line.actual_purchase_quantity is not None),
            key=lambda line: (line.line_number, str(line.pk)),
        )
        for order in orders
    }
    production_lines = [
        line for order in orders if order.source_type == "PRODUCTION"
        for line in lines_by_order[order.pk]
    ]
    products = {
        (product.pk, product.production_task_id): product
        for product in ProductionTaskProduct.objects.filter(
            pk__in={line.product_line_id_snapshot for line in production_lines if line.product_line_id_snapshot},
        ).only("id", "production_task_id", "item_number_snapshot", "material_snapshot", "color_name_snapshot")
    }
    boms = {
        bom.pk: bom
        for bom in Bom.objects.filter(pk__in={line.bom_id for line in production_lines if line.bom_id}).only(
            "id", "production_task_id", "product_line_id", "item_number_snapshot",
            "material_snapshot", "product_color_name_snapshot",
        )
    }
    sample_products = {}
    sample_ids = {order.sample_procurement_request_id for order in orders if order.source_type == "SAMPLE"}
    items = SampleItem.objects.filter(
        sample_request__material_request__procurement_request__id__in=sample_ids,
    ).select_related("sample_product").annotate(
        procurement_request_id=F("sample_request__material_request__procurement_request__id"),
    ).order_by("sample_request_id", "line_number", "id")
    for item in items:
        product = item.sample_product
        if product and product.sample_request_id != item.sample_request_id:
            product = None
        sample_products.setdefault(item.procurement_request_id, []).append(_inbound_product_summary(
            item.pk, item.product_description_snapshot, item.specification_snapshot,
            product.item_number_snapshot if product else "", item.color_name_snapshot,
            product.material_snapshot if product else "",
        ))
    result = {}
    for order in orders:
        if order.source_type == "SAMPLE":
            result[order.pk] = sample_products.get(order.sample_procurement_request_id, [])
            continue
        summary, seen = [], set()
        for line in lines_by_order[order.pk]:
            product = products.get((line.product_line_id_snapshot, order.production_task_id))
            if not product or product.pk in seen:
                continue
            seen.add(product.pk)
            bom = boms.get(line.bom_id)
            if bom and (bom.product_line_id != product.pk or bom.production_task_id != order.production_task_id):
                bom = None
            source = bom or product
            # 采购行 material_snapshot 是原料材质，不能作为成品材质。
            summary.append(_inbound_product_summary(
                product.pk, line.product_name_snapshot, line.product_specification_snapshot,
                source.item_number_snapshot,
                bom.product_color_name_snapshot if bom else product.color_name_snapshot,
                source.material_snapshot,
            ))
        result[order.pk] = summary
    return result


def _inbound_product_summary(product_id, name, specification, item_number, color, material):
    return {
        "product_line_id": str(product_id),
        "product_name": name or "",
        "item_number": item_number or "",
        "specification": specification_display(SimpleNamespace(
            specification_snapshot=specification, color_snapshot=color, material_snapshot=material,
        )),
        "color_name": color or "",
        "material": material or "",
    }


def material_inbound_order_totals(order_ids):
    """列表只汇总进度；批次跨多行时用 distinct 防止批次数被放大。"""
    rows = MaterialInbound.objects.filter(purchase_order_id__in=order_ids).order_by().values("purchase_order_id").annotate(
        pending_count=Count("id", filter=Q(status=MaterialInboundStatus.PENDING_QUALITY), distinct=True),
        confirmed_count=Count("id", filter=Q(status=MaterialInboundStatus.CONFIRMED), distinct=True),
        received_quantity=Sum("lines__received_quantity", default=0),
        return_quantity=Sum("lines__return_quantity", default=0),
    )
    return {row["purchase_order_id"]: row for row in rows}


def material_inbounds(queryset=None, *, read_optimized=False):
    if queryset is None:
        queryset = MaterialInbound.objects.all()
    if read_optimized:
        # 品质读取使用数量/物料快照，无需再加载采购行和原料对象。
        return queryset.select_related("purchase_order", "received_by_employee", "quality_confirmed_by_employee").prefetch_related(
            Prefetch("lines", queryset=MaterialInboundLine.objects.select_related("zone__warehouse", "location")),
        )
    return queryset.select_related(
        "purchase_order",
        "received_by_employee",
        "quality_confirmed_by_employee",
    ).prefetch_related(
        "lines__purchase_order_line",
        "lines__raw_material_information",
        "lines__zone__warehouse",
        "lines__location",
    )


def receipt_batches(queryset=None):
    if queryset is None:
        queryset = FinishedGoodsReceipt.objects.all()
    return queryset.select_related(
        "production_task_product",
        "production_task_product__production_task",
        "source_sample_inventory_line",
        "source_sample_inventory_line__receipt",
        "source_sample_inventory_line__sample_item__sample_request",
        "location",
        "location__zone",
        "location__zone__warehouse",
        "supplier",
        "unit",
        "received_by_employee",
    )


def eligible_products():
    return (
        ProductionTaskProduct.objects.filter(
            production_task__status=ProductionTaskStatus.IN_PRODUCTION,
            production_task__archived_at__isnull=True,
        )
        .select_related("product", "product__category", "product__product_item", "unit", "production_task")
        .order_by("product_number_snapshot", "id")
    )


def eligible_product_lines_with_remaining():
    lines = list(eligible_products())
    from .assembly_reporting_limits import assembly_reporting_limits
    reporting = assembly_reporting_limits(lines)
    receipt_totals = dict(
        FinishedGoodsReceipt.objects.filter(production_task_product__in=lines)
        .values_list("production_task_product_id")
        .annotate(total=Sum("received_quantity"))
    )
    result = []
    for line in lines:
        tolerance = Decimal(line.production_task.order_tolerance_percent) / Decimal("100")
        maximum = (Decimal(line.quantity) * (Decimal("1") + tolerance)).to_integral_value(rounding=ROUND_FLOOR)
        maximum = min(maximum, reporting[line.pk]['reported_minimum'])
        if Decimal(receipt_totals.get(line.pk, 0)) < maximum:
            result.append(line)
    return result


def eligible_orders_for_product(product_id):
    rows = list(eligible_products().filter(product_id=product_id).select_related("production_task"))
    from .assembly_reporting_limits import assembly_reporting_limits
    reporting = assembly_reporting_limits(rows)
    receipt_totals = dict(
        FinishedGoodsReceipt.objects.filter(production_task_product__in=rows)
        .values_list("production_task_product_id")
        .annotate(total=Sum("received_quantity"))
    )
    result = []
    for line in rows:
        tolerance = Decimal(line.production_task.order_tolerance_percent) / Decimal("100")
        maximum = (Decimal(line.quantity) * (Decimal("1") + tolerance)).to_integral_value(rounding=ROUND_FLOOR)
        maximum = min(maximum, reporting[line.pk]['reported_minimum'])
        received = Decimal(receipt_totals.get(line.pk, 0))
        remaining = max(maximum - received, Decimal("0"))
        if remaining <= 0:
            continue
        result.append((line, int(maximum), int(received), int(remaining)))
    return result
