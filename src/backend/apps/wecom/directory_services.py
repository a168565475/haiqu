"""员工同步：预览不写业务库，提交整批成功或整批回滚。"""
import hashlib
import json
import uuid

from django.contrib.auth import get_user_model
from django.core import signing
from django.db import transaction
from django.utils import timezone
from django.views.decorators.debug import sensitive_variables
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.access_control.services import require_manager
from apps.access_control.organization_services import require_organization_manager
from apps.core.api.concurrency import PreconditionFailed, etag_for_instance
from apps.core.api.exceptions import Conflict
from apps.organizations.models import Employee, EmployeeOrganizationAssignment, OrganizationUnit
from . import department_mapping_selectors as department_selectors
from .department_assignment_selectors import department_plan
from .department_mapping_services import require_schema as require_department_schema
from .directory_client import WeComDirectoryClient
from .directory_selectors import directory_plan, employee_summary, member_rejection
from .models import WeComBinding, WeComConfig
from .selectors import config_etag, configuration_complete, get_config
from .services import _create_binding, _existing_binding, _locked_employee_and_user, _new_user, audit, require_etag


PREVIEW_SALT = "wecom.employee-directory.v1"
PREVIEW_MAX_AGE = 600


def require_access(request):
    # 上游读取可能耗时；用新实例验权，避免沿用读取前缓存的员工状态或角色。
    user = get_user_model().objects.filter(pk=request.user.pk).first()
    if user is None:
        raise PermissionDenied("当前账号已失效。")
    request.user = user
    return require_manager(request, "access_control.manage_accounts")


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def plan_digest(row):
    return digest({"action": row["action"], "candidates": sorted(
        ((candidate["id"], candidate["etag"]) for candidate in row["candidates"])),
    })


@sensitive_variables()
def read_source(config):
    if config._state.adding or not config.enabled or not configuration_complete(config):
        raise Conflict("企业微信应用未启用或配置不完整，请联系管理员。")
    return WeComDirectoryClient(config).read_directory()


@sensitive_variables()
def preview_directory(request, *, apply_departments=False):
    require_access(request)
    if apply_departments:
        require_organization_manager(request)
        require_department_schema()
    config = get_config()
    directory = read_source(config)
    require_access(request)
    if apply_departments:
        require_organization_manager(request)
    require_etag(config_etag(config), config_etag(get_config()))
    mappings = department_selectors.mapping_snapshot(config.corp_id) if apply_departments else None
    rows = directory_plan(directory, mappings=mappings)
    source_digest = digest(directory)
    version = {
        "actor": str(request.user.pk), "config": config_etag(config), "directory": source_digest,
        "plans": {row["userid"].lower(): plan_digest(row) for row in rows if row["action"] in ("CREATE", "REVIEW")},
        "apply_departments": apply_departments,
    }
    if apply_departments:
        version["department_version"] = digest(mappings)
        version["department_plans"] = {row["userid"].lower(): {
            "plan": digest(row["department_plan"]),
            "employee_id": row["employee"]["id"] if row["employee"] else None,
            "employee_etag": row["employee"]["etag"] if row["employee"] else None,
        } for row in rows}
    token = signing.dumps(version, salt=PREVIEW_SALT, compress=True)
    return {**directory, "members": rows, "preview_token": token, "apply_departments": apply_departments}, f'"{source_digest}"'


@sensitive_variables()
def prepare_submission(request, data):
    require_access(request)
    try:
        preview = signing.loads(data["preview_token"], salt=PREVIEW_SALT, max_age=PREVIEW_MAX_AGE)
    except signing.BadSignature as exc:
        raise ValidationError({"preview_token": "预览已过期或无效，请重新读取并核对。"}) from exc
    if preview["actor"] != str(request.user.pk):
        raise ValidationError({"preview_token": "请使用当前账号重新预览。"})
    if data.get("apply_departments", False) != preview.get("apply_departments", False):
        raise ValidationError({"apply_departments": "部门同步方式必须与预览一致，请重新预览。"})
    if preview.get("apply_departments", False):
        require_organization_manager(request)
        require_department_schema()
    require_etag(request.headers.get("If-Match"), f'"{preview["directory"]}"')
    config = get_config()
    require_etag(preview["config"], config_etag(config))
    directory = read_source(config)
    if digest(directory) != preview["directory"]:
        raise PreconditionFailed("企业微信通讯录已变化，请重新预览。")
    return config, directory, preview


def lock_configuration(request, config):
    # 与 OAuth 首次建档及原人工绑定共用同一行锁，统一外部身份的并发入口。
    locked = WeComConfig.objects.select_for_update().get(pk=config.pk)
    require_etag(config_etag(config), config_etag(locked))
    actor = require_access(request)
    return locked, actor


def result_for(binding, result):
    return {"user_id": binding.user_id, "employee_id": str(binding.employee_id), "result": result}


def lock_department_context(request, config, preview):
    if not preview.get("apply_departments", False):
        return None
    # 组织维护统一先锁根组织，再锁员工和目标部门；与既有部门维护避免反向等待。
    root = OrganizationUnit.objects.select_for_update().filter(unit_code="HAIQU").first()
    if root is None or root.status != "ACTIVE" or root.archived_at is not None:
        raise Conflict("ERP 根组织未就绪，请先维护组织结构。")
    require_access(request)
    require_organization_manager(request)
    mappings = department_selectors.mapping_snapshot(config.corp_id)
    if digest(mappings) != preview["department_version"]:
        raise PreconditionFailed("部门映射或目标部门已变化，请重新预览。")
    return mappings


def fill_departments(request, binding, member, preview, mappings, actor, result):
    employee, user = _locked_employee_and_user(binding.employee_id)
    employee.user = user
    plan = department_plan(member, mappings, employee=employee_summary(employee),
                           has_history=employee.organization_assignments.exists(), rejection=member_rejection(member))
    # 已有归属一律保留，也覆盖本次操作成功后重试的情况。
    if plan["status"] == "PRESERVED":
        return plan
    expected = preview["department_plans"][member["userid"].lower()]
    if plan["status"] == "READY" and not expected["employee_id"] and result == "EXISTING" and binding.source == "MANUAL":
        raise PreconditionFailed("成员已被人工关联到 ERP 员工，请重新预览部门归属。")
    if expected["employee_id"] and (expected["employee_id"] != str(employee.pk)
                                    or expected["employee_etag"] != etag_for_instance(employee)):
        raise PreconditionFailed("ERP 员工已变化，请重新预览部门归属。")
    if expected["plan"] != digest(plan):
        raise PreconditionFailed("员工部门计划已变化，请重新预览。")
    if plan["status"] != "READY":
        return plan
    ids = [row["department_id"] for row in plan["assignments"]]
    targets = list(OrganizationUnit.objects.select_for_update().filter(pk__in=ids).order_by("id"))
    versions = {row["organization_unit_id"]: row["organization_etag"] for row in mappings["mappings"]}
    if len(targets) != len(ids) or any(
        unit.status != "ACTIVE" or unit.archived_at is not None or etag_for_instance(unit) != versions[str(unit.pk)]
        for unit in targets
    ):
        raise PreconditionFailed("目标部门已变化，请重新预览。")
    now = timezone.now()
    for row in plan["assignments"]:
        EmployeeOrganizationAssignment.objects.create(
            employee=employee, organization_unit_id=row["department_id"], is_primary=row["is_primary"],
            effective_from=now, assigned_by_employee=actor,
        )
    employee.save(update_fields=["updated_at"])
    audit(request, employee, "DIRECTORY_DEPARTMENTS_FILL", actor=actor, user_id=binding.user_id,
          employee_name=employee.display_name, after={"departments": plan["assignments"]},
          message="按已确认映射补充空白部门归属，未授予角色。")
    return {**plan, "status": "APPLIED", "reason": "已补充部门归属，未授予角色。"}


def directory_result(request, binding, member, result, preview, mappings, actor):
    payload = result_for(binding, result)
    if mappings is not None:
        plan = fill_departments(request, binding, member, preview, mappings, actor, result)
        payload.update(department_status=plan["status"], department_reason=plan["reason"])
    return payload


@sensitive_variables()
def sync_directory(request, data):
    config, directory, preview = prepare_submission(request, data)
    selected = {value.lower() for value in data["user_ids"]}
    confirmed = {value.lower() for value in data["confirmed_new_user_ids"]}
    with transaction.atomic():
        locked, actor = lock_configuration(request, config)
        mappings = lock_department_context(request, locked, preview)
        rows = {row["userid"].lower(): row for row in directory_plan(directory)}
        if not selected.issubset(rows):
            raise ValidationError({"user_ids": "只能选择当前预览中的成员。"})
        results = []
        # 先校验整批，再开始写入；任何审计或写入失败仍由外层事务全量回滚。
        for key in sorted(selected):
            row = rows[key]
            if row["action"] == "EXISTING":
                continue
            if row["action"] == "SKIP" or (row["action"] == "REVIEW" and key not in confirmed):
                raise Conflict("所选成员含暂不可建档或待人工核对项，请处理后重试。")
            if preview["plans"].get(key) != plan_digest(row):
                raise PreconditionFailed("ERP 同名候选已变化，请重新预览并核对。")
        for key in sorted(selected):
            row = rows[key]
            existing = _existing_binding(locked.corp_id, row["userid"])
            if existing:
                results.append(directory_result(request, existing, row, "EXISTING", preview, mappings, actor))
                continue
            user = _new_user(row["name"])
            employee = Employee.objects.create(
                user=user, employee_code="WECOM-" + uuid.uuid4().hex.upper(), display_name=row["name"],
            )
            binding = _create_binding(locked, row, employee, source="AUTO", created_account=True, actor=actor)
            audit(request, binding, "DIRECTORY_CONFIRM_NEW" if key in confirmed else "DIRECTORY_CREATE",
                  actor=actor, user_id=binding.user_id, employee_name=employee.display_name,
                  message="通讯录建档：创建员工及无密码账号，未分配角色。")
            results.append(directory_result(request, binding, row, "CREATED", preview, mappings, actor))
        return results


@sensitive_variables()
def match_directory_employee(request, data):
    config, directory, preview = prepare_submission(request, data)
    member = next((row for row in directory["members"] if row["userid"].lower() == data["user_id"].lower()), None)
    if member is None:
        raise ValidationError({"user_id": "只能匹配当前预览中的成员。"})
    if reason := member_rejection(member):
        raise Conflict(reason)
    with transaction.atomic():
        locked, actor = lock_configuration(request, config)
        mappings = lock_department_context(request, locked, preview)
        employee, user = _locked_employee_and_user(data["employee_id"])
        if employee.status != "ACTIVE" or employee.archived_at is not None or (user and not user.is_active):
            raise Conflict("只能匹配在职、未归档员工及启用的账号。")
        if user and (user.is_superuser or user.is_staff or user.get_username() == "admin"):
            raise Conflict("管理账号受保护，请使用专门的管理员维护流程。")
        existing = _existing_binding(locked.corp_id, member["userid"])
        if existing:
            if existing.employee_id == employee.pk:
                return directory_result(request, existing, member, "EXISTING", preview, mappings, actor)
            raise Conflict("此企业微信成员已关联其他员工，不能覆盖或自动合并。")
        require_etag(data["employee_etag"], etag_for_instance(employee))
        if WeComBinding.objects.filter(employee=employee).exists():
            raise Conflict("所选员工已关联企业微信成员，不能覆盖。")
        created_account = user is None
        if created_account:
            employee.user = _new_user(employee.display_name)
            employee.save(update_fields=["user", "updated_at"])
        binding = _create_binding(locked, member, employee, source="MANUAL", created_account=created_account, actor=actor)
        audit(request, binding, "DIRECTORY_MATCH", actor=actor, user_id=binding.user_id,
              employee_name=employee.display_name, message="管理员确认成员身份并关联已有员工，保留 ERP 资料和权限。")
        return directory_result(request, binding, member, "MATCHED", preview, mappings, actor)
