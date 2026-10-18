"""生产工作台只读汇总；沿用来源权限和范围，明细先分页再批量补齐。"""

from collections import defaultdict
from contextlib import contextmanager
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from django.db.models import BigIntegerField, Case, Count, DateField, Exists, F, OuterRef, Prefetch, Q, Subquery, Sum, Value, When
from django.db.models.functions import Coalesce
from django.utils import timezone
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.api.permissions import BusinessActionPermission, HasActiveEmployee
from apps.inventory.api.finished_receipts import record_queryset
from apps.outsourcing.unified_selectors import unified_order_rows, unified_order_sources
from apps.production_scheduling.models import ProductionScheduleProduct, ProductionScheduleProductCraft
from apps.production_scheduling.selectors import accessible_production_schedules
from apps.workshop_reporting.models import WageScheme, WageSchemeLine, WorkReportLine, WorkshopPlanExecution
from apps.workshop_reporting.selectors import accessible_work_reports, allowed_workshop_ids

from .models import ProductionTask, ProductionTaskProduct, ProductionTaskStatus
from .selectors import accessible_production_tasks


LIMIT = 20
REPORT_PERMISSION = "workshop_reporting.view_workreport"
TASK_STATUSES = ["PENDING_VALIDATION", "READY", "IN_PRODUCTION", "PAUSED", "COMPLETED"]
CATEGORY_GROUPS = {"METAL": ("METAL",), "SEWING": ("CUTTING", "SEWING"), "ASSEMBLY": ("ASSEMBLY",)}
PLAN_ROUTES = {"METAL": "metalworking", "CUTTING": "cutting", "SEWING": "sewing", "ASSEMBLY": "assembly"}


class DashboardFilters(serializers.Serializer):
    q = serializers.CharField(max_length=120, allow_blank=True, default="")
    days = serializers.ChoiceField(choices=[3, 7], default=7)
    status = serializers.ChoiceField(choices=["ALL", *TASK_STATUSES], default="ALL")
    focus = serializers.ChoiceField(choices=["ALL", "OVERDUE", "DUE_SOON", "UNSCHEDULED"], default="ALL")
    production_date = serializers.DateField(default=timezone.localdate)
    workshop = serializers.ChoiceField(choices=list(CATEGORY_GROUPS), default="METAL")
    task_date = serializers.DateField(allow_null=True, default=None)
    task_page = serializers.IntegerField(min_value=1, max_value=2147483647, default=1)


def section(data=None, *, state=None, reason="", empty=False):
    return {"state": state or ("EMPTY" if empty else "READY"), "reason": reason, "data": data}


def forbidden(reason="当前账号没有来源数据的读取权限。"):
    return section(state="FORBIDDEN", reason=reason)


def progress(state="UNKNOWN", percent=None, label="数据口径尚不完整"):
    return {"state": state, "percent": percent, "label": label}


def decimal_string(value):
    return format(Decimal(value).normalize(), "f")


def quantity_progress(required, completed):
    if required is None or required <= 0:
        return progress(label="缺少需完成数量")
    percent = int(min(Decimal(100), max(Decimal(0), Decimal(completed) * 100 / Decimal(required)))
                  .quantize(Decimal(1), rounding=ROUND_HALF_UP))
    return progress("READY", percent, f"{percent}%")


@contextmanager
def source_context(request, view_class):
    """让既有权限和资源范围解析看到原视图，而非新聚合视图。"""
    source_view = view_class()
    source_view.action = "list"
    source_view.request = request
    original_context = request.parser_context
    request.parser_context = {**(original_context or {}), "view": source_view}
    try:
        yield source_view
    finally:
        request.parser_context = original_context


def source_permissions(request):
    from apps.inventory.api.finished_receipts import FinishedRecordViewSet
    from apps.outsourcing.api.unified_views import UnifiedOutsourcingOrderViewSet
    from apps.production_scheduling.api.views import ProductionScheduleItemViewSet, ProductionScheduleViewSet
    from .api.views import ProductionTaskViewSet

    sources = {
        "tasks": ProductionTaskViewSet, "schedules": ProductionScheduleViewSet,
        "workshop": ProductionScheduleItemViewSet, "receipts": FinishedRecordViewSet,
        "outsourcing": UnifiedOutsourcingOrderViewSet,
    }
    permissions = {}
    for name, view_class in sources.items():
        with source_context(request, view_class) as source_view:
            permissions[name] = BusinessActionPermission().has_permission(request, source_view)
    # 日期报工列表直接检查 Django permission；聚合接口保持同一个门禁。
    permissions["reports"] = request.user.has_perm(REPORT_PERMISSION)
    return permissions, sources


def task_scope(request, filters, today):
    return filter_tasks(accessible_production_tasks(request), filters, today)


def filter_tasks(queryset, filters, today):
    end = today + timedelta(days=filters["days"])
    queryset = queryset.filter(archived_at__isnull=True, status__in=TASK_STATUSES)
    queryset = queryset.filter(delivery_date__lt=end).filter(
        ~Q(status="COMPLETED") | Q(delivery_date__gte=today),
    )
    if filters["status"] != "ALL":
        queryset = queryset.filter(status=filters["status"])
    if filters["q"]:
        matching_products = ProductionTaskProduct.objects.filter(
            production_task_id=OuterRef("pk"), product_name_snapshot__icontains=filters["q"],
        )
        queryset = queryset.alias(matching_product=Exists(matching_products)).filter(
            Q(task_number__icontains=filters["q"]) | Q(matching_product=True),
        )
    return queryset


def active_plans(request):
    return ProductionScheduleProduct.objects.filter(
        schedule__in=accessible_production_schedules(request),
        schedule__record_status="ACTIVE", removed_at__isnull=True,
    )


def plan_context(queryset):
    return queryset.select_related("schedule__production_task", "product_line", "unit").prefetch_related(
        Prefetch("crafts", queryset=ProductionScheduleProductCraft.objects.filter(
            removed_at__isnull=True, craft_type_snapshot="INTERNAL",
        ).select_related("craft"), to_attr="dashboard_crafts"),
    )


def plan_metrics(request, plans, permissions, production_date):
    """只对当前页排产产品批量计算；不同产品、单位不生成合计百分比。"""
    metrics, scopes, allowed_ids = {}, set(), set()
    if permissions["reports"]:
        ids = allowed_workshop_ids(request, for_work_reports=True, permission=REPORT_PERMISSION)
        allowed_ids = None if ids is None else set(ids)
    for plan in plans:
        for link in plan.dashboard_crafts:
            if link.plan_category in {"METAL", "CUTTING", "SEWING"}:
                if permissions["reports"] and (allowed_ids is None or link.craft.workshop_id in allowed_ids):
                    scopes.add((plan.product_line_id, link.craft.workshop_id, link.craft_id))
    schemes_by_scope = defaultdict(list)
    if scopes:
        schemes = WageScheme.objects.filter(
            product_line_id__in={key[0] for key in scopes}, workshop_id__in={key[1] for key in scopes},
            scope_craft_id__in={key[2] for key in scopes}, status="APPROVED", effective_from__lte=production_date,
        ).filter(Q(effective_to__isnull=True) | Q(effective_to__gte=production_date)).prefetch_related(
            Prefetch("lines", queryset=WageSchemeLine.objects.filter(status="ACTIVE"), to_attr="active_lines"),
        )
        for scheme in schemes:
            key = (scheme.product_line_id, scheme.workshop_id, scheme.scope_craft_id)
            if key in scopes:
                schemes_by_scope[key].append(scheme)
    reported = {}
    if scopes:
        report_rows = accessible_work_reports(request, permission=REPORT_PERMISSION)
        work_ids = {line.work_item_id for schemes in schemes_by_scope.values()
                    for scheme in schemes for line in scheme.active_lines}
        for row in WorkReportLine.objects.filter(
            report__in=report_rows, report__schedule_product_id__in=[plan.pk for plan in plans],
            work_item_id__in=work_ids,
        ).order_by().values("report__schedule_product_id", "work_item_id").annotate(
            cumulative=Sum("quantity"), today=Sum("quantity", filter=Q(report__production_date=production_date)),
        ):
            reported[(row["report__schedule_product_id"], row["work_item_id"])] = row
    receipts = {}
    if permissions["receipts"] and plans:
        for row in record_queryset().filter(
            source_type="PRODUCTION_ORDER", production_task_product_id__in=[plan.product_line_id for plan in plans],
        ).order_by().values("production_task_product_id", "unit_id").annotate(
            cumulative=Sum("received_quantity"), today=Sum("received_quantity", filter=Q(business_date=production_date)),
        ):
            receipts[(row["production_task_product_id"], row["unit_id"])] = row
    for plan in plans:
        for link in plan.dashboard_crafts:
            item = {"required": None, "cumulative": None, "today": None, "remaining": None,
                    "unit": plan.unit_name_snapshot, "progress": progress()}
            if link.plan_category == "ASSEMBLY":
                item = assembly_metric(plan, receipts, permissions["receipts"])
            elif not permissions["reports"] or (allowed_ids is not None and link.craft.workshop_id not in allowed_ids):
                item["progress"] = progress("FORBIDDEN", label="无该车间报工读取权限")
            else:
                key = (plan.product_line_id, link.craft.workshop_id, link.craft_id)
                schemes = schemes_by_scope.get(key, [])
                if len(schemes) != 1:
                    item["progress"] = progress(label="未找到唯一有效的已批准工价方案")
                else:
                    lines = schemes[0].active_lines
                    units = {line.unit_name_snapshot for line in lines}
                    if not lines or any(line.required_quantity_snapshot is None for line in lines):
                        item["progress"] = progress(label="工价方案缺少需完成次数")
                    elif len(lines) != 1 or len(units) != 1:
                        item["progress"] = progress(label="多个计件项目需逐项查看，不合计工序数量")
                    else:
                        required = sum((line.required_quantity_snapshot for line in lines), Decimal(0))
                        cumulative = sum((reported.get((plan.pk, line.work_item_id), {}).get("cumulative") or 0 for line in lines), Decimal(0))
                        today = sum((reported.get((plan.pk, line.work_item_id), {}).get("today") or 0 for line in lines), Decimal(0))
                        item = metric_values(required, cumulative, today, next(iter(units)))
            metrics[(plan.pk, link.craft_id)] = item
        metrics[(plan.pk, "ASSEMBLY")] = assembly_metric(plan, receipts, permissions["receipts"])
    return metrics


def metric_values(required, cumulative, today, unit):
    return {"required": decimal_string(required), "cumulative": decimal_string(cumulative),
            "today": decimal_string(today), "remaining": decimal_string(max(required - cumulative, 0)),
            "unit": unit, "progress": quantity_progress(required, cumulative)}


def assembly_metric(plan, receipts, allowed):
    empty = {"required": None, "cumulative": None, "today": None, "remaining": None,
             "unit": plan.unit_name_snapshot, "progress": progress()}
    if not allowed:
        return {**empty, "progress": progress("FORBIDDEN", label="无成品入库读取权限")}
    if any(product_id == plan.product_line_id and unit_id != plan.product_line.unit_id for product_id, unit_id in receipts):
        return {**empty, "progress": progress(label="入库单位与生产产品单位不一致")}
    row = receipts.get((plan.product_line_id, plan.product_line.unit_id), {})
    return metric_values(plan.product_line.quantity, row.get("cumulative") or 0, row.get("today") or 0, plan.unit_name_snapshot)


def task_section(request, filters, today, permissions):
    queryset = task_scope(request, filters, today)
    if permissions["schedules"]:
        schedules = accessible_production_schedules(request).filter(record_status="ACTIVE", production_task_id=OuterRef("pk"))
        queryset = queryset.annotate(dashboard_schedule_id=Subquery(schedules.values("pk")[:1]))
    counts = queryset.aggregate(
        total=Count("pk", distinct=True),
        overdue=Count("pk", filter=Q(delivery_date__lt=today) & ~Q(status="COMPLETED"), distinct=True),
        due_soon=Count("pk", filter=Q(delivery_date__gte=today, delivery_date__lt=today + timedelta(days=3)) & ~Q(status="COMPLETED"), distinct=True),
        completed=Count("pk", filter=Q(status="COMPLETED"), distinct=True),
        paused=Count("pk", filter=Q(status="PAUSED"), distinct=True),
    )
    counts["unscheduled"] = queryset.filter(dashboard_schedule_id__isnull=True).exclude(status="COMPLETED").count() if permissions["schedules"] else None
    distribution = {row["status"]: row["count"] for row in queryset.order_by().values("status").annotate(count=Count("pk", distinct=True))}
    due_rows = {row["delivery_date"]: row["count"] for row in queryset.filter(delivery_date__gte=today).exclude(
        status="COMPLETED",
    ).order_by().values("delivery_date").annotate(count=Count("pk", distinct=True))}
    selected = queryset
    if filters["focus"] == "OVERDUE":
        selected = selected.filter(delivery_date__lt=today).exclude(status="COMPLETED")
    elif filters["focus"] == "DUE_SOON":
        selected = selected.filter(delivery_date__gte=today, delivery_date__lt=today + timedelta(days=3)).exclude(status="COMPLETED")
    elif filters["focus"] == "UNSCHEDULED":
        if not permissions["schedules"]:
            raise PermissionDenied("当前账号没有按未排产状态筛选的权限。")
        selected = selected.filter(dashboard_schedule_id__isnull=True).exclude(status="COMPLETED")
    if filters["task_date"] is not None:
        selected = selected.filter(delivery_date=filters["task_date"]).exclude(status="COMPLETED")
    total = selected.count()
    offset = (filters["task_page"] - 1) * LIMIT
    tasks = list(selected.select_related("customer_account").prefetch_related(
        Prefetch("products", queryset=ProductionTaskProduct.objects.select_related("unit").order_by("line_number", "pk")),
    ).order_by("delivery_date", "task_number", "pk")[offset:offset + LIMIT])
    plans_by_task = defaultdict(list)
    metrics = {}
    if permissions["schedules"] and tasks:
        plans = list(plan_context(active_plans(request).filter(schedule__production_task_id__in=[task.pk for task in tasks])))
        metrics = plan_metrics(request, plans, permissions, filters["production_date"])
        for plan in plans:
            plans_by_task[plan.schedule.production_task_id].append(plan)
    items = []
    for task in tasks:
        products = list(task.products.all())
        plans = plans_by_task[task.pk]
        stages = {}
        for name, categories in CATEGORY_GROUPS.items():
            if not permissions["schedules"]:
                result = progress("FORBIDDEN", label="无排产读取权限")
            elif name == "ASSEMBLY" and not permissions["receipts"]:
                result = progress("FORBIDDEN", label="无成品入库读取权限")
            elif name != "ASSEMBLY" and not permissions["reports"]:
                result = progress("FORBIDDEN", label="无报工读取权限")
            elif len(products) > 1 or len(plans) > 1:
                result = progress(label="多产品进度需逐项查看")
            elif not plans:
                result = progress(label="尚未排产")
            elif name == "ASSEMBLY":
                result = metrics[(plans[0].pk, "ASSEMBLY")]["progress"]
            else:
                links = [link for link in plans[0].dashboard_crafts if link.plan_category in categories]
                result = metrics[(plans[0].pk, links[0].craft_id)]["progress"] if len(links) == 1 else progress(label="未配置或包含多个工艺，请逐项查看")
            stages[name.lower()] = result
        items.append({
            "id": str(task.pk), "task_number": task.task_number,
            "customer_name": task.customer_account.account_name if task.customer_account_id else "",
            "delivery_date": task.delivery_date, "days_to_due": (task.delivery_date - today).days,
            "status": task.status, "status_display": task.get_status_display(), "priority": task.production_priority,
            "products": [{"id": str(product.pk), "name": product.product_name_snapshot,
                          "quantity": str(product.quantity), "unit": product.unit.unit_name} for product in products],
            "schedule_id": str(task.dashboard_schedule_id) if permissions["schedules"] and task.dashboard_schedule_id else None,
            "stages": stages, "href": f"/production-tasks/{task.pk}",
        })
    return section({
        "counts": counts, "status_distribution": [{"status": status, "label": ProductionTaskStatus(status).label,
            "count": distribution.get(status, 0)} for status in TASK_STATUSES],
        "due_series": [{"date": today + timedelta(days=offset), "count": due_rows.get(today + timedelta(days=offset), 0)}
                       for offset in range(filters["days"])],
        "items": items, "total": total, "truncated": total > LIMIT,
    }, empty=not counts["total"])


def outsourcing_section(request, filters, today):
    sources = unified_order_sources(request, {})
    candidates, total, overdue = [], 0, 0
    fields = ("id", "updated_at", "record_type", "unified_source", "unified_access")
    for index, queryset in enumerate(sources):
        queryset = queryset.filter(status__in=["PROCESSING", "PARTIAL_RETURN"])
        if index == 0:
            # 金工受限投影不提供原单交期，也不能通过逾期计数间接泄露它。
            due = Case(When(unified_access="REGULAR", then=F("delivery_date")), default=Value(None), output_field=DateField())
        elif index == 2:
            due = F("expected_return_date")
        else:
            due = Value(None, output_field=DateField())
        queryset = queryset.annotate(dashboard_due=due).filter(
            Q(dashboard_due__lt=today + timedelta(days=filters["days"])) | Q(dashboard_due__isnull=True),
        )
        overdue += queryset.filter(dashboard_due__lt=today).distinct().count()
        total += queryset.distinct().count()
        ordering = ("-updated_at", "id") if index == 1 else (F("dashboard_due").asc(nulls_last=True), "id")
        candidates.extend(queryset.order_by(*ordering).values(*fields).distinct()[:LIMIT])
    # 每个渠道最多取 20 条，再合并排序；全量计数已在 SQL 完成。
    rows = unified_order_rows(request, candidates, {})
    rows.sort(key=lambda row: (row["delivery_date"] is None, str(row["delivery_date"] or ""), row["row_key"]))
    items = []
    for row in rows[:LIMIT]:
        # 外发原料与回货加工件并非同一数量口径，不能相减；仅展示单产品已回货量。
        quantities = row["returned_quantities"] if row["product_count"] == 1 else []
        prefix = {"ORIGINAL": "", "REWORK": "rework/", "TUBE": "tube/"}[row["record_type"]]
        query = "?view=metal" if row["record_type"] == "ORIGINAL" and row["detail_access"] == "METAL" else ""
        items.append({"id": row["id"], "row_key": row["row_key"], "order_number": row["order_number"],
                      "delivery_date": row["delivery_date"], "status": row["status"], "status_display": row["status_display"],
                      "factory_names": row["factory_names"], "quantities": quantities,
                      "receipt_state": row.get("receipt_state", "UNKNOWN"),
                      "href": f"/workshop/outsourcing/{prefix}{row['id']}{query}"})
    return section({"pending_count": total, "overdue_count": overdue, "items": items, "total": total,
                    "truncated": total > LIMIT}, empty=not total,
                   reason="待回为加工中或部分回货；无预计回货日的重加工单不计逾期，数量沿用统一委外来源口径。")


def receipts_section(request, filters, today, permissions):
    receipts = record_queryset().filter(source_type="PRODUCTION_ORDER")
    daily = receipts.filter(business_date=filters["production_date"])
    total = daily.count()
    quantities = [{"quantity": str(row["quantity"]), "unit": row["unit__unit_name"],
                   "name": row["product_name_snapshot"],
                   "product_line_id": str(row["production_task_product_id"]) if row["production_task_product_id"] else None}
                  for row in daily.order_by().values("production_task_product_id", "product_name_snapshot", "unit__unit_name")
                  .annotate(quantity=Sum("received_quantity")).order_by("product_name_snapshot", "unit__unit_name")]
    pending = []
    pending_unknown = False
    if permissions["tasks"]:
        received = receipts.filter(production_task_product_id=OuterRef("pk"), unit_id=OuterRef("unit_id")).order_by().values(
            "production_task_product_id",
        ).annotate(quantity=Sum("received_quantity")).values("quantity")
        wrong_unit = receipts.filter(production_task_product_id=OuterRef("pk")).exclude(unit_id=OuterRef("unit_id"))
        products = ProductionTaskProduct.objects.filter(
            production_task__in=task_scope(request, filters, today).exclude(status="COMPLETED"),
        ).annotate(received=Coalesce(Subquery(received), Value(0), output_field=BigIntegerField()),
                   wrong_receipt_unit=Exists(wrong_unit)).filter(Q(received__lt=F("quantity")) | Q(wrong_receipt_unit=True))
        pending_unknown = products.filter(wrong_receipt_unit=True).exists()
        for product in products.select_related("production_task", "unit").order_by("production_task__delivery_date", "pk")[:LIMIT]:
            pending.append({"product_line_id": str(product.pk), "task_number": product.production_task.task_number,
                            "name": product.product_name_snapshot, "unit": product.unit.unit_name,
                            "state": "UNKNOWN" if product.wrong_receipt_unit else "READY",
                            "required": str(product.quantity), "received": None if product.wrong_receipt_unit else str(product.received),
                            "remaining": None if product.wrong_receipt_unit else str(product.quantity - product.received),
                            "href": f"/production-tasks/{product.production_task_id}"})
    items = [{"id": str(row.pk), "number": row.receipt_number, "date": row.business_date,
              "name": row.product_name_snapshot, "quantity": str(row.received_quantity), "unit": row.unit.unit_name,
              "href": "/inventory/finished-goods?tab=records"}
             for row in daily.order_by("-business_date", "-received_at", "-id")[:LIMIT]]
    return section({"today_count": total, "today_quantities": quantities, "pending_products": pending,
                    "pending_state": ("UNKNOWN" if pending_unknown else "READY" if pending else "EMPTY") if permissions["tasks"] else "FORBIDDEN",
                    "items": items, "total": total, "truncated": total > LIMIT}, empty=not total and not pending)


def workshop_section(request, filters, today, permissions):
    # 排产源的全量读取权限独立于任务单全量权限，不能再用任务范围缩小已授权排产。
    tasks = filter_tasks(ProductionTask.objects.all(), filters, today)
    plans = active_plans(request).filter(schedule__production_task__in=tasks)
    links = ProductionScheduleProductCraft.objects.filter(
        schedule_product__in=plans, removed_at__isnull=True, craft_type_snapshot="INTERNAL",
        plan_category__in=CATEGORY_GROUPS[filters["workshop"]],
    )
    total = links.count()
    date_field = {"METAL": "metal_return_date", "SEWING": "sewing_return_date", "ASSEMBLY": "finished_inbound_date"}[filters["workshop"]]
    selected_links = list(links.select_related("craft").order_by(f"schedule_product__{date_field}", "id")[:LIMIT])
    selected_plans = list(plan_context(plans.filter(pk__in=[link.schedule_product_id for link in selected_links])))
    by_id = {plan.pk: plan for plan in selected_plans}
    metrics = plan_metrics(request, selected_plans, permissions, filters["production_date"])
    executions = {(row.schedule_product_id, row.craft_id): row.status for row in WorkshopPlanExecution.objects.filter(
        schedule_product_id__in=by_id, craft_id__in=[link.craft_id for link in selected_links],
    )}
    items = []
    for link in selected_links:
        plan = by_id[link.schedule_product_id]
        task = plan.schedule.production_task
        status = task.status if task.status in {"PAUSED", "COMPLETED"} else executions.get((plan.pk, link.craft_id), "UNKNOWN")
        items.append({"key": str(link.pk), "schedule_id": str(plan.schedule_id), "task_number": task.task_number,
                      "name": plan.product_line.product_name_snapshot, "craft_name": link.craft_name_snapshot,
                      "plan_date": getattr(plan, date_field), "status": status,
                      **metrics[(plan.pk, link.craft_id)],
                      "href": f"/workshop/plans/{PLAN_ROUTES[link.plan_category]}?schedule_product_id={plan.pk}"})
    return section({"category": filters["workshop"], "plan_count": total, "items": items,
                    "total": total, "truncated": total > LIMIT}, empty=not total)


def reports_section(request, filters):
    queryset = accessible_work_reports(request, permission=REPORT_PERMISSION).filter(production_date=filters["production_date"])
    counts = queryset.aggregate(report_count=Count("pk", distinct=True), employee_count=Count("lines__workshop_employee_id", distinct=True))
    items = [{"id": str(report.pk), "number": report.report_number, "task_number": report.task_number_snapshot,
              "workshop_name": report.workshop.name, "production_date": report.production_date,
              "lines": [{"operation": line.operation_name_snapshot or line.display_name_snapshot,
                         "quantity": decimal_string(line.quantity), "unit": line.unit_name_snapshot} for line in report.lines.all()],
              "href": f"/workshop/work-reports/days/{report.production_date}"}
             for report in queryset.select_related("workshop").prefetch_related("lines").order_by("-created_at", "-id")[:LIMIT]]
    return section({"date": filters["production_date"], **counts, "items": items,
                    "total": counts["report_count"], "truncated": counts["report_count"] > LIMIT}, empty=not counts["report_count"])


class ProductionDashboardView(APIView):
    permission_classes = [HasActiveEmployee]
    http_method_names = ["get", "head", "options"]

    @extend_schema(parameters=[DashboardFilters], responses=OpenApiTypes.OBJECT)
    def get(self, request):
        serializer = DashboardFilters(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        filters = serializer.validated_data
        permissions, sources = source_permissions(request)
        names = ("tasks", "outsourcing", "receipts", "workshop", "reports")
        if not any(permissions[name] for name in names):
            raise PermissionDenied("当前账号没有生产工作台所需的来源数据读取权限。")
        today = timezone.localdate()
        sections = {}
        builders = {
            "tasks": task_section, "outsourcing": outsourcing_section,
            "receipts": receipts_section, "workshop": workshop_section,
        }
        for name, builder in builders.items():
            if not permissions[name]:
                sections[name] = forbidden()
                continue
            with source_context(request, sources[name]):
                sections[name] = builder(request, filters, today) if name == "outsourcing" else builder(request, filters, today, permissions)
        sections["reports"] = reports_section(request, filters) if permissions["reports"] else forbidden()
        return Response({"data": {"generated_at": timezone.now(), "filters": filters, "sections": sections},
                         "meta": {"read_only": True}})
