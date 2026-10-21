from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.generics import get_object_or_404

from apps.core.api.concurrency import require_matching_etag
from apps.core.api.exceptions import Conflict
from apps.core.audit import write_audit_log
from apps.core.auth import active_employee_for
from apps.organizations.models import Employee, EmployeeOrganizationAssignment, OrganizationUnit, RoleProfile
from .permissions import CanManageOrganization


def require_organization_manager(request):
    if not CanManageOrganization().has_permission(request, None):
        raise PermissionDenied(CanManageOrganization.message)
    return active_employee_for(request.user)


def audit(request, obj, action, before, after):
    write_audit_log(object_type="ACCESS_ORGANIZATION", object_id=obj.pk, action=action,
                    actor_employee=require_organization_manager(request), before_data=before,
                    after_data=after, request=request)


def snapshot(unit):
    return {"unit_code": unit.unit_code, "unit_name": unit.unit_name, "parent_id": str(unit.parent_id) if unit.parent_id else None,
            "status": unit.status, "sort_order": unit.sort_order}


def live_or_future():
    return Q(effective_to__isnull=True) | Q(effective_to__gt=timezone.now())


def lock_departments(ids):
    units = list(OrganizationUnit.objects.select_for_update().filter(pk__in=ids).order_by("id"))
    if len(units) != len(set(ids)) or any(u.archived_at or u.status != "ACTIVE" for u in units):
        raise ValidationError({"department_id": "部门不存在或已停用。"})
    return units


@transaction.atomic
def create_department(request, data):
    require_organization_manager(request)
    # The seeded company row serializes department name checks without altering old data.
    OrganizationUnit.objects.select_for_update().get(unit_code="HAIQU")
    parent_id = data.get("parent_id")
    if parent_id:
        lock_departments([parent_id])
    if OrganizationUnit.objects.filter(unit_name=data["unit_name"]).exists():
        raise Conflict("存在同名组织，请核对并复用原部门。")
    try:
        with transaction.atomic():
            unit = OrganizationUnit.objects.create(**data)
    except IntegrityError as exc:
        raise Conflict("部门编码已存在，请核对原部门。") from exc
    audit(request, unit, "DEPARTMENT_CREATE", {}, snapshot(unit))
    return unit


@transaction.atomic
def update_department(request, pk, data):
    require_organization_manager(request)
    OrganizationUnit.objects.select_for_update().get(unit_code="HAIQU")
    unit = get_object_or_404(OrganizationUnit.objects.select_for_update(), pk=pk, archived_at__isnull=True)
    require_matching_etag(request, unit)
    if "unit_name" in data and OrganizationUnit.objects.exclude(pk=pk).filter(unit_name=data["unit_name"]).exists():
        raise Conflict("存在同名组织，请核对原部门。")
    if data.get("status") == "INACTIVE":
        if unit.unit_code == "HAIQU" or unit.children.exists() or unit.roles.exists() or unit.employee_assignments.filter(live_or_future()).exists():
            raise Conflict("部门仍有下级、角色或有效/未来员工归属，不能停用；海趣根组织也不能停用。")
    before = snapshot(unit)
    for key, value in data.items():
        setattr(unit, key, value)
    unit.save()
    audit(request, unit, "DEPARTMENT_UPDATE", before, snapshot(unit))
    return unit


@transaction.atomic
def set_role_department(request, pk, department_id):
    require_organization_manager(request)
    OrganizationUnit.objects.select_for_update().get(unit_code="HAIQU")
    role = get_object_or_404(RoleProfile.objects.select_for_update(), pk=pk)
    require_matching_etag(request, role)
    if department_id:
        lock_departments([department_id])
    before = {"department_id": str(role.department_id) if role.department_id else None}
    role.department_id = department_id
    role.save(update_fields=["department", "updated_at"])
    audit(request, role, "ROLE_DEPARTMENT_UPDATE", before,
          {"department_id": str(department_id) if department_id else None, "role_code": role.role_code})
    return role


def assignment_snapshot(employee):
    return [{"id": str(a.pk), "department_id": str(a.organization_unit_id), "department_name": a.organization_unit.unit_name,
             "is_primary": a.is_primary, "position_title": a.position_title,
             "effective_from": a.effective_from.isoformat(), "effective_to": a.effective_to.isoformat() if a.effective_to else None}
            for a in employee.organization_assignments.select_related("organization_unit").order_by("-effective_from", "id")]


@transaction.atomic
def replace_employee_departments(request, pk, rows):
    actor = require_organization_manager(request)
    OrganizationUnit.objects.select_for_update().get(unit_code="HAIQU")
    employee = get_object_or_404(Employee.objects.select_for_update(no_key=True), pk=pk, archived_at__isnull=True)
    require_matching_etag(request, employee)
    if employee.status != "ACTIVE":
        raise Conflict("只能调整在职员工部门。")
    ids = [r["department_id"] for r in rows]
    if len(ids) != len(set(ids)):
        raise ValidationError({"departments": "部门不可重复。"})
    if rows and sum(r["is_primary"] for r in rows) != 1:
        raise ValidationError({"departments": "有部门时必须且只能选择一个主部门。"})
    lock_departments(ids)
    now = timezone.now()
    if employee.organization_assignments.filter(effective_from__gt=now).exists():
        raise Conflict("存在未来生效部门，请先审阅，不可覆盖。")
    before = assignment_snapshot(employee)
    existing = list(employee.organization_assignments.select_for_update().filter(effective_from__lte=now).filter(live_or_future()))
    previous_ends = {a.organization_unit_id: a.effective_to for a in existing}
    wanted = {r["department_id"]: r for r in rows}
    unchanged = set()
    # End every changed range before creating a replacement primary assignment.
    for a in existing:
        row = wanted.get(a.organization_unit_id)
        if row and row["is_primary"] == a.is_primary and row["position_title"] == a.position_title:
            unchanged.add(a.organization_unit_id)
        else:
            a.effective_to = now
            a.save(update_fields=["effective_to", "updated_at"])
    for row in rows:
        if row["department_id"] not in unchanged:
            EmployeeOrganizationAssignment.objects.create(employee=employee, organization_unit_id=row["department_id"],
                is_primary=row["is_primary"], position_title=row["position_title"], effective_from=now,
                effective_to=previous_ends.get(row["department_id"]), assigned_by_employee=actor)
    employee.save(update_fields=["updated_at"])
    audit(request, employee, "EMPLOYEE_DEPARTMENTS_REPLACE", {"departments": before}, {"departments": assignment_snapshot(employee)})
    return employee
