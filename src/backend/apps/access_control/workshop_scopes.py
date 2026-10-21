"""计划、领料按当前动作解析资源；空资源始终返回空集合。"""
from rest_framework.exceptions import PermissionDenied

from .resource_scopes import current_permission, resource_ids, has_legacy_permission


def workshop_ids(request, permission):
    return resource_ids(request, permission, 'WORKSHOP')


def filter_task_products(queryset, request, permission):
    ids = resource_ids(request, permission, 'WORKSHOP', include_legacy=False)
    if ids is None:
        return queryset
    selected = queryset.filter(schedule_products__removed_at__isnull=True,
        schedule_products__schedule__record_status='ACTIVE',
        schedule_products__crafts__removed_at__isnull=True,
        schedule_products__crafts__craft__workshop_id__in=ids).distinct()
    if has_legacy_permission(request, permission):
        from apps.production_tasks.selectors import legacy_accessible_production_tasks
        return selected | queryset.filter(production_task_id__in=legacy_accessible_production_tasks(request).values('id')).distinct()
    return selected


def require_task_workshop(request, permission, task_id, workshop_id, *, owner_id=None, legacy_global=None):
    ids = resource_ids(request, permission, 'WORKSHOP', include_legacy=False)
    if ids is None or str(workshop_id) in ids:
        return
    if has_legacy_permission(request, permission):
        from apps.production_tasks.selectors import legacy_accessible_production_tasks
        if (legacy_global and request.user.has_perm(legacy_global)) or (
            task_id is None and owner_id == getattr(request.employee, 'pk', None)
        ) or legacy_accessible_production_tasks(request).filter(pk=task_id).exists():
            return
    raise PermissionDenied('当前动作未授权该任务与车间范围。')


def filter_schedules(queryset, request, permission=None):
    permission = permission or current_permission(request, 'production_scheduling.view_productionschedule')
    ids = resource_ids(request, permission, 'WORKSHOP', include_legacy=False)
    if ids is None:
        return queryset
    return queryset.filter(products__removed_at__isnull=True, products__crafts__removed_at__isnull=True,
                           products__crafts__craft__workshop_id__in=ids).distinct()


def require_schedule_write(request, permission, craft_ids, schedule=None, *, task_id=None):
    if request is None:
        return
    ids = resource_ids(request, permission, 'WORKSHOP', include_legacy=False)
    if ids is None:
        return
    if has_legacy_permission(request, permission):
        from apps.production_tasks.selectors import legacy_accessible_production_tasks
        if (schedule is not None and request.user.has_perm('production_scheduling.view_all_productionschedule')) or legacy_accessible_production_tasks(request).filter(
            pk=schedule.production_task_id if schedule is not None else task_id).exists():
            return
    from apps.workshop_config.models import Craft
    crafts = Craft.objects.filter(pk__in=craft_ids)
    if schedule is not None:
        crafts = crafts | Craft.objects.filter(schedule_product_links__schedule_product__schedule=schedule,
            schedule_product_links__removed_at__isnull=True,
            schedule_product_links__schedule_product__removed_at__isnull=True)
    # 整单修改会影响所有工艺；不能用“含一个本车间工艺”获得整单写权。
    if not crafts.exists() or crafts.exclude(workshop_id__in=ids).exists():
        raise PermissionDenied('当前操作超出授权车间，不能修改整张计划。')
