from django.db.models import Exists, OuterRef, Prefetch, Q

from apps.production_tasks.selectors import (
    accessible_production_tasks,
    legacy_accessible_production_tasks,
    production_task_product_image as schedule_product_image,
    production_task_source_image_ids as schedule_source_image_ids,
)

from .models import ProductionSchedule, ProductionScheduleProduct, ProductionScheduleProductCraft, ScheduleStatus


def accessible_production_schedules(request):
    queryset = ProductionSchedule.objects.all()
    from apps.access_control.workshop_scopes import filter_schedules
    from apps.access_control.resource_scopes import enforcing, current_permission
    from apps.access_control.role_policy import filter_task_scope
    code = current_permission(request, 'production_scheduling.view_productionschedule')
    if request.user.is_superuser or (code == 'production_scheduling.view_productionschedule'
                                   and request.user.has_perm("production_scheduling.view_all_productionschedule")):
        return queryset
    legacy = queryset.filter(production_task_id__in=legacy_accessible_production_tasks(request).values('id'))
    if enforcing(request, code):
        from apps.access_control.resource_scopes import has_legacy_permission
        selected = filter_schedules(queryset, request, code)
        selected = selected.distinct() | filter_task_scope(request, queryset, code).distinct()
        return selected.distinct() | legacy.distinct() if has_legacy_permission(request, code) else selected
    task_ids = accessible_production_tasks(request).values("id")
    return queryset.filter(production_task_id__in=task_ids)


def schedules_with_context(queryset=None, request=None):
    queryset = queryset if queryset is not None else ProductionSchedule.objects.all()
    active_crafts = ProductionScheduleProductCraft.objects.filter(removed_at__isnull=True).select_related("craft")
    active_products = ProductionScheduleProduct.objects.filter(removed_at__isnull=True).select_related(
        "product_line", "unit", "image_file"
    ).prefetch_related(Prefetch("crafts", queryset=active_crafts, to_attr="active_crafts"))
    if request is not None:
        from apps.access_control.resource_scopes import current_permission, resource_ids
        code = current_permission(request, 'production_scheduling.view_productionschedule')
        ids = resource_ids(request, code, 'WORKSHOP', include_legacy=False)
        if ids is not None:
            from apps.access_control.resource_scopes import has_legacy_permission
            from apps.access_control.role_policy import filter_task_scope
            allowed = Q(craft__workshop_id__in=ids)
            followed = filter_task_scope(request, ProductionSchedule.objects.all(), code)
            allowed |= Q(schedule_product__schedule__in=followed)
            if has_legacy_permission(request, code):
                allowed |= Q(schedule_product__schedule__production_task_id__in=legacy_accessible_production_tasks(request).values('id'))
            if code == 'production_scheduling.view_productionschedule' and request.user.has_perm('production_scheduling.view_all_productionschedule'):
                allowed = Q()
            active_crafts = active_crafts.filter(allowed)
            active_products = active_products.prefetch_related(None).filter(
                Q(crafts__in=active_crafts) | Q(schedule__in=followed)).distinct().prefetch_related(
                    Prefetch('crafts', queryset=active_crafts, to_attr='active_crafts'))
    return queryset.select_related(
        "production_task", "production_task__customer_account", "created_by_employee", "updated_by_employee",
        "voided_by_employee",
    ).prefetch_related(Prefetch("products", queryset=active_products, to_attr="active_products"), "production_task__followers")


def schedule_plan_categories(request):
    from apps.access_control.resource_scopes import has_legacy_permission, resource_ids
    from apps.access_control.sales_policy import access_for
    from apps.material_issues.scopes import PLAN_WORKSHOP_NAMES
    from apps.workshop_config.models import PlanCategory, Workshop

    code = "production_scheduling.view_productionschedule"
    ids = resource_ids(request, code, "WORKSHOP", include_legacy=False)
    if ids is None or request.user.has_perm("production_scheduling.view_all_productionschedule"):
        return PlanCategory.values
    names = set(Workshop.objects.filter(pk__in=ids).values_list("name", flat=True))
    access = access_for(request)["actions"].get(code, {})
    has_task_scope = "FOLLOWED" in access.get("scopes", []) or has_legacy_permission(request, code)
    return [
        category for category in PlanCategory.values
        if PLAN_WORKSHOP_NAMES[category] in names
        or (has_task_scope and schedule_items_for_category(request, category).exists())
    ]


def available_internal_craft_links(links):
    from apps.outsourcing.sewing_assignments import internal_sewing_products
    return links.filter(~Q(plan_category="SEWING") | Q(schedule_product_id__in=internal_sewing_products().values("pk")))


def schedule_items_for_category(request, category):
    from apps.access_control.resource_scopes import resource_ids, has_legacy_permission
    from apps.access_control.role_policy import filter_task_scope
    code = 'production_scheduling.view_productionschedule'
    ids = resource_ids(request, code, 'WORKSHOP', include_legacy=False)
    craft_match = ProductionScheduleProductCraft.objects.filter(
        schedule_product_id=OuterRef("pk"), removed_at__isnull=True,
        craft_type_snapshot="INTERNAL", plan_category=category,
    )
    if category == "SEWING":
        craft_match = available_internal_craft_links(craft_match)
    visible_crafts = ProductionScheduleProductCraft.objects.filter(removed_at__isnull=True)
    if ids is not None:
        allowed = Q(craft__workshop_id__in=ids)
        allowed |= Q(schedule_product__schedule__in=filter_task_scope(request, ProductionSchedule.objects.all(), code))
        if has_legacy_permission(request, code):
            allowed |= Q(schedule_product__schedule__production_task_id__in=legacy_accessible_production_tasks(request).values('id'))
        if request.user.has_perm('production_scheduling.view_all_productionschedule'):
            allowed = Q()
        craft_match = craft_match.filter(allowed)
        visible_crafts = visible_crafts.filter(allowed)
    schedule_ids = accessible_production_schedules(request).filter(
        record_status=ScheduleStatus.ACTIVE
    ).values("id")
    return ProductionScheduleProduct.objects.filter(
        schedule_id__in=schedule_ids, removed_at__isnull=True,
    ).annotate(_category_match=Exists(craft_match)).filter(_category_match=True).select_related(
        "schedule", "schedule__production_task", "schedule__production_task__customer_account",
        "product_line", "unit", "image_file",
    ).prefetch_related(
        Prefetch("crafts", queryset=visible_crafts, to_attr="active_crafts")
    )
