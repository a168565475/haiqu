"""排产列表金额批量汇总；无配置为零，权限或计价依据不完整仍为未知。"""
from collections import defaultdict
from decimal import Decimal, ROUND_HALF_UP, localcontext

from django.db.models import Count, Sum
from django.utils import timezone

from apps.workshop_reporting.models import WageScheme, WorkReportLine
from apps.workshop_reporting.selectors import accessible_work_reports
from .detail_reporting import WAGE_PERMISSION, REPORT_PERMISSION, _allows, _estimated_wage, _workshop_scope
from .models import ProductionScheduleProduct, ProductionScheduleProductCraft


def _money_total(values):
    if any(value is None for value in values):
        return None
    with localcontext() as context:
        context.prec = 48
        return format(sum((Decimal(value) for value in values), Decimal(0)).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP,
        ), ".2f")


def schedule_list_amounts(request, schedules):
    if not schedules:
        return {}
    schedule_ids = [schedule.pk for schedule in schedules]
    products = [product for schedule in schedules for product in schedule.active_products]
    wage_scope = _workshop_scope(request, WAGE_PERMISSION)
    report_scope = _workshop_scope(request, REPORT_PERMISSION)
    counts = dict(ProductionScheduleProduct.objects.filter(
        schedule_id__in=schedule_ids, removed_at__isnull=True,
    ).values("schedule_id").annotate(total=Count("id")).values_list("schedule_id", "total"))
    craft_ids = defaultdict(set)
    for schedule_id, link_id in ProductionScheduleProductCraft.objects.filter(
        schedule_product__schedule_id__in=schedule_ids, schedule_product__removed_at__isnull=True,
        removed_at__isnull=True,
    ).values_list("schedule_product__schedule_id", "pk"):
        craft_ids[schedule_id].add(link_id)
    schemes = defaultdict(list)
    today = timezone.localdate()
    for scheme in WageScheme.objects.filter(
        product_line_id__in=[product.product_line_id for product in products],
        status="APPROVED", effective_from__lte=today,
    ).prefetch_related("lines"):
        if scheme.effective_to is None or scheme.effective_to >= today:
            schemes[(scheme.product_line_id, scheme.scope_craft_id)].append(scheme)
    all_report_counts = dict(WorkReportLine.objects.filter(
        report__schedule_product__schedule_id__in=schedule_ids,
    ).values("report__schedule_product__schedule_id").annotate(total=Count("id"))
        .values_list("report__schedule_product__schedule_id", "total"))
    reports = {}
    if report_scope is None or report_scope:
        visible = accessible_work_reports(request, permission=REPORT_PERMISSION)
        for row in WorkReportLine.objects.filter(
            report__in=visible, report__schedule_product__schedule_id__in=schedule_ids,
        ).values("report__schedule_product__schedule_id").annotate(total=Count("id"), amount=Sum("amount")):
            reports[row["report__schedule_product__schedule_id"]] = row
    result = {}
    for schedule in schedules:
        links = [link for product in schedule.active_products for link in product.active_crafts]
        complete = (len(schedule.active_products) == counts.get(schedule.pk, 0)
                    and {link.pk for link in links} == craft_ids[schedule.pk])
        estimates = []
        for product in schedule.active_products:
            for link in product.active_crafts:
                if link.craft_type_snapshot != "INTERNAL":
                    continue
                candidates = schemes[(product.product_line_id, link.craft_id)]
                if not _allows(wage_scope, link.craft.workshop_id) or len(candidates) > 1:
                    estimates.append(None)
                elif not candidates:
                    estimates.append("0")
                else:
                    estimates.append(_estimated_wage(candidates[0], product)[0])
        report = reports.get(schedule.pk, {"total": 0, "amount": Decimal(0)})
        report_allowed = (report_scope is None or bool(report_scope)) and all(
            _allows(report_scope, link.craft.workshop_id)
            for link in links if link.craft_type_snapshot == "INTERNAL"
        )
        result[str(schedule.pk)] = {
            "estimated_wage": _money_total(estimates) if complete and (wage_scope is None or wage_scope) else None,
            "reported_amount": _money_total([report["amount"]]) if complete and report_allowed
            and report["total"] == all_report_counts.get(schedule.pk, 0) else None,
        }
    return result
