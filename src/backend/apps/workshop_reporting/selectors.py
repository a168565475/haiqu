from django.db.models import Prefetch, Q

from .models import WageScheme, WageSchemeLine, WorkshopReportingScope, WorkReport


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
    if resource_scopes.enabled():
        default = 'workshop_reporting.view_workreport' if for_work_reports else 'workshop_reporting.view_wagescheme'
        code = permission or resource_scopes.current_permission(request, default)
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


def search_wage_schemes(queryset, keyword):
    if not keyword:
        return queryset
    return queryset.filter(
        Q(scheme_number__icontains=keyword)
        | Q(product_line__production_task__task_number__icontains=keyword)
        | Q(product_line__production_task__order_number__icontains=keyword)
        | Q(product_name_snapshot__icontains=keyword)
    )
