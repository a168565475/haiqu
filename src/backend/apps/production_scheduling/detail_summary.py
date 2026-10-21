from decimal import Decimal, ROUND_HALF_UP, localcontext

from .detail_related import related_summary
from .detail_reporting import reporting_summary
from .models import ProductionScheduleProductCraft


def _total(values):
    values = list(values)
    if not values or any(value is None for value in values):
        return None
    with localcontext() as context:
        context.prec = 48
        return str(sum((Decimal(value) for value in values), Decimal("0")).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP,
        ))


def schedule_detail_summary(request, schedule):
    products = list(schedule.active_products)
    reporting = reporting_summary(request, schedule, products)
    related = related_summary(request, schedule, products)
    rows = []
    for product in products:
        key = str(product.pk)
        rows.append({"schedule_product_id": key, **reporting[key], **related[key]})

    # 排产的车间范围可能只显示部分产品或工艺，此时不能把局部金额冠以整单总额。
    visible_craft_ids = {link.pk for product in products for link in product.active_crafts}
    complete_scope = (
        schedule.products.filter(removed_at__isnull=True).count() == len(products)
        and not ProductionScheduleProductCraft.objects.filter(
            schedule_product__schedule=schedule, schedule_product__removed_at__isnull=True,
            removed_at__isnull=True,
        ).exclude(pk__in=visible_craft_ids).exists()
    )
    estimated_rows = [row for row in rows if row.get("estimated_amount_status") != "NOT_APPLICABLE"]
    reported_rows = [row for row in rows if row.get("reported_amount_status") != "NOT_APPLICABLE"]
    totals = {
        "estimated_wage": _total(row["estimated_wage"] for row in estimated_rows),
        "reported_amount": _total(row["reported_amount"] for row in reported_rows),
        "outsourcing_planned_amount": _total(row["outsourcing"]["planned_amount"] for row in rows),
        "complete_scope": complete_scope,
        "reason": "" if complete_scope else "当前仅可查看部分产品或工艺，整单金额不可汇总。",
    }
    if not complete_scope:
        for field in ("estimated_wage", "reported_amount", "outsourcing_planned_amount"):
            totals[field] = None
    elif totals["reported_amount"] is not None and (
        getattr(schedule, "_detail_reported_product_ids", set()) - {product.pk for product in products}
    ):
        totals["reported_amount"] = None
        totals["reason"] = "存在当前产品清单外的历史报工，暂不显示不完整的已报工总额。"
    return {"schedule_id": str(schedule.pk), "products": rows, "totals": totals}
