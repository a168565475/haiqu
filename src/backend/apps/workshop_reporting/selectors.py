from decimal import Decimal, ROUND_HALF_UP, localcontext

from django.db.models import Prefetch, Q, Sum
from django.urls import reverse
from django.utils import timezone

from .models import WageScheme, WageSchemeLine, WageSchemeStatus, WorkshopReportingScope, WorkReport, WorkReportLine


def reporting_source_products(request, permission):
    from apps.access_control.resource_scopes import enabled
    from apps.production_scheduling.models import ProductionScheduleProduct, ScheduleStatus
    from apps.production_scheduling.selectors import accessible_production_schedules
    queryset = ProductionScheduleProduct.objects.filter(
        removed_at__isnull=True, schedule__record_status=ScheduleStatus.ACTIVE)
    if not enabled():
        return queryset.filter(schedule__in=accessible_production_schedules(request))
    ids = allowed_workshop_ids(request, permission=permission, for_work_reports=permission.endswith('workreport'))
    if ids is not None:
        queryset = queryset.filter(crafts__removed_at__isnull=True, crafts__craft__workshop_id__in=ids)
    return queryset.distinct()


def allowed_workshop_ids(request, *, for_work_reports=False, permission=None):
    from apps.access_control import module_policy
    from apps.access_control import resource_scopes
    default = 'workshop_reporting.view_workreport' if for_work_reports else 'workshop_reporting.view_wagescheme'
    code = permission or resource_scopes.current_permission(request, default)
    if resource_scopes.enforcing(request, code):
        ids = resource_scopes.resource_ids(request, code, 'WORKSHOP', include_legacy=False)
        if ids is None:
            return None
        from apps.access_control.sales_policy import access_for
        access = access_for(request)
        legacy = {row['permission'] for row in access['legacy_sources']}
        if code in legacy:
            global_code = 'workshop_reporting.view_all_workreport' if for_work_reports else 'workshop_reporting.view_all_wagescheme'
            if global_code in legacy:
                return None
            ids.update(str(pk) for pk in WorkshopReportingScope.objects.filter(
                employee=request.employee, is_active=True).values_list('workshop_id', flat=True))
        from apps.workshop_config.models import Workshop
        return Workshop.objects.filter(pk__in=ids).values_list('pk', flat=True)
    if module_policy.enabled() and module_policy.has_module_grant(request, 'workshop_reporting'):
        return None
    global_permission = (
        "workshop_reporting.view_all_workreport"
        if for_work_reports else "workshop_reporting.view_all_wagescheme"
    )
    if request.user.is_superuser or request.user.has_perm(global_permission):
        return None
    return WorkshopReportingScope.objects.filter(
        employee=request.employee, is_active=True
    ).values_list("workshop_id", flat=True)


def accessible_wage_schemes(request, permission=None):
    queryset = WageScheme.objects.all()
    workshop_ids = allowed_workshop_ids(request, permission=permission)
    if workshop_ids is not None:
        queryset = queryset.filter(workshop_id__in=workshop_ids)
    return queryset


def wage_schemes_with_context(queryset=None):
    queryset = queryset if queryset is not None else WageScheme.objects.all()
    return queryset.select_related(
        "product_line", "product_line__production_task", "workshop", "scope_craft", "schedule_product",
        "created_by_employee", "updated_by_employee", "approved_by_employee", "parent_scheme",
    ).prefetch_related(
        Prefetch("lines", queryset=WageSchemeLine.objects.select_related("work_item", "work_item__craft", "work_item__operation")),
        "scheme_crafts__craft", "events__actor_employee", "change_versions",
    )


def accessible_work_reports(request, permission=None):
    queryset = WorkReport.objects.all()
    workshop_ids = allowed_workshop_ids(request, for_work_reports=True, permission=permission)
    if workshop_ids is not None:
        queryset = queryset.filter(workshop_id__in=workshop_ids)
    return queryset


def work_report_selection_sources(request):
    from apps.production_scheduling.models import ProductionScheduleProductCraft
    from apps.workshop_config.models import CraftType, RecordStatus

    permission = "workshop_reporting.view_workreport"
    reports = accessible_work_reports(request, permission=permission)
    products = reporting_source_products(request, permission)
    crafts = ProductionScheduleProductCraft.objects.filter(
        schedule_product__in=products, removed_at__isnull=True,
        craft_type_snapshot=CraftType.INTERNAL, craft__craft_type=CraftType.INTERNAL,
        craft__status=RecordStatus.ACTIVE, craft__workshop__status=RecordStatus.ACTIVE,
    )
    workshop_ids = allowed_workshop_ids(request, for_work_reports=True, permission=permission)
    if workshop_ids is not None:
        crafts = crafts.filter(craft__workshop_id__in=workshop_ids)
    return reports, crafts


def work_report_tasks(reports, crafts, keyword=""):
    from apps.production_tasks.models import ProductionTask

    queryset = ProductionTask.objects.filter(
        Q(pk__in=reports.order_by().values("product_line__production_task_id"))
        | Q(pk__in=crafts.order_by().values("schedule_product__schedule__production_task_id"))
    )
    if keyword:
        queryset = queryset.filter(Q(task_number__icontains=keyword) | Q(order_number__icontains=keyword))
    return queryset.order_by("-created_at", "-id")


def work_report_task_products(reports, crafts):
    from apps.production_tasks.models import ProductionTaskProduct

    return ProductionTaskProduct.objects.filter(
        Q(pk__in=reports.order_by().values("product_line_id"))
        | Q(pk__in=crafts.order_by().values("schedule_product__product_line_id"))
    ).select_related(
        "production_task", "image_file", "sales_order_delivery_batch_line__sales_order_line__product_image",
    ).prefetch_related("images__image_file").order_by("production_task_id", "line_number", "id")


def _work_report_progress(metrics):
    if not metrics:
        return {"status": "UNAVAILABLE", "percentage": None}
    if any(metric is None for metric in metrics):
        return {"status": "NOT_CONFIGURED", "percentage": None}
    with localcontext() as context:
        context.prec = 48
        required = sum((metric["required_total"] for metric in metrics), Decimal("0"))
        reported = sum((metric["reported_total"] for metric in metrics), Decimal("0"))
        percentage = int(min(Decimal("100"), reported * 100 / required).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP,
        ))
    return {"status": "READY", "percentage": max(0, percentage)}


def work_report_task_cards(tasks, reports, crafts):
    from apps.production_tasks.selectors import production_task_product_image
    from .services import wage_scheme_progress

    task_ids = [task.pk for task in tasks]
    reports = reports.filter(product_line__production_task_id__in=task_ids)
    crafts = crafts.filter(schedule_product__schedule__production_task_id__in=task_ids)
    products_by_task = {task_id: [] for task_id in task_ids}
    for product in work_report_task_products(reports, crafts):
        products_by_task[product.production_task_id].append(product)

    workshops_by_task = {task_id: {} for task_id in task_ids}
    amounts = {}
    # 金额独立从授权报工行汇总，避免连接产品或工艺清单后重复计费。
    for row in reports.order_by().values(
        "product_line__production_task_id", "workshop_id", "workshop__name",
    ).annotate(amount=Sum("lines__amount")):
        task_id, workshop_id = row["product_line__production_task_id"], row["workshop_id"]
        workshops_by_task[task_id][workshop_id] = row["workshop__name"]
        amounts[(task_id, workshop_id)] = row["amount"] or Decimal("0")

    scopes_by_workshop = {}
    for link in crafts.select_related("schedule_product__product_line", "craft__workshop"):
        product = link.schedule_product
        task_id, workshop_id = product.product_line.production_task_id, link.craft.workshop_id
        workshops_by_task[task_id][workshop_id] = link.craft.workshop.name
        scopes_by_workshop.setdefault((task_id, workshop_id), set()).add(
            (product.pk, product.product_line_id, workshop_id, link.craft_id)
        )
    scopes = {scope for values in scopes_by_workshop.values() for scope in values}
    today = timezone.localdate()
    schemes = WageScheme.objects.filter(
        product_line_id__in={scope[1] for scope in scopes},
        workshop_id__in={scope[2] for scope in scopes},
        scope_craft_id__in={scope[3] for scope in scopes},
        status=WageSchemeStatus.APPROVED, effective_from__lte=today,
    ).filter(Q(effective_to__isnull=True) | Q(effective_to__gte=today)).prefetch_related("lines")
    schemes_by_scope = {}
    for scheme in schemes:
        schemes_by_scope.setdefault((scheme.product_line_id, scheme.workshop_id, scheme.scope_craft_id), []).append(scheme)
    cumulative_by_plan = {}
    for (product_id, workshop_id, work_item_id), quantity in work_report_cumulative_quantities(
        reports.filter(schedule_product_id__in={scope[0] for scope in scopes}),
    ).items():
        cumulative_by_plan.setdefault((product_id, workshop_id), {})[work_item_id] = quantity

    payload = []
    for task in tasks:
        task_metrics = []
        workshops = []
        for workshop_id, name in sorted(workshops_by_task[task.pk].items(), key=lambda item: (item[1], str(item[0]))):
            metrics = []
            for product_id, product_line_id, scope_workshop_id, craft_id in scopes_by_workshop.get((task.pk, workshop_id), set()):
                candidates = schemes_by_scope.get((product_line_id, scope_workshop_id, craft_id), [])
                metrics.append(wage_scheme_progress(
                    candidates[0], cumulative_by_plan.get((product_id, workshop_id), {}),
                ) if len(candidates) == 1 else None)
            task_metrics.extend(metrics)
            workshops.append({
                "id": str(workshop_id), "name": name,
                "reported_amount": format(amounts.get((task.pk, workshop_id), Decimal("0")), ".2f"),
                "progress": _work_report_progress(metrics),
            })
        products = products_by_task[task.pk]
        product_data = None
        if products:
            product = products[0]
            image = production_task_product_image(product)
            product_data = {
                "id": str(product.pk), "name": product.product_name_snapshot,
                "number": product.product_number_snapshot,
                "image_url": reverse("work-report-task-product-image", kwargs={
                    "task_id": task.pk, "product_line_id": product.pk,
                }) if image and image.content_type.startswith("image/") else None,
            }
        with localcontext() as context:
            context.prec = 48
            amount = sum((Decimal(workshop["reported_amount"]) for workshop in workshops), Decimal("0"))
        payload.append({
            "id": str(task.pk), "task_number": task.task_number, "order_number": task.order_number,
            "product": product_data, "product_count": len(products), "reported_amount": format(amount, ".2f"),
            "progress": _work_report_progress(task_metrics), "workshops": workshops,
        })
    return payload


def wage_scheme_line_metrics(request, scheme):
    from apps.access_control.module_policy import has_permission

    permission = "workshop_reporting.view_workreport"
    if not has_permission(request, permission):
        return {}
    workshop_ids = allowed_workshop_ids(request, for_work_reports=True, permission=permission)
    if workshop_ids is not None and str(scheme.workshop_id) not in {str(pk) for pk in workshop_ids}:
        return {}

    work_item_ids = {line.work_item_id for line in scheme.lines.all()}
    metrics = {
        work_item_id: {"completed_quantity": "0", "completed_amount": "0.00"}
        for work_item_id in work_item_ids
    }
    lines = WorkReportLine.objects.filter(
        report__product_line_id=scheme.product_line_id,
        report__workshop_id=scheme.workshop_id,
        report__scheme__scope_craft_id=scheme.scope_craft_id,
        work_item_id__in=work_item_ids,
    )
    if scheme.schedule_product_id:
        lines = lines.filter(report__schedule_product_id=scheme.schedule_product_id)
    # 工作项跨工价版本累计，金额使用报工时保存的快照，不按当前工价重算。
    for row in lines.order_by().values("work_item_id").annotate(
        completed_quantity=Sum("quantity"), completed_amount=Sum("amount"),
    ):
        metrics[row["work_item_id"]] = {
            "completed_quantity": str(row["completed_quantity"]),
            "completed_amount": str(row["completed_amount"]),
        }
    return metrics


def work_reports_with_context(queryset=None):
    queryset = queryset if queryset is not None else WorkReport.objects.all()
    return queryset.select_related(
        "product_line", "product_line__production_task", "schedule_product", "workshop", "scheme", "scheme__scope_craft",
        "recorder_employee", "updated_by_employee",
    ).prefetch_related(
        "lines__workshop_employee",
        "lines__scheme_line",
        "lines__work_item__operation",
    )


def work_report_cumulative_quantities(reports):
    return {
        (row["report__schedule_product_id"], row["report__workshop_id"], row["work_item_id"]): row["quantity"]
        for row in WorkReportLine.objects.filter(report__in=reports).order_by().values(
            "report__schedule_product_id", "report__workshop_id", "work_item_id",
        ).annotate(quantity=Sum("quantity"))
    }


def search_wage_schemes(queryset, keyword):
    if not keyword:
        return queryset
    return queryset.filter(
        Q(scheme_number__icontains=keyword)
        | Q(product_line__production_task__task_number__icontains=keyword)
        | Q(product_line__production_task__order_number__icontains=keyword)
        | Q(product_name_snapshot__icontains=keyword)
    )
