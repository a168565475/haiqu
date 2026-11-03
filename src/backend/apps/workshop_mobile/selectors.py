from collections import defaultdict
from decimal import Decimal, ROUND_HALF_UP

from django.db.models import Q, Sum
from django.urls import reverse
from django.utils import timezone

from apps.access_control import module_policy, resource_scopes
from apps.material_issues.scopes import PLAN_WORKSHOP_NAMES
from apps.material_issues.services import ELIGIBLE_TASK_STATUSES
from apps.organizations.models import Employee
from apps.production_scheduling.models import ProductionScheduleProductCraft, ScheduleStatus
from apps.production_tasks.selectors import legacy_accessible_production_tasks, production_task_product_image
from apps.workshop_config.selectors import active_employees
from apps.workshop_config.constants import FIXED_WORKSHOP_NAMES
from apps.workshop_config.models import CraftType, PlanCategory, RecordStatus, Workshop
from apps.workshop_reporting.models import WageScheme, WageSchemeStatus, WorkReportLine, WorkshopPlanExecution, WorkshopPlanStatus
from apps.workshop_reporting.selectors import allowed_workshop_ids, reporting_source_products
from apps.workshop_reporting.services import WORK_REPORT_TASK_STATUSES, wage_scheme_progress
from apps.workshop_reporting.tube_plan_services import is_current_tube_scheme, tube_plan_is_complete

from .finished_receipts import FINISHED_RECEIPT_ADD, finished_receipt_products
from .semi_receipts import SEMI_RECEIPT_ADD, SEMI_RECEIPT_VIEW, semi_receipt_products

ISSUE_VIEW = "material_issues.view_materialissue"
ISSUE_ADD = "material_issues.add_materialissue"
ISSUE_SUBMIT = "material_issues.submit_materialissue"
REPORT_VIEW = "workshop_reporting.view_workreport"
REPORT_ADD = "workshop_reporting.add_workreport"
PLAN_LABELS = {value: label for value, label in PlanCategory.choices}


def mobile_workshop_filter(request):
    """切换是界面能力；仍按已有查看动作取范围，不按岗位名称另授权限。"""
    enabled = False
    if module_policy.has_permission(request, REPORT_VIEW):
        enabled = allowed_workshop_ids(request, for_work_reports=True, permission=REPORT_VIEW) is None
    if not enabled and module_policy.has_permission(request, ISSUE_VIEW):
        legacy_all_tasks = request.user.is_superuser or request.user.has_perm("production_tasks.view_all_productiontask")
        if resource_scopes.enforcing(request, ISSUE_VIEW):
            ids = resource_scopes.resource_ids(request, ISSUE_VIEW, "WORKSHOP", include_legacy=False)
            enabled = ids is None or (
                resource_scopes.has_legacy_permission(request, ISSUE_VIEW) and legacy_all_tasks
            )
        else:
            enabled = legacy_all_tasks
    if not enabled:
        return {"enabled": False, "options": [], "default_id": None}
    # 全车间查看权来自上面的业务范围；目录不依赖某页计划，也包含尚无计划的活跃车间。
    rows = list(Workshop.objects.filter(status=RecordStatus.ACTIVE).values("id", "name"))
    order = {name: index for index, name in enumerate(FIXED_WORKSHOP_NAMES)}
    rows.sort(key=lambda row: (order.get(row["name"], len(order)), row["name"], str(row["id"])))
    options = [{"id": str(row["id"]), "name": row["name"]} for row in rows]
    return {"enabled": True, "options": options, "default_id": options[0]["id"] if options else None}


def plan_links():
    return ProductionScheduleProductCraft.objects.filter(
        removed_at__isnull=True, craft_type_snapshot=CraftType.INTERNAL,
        craft__craft_type=CraftType.INTERNAL, craft__status=RecordStatus.ACTIVE,
        craft__workshop__status=RecordStatus.ACTIVE, plan_category__in=PlanCategory.values,
        schedule_product__removed_at__isnull=True,
        schedule_product__schedule__record_status=ScheduleStatus.ACTIVE,
        schedule_product__schedule__production_task__archived_at__isnull=True,
    )


def links_for_permission(queryset, request, permission):
    """每个动作独立取资源，避免一个车间的查看权放大另一动作的写入权。"""
    if not module_policy.has_permission(request, permission):
        return queryset.none()
    if permission == FINISHED_RECEIPT_ADD:
        queryset = queryset.filter(plan_category=PlanCategory.ASSEMBLY,
            schedule_product__in=finished_receipt_products(request))
    if permission == SEMI_RECEIPT_ADD:
        if not module_policy.has_permission(request, SEMI_RECEIPT_VIEW):
            return queryset.none()
        queryset = queryset.filter(
            Q(plan_category=PlanCategory.METAL, schedule_product__in=semi_receipt_products(request, PlanCategory.METAL))
            | Q(plan_category=PlanCategory.SEWING, schedule_product__in=semi_receipt_products(request, PlanCategory.SEWING))
        )
    if permission.startswith("workshop_reporting."):
        products = reporting_source_products(request, permission)
        queryset = queryset.filter(schedule_product__in=products)
        ids = allowed_workshop_ids(request, for_work_reports=True, permission=permission)
        return queryset if ids is None else queryset.filter(craft__workshop_id__in=ids)
    if not resource_scopes.enforcing(request, permission):
        return queryset.filter(schedule_product__schedule__production_task__in=legacy_accessible_production_tasks(request))
    ids = resource_scopes.resource_ids(request, permission, "WORKSHOP", include_legacy=False)
    if ids is None:
        return queryset
    selected = Q(craft__workshop_id__in=ids)
    if resource_scopes.has_legacy_permission(request, permission):
        selected |= Q(schedule_product__schedule__production_task__in=legacy_accessible_production_tasks(request))
    return queryset.filter(selected)


def visible_plan_links(request):
    base = plan_links()
    return base.filter(
        Q(pk__in=links_for_permission(base, request, ISSUE_VIEW).values("pk"))
        | Q(pk__in=links_for_permission(base, request, REPORT_VIEW).values("pk"))
        | Q(pk__in=links_for_permission(base, request, FINISHED_RECEIPT_ADD).values("pk"))
        | Q(pk__in=links_for_permission(base, request, SEMI_RECEIPT_ADD).values("pk"))
    )


def filtered_plan_keys(request, filters):
    queryset = visible_plan_links(request)
    if filters.get("search"):
        keyword = filters["search"]
        queryset = queryset.filter(
            Q(schedule_product__schedule__production_task__task_number__icontains=keyword)
            | Q(schedule_product__product_snapshot__product_name__icontains=keyword)
            | Q(schedule_product__product_snapshot__product_number__icontains=keyword)
            | Q(schedule_product__product_snapshot__specification__icontains=keyword)
            | Q(schedule_product__product_line__product_name_snapshot__icontains=keyword)
            | Q(schedule_product__product_line__product_number_snapshot__icontains=keyword)
            | Q(schedule_product__product_line__specification_snapshot__icontains=keyword)
        )
    if filters.get("plan_category"):
        queryset = queryset.filter(plan_category=filters["plan_category"])
    if filters.get("workshop_id"):
        queryset = queryset.filter(craft__workshop_id=filters["workshop_id"])
    if filters.get("production_task_id"):
        queryset = queryset.filter(schedule_product__schedule__production_task_id=filters["production_task_id"])
    if filters.get("status", "ALL") != "ALL":
        queryset = queryset.filter(schedule_product__schedule__production_task__status=filters["status"])
    return queryset.order_by(
        "schedule_product__schedule__production_task__task_number", "schedule_product_id", "plan_category", "craft__workshop_id",
    ).values(
        "schedule_product_id", "plan_category", "craft__workshop_id",
        "schedule_product__schedule__production_task__task_number",
    ).distinct()


def _key(row):
    return row["schedule_product_id"], row["plan_category"], row["craft__workshop_id"]


def _progress(metrics):
    if not metrics or any(metric is None for metric in metrics):
        return {"status": "NOT_CONFIGURED", "percentage": None, "reported_quantity": None, "required_quantity": None}
    required = sum((metric["required_total"] for metric in metrics), Decimal("0"))
    reported = sum((metric["reported_total"] for metric in metrics), Decimal("0"))
    percentage = int(min(Decimal("100"), reported * 100 / required).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    return {"status": "READY", "percentage": max(0, percentage), "reported_quantity": str(reported), "required_quantity": str(required)}


def mobile_plan_data(request, keys, *, production_date=None, include_people=False):
    if not keys:
        return []
    production_date = production_date or timezone.localdate()
    selected = Q(pk__in=[])
    for key in keys:
        selected |= Q(schedule_product_id=key["schedule_product_id"], plan_category=key["plan_category"], craft__workshop_id=key["craft__workshop_id"])
    queryset = visible_plan_links(request).filter(selected)
    permission_ids = {
        code: set(links_for_permission(queryset, request, code).values_list("pk", flat=True))
        for code in (ISSUE_VIEW, ISSUE_ADD, ISSUE_SUBMIT, REPORT_VIEW, REPORT_ADD, FINISHED_RECEIPT_ADD, SEMI_RECEIPT_ADD)
    }
    links = list(queryset.select_related(
        "craft__workshop", "schedule_product__schedule__production_task", "schedule_product__product_line__image_file",
        "schedule_product__product_line__production_task",
        "schedule_product__product_line__sales_order_delivery_batch_line__sales_order_line__product_image",
    ).prefetch_related("schedule_product__product_line__images__image_file").order_by("craft__name", "id"))
    grouped = defaultdict(list)
    for link in links:
        grouped[(link.schedule_product_id, link.plan_category, link.craft.workshop_id)].append(link)
    report_links = [link for link in links if link.pk in permission_ids[REPORT_VIEW]]
    schemes_by_scope = defaultdict(list)
    cumulative = defaultdict(dict)
    executions = {}
    if report_links:
        product_ids = {link.schedule_product_id for link in report_links}
        workshop_ids = {link.craft.workshop_id for link in report_links}
        schemes = WageScheme.objects.filter(
            product_line_id__in={link.schedule_product.product_line_id for link in report_links},
            workshop_id__in=workshop_ids, scope_craft_id__in={link.craft_id for link in report_links},
            status=WageSchemeStatus.APPROVED, effective_from__lte=production_date,
        ).filter(Q(effective_to__isnull=True) | Q(effective_to__gte=production_date)).prefetch_related("lines")
        for scheme in schemes:
            schemes_by_scope[(scheme.product_line_id, scheme.workshop_id, scheme.scope_craft_id)].append(scheme)
        for row in WorkReportLine.objects.filter(
            report__schedule_product_id__in=product_ids, report__workshop_id__in=workshop_ids,
        ).values("report__schedule_product_id", "report__workshop_id", "work_item_id").annotate(total=Sum("quantity")):
            cumulative[(row["report__schedule_product_id"], row["report__workshop_id"])][row["work_item_id"]] = row["total"]
        executions = {
            (item.schedule_product_id, item.craft_id): item.status
            for item in WorkshopPlanExecution.objects.filter(schedule_product_id__in=product_ids, craft_id__in={link.craft_id for link in report_links})
        }
    employees_by_workshop = defaultdict(list)
    if include_people:
        people_workshops = {link.craft.workshop_id for link in links if link.pk in permission_ids[ISSUE_VIEW] or link.pk in permission_ids[REPORT_VIEW]}
        for employee in active_employees(Employee.objects.filter(workshop_id__in=people_workshops)).order_by("display_name", "id"):
            employees_by_workshop[employee.workshop_id].append({"id": str(employee.pk), "name": employee.display_name, "workshop_id": str(employee.workshop_id)})
    result = []
    for key in keys:
        group = grouped.get(_key(key))
        if not group:
            # 分页后排产或权限可能已变化；不继续使用过期键返回业务数据。
            continue
        source = group[0].schedule_product
        task = source.schedule.production_task
        product = source.product_line
        product_snapshot = source.product_snapshot or {}
        workshop = group[0].craft.workshop
        category = key["plan_category"]
        issue_visible = any(link.pk in permission_ids[ISSUE_VIEW] for link in group)
        report_visible = any(link.pk in permission_ids[REPORT_VIEW] for link in group)
        issue_allowed = any(link.pk in permission_ids[ISSUE_VIEW] & permission_ids[ISSUE_ADD] & permission_ids[ISSUE_SUBMIT] for link in group)
        issue_reason = "" if issue_allowed else "当前账号没有该车间的领料申请权限。"
        finished_receipt_reason = ""
        if category != PlanCategory.ASSEMBLY:
            finished_receipt_reason = "只有装配计划可以办理成品入库。"
        elif not any(link.pk in permission_ids[FINISHED_RECEIPT_ADD] for link in group):
            finished_receipt_reason = "当前账号没有该装配计划的成品入库权限。"
        elif task.status != 'IN_PRODUCTION':
            finished_receipt_reason = "只有生产中的订单产品可以办理成品入库。"
        semi_receipt_reason = ""
        if category not in {PlanCategory.METAL, PlanCategory.SEWING}:
            semi_receipt_reason = "只有金工、车缝计划可以办理半成品入库。"
        elif not any(link.pk in permission_ids[SEMI_RECEIPT_ADD] for link in group):
            semi_receipt_reason = "当前账号没有该计划的半成品入库查看和提交权限。"
        elif task.status != 'IN_PRODUCTION':
            semi_receipt_reason = "只有生产中的订单产品可以办理半成品入库。"
        if issue_allowed and task.status not in ELIGIBLE_TASK_STATUSES:
            issue_reason = "当前生产任务状态不能申请领料。"
        if issue_allowed and PLAN_WORKSHOP_NAMES.get(category) != workshop.name:
            issue_reason = "该计划类型与领料车间不一致，暂不能申请领料。"
        reporting_crafts = []
        metrics = []
        for link in group:
            if link.pk not in permission_ids[REPORT_VIEW]:
                continue
            candidates = schemes_by_scope.get((source.product_line_id, workshop.pk, link.craft_id), [])
            scheme = candidates[0] if len(candidates) == 1 else None
            counts = cumulative.get((source.pk, workshop.pk), {})
            metric = wage_scheme_progress(scheme, counts) if scheme else None
            plan_status = executions.get((source.pk, link.craft_id), WorkshopPlanStatus.IN_PROGRESS)
            if scheme and plan_status == WorkshopPlanStatus.COMPLETED and is_current_tube_scheme(scheme) and not tube_plan_is_complete(source.pk, scheme, cumulative_by_work_item=counts):
                plan_status = WorkshopPlanStatus.IN_PROGRESS
            reason = ""
            if link.pk not in permission_ids[REPORT_ADD]:
                reason = "当前账号没有该车间的报工权限。"
            elif task.status not in WORK_REPORT_TASK_STATUSES:
                reason = "生产任务当前状态不允许报工。"
            elif not scheme:
                reason = "当前日期存在多个适用工价版本。" if len(candidates) > 1 else "当前日期没有适用的已批准工价方案。"
            elif metric is None:
                reason = "工价方案缺少需完成次数，请联系负责人配置。"
            elif plan_status == WorkshopPlanStatus.COMPLETED:
                reason = "当前生产计划已完成。"
            can_open_report = (
                link.pk in permission_ids[REPORT_ADD]
                and task.status in WORK_REPORT_TASK_STATUSES
                and plan_status != WorkshopPlanStatus.COMPLETED
            )
            metrics.append(metric)
            reporting_crafts.append({
                "id": str(link.craft_id), "name": link.craft.name,
                "scheme_id": str(scheme.pk) if scheme else None, "scheme_revision": scheme.revision if scheme else None,
                "can_report": not reason, "can_open_report": can_open_report, "reason": reason, "plan_status": plan_status,
                "progress": _progress([metric]),
            })
        can_report = any(item["can_report"] for item in reporting_crafts)
        report_reason = "" if can_report else (reporting_crafts[0]["reason"] if reporting_crafts else "当前账号没有该车间的报工查看权限。")
        image = production_task_product_image(product)
        image_url = None
        if image and image.content_type.startswith("image/") and (report_visible or issue_visible):
            image_url = reverse("work-report-task-product-image", kwargs={"task_id": task.pk, "product_line_id": product.pk}) if report_visible else reverse("material-issue-product-image", kwargs={"task_id": task.pk, "file_id": image.pk})
        data = {
            "key": f"{source.pk}:{category}:{workshop.pk}", "schedule_product_id": str(source.pk), "schedule_id": str(source.schedule_id),
            "production_task_id": str(task.pk), "product_line_id": str(product.pk), "task_number": task.task_number,
            "schedule_number": source.schedule.schedule_number,
            "product": {"name": product_snapshot.get("product_name", product.product_name_snapshot), "number": product_snapshot.get("product_number", product.product_number_snapshot), "specification": product_snapshot.get("specification", product.specification_snapshot),
                        "color": product_snapshot.get("color_name", product.color_name_snapshot), "material": product_snapshot.get("material", product.material_snapshot),
                        "quantity": str(source.planned_quantity), "order_quantity": str(source.source_quantity_snapshot), "unit": source.unit_name_snapshot, "image_url": image_url},
            "plan_category": category, "plan_category_label": PLAN_LABELS[category], "workshop": {"id": str(workshop.pk), "name": workshop.name},
            "plan_date": {"METAL": source.metal_return_date, "CUTTING": source.sewing_return_date, "SEWING": source.sewing_return_date, "ASSEMBLY": source.finished_inbound_date}[category],
            "task_status": task.status, "task_status_display": task.get_status_display(), "production_date": production_date,
            "can_view_issues": issue_visible, "can_view_reports": report_visible,
            "can_issue": issue_allowed and not issue_reason, "issue_reason": issue_reason,
            "can_report": can_report, "can_open_report": any(item["can_open_report"] for item in reporting_crafts), "report_reason": report_reason,
            "can_receive_finished": not finished_receipt_reason, "finished_receipt_reason": finished_receipt_reason,
            "can_receive_semi": not semi_receipt_reason, "semi_receipt_reason": semi_receipt_reason,
            "progress": _progress(metrics) if report_visible else None, "reporting_crafts": reporting_crafts,
        }
        if include_people:
            data["recipients"] = employees_by_workshop[workshop.pk] if issue_visible else []
            data["reporting_employees"] = employees_by_workshop[workshop.pk] if report_visible else []
        result.append(data)
    return result
