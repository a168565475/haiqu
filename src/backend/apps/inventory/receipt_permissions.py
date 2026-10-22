"""待入库删除归属和仓库确认所需的局部计划访问。"""
from apps.access_control.module_policy import has_permission
from apps.access_control.selectors import current_assignments
from apps.core.auth import active_employee_for


ALL_PENDING_ROLES = {'WAREHOUSE_KEEPER', 'FACTORY_MANAGER', 'GENERAL_MANAGER'}
DIRECTOR_ROLES = {'METAL': 'METAL_DIRECTOR', 'SEWING': 'SEWING_DIRECTOR', 'ASSEMBLY': 'ASSEMBLY_DIRECTOR'}


def receipt_roles(request):
    if not hasattr(request, '_inventory_receipt_roles'):
        actor = active_employee_for(request.user)
        request._inventory_receipt_roles = set(current_assignments(actor).values_list(
            'role_profile__role_code', flat=True)) if actor else set()
    return request._inventory_receipt_roles


def can_delete_pending_receipt(request, receipt, category):
    if request is None or receipt.status != 'PENDING':
        return False
    actor = active_employee_for(request.user)
    permission = 'inventory.delete_finishedgoodsreceipt' if category == 'ASSEMBLY' else 'inventory.delete_internalsemifinishedreceipt'
    if actor is None or not has_permission(request, permission):
        return False
    if request.user.is_superuser:
        return True
    roles = receipt_roles(request)
    if roles & ALL_PENDING_ROLES:
        return True
    return (DIRECTOR_ROLES.get(category) in roles
            and receipt.submitted_by_employee_id == actor.pk)


def receipt_plans_for_category(request, category, *, confirmation=False):
    from apps.production_scheduling.models import ProductionScheduleProduct, ScheduleStatus
    from apps.production_scheduling.selectors import schedule_items_for_category
    permission = ('inventory.confirm_finishedgoodsreceipt' if category == 'ASSEMBLY'
                  else 'inventory.confirm_internalsemifinishedreceipt')
    warehouse_scope = (confirmation and active_employee_for(request.user) is not None
                       and has_permission(request, permission)
                       and (request.user.is_superuser or bool(receipt_roles(request) & ALL_PENDING_ROLES)))
    if not warehouse_scope:
        return schedule_items_for_category(request, category)
    # 仓库按入库职责确认来源，不因此获得作业计划模块的查看权限。
    return ProductionScheduleProduct.objects.filter(
        schedule__record_status=ScheduleStatus.ACTIVE, removed_at__isnull=True,
        crafts__removed_at__isnull=True, crafts__craft_type_snapshot='INTERNAL',
        crafts__plan_category=category,
    ).distinct().select_related('schedule', 'schedule__production_task',
        'schedule__production_task__customer_account', 'product_line', 'unit', 'image_file')
