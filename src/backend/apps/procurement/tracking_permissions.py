"""跟踪页面与后台通知共用真实账号的采购查看范围。"""
from django.conf import settings
from django.db.models import Q
from django.utils import timezone

from apps.access_control.selectors import effective_access
from apps.customers.models import CustomerAccount, CustomerAssignment, CustomerDataAccessGrant
from apps.organizations.models import Employee
from apps.production_tasks.models import ProductionTask


VIEW_PERMISSION = 'procurement.view_purchaseorder'


def _legacy_customers(user, employee, access):
    """沿用客户归属规则，不把其他业务的模块授权变成采购全量查看。"""
    now = timezone.now()
    period = Q(effective_from__lte=now) & (Q(effective_to__isnull=True) | Q(effective_to__gt=now))
    assignments = CustomerAssignment.objects.filter(period)
    grants = CustomerDataAccessGrant.objects.filter(period, employee=employee, revoked_at__isnull=True,
        permission__content_type__app_label='customers', permission__codename='view_customeraccount')
    legacy_ids = assignments.filter(employee=employee).values('customer_account_id')
    legacy_query = Q(pk__in=legacy_ids) | Q(pk__in=grants.values('customer_account_id'))
    if not getattr(settings, 'SALES_ACCESS_ENABLED', False):
        return CustomerAccount.objects.all() if user.has_perm('customers.view_all_customer') else CustomerAccount.objects.filter(legacy_query)
    code = 'customers.view_customeraccount'
    scopes = set(access['actions'].get(code, {}).get('scopes', []))
    if 'ALL' in scopes:
        return CustomerAccount.objects.all()
    owners = Q(pk__in=[])
    if 'OWN' in scopes:
        owners |= Q(pk=employee.pk)
    if 'TEAM' in scopes:
        from apps.access_control.models import SalesTeamMembership
        owners |= Q(pk__in=SalesTeamMembership.objects.filter(team__manager=employee,
            team__is_active=True).values('employee_id'))
    allowed = Q(pk__in=assignments.filter(assignment_role='PRIMARY_OWNER',
        employee__in=Employee.objects.filter(owners)).values('customer_account_id'))
    legacy = {row['permission'] for row in access['legacy_sources']}
    if code in legacy:
        if user.has_perm('customers.view_all_customer'):
            return CustomerAccount.objects.all()
        allowed |= legacy_query
    if scopes or code in legacy:
        allowed |= Q(pk__in=assignments.filter(employee=employee, assignment_role='COLLABORATOR').values('customer_account_id'))
        allowed |= Q(pk__in=grants.values('customer_account_id'))
    return CustomerAccount.objects.filter(allowed)


def _task_queryset(user, employee, permission, access):
    queryset = ProductionTask.objects.all()
    if not access['active']:
        return queryset.none()
    if access['is_superuser']:
        return queryset
    legacy = {row['permission'] for row in access['legacy_sources']}
    entry = access['actions'].get(permission, {})
    # 关闭模块开关不能把已配置的 FOLLOWED/WORKSHOP 投影变成旧的宽范围权限。
    scopes = set(entry.get('scopes', []))
    granted = bool(scopes or permission in legacy) if getattr(settings, 'MODULE_ACCESS_ENABLED', False) else user.has_perm(permission)
    if not granted:
        return queryset.none()
    if scopes & {'MODULE', 'ALL'}:
        return queryset
    has_legacy = permission in legacy or (not scopes and not getattr(settings, 'MODULE_ACCESS_ENABLED', False))
    allowed = Q(pk__in=[])
    if 'FOLLOWED' in scopes:
        allowed |= Q(followers=employee)
    workshop_ids = {identifier for source in entry.get('sources', []) if source.get('scope') == 'WORKSHOP'
                    for identifier in source.get('resource_ids', [])}
    if workshop_ids:
        allowed |= Q(production_schedules__record_status='ACTIVE', production_schedules__products__removed_at__isnull=True,
            production_schedules__products__crafts__removed_at__isnull=True,
            production_schedules__products__crafts__craft__workshop_id__in=workshop_ids)
    if has_legacy:
        if user.has_perm('production_tasks.view_all_productiontask'):
            return queryset
        allowed |= Q(customer_account_id__in=_legacy_customers(user, employee, access).values('id'))
        allowed |= Q(salesperson=employee) | Q(followers=employee) | Q(created_by_employee=employee)
    return queryset.filter(allowed).distinct()


def accessible_tracking_task_ids(request, permission=VIEW_PERMISSION):
    if not request.user.is_authenticated or not request.user.is_active:
        return ProductionTask.objects.none().values_list('pk', flat=True)
    employee = Employee.objects.filter(user_id=request.user.pk, status='ACTIVE', archived_at__isnull=True).first()
    if employee is None:
        return ProductionTask.objects.none().values_list('pk', flat=True)
    access = effective_access(request.user)
    return _task_queryset(request.user, employee, permission, access).order_by().values_list('pk', flat=True)


def employee_can_view_task(employee, task_id):
    current = Employee.objects.select_related('user').filter(pk=getattr(employee, 'pk', None), status='ACTIVE',
        archived_at__isnull=True, user__is_active=True).first()
    if current is None:
        return False
    return _task_queryset(current.user, current, VIEW_PERMISSION, effective_access(current.user)).filter(pk=task_id).exists()
