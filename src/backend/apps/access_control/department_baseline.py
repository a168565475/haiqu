"""User-confirmed department classification; does not grant actions or move employees."""
from django.db import connection, transaction
from rest_framework.exceptions import ValidationError

from apps.organizations.models import OrganizationUnit, RoleProfile
from . import organization_services as services
from apps.core.api.concurrency import etag_for_instance

DEPARTMENTS = (
    ("DEPT_GENERAL", "总经办", ("GENERAL_MANAGER",)),
    ("DEPT_FINANCE", "财务部", ("FINANCE", "CASHIER")),
    ("DEPT_ADMIN", "行政部", ("ADMINISTRATION", "MERCHANDISER")),
    ("DEPT_PRODUCTION", "生产部", ("FACTORY_MANAGER", "METAL_DIRECTOR", "ASSEMBLY_DIRECTOR", "SEWING_DIRECTOR", "METAL_SAMPLING", "FABRIC_SAMPLING", "COATING_MATERIALS")),
    ("DEPT_PMC", "PMC部", ("PMC",)),
    ("DEPT_PURCHASE", "采购部", ("PURCHASING",)),
    ("DEPT_WAREHOUSE", "仓储部", ("WAREHOUSE_KEEPER",)),
    ("DEPT_OUTSOURCING", "外协部", ("OUTSOURCING",)),
    ("DEPT_TECHNICAL", "技术部", ("TECHNICAL",)),
    ("DEPT_QUALITY", "品质部", ("QUALITY",)),
    ("DEPT_SUPPORT", "技术支持", ()),
    ("DEPT_BUSINESS", "业务部", ("ACCOUNT_MANAGER", "SALESPERSON")),
)


def baseline_plan():
    units = list(OrganizationUnit.objects.all())
    root = next((u for u in units if u.unit_code == "HAIQU" and not u.archived_at and u.status == "ACTIVE"), None)
    with connection.cursor() as cursor:
        columns = {c.name for c in connection.introspection.get_table_description(cursor, "role_profile")}
    migrated = "department_id" in columns
    fields = ["id", "role_code", "archived_at"] + (["department_id"] if migrated else [])
    roles = {r["role_code"]: r for r in RoleProfile.objects.values(*fields)}
    result = {"database": connection.settings_dict["NAME"], "schema_ready": migrated, "departments": [], "roles": [], "conflicts": []}
    if root is None:
        result["conflicts"].append("海趣根组织缺失或停用。")
    for index, (code, name, role_codes) in enumerate(DEPARTMENTS, 1):
        matches = [u for u in units if u.unit_name == name or u.unit_code == code]
        unit = matches[0] if len(matches) == 1 else None
        conflict = bool(matches) and (unit is None or unit.unit_name != name or unit.archived_at is not None or unit.status != "ACTIVE" or (root and unit.parent_id != root.pk))
        if conflict:
            result["conflicts"].append(f"{name}名称/编码/父级/状态冲突：" + ";".join(f"{u.pk}:{u.unit_code}:{u.unit_name}" for u in matches))
        result["departments"].append({"unit_code": unit.unit_code if unit else code, "unit_name": name,
            "id": str(unit.pk) if unit else None, "parent_id": str(root.pk) if root else None,
            "sort_order": unit.sort_order if unit else index * 10,
            "action": "CONFLICT" if conflict else "REUSE" if unit else "CREATE",
            "employee_assignment_count": unit.employee_assignments.count() if unit else 0,
            "role_reference_count": unit.roles.count() if unit and migrated else None})
        for role_code in role_codes:
            role = roles.get(role_code)
            if not role or role["archived_at"]:
                result["conflicts"].append(f"既有角色{role_code}缺失或停用。")
            previous = role.get("department_id") if role else None
            if previous and (unit is None or previous != unit.pk):
                result["conflicts"].append(f"{role_code}已有其他部门{previous}，需审阅后处理。")
            result["roles"].append({"role_code": role_code, "department_name": name,
                                    "action": "REUSE" if previous and unit and previous == unit.pk else "LINK"})
    known = {code for _, _, codes in DEPARTMENTS for code in codes}
    result["unclassified_new_roles"] = sorted(set(roles) - known)
    support = next((u for u in units if u.unit_name == "技术支持"), None)
    if support and migrated and support.roles.exists():
        result["conflicts"].append("技术支持已有角色，不能自动清空。")
    return result


@transaction.atomic
def apply_baseline(request):
    services.require_organization_manager(request)
    OrganizationUnit.objects.select_for_update().get(unit_code="HAIQU")
    list(RoleProfile.objects.select_for_update().order_by("id"))
    plan = baseline_plan()
    if not plan["schema_ready"] or plan["conflicts"]:
        raise ValidationError({"baseline": plan["conflicts"] or ["请先应用结构迁移。"]})
    units = {}
    for row in plan["departments"]:
        units[row["unit_name"]] = OrganizationUnit.objects.get(pk=row["id"]) if row["id"] else services.create_department(request, {
            key: row[key] for key in ("unit_code", "unit_name", "parent_id", "sort_order")})
    for row in plan["roles"]:
        if row["action"] == "REUSE":
            continue
        role = RoleProfile.objects.get(role_code=row["role_code"])
        request.headers = {**request.headers, "If-Match": etag_for_instance(role)}
        services.set_role_department(request, role.pk, units[row["department_name"]].pk)
    return {"applied": plan, "after": baseline_plan()}
