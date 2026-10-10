from django.db import IntegrityError, transaction
from rest_framework.exceptions import ValidationError
from rest_framework.generics import get_object_or_404

from apps.core.api.concurrency import require_matching_etag
from apps.core.api.exceptions import Conflict
from apps.organizations.models import Employee
from .models import SalesTeam, SalesTeamMembership
from .services import audit, require_manager


def active_employee(pk):
    return get_object_or_404(Employee.objects.select_for_update(no_key=True), pk=pk, status="ACTIVE", archived_at__isnull=True)


def snapshot(team):
    return {"code": team.code, "name": team.name, "manager_id": str(team.manager_id), "is_active": team.is_active,
            "member_ids": sorted(str(pk) for pk in team.memberships.values_list("employee_id", flat=True))}


@transaction.atomic
def create_team(request, data):
    require_manager(request)
    manager = active_employee(data["manager_id"])
    try:
        with transaction.atomic():
            team = SalesTeam.objects.create(code=data["code"], name=data["name"], manager=manager)
    except IntegrityError as exc:
        raise Conflict("团队编号已存在。") from exc
    audit(request, team, "TEAM_CREATE", {}, snapshot(team), "ACCESS_TEAM")
    return team


@transaction.atomic
def update_team(request, pk, data):
    require_manager(request)
    team = get_object_or_404(SalesTeam.objects.select_for_update(), pk=pk)
    require_matching_etag(request, team)
    before = snapshot(team)
    # Manager reassignment changes all member visibility and is intentionally absent.
    for field in ("name", "is_active"):
        if field in data: setattr(team, field, data[field])
    team.save()
    audit(request, team, "TEAM_UPDATE", before, snapshot(team), "ACCESS_TEAM")
    return team


@transaction.atomic
def add_members(request, pk, employee_ids):
    actor = require_manager(request)
    team = get_object_or_404(SalesTeam.objects.select_for_update(), pk=pk)
    require_matching_etag(request, team)
    if not team.is_active:
        raise Conflict("请先启用团队。")
    if not employee_ids or len(employee_ids) != len(set(employee_ids)):
        raise ValidationError({"employee_ids": "请选择不重复的员工。"})
    employees = list(Employee.objects.select_for_update(no_key=True).filter(pk__in=employee_ids, status="ACTIVE", archived_at__isnull=True).order_by("id"))
    if len(employees) != len(employee_ids):
        raise ValidationError({"employee_ids": "存在无效员工。"})
    if SalesTeamMembership.objects.filter(employee_id__in=employee_ids).exists():
        raise Conflict("包含已分组员工；本次不支持成员换团队。")
    before = snapshot(team)
    try:
        with transaction.atomic():
            SalesTeamMembership.objects.bulk_create([SalesTeamMembership(team=team, employee=e, created_by_employee=actor) for e in employees])
    except IntegrityError as exc:
        raise Conflict("员工刚刚被加入其他团队，请刷新后重试。") from exc
    team.save(update_fields=["updated_at"])
    audit(request, team, "TEAM_MEMBERS_ADD", before, snapshot(team), "ACCESS_TEAM")
    return team
