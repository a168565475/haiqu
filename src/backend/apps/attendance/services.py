import hashlib
import json
import uuid
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone
from django.views.decorators.debug import sensitive_variables
from rest_framework.exceptions import NotFound, PermissionDenied, Throttled
from rest_framework.generics import get_object_or_404

from apps.access_control import module_policy
from apps.core.api.concurrency import require_matching_etag
from apps.core.api.exceptions import Conflict
from apps.core.api.permissions import HasActiveEmployee
from apps.core.audit import write_audit_log
from apps.wecom.client import WeComError
from apps.wecom.models import WeComConfig
from apps.wecom.selectors import configuration_complete, get_config
from .client import AttendanceClient
from .models import AttendanceMember, AttendanceMonth, AttendancePerson, AttendanceRecord, AttendanceSyncRun
from .source import build_record_steps, normalize_record, source_error


LEASE_SECONDS = 90


def require_access(request, *, sync=False, fresh=False):
    if fresh:
        user = get_user_model().objects.filter(pk=request.user.pk).first()
        if user is None:
            raise PermissionDenied("当前账号已失效。")
        request.user = user
        if hasattr(request, "_sales_access_snapshot"):
            del request._sales_access_snapshot
    if not HasActiveEmployee().has_permission(request, None):
        raise PermissionDenied("当前账号没有有效员工档案。")
    codes = ["attendance.view_attendance"] + (["attendance.sync_attendance"] if sync else [])
    if not all(module_policy.has_permission(request, code) for code in codes):
        raise PermissionDenied("当前账号没有考勤查看或同步权限。")
    return request.employee


@sensitive_variables()
def configuration_version(config):
    if config is None:
        return ""
    material = [str(config.pk), config.corp_id, config.agent_id, config.enabled,
                config.secret_ciphertext, config.updated_at.isoformat()]
    return hashlib.sha256(json.dumps(material, separators=(",", ":")).encode()).hexdigest()


def valid_configuration(config):
    return bool(config and config.enabled and configuration_complete(config))


@sensitive_variables()
def current_vacation(request, month, user_id):
    require_access(request, fresh=True)
    config = get_config()
    if not valid_configuration(config):
        raise Conflict("企业微信应用未启用或配置不完整，请联系管理员。")
    period = AttendanceMonth.objects.select_related("active_run").filter(corp_id=config.corp_id, month=month).first()
    run = period.active_run if period else None
    member = (run.members.filter(person__corp_id=config.corp_id, user_id__iexact=user_id).first()
              if run and run.status == AttendanceSyncRun.Status.SUCCESS else None)
    if member is None:
        raise NotFound("当前企业的成功考勤快照中未找到此成员。")
    version = configuration_version(config)
    client = AttendanceClient(config)
    definitions = {item["id"]: item for item in client.get_vacation_config()}
    balances = client.get_vacation_quota(member.user_id)
    require_access(request, fresh=True)
    current_config = get_config()
    if not valid_configuration(current_config) or configuration_version(current_config) != version:
        raise Conflict("读取期间企业微信配置已变化，请重新查询。")
    if not AttendanceMonth.objects.filter(pk=period.pk, active_run_id=run.pk).exists():
        raise Conflict("读取期间考勤快照已更新，请重新查询。")
    items = []
    for balance in balances:
        definition = definitions.get(balance["id"], {})
        items.append({**balance, "name": balance["name"] if balance["name"] is not None else definition.get("name"),
                      **{key: definition.get(key) for key in ("time_attr", "duration_type", "quota_type", "perday_duration")}})
    return {"user_id": member.user_id, "fetched_at": timezone.now(), "is_current": True, "items": items}


def _audit(request, run, action):
    write_audit_log(object_type="ATTENDANCE_SYNC", object_id=run.pk, action=action,
                    actor_employee=request.employee, request=request,
                    after_data={"month": run.period.month, "status": run.status,
                                "completed_steps": run.completed_steps, "error_code": run.error_code})


def _invalidate(request, run, code="CONFIGURATION_CHANGED", message="企业微信配置已变化，请重新开始同步。"):
    run.status = AttendanceSyncRun.Status.INVALIDATED
    run.error_code, run.error_message = code, message
    run.lease_token = run.lease_expires_at = None
    run.save()
    _audit(request, run, "SYNC_INVALIDATED")
    return run


@transaction.atomic
@sensitive_variables()
def start_sync(request, month, idempotency_key):
    require_access(request, sync=True, fresh=True)
    config = WeComConfig.objects.select_for_update().first()
    if not valid_configuration(config):
        raise Conflict("企业微信应用未启用或配置不完整，请联系管理员。")
    existing = AttendanceSyncRun.objects.select_related("period").filter(idempotency_key=idempotency_key).first()
    if existing:
        if existing.period.month != month or existing.period.corp_id != config.corp_id:
            raise Conflict("此幂等键已用于其他企业或月份。")
        return existing
    period, _ = AttendanceMonth.objects.get_or_create(corp_id=config.corp_id, month=month)
    period = AttendanceMonth.objects.select_for_update().get(pk=period.pk)
    if period.current_run_id:
        current = AttendanceSyncRun.objects.select_for_update().get(pk=period.current_run_id)
        if current.status in {"PENDING", "RUNNING", "FAILED"}:
            if current.config_version == configuration_version(config):
                return current
            _invalidate(request, current)
    run = AttendanceSyncRun.objects.create(period=period, idempotency_key=idempotency_key,
        config_version=configuration_version(config), requested_by=str(request.employee.pk),
        steps=[{"phase": "scope"}, {"phase": "departments"}])
    period.current_run = run
    period.save(update_fields=["current_run", "updated_at"])
    _audit(request, run, "SYNC_STARTED")
    return run


def _lock_run(run_id):
    # 锁顺序固定为配置、企业月份、任务；外部请求不持有这些锁。
    config = WeComConfig.objects.select_for_update().first()
    period_id = get_object_or_404(AttendanceSyncRun, pk=run_id).period_id
    period = AttendanceMonth.objects.select_for_update().get(pk=period_id)
    run = AttendanceSyncRun.objects.select_for_update().get(pk=run_id)
    run.period = period
    return config, period, run


def _same_configuration(config, run):
    return (valid_configuration(config) and config.corp_id == run.period.corp_id
            and configuration_version(config) == run.config_version)


@transaction.atomic
@sensitive_variables()
def _claim(request, run_id):
    require_access(request, sync=True, fresh=True)
    config, period, run = _lock_run(run_id)
    # 其他企业的旧任务不暴露数据；当前企业的配置变更则显式作废。
    if config is None or config.corp_id != period.corp_id:
        raise Conflict("当前企业与同步任务不一致。")
    require_matching_etag(request, run)
    if run.status in {"SUCCESS", "INVALIDATED"}:
        return config, run, None
    if period.current_run_id != run.pk:
        return config, _invalidate(request, run, "SUPERSEDED", "此任务已被新的同步任务替代。"), None
    if not _same_configuration(config, run):
        return config, _invalidate(request, run), None
    now = timezone.now()
    if run.lease_token and run.lease_expires_at > now:
        raise Conflict("此同步步骤正在执行，请刷新进度后继续。")
    if run.retry_after and run.retry_after > now:
        raise Throttled(wait=max(1, int((run.retry_after - now).total_seconds())))
    run.lease_token = uuid.uuid4()
    run.lease_expires_at = now + timedelta(seconds=LEASE_SECONDS)
    run.status = AttendanceSyncRun.Status.RUNNING
    run.error_code = run.error_message = ""
    run.retry_after = None
    run.save()
    return config, run, run.steps[run.completed_steps]


def _fetch(config, step):
    client = AttendanceClient(config)
    if step["phase"] == "scope":
        return client.get_scope()
    if step["phase"] == "departments":
        return client.get_departments()
    if step["phase"] == "members":
        return client.get_department_members(step["department_id"])
    if step["phase"] == "records":
        return client.get_records(step["kind"], step["starttime"], step["endtime"], step["userids"])
    raise RuntimeError("未知考勤同步步骤。")


def _merge_members(run, rows):
    for row in rows:
        user_id, name = row["userid"], row["name"]
        if len(name) > AttendanceMember._meta.get_field("name").max_length:
            raise source_error()
        key = user_id.lower()
        existing = run.roster.get(key)
        if existing is None or (not existing["name"] and name):
            run.roster[key] = {"userid": user_id, "name": name}


def _store_result(run, step, result):
    if step["phase"] == "scope":
        if 1 not in result["allow_partys"]["partyid"]:
            raise WeComError("SCOPE_INCOMPLETE", "当前应用未获根部门全员读取权限，不能完成全企业考勤同步。")
        run.scope = result
    elif step["phase"] == "departments":
        ids = {row["id"] for row in result}
        if 1 not in ids:
            raise WeComError("SCOPE_INCOMPLETE", "企业微信部门结果缺少根部门，不能确认全员范围。")
        run.steps.extend({"phase": "members", "department_id": department_id} for department_id in sorted(ids))
    elif step["phase"] == "members":
        _merge_members(run, result)
        if run.completed_steps + 1 == len(run.steps):
            if not run.roster:
                raise WeComError("EMPTY_ROSTER", "企业微信未返回任何当前成员，不能用空名单替换考勤快照。")
            for key, member in run.roster.items():
                person, _ = AttendancePerson.objects.get_or_create(corp_id=run.period.corp_id, user_id=key)
                AttendanceMember.objects.create(run=run, person=person, user_id=key, name=member["name"])
            run.scanned_members = len(run.roster)
            run.steps.extend(build_record_steps(run.period.month, [item["userid"] for item in run.roster.values()]))
    elif step["phase"] == "records":
        if not isinstance(result, list):
            raise source_error()
        records = []
        for index, row in enumerate(result):
            record = normalize_record(step["kind"], row, step["userids"], run.period.month)
            if step["kind"] == "raw":
                from datetime import datetime
                timestamp = int(datetime.fromisoformat(record["payload"]["checkin_time"]).timestamp())
                if not step["starttime"] <= timestamp <= step["endtime"]:
                    raise source_error()
            records.append(AttendanceRecord(run=run, step_index=run.completed_steps, row_index=index, **record))
        AttendanceRecord.objects.bulk_create(records)


@transaction.atomic
@sensitive_variables()
def _finish(request, claimed, step, result, failure=None):
    config, period, run = _lock_run(claimed.pk)
    if (run.lease_token != claimed.lease_token or run.completed_steps != claimed.completed_steps
            or run.lease_expires_at is None or run.lease_expires_at <= timezone.now()
            or period.current_run_id != run.pk):
        raise Conflict("执行标识已过期或任务已更新，本次迟到结果未保存。")
    try:
        require_access(request, sync=True, fresh=True)
    except PermissionDenied:
        return _invalidate(request, run, "PERMISSION_REVOKED", "账号状态或考勤权限已变化，请重新开始同步。")
    if not _same_configuration(config, run):
        return _invalidate(request, run)
    if failure is None:
        try:
            with transaction.atomic():
                _store_result(run, step, result)
        except WeComError as error:
            # 保存点回滚不会还原 Python 对象；丢弃失败步骤对名单/计划的内存修改。
            run.refresh_from_db()
            failure = error
    if failure is not None:
        # 只保存固定的本地错误说明；上游 errmsg、URL和凭据不会进入审计或响应。
        known = {"SCOPE_INCOMPLETE", "EMPTY_ROSTER", "INVALID_SOURCE_DATA"}
        run.error_code = failure.code if failure.code in known else "UPSTREAM_UNAVAILABLE"
        run.error_message = failure.message if failure.code in known else "企业微信接口暂不可用，请稍后重试。"
        run.status = AttendanceSyncRun.Status.FAILED
        run.retry_after = timezone.now() + timedelta(seconds=3)
    else:
        run.completed_steps += 1
        if run.completed_steps == len(run.steps):
            run.status = AttendanceSyncRun.Status.SUCCESS
            run.finished_at = timezone.now()
            period.active_run = run
            period.save(update_fields=["active_run", "updated_at"])
    run.lease_token = run.lease_expires_at = None
    run.save()
    _audit(request, run, "SYNC_FAILED" if failure else "SYNC_STEP_COMPLETED")
    return run


@sensitive_variables()
def advance_sync(request, run_id):
    config, run, step = _claim(request, run_id)
    if step is None:
        return run
    try:
        result = _fetch(config, step)
    except WeComError as error:
        completed = _finish(request, run, step, None, error)
    else:
        completed = _finish(request, run, step, result)
    if completed.error_code == "PERMISSION_REVOKED":
        raise PermissionDenied("账号状态或考勤权限已变化。")
    return completed
