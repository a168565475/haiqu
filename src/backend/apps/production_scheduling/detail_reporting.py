"""排产详情的内部作业与报工金额，只读汇总。"""
from decimal import Decimal, ROUND_HALF_UP, localcontext
from zoneinfo import ZoneInfo

from django.db.models import Sum, prefetch_related_objects
from django.utils import timezone

from apps.access_control.module_policy import has_permission
from apps.workshop_config.models import CraftType, PlanCategory
from apps.workshop_reporting.models import (
    WageScheme, WageSchemeLineStatus, WageSchemeStatus, WorkReportLine,
    WorkshopPlanExecution, WorkshopPlanStatus,
)
from apps.workshop_reporting.selectors import accessible_work_reports, allowed_workshop_ids
from apps.workshop_reporting.services import wage_scheme_progress
from apps.workshop_reporting.tube_plan_services import tube_plan_is_complete


WAGE_PERMISSION = "workshop_reporting.view_wagescheme"
REPORT_PERMISSION = "workshop_reporting.view_workreport"
PLAN_DATES = {
    PlanCategory.METAL: ("metal_return_date", "金工回货日期"),
    PlanCategory.CUTTING: ("sewing_return_date", "车缝回货日期"),
    PlanCategory.SEWING: ("sewing_return_date", "车缝回货日期"),
    PlanCategory.ASSEMBLY: ("finished_inbound_date", "成品入库日期"),
}


def _workshop_scope(request, permission):
    if not has_permission(request, permission):
        return set()
    ids = allowed_workshop_ids(
        request, permission=permission, for_work_reports=permission == REPORT_PERMISSION,
    )
    return None if ids is None else {str(pk) for pk in ids}


def _allows(scope, workshop_id):
    return scope is None or str(workshop_id) in scope


def _estimated_wage(scheme, product):
    lines = [line for line in scheme.lines.all() if line.status == WageSchemeLineStatus.ACTIVE]
    if not lines or any(
        line.required_quantity_snapshot is None or line.order_quantity_snapshot is None
        for line in lines
    ):
        return None, "NOT_CONFIGURED", "工价方案缺少完整的计数快照。"
    # 需完成次数来自已批准方案；现时 BOM 不能替代该方案的历史计数依据。
    # 尤其金工没有独立冻结的每件支数，不能把来源金额按排产数量直接等比折算。
    if any(line.order_quantity_snapshot != product.planned_quantity for line in lines):
        return None, "QUANTITY_BASIS_MISMATCH", "工价计数基数与本排产数量不一致，报工总价待确认。"
    with localcontext() as context:
        context.prec = 48
        amount = sum(
            (line.required_quantity_snapshot * line.declared_price for line in lines), Decimal("0"),
        ).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
    return format(amount, ".4f"), "READY", ""


def _total(rows, amount_key, status_key, places):
    if not rows:
        return None, "NOT_APPLICABLE"
    statuses = {row[status_key] for row in rows}
    if statuses != {"READY"}:
        return None, next(iter(statuses)) if len(statuses) == 1 else "PARTIAL"
    with localcontext() as context:
        context.prec = 48
        amount = sum((Decimal(row[amount_key]) for row in rows), Decimal("0"))
    return format(amount, f".{places}f"), "READY"


def reporting_summary(request, schedule, products):
    """products 和 active_crafts 必须来自现有排产详情的数据权限筛选。"""
    products = [
        product for product in products
        if product.schedule_id == schedule.pk and product.removed_at is None
    ]
    wage_scope = _workshop_scope(request, WAGE_PERMISSION)
    report_scope = _workshop_scope(request, REPORT_PERMISSION)
    as_of = timezone.localdate(timezone=ZoneInfo("Asia/Shanghai"))
    product_links = {
        product.pk: [
            link for link in product.active_crafts
            if link.removed_at is None and link.craft_type_snapshot == CraftType.INTERNAL
            and link.plan_category in PLAN_DATES
        ]
        for product in products
    }
    prefetch_related_objects([link.craft for links in product_links.values() for link in links], "workshop")
    # 仅用历史归属键判断合计是否完整，不向响应暴露范围外的工艺、数量或金额。
    # 同一查询覆盖被移除产品，供整单汇总复用，避免再读取一次历史报工。
    historical_keys = set(WorkReportLine.objects.filter(
        report__schedule_product__schedule_id=schedule.pk,
    ).order_by().values_list(
        "report__schedule_product_id", "report__workshop_id", "report__scheme__scope_craft_id",
    ).distinct())
    schedule._detail_reported_product_ids = {key[0] for key in historical_keys}
    represented_keys = {
        (product.pk, link.craft.workshop_id, link.craft_id)
        for product in products for link in product_links[product.pk]
    }
    incomplete_report_products = {key[0] for key in historical_keys - represented_keys}
    scope_keys = {
        (product.product_line_id, link.craft.workshop_id, link.craft_id)
        for product in products for link in product_links[product.pk]
        if _allows(wage_scope, link.craft.workshop_id) or _allows(report_scope, link.craft.workshop_id)
    }
    schemes_by_scope = {}
    if scope_keys:
        schemes = WageScheme.objects.filter(
            product_line_id__in={key[0] for key in scope_keys},
            workshop_id__in={key[1] for key in scope_keys},
            scope_craft_id__in={key[2] for key in scope_keys},
        ).prefetch_related("lines").order_by("-created_at", "-id")
        for scheme in schemes:
            key = (scheme.product_line_id, scheme.workshop_id, scheme.scope_craft_id)
            if key in scope_keys:
                schemes_by_scope.setdefault(key, []).append(scheme)

    amounts = {}
    quantities = {}
    if report_scope is None or report_scope:
        reports = accessible_work_reports(request, permission=REPORT_PERMISSION).filter(
            schedule_product_id__in=product_links, schedule_product__schedule_id=schedule.pk,
        )
        # 只连接报工行一次。金额保留当时报工快照，旧版本中已移除的工序也计入。
        for row in WorkReportLine.objects.filter(report__in=reports).order_by().values(
            "report__schedule_product_id", "report__workshop_id", "report__scheme__scope_craft_id", "work_item_id",
        ).annotate(amount=Sum("amount"), quantity=Sum("quantity")):
            key = (row["report__schedule_product_id"], row["report__workshop_id"], row["report__scheme__scope_craft_id"])
            with localcontext() as context:
                context.prec = 48
                amounts[key] = amounts.get(key, Decimal("0")) + row["amount"]
            quantities.setdefault(key, {})[row["work_item_id"]] = row["quantity"]

    executions = {
        (item.schedule_product_id, item.craft_id): item
        for item in WorkshopPlanExecution.objects.filter(schedule_product_id__in=product_links)
    }
    result = {}
    for product in products:
        rows = []
        for link in product_links[product.pk]:
            workshop_id = link.craft.workshop_id
            can_view_wage = _allows(wage_scope, workshop_id)
            can_view_reports = _allows(report_scope, workshop_id)
            candidates = schemes_by_scope.get((product.product_line_id, workshop_id, link.craft_id), [])
            active = [
                scheme for scheme in candidates
                if scheme.status == WageSchemeStatus.APPROVED and scheme.effective_from <= as_of
                and (scheme.effective_to is None or scheme.effective_to >= as_of)
            ]
            scheme = active[0] if len(active) == 1 else None
            estimated = None
            scheme_id = None
            if not can_view_wage:
                wage_status = estimated_status = "FORBIDDEN"
                reason = "当前账号没有该车间的工价查看权限。"
            elif len(active) > 1:
                wage_status = estimated_status = "CONFLICT"
                reason = "当前日期存在多个适用工价版本。"
            elif scheme:
                scheme_id = str(scheme.pk)
                wage_status = scheme.status
                estimated, estimated_status, reason = _estimated_wage(scheme, product)
            else:
                latest = candidates[0] if candidates else None
                scheme_id = str(latest.pk) if latest else None
                wage_status = (
                    latest.status if latest and latest.status != WageSchemeStatus.APPROVED
                    else "NO_EFFECTIVE_VERSION" if latest else "NOT_CREATED"
                )
                estimated_status = "NOT_CONFIGURED"
                reason = "当前日期没有适用的已批准工价方案。"

            report_key = (product.pk, workshop_id, link.craft_id)
            cumulative = quantities.get(report_key, {})
            progress = None
            if can_view_reports and scheme:
                with localcontext() as context:
                    context.prec = 48
                    progress = wage_scheme_progress(scheme, cumulative)
            execution = executions.get((product.pk, link.craft_id))
            plan_status = execution.status if execution else WorkshopPlanStatus.IN_PROGRESS
            if (
                plan_status == WorkshopPlanStatus.COMPLETED and link.plan_category == PlanCategory.METAL
                and can_view_reports and scheme
                and not tube_plan_is_complete(product.pk, scheme, cumulative_by_work_item=cumulative)
            ):
                plan_status = WorkshopPlanStatus.IN_PROGRESS
            date_field, milestone = PLAN_DATES[link.plan_category]
            rows.append({
                "category": link.plan_category, "craft_id": str(link.craft_id),
                "craft_name": link.craft_name_snapshot, "workshop_id": str(workshop_id),
                "workshop_name": link.craft.workshop.name,
                "plan_date": getattr(product, date_field).isoformat(), "milestone": milestone,
                "planned_quantity": str(product.planned_quantity), "unit_name": product.unit_name_snapshot,
                "estimated_wage": estimated, "estimated_amount_status": estimated_status,
                "reported_amount": format(amounts.get(report_key, Decimal("0")), ".2f") if can_view_reports else None,
                "reported_amount_status": "READY" if can_view_reports else "FORBIDDEN",
                "progress_percent": progress["percentage"] if progress else None,
                "plan_status": plan_status, "plan_status_display": WorkshopPlanStatus(plan_status).label,
                "wage_status": wage_status, "reason": reason, "scheme_id": scheme_id,
                "can_view_wage": can_view_wage, "can_view_reports": can_view_reports,
            })
        estimated, estimated_status = _total(rows, "estimated_wage", "estimated_amount_status", 4)
        reported, reported_status = _total(rows, "reported_amount", "reported_amount_status", 2)
        if product.pk in incomplete_report_products:
            reported, reported_status = None, "PARTIAL"
        result[str(product.pk)] = {
            "internal_plans": rows, "estimated_wage": estimated, "reported_amount": reported,
            "estimated_amount_status": estimated_status, "reported_amount_status": reported_status,
        }
    return result
