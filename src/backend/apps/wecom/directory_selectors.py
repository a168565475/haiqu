"""通讯录与 ERP 员工的只读比对；同名只作为人工核对线索。"""
import re
import unicodedata
from collections import Counter, defaultdict

from django.db.models import Exists, OuterRef

from apps.core.api.concurrency import etag_for_instance
from apps.organizations.models import Employee, EmployeeOrganizationAssignment
from .department_assignment_selectors import department_plan
from .models import WeComBinding


def normalized_name(value):
    return " ".join(unicodedata.normalize("NFKC", value).split()).casefold()


def member_rejection(member):
    if member["status"] not in (1, 4):
        return "企业微信账号已禁用、退出企业或状态未知，暂不建档或匹配。"
    if not re.fullmatch(r"[A-Za-z0-9_.@-]{1,64}", member["userid"]):
        return "成员 UserID 不满足现有登录规则，需先核对来源。"
    if not member["name"] or len(member["name"]) > 150:
        return "成员姓名缺失或超过 150 字符，需先核对来源。"
    return ""


def employee_summary(employee):
    user = employee.user
    return {
        "id": str(employee.pk), "employee_code": employee.employee_code,
        "display_name": employee.display_name, "status": employee.status,
        "archived": employee.archived_at is not None, "has_account": user is not None,
        "account_active": bool(user and user.is_active), "etag": etag_for_instance(employee),
    }


def directory_plan(directory, *, mappings=None):
    employees = Employee.objects.select_related("user").only(
        "id", "employee_code", "display_name", "status", "archived_at", "updated_at", "user_id",
        "user__is_active",
    )
    by_name = defaultdict(list)
    for employee in employees:
        summary = employee_summary(employee)
        by_name[normalized_name(employee.display_name)].append(summary)
    binding_rows = WeComBinding.objects.filter(corp_id=directory["corp_id"]).select_related("employee__user")
    if mappings is not None:
        binding_rows = binding_rows.annotate(has_department_history=Exists(
            EmployeeOrganizationAssignment.objects.filter(employee_id=OuterRef("employee_id"))))
    bindings = {row.user_id.lower(): row for row in binding_rows}
    source_names = Counter(normalized_name(member["name"]) for member in directory["members"])
    rows = []
    for member in directory["members"]:
        binding = bindings.get(member["userid"].lower())
        candidates = []
        employee = employee_summary(binding.employee) if binding else None
        if binding:
            action, reason = "EXISTING", "已关联 ERP 员工，保留现有资料、账号及权限。"
            if (employee["status"] != "ACTIVE" or employee["archived"]
                    or not employee["account_active"]):
                reason = "已关联，但 ERP 员工或账号不可用；本次不自动恢复或补建账号。"
        elif reason := member_rejection(member):
            action = "SKIP"
        else:
            key = normalized_name(member["name"])
            candidates = by_name.get(key, [])
            if candidates or source_names[key] > 1:
                action, reason = "REVIEW", "存在同名员工或企业微信同名成员，请确认关联已有员工或作为不同人员新建。"
            else:
                action, reason = "CREATE", "可新增员工及无密码账号，后续由管理员分配权限。"
        row = {**member, "action": action, "reason": reason,
               "employee": employee, "candidates": candidates}
        if mappings is not None:
            row["department_plan"] = department_plan(member, mappings, employee=employee,
                has_history=bool(binding and binding.has_department_history), rejection=member_rejection(member))
        rows.append(row)
    return rows
