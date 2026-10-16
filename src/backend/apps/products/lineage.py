from dataclasses import dataclass


@dataclass(frozen=True)
class ProductLineage:
    """生产任务产品能够由真实外键证明的上游明细链。"""

    production_task_product_id: object
    sales_order_delivery_batch_line_id: object | None
    sales_order_line_id: object | None
    quotation_line_id: object | None
    inquiry_item_id: object | None
    bom_writeback_allowed: bool
    writeback_scope: str


def resolve_production_task_product_lineage(product_line):
    """只沿生产任务产品的实际来源外键解析，不按产品主档或文字猜测。"""
    batch_line = getattr(product_line, "sales_order_delivery_batch_line", None)
    sales_order_line = getattr(batch_line, "sales_order_line", None) if batch_line else None
    quotation_line = getattr(sales_order_line, "source_quotation_line", None) if sales_order_line else None
    inquiry_item = getattr(quotation_line, "source_inquiry_item", None) if quotation_line else None

    return ProductLineage(
        production_task_product_id=product_line.pk,
        sales_order_delivery_batch_line_id=getattr(batch_line, "pk", None),
        sales_order_line_id=getattr(sales_order_line, "pk", None),
        quotation_line_id=getattr(quotation_line, "pk", None),
        inquiry_item_id=getattr(inquiry_item, "pk", None),
        bom_writeback_allowed=True,
        writeback_scope="PRODUCTION_AND_SALES" if sales_order_line else "PRODUCTION_ONLY",
    )


def get_production_task_product_lineage(product_line_id):
    """按生产任务产品 UUID 读取来源，再交给纯解析函数。"""
    from apps.production_tasks.models import ProductionTaskProduct

    product_line = ProductionTaskProduct.objects.select_related(
        "sales_order_delivery_batch_line__sales_order_line__source_quotation_line__source_inquiry_item",
    ).get(pk=product_line_id)
    return resolve_production_task_product_lineage(product_line)
