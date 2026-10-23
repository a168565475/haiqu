from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.core.api.concurrency import etag_for_instance, PreconditionFailed
from apps.core.api.exceptions import Conflict
from apps.organizations.models import Employee, OrganizationUnit, RoleProfile
from . import organization_services, services


@transaction.atomic
def adjust_employees(request, data):
    department_ids = data["department_ids"]
    role_ids = data["role_ids"]
    organization_services.require_organization_manager(request)
    services.require_manager(request)
    # Match the single-employee department lock order; lock the whole batch
    # before changing anything so concurrent edits cannot leave a partial batch.
    OrganizationUnit.objects.select_for_update().get(unit_code="HAIQU")
    items = data["items"]
    expected = {item["id"]: item["etag"] for item in items}
    employees = list(Employee.objects.select_for_update(no_key=True)
                     .filter(pk__in=expected, archived_at__isnull=True).order_by("id"))
    if len(employees) != len(items):
        raise ValidationError({"items": "员工不存在或已删除，请刷新名单。"})
    for employee in employees:
        if etag_for_instance(employee) != expected[employee.pk]:
            raise PreconditionFailed(f"{employee.display_name} 的资料已变化，请刷新后重新选择。")
        if employee.status != "ACTIVE":
            raise Conflict(f"{employee.display_name} 不在职，不能批量调整。")
    organization_services.lock_departments(department_ids)
    roles = list(RoleProfile.objects.select_for_update().filter(pk__in=role_ids).order_by("id"))
    if len(roles) != len(role_ids) or any(role.archived_at for role in roles):
        raise ValidationError({"role_ids": "角色不存在或已停用。"})
    if any(role.department_id not in department_ids for role in roles):
        raise ValidationError({"role_ids": "所选角色必须属于本次选择的部门。"})
    for employee in employees:
        now = timezone.now()
        current = {assignment.organization_unit_id: assignment for assignment in employee.organization_assignments
            .filter(organization_unit_id__in=department_ids, effective_from__lte=now).filter(services.transaction_range_open(now))}
        # 原主部门仍被选中则保留，否则使用首个所选部门；空列表清空全部当前归属。
        primary_id = next((key for key, assignment in current.items() if assignment.is_primary), department_ids[0] if department_ids else None)
        employee = organization_services.replace_employee_departments(request, employee.pk,
            [{"department_id": department_id, "is_primary": department_id == primary_id,
              "position_title": current[department_id].position_title if department_id in current else ""}
             for department_id in department_ids],
            expected_etag=etag_for_instance(employee))
        services.replace_employee_roles(request, employee.pk, role_ids, expected_etag=etag_for_instance(employee))
    return {"updated_count": len(employees)}
