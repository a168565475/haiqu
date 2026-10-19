from decimal import Decimal, ROUND_HALF_UP

from django.db.models import Exists, F, OuterRef, Prefetch, Q

from apps.boms.models import Bom
from apps.production_tasks.models import ProductionTask, ProductionTaskProduct

from .models import PurchaseOrder, PurchaseOrderLine, Supplier


def active_suppliers():
    return Supplier.objects.filter(archived_at__isnull=True)


def suppliers_with_context(queryset=None):
    if queryset is None:
        queryset = Supplier.objects.all()
    return queryset.select_related(
        "submitted_by_employee",
        "created_by_employee",
        "updated_by_employee",
    )


def search_suppliers(queryset, search_text):
    if not search_text:
        return queryset
    return queryset.filter(
        Q(supplier_number__icontains=search_text)
        | Q(supplier_name__icontains=search_text)
        | Q(phone__icontains=search_text)
    )


def active_purchase_orders():
    return PurchaseOrder.objects.filter(archived_at__isnull=True)


def purchase_return_amount(record):
    """按本次退货数量和原采购单价汇总，沿用采购金额四位小数规则。"""
    lines = list(record.lines.all())
    if not lines:
        return None
    total = Decimal("0")
    for line in lines:
        purchase_line = line.inbound_line.purchase_order_line
        if not purchase_line or purchase_line.unit_price is None:
            return None
        total += (line.quantity * purchase_line.unit_price).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
    return format(total, ".4f")


def filter_purchase_return_status(queryset, status):
    from apps.inventory.models import MaterialInboundLine, MaterialInboundStatus
    from .models import PurchaseReturn, PurchaseReturnStatus

    returned = MaterialInboundLine.objects.filter(
        purchase_order_line__purchase_order_id=OuterRef("pk"),
        inbound__status=MaterialInboundStatus.CONFIRMED, return_quantity__gt=0,
    )
    records = PurchaseReturn.objects.filter(purchase_order_id=OuterRef("pk"))
    queryset = queryset.alias(
        has_returns=Exists(returned),
        missing_returns=Exists(returned.filter(Q(purchase_return_line__isnull=True) | ~Q(purchase_return_line__quantity=F("return_quantity")))),
        quality_returns=Exists(records.filter(status=PurchaseReturnStatus.QUALITY_GENERATED)),
        confirmed_returns=Exists(records.filter(status=PurchaseReturnStatus.PROCUREMENT_CONFIRMED)),
    )
    if status == "NONE":
        return queryset.filter(has_returns=False)
    if status == "MISSING":
        return queryset.filter(missing_returns=True)
    queryset = queryset.filter(missing_returns=False)
    if status == PurchaseReturnStatus.QUALITY_GENERATED:
        return queryset.filter(quality_returns=True)
    if status == PurchaseReturnStatus.PROCUREMENT_CONFIRMED:
        return queryset.filter(quality_returns=False, confirmed_returns=True)
    return queryset.filter(has_returns=True, quality_returns=False, confirmed_returns=False)


def purchase_orders_with_context(queryset=None, *, read_optimized=False):
    if queryset is None:
        queryset = PurchaseOrder.objects.all()
    # 读接口使用订单快照；写入服务仍保留原有关联对象。
    line_relations = ("sample_material_source",) if read_optimized else ("supplier", "bom", "bom_line", "sample_material_source")
    lines = PurchaseOrderLine.objects.select_related(*line_relations).prefetch_related(
        "material_inbound_lines__inbound",
        "material_inbound_lines__purchase_return_line__return_order",
    )
    products = ProductionTaskProduct.objects.only(
        "id",
        "production_task_id",
        "line_number",
        "color_card_snapshot",
        "color_name_snapshot",
        "color_code_snapshot",
        "material_snapshot",
    ).order_by("line_number", "id")
    relations = (
        "production_task",
        "sample_procurement_request__material_request__sample_request",
        "created_by_employee",
    ) if read_optimized else (
        "production_task",
        "production_task__sales_order",
        "sample_procurement_request__material_request__sample_request__customer_account",
        "currency",
        "created_by_employee",
    )
    return queryset.select_related(*relations).prefetch_related(
        Prefetch("lines", queryset=lines),
        Prefetch(
            "production_task__products",
            queryset=products,
            to_attr="purchase_order_products",
        ),
    )


def search_purchase_orders(queryset, search_text):
    if not search_text:
        return queryset
    return queryset.filter(
        Q(order_number__icontains=search_text)
        | Q(production_task_number_snapshot__icontains=search_text)
        | Q(sales_order_number_snapshot__icontains=search_text)
        | Q(sample_number_snapshot__icontains=search_text)
        | Q(customer_name_snapshot__icontains=search_text)
        | Q(lines__supplier_number_snapshot__icontains=search_text)
        | Q(lines__supplier_name_snapshot__icontains=search_text)
        | Q(lines__part_name_snapshot__icontains=search_text)
    ).distinct()


def production_tasks_with_purchase_sources(queryset=None):
    if queryset is None:
        queryset = ProductionTask.objects.filter(archived_at__isnull=True)
    boms = (
        Bom.objects.filter(archived_at__isnull=True)
        .order_by("-version_number", "-id")
        .prefetch_related("sections__lines")
    )
    products = (
        ProductionTaskProduct.objects.select_related("unit")
        .order_by("line_number", "id")
        .prefetch_related(Prefetch("boms", queryset=boms, to_attr="purchase_source_boms"))
    )
    return queryset.select_related("customer_account").prefetch_related(
        Prefetch("products", queryset=products, to_attr="purchase_source_products")
    )
