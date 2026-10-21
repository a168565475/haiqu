from datetime import timedelta

from django.db.migrations.recorder import MigrationRecorder
from django.utils import timezone
from rest_framework.exceptions import NotFound

from apps.core.api.concurrency import etag_for_instance
from apps.wecom.models import WeComBinding
from apps.wecom.selectors import get_config
from .models import AttendanceMonth, AttendanceSyncRun
from .source import BEIJING, calendar_day, month_dates


HISTORY_NOTICE = "名单覆盖同步时企业微信当前全员，历史离职成员完整性尚待核对。部门筛选采用来源考勤部门；缺失部门不以当前组织结构补填。"


def schema_is_ready():
    return MigrationRecorder.Migration.objects.filter(app="attendance", name="0001_initial").exists()


def run_payload(run):
    return {"id": run.pk, "month": run.period.month, "status": run.status,
            "phase": run.steps[run.completed_steps]["phase"] if run.completed_steps < len(run.steps) else "completed",
            "completed_steps": run.completed_steps, "total_steps": len(run.steps),
            "scanned_members": run.scanned_members, "error_code": run.error_code, "error_message": run.error_message,
            "can_retry": run.status in {"PENDING", "RUNNING", "FAILED"}, "etag": etag_for_instance(run),
            "created_at": run.created_at, "updated_at": run.updated_at}


def period_for(month):
    corp_id = get_config().corp_id
    period = AttendanceMonth.objects.select_related("active_run", "current_run").filter(corp_id=corp_id, month=month).first()
    return corp_id, period


def get_run(run_id):
    run = AttendanceSyncRun.objects.select_related("period").filter(pk=run_id, period__corp_id=get_config().corp_id).first()
    if run is None:
        raise NotFound("同步任务不存在。")
    return run


def _department_paths(value):
    return {part.strip() for part in (value or "").replace("；", ";").split(";") if part.strip()}


def overview(month):
    corp_id, period = period_for(month)
    run = period.active_run if period else None
    records = list(run.records.values("kind", "user_id", "date", "payload__department_name")) if run else []
    dates = [row["date"] for row in records if row["kind"] in {"raw", "daily"}]
    return {"month": month, "corp_id": corp_id, "has_data": bool(run),
            "last_synced_at": run.finished_at if run else None, "scanned_members": run.scanned_members if run else 0,
            "attendance_members": len({row["user_id"] for row in records}),
            "raw_count": sum(row["kind"] == "raw" for row in records),
            "daily_count": sum(row["kind"] == "daily" for row in records),
            "monthly_count": sum(row["kind"] == "monthly" for row in records),
            "source_start": min(dates) if dates else None, "source_end": max(dates) if dates else None,
            "departments": sorted({path for row in records for path in _department_paths(row["payload__department_name"])}),
            "current_run": run_payload(period.current_run) if period and period.current_run else None,
            "history_notice": HISTORY_NOTICE}


def _snapshot(month):
    corp_id, period = period_for(month)
    run = period.active_run if period else None
    members = {member.user_id: member for member in run.members.all()} if run else {}
    bindings = {}
    # 绑定标识在现有表中大小写不敏感，不能因官方返回大小写变化丢失ERP归属。
    if members:
        bindings = {binding.user_id.lower(): binding for binding in
                    WeComBinding.objects.filter(corp_id=corp_id).select_related("employee")
                    if binding.user_id.lower() in members}
    return corp_id, run, members, bindings


def _base(member, payload, binding):
    return {"user_id": member.user_id, "name": payload.get("name") or member.name,
            "department_name": payload.get("department_name", ""),
            "employee_id": str(binding.employee_id) if binding else None,
            "employee_name": binding.employee.display_name if binding else None}


def _exception_count(payload, kind):
    exceptions = payload.get("exceptions")
    if exceptions is None:
        return None
    matches = [item["count"] for item in exceptions if item["type"] == kind]
    return matches[0] if len(matches) == 1 else (0 if not matches else None)


def record_payload(record, member, binding=None):
    payload = record.payload
    base = _base(member, payload, binding)
    if record.kind == "monthly":
        return {**base, "record_status": "RETURNED", "work_days": payload["work_days"],
                "standard_work_sec": payload["standard_work_sec"], "regular_work_sec": payload["regular_work_sec"],
                "late_count": _exception_count(payload, 1), "early_count": _exception_count(payload, 2),
                "missing_count": _exception_count(payload, 3),
                "sp_items": payload.get("sp_items"), "overwork_info": payload.get("overwork_info")}
    common = {"id": record.pk, "date": record.date.isoformat(), "user_id": base["user_id"], "name": base["name"],
              "department_name": base["department_name"], "group_name": payload["group_name"]}
    if record.kind == "raw":
        return {**common, "checkin_time": payload["checkin_time"], "checkin_type": payload["checkin_type"],
                "exceptions": payload["exceptions"]}
    return {**common, "schedule_name": payload["schedule_name"], "checkin_count": payload["checkin_count"],
            "standard_work_sec": payload["standard_work_sec"], "regular_work_sec": payload["regular_work_sec"],
            "exceptions": payload["exceptions"], "sp_items": payload.get("sp_items"), "ot_info": payload.get("ot_info")}


def rows(kind, parameters):
    _, run, members, bindings = _snapshot(parameters["month"])
    result = []
    returned = set()
    if run:
        query = run.records.filter(kind=kind).order_by("date", "user_id", "step_index", "row_index")
        if parameters.get("date"):
            query = query.filter(date=parameters["date"])
        for record in query:
            returned.add(record.user_id)
            result.append(record_payload(record, members[record.user_id], bindings.get(record.user_id)))
    if kind == "monthly":
        for user_id, member in members.items():
            if user_id not in returned:
                result.append({**_base(member, {}, bindings.get(user_id)), "record_status": "NOT_RETURNED",
                    **dict.fromkeys(["work_days", "standard_work_sec", "regular_work_sec", "late_count", "early_count", "missing_count", "sp_items", "overwork_info"])})
    search = parameters.get("search", "").casefold()
    selected = []
    for row in result:
        if parameters.get("user_id") and row["user_id"] != parameters["user_id"].lower():
            continue
        if parameters.get("department") and parameters["department"] not in _department_paths(row["department_name"]):
            continue
        if search and search not in (row["name"] + " " + row["user_id"]).casefold():
            continue
        if parameters.get("status") and row.get("record_status") != parameters["status"]:
            continue
        if parameters.get("binding") and ("BOUND" if row["user_id"] in bindings else "UNBOUND") != parameters["binding"]:
            continue
        selected.append(row)
    page, size = parameters["page"], parameters["page_size"]
    return {"data": selected[(page - 1) * size:page * size], "count": len(selected), "page": page, "page_size": size}


def member_calendar(month, user_id):
    _, run, members, bindings = _snapshot(month)
    member = members.get(user_id.lower())
    if member is None:
        raise NotFound("当前成功快照中未找到此成员。")
    daily, raw = {}, {}
    for record in run.records.filter(user_id=member.user_id).exclude(kind="monthly").order_by("date", "step_index", "row_index"):
        target = daily if record.kind == "daily" else raw
        target.setdefault(record.date, []).append(record_payload(record, member, bindings.get(member.user_id)))
    first, last = month_dates(month)
    today = timezone.now().astimezone(BEIJING).date()
    return {"month": month, "user_id": member.user_id, "name": member.name,
            "days": [calendar_day(day, daily.get(day, []), raw.get(day, []), today)
                     for day in (first + timedelta(days=index) for index in range((last - first).days + 1))]}
