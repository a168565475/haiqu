"""全员月度安排；仅供展示，不重新计算企业微信考勤结果。"""
import calendar
import hashlib
from datetime import date, datetime
from zoneinfo import ZoneInfo

from django.core import signing
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.core.api.concurrency import PreconditionFailed, PreconditionRequired, etag_for_instance
from apps.core.audit import write_audit_log

BEIJING = ZoneInfo("Asia/Shanghai")
IMPORT_SALT = "attendance.schedule-source.v1"


class RuleNeedsReview(ValueError):
    pass


def month_days(month):
    return [date(month.year, month.month, day) for day in range(1, calendar.monthrange(month.year, month.month)[1] + 1)]


def empty_days(month):
    return [{"date": day.isoformat(), "kind": "UNSET", "periods": []} for day in month_days(month)]


def _periods(rows):
    if not isinstance(rows, list) or not 1 <= len(rows) <= 8:
        raise RuleNeedsReview("规则缺少确定的上下班时段，请手动设置。")
    periods = []
    for row in rows:
        if not isinstance(row, dict):
            raise RuleNeedsReview("规则时段格式不可用，请手动设置。")
        start, end = row.get("work_sec"), row.get("off_work_sec")
        if type(start) is not int or type(end) is not int or not 0 <= start < end < 86400:
            raise RuleNeedsReview("时段缺失或涉及跨日，无法直接导入当前月安排。")
        periods.append({"start_sec": start, "end_sec": end})
    periods.sort(key=lambda item: item["start_sec"])
    if any(left["end_sec"] > right["start_sec"] for left, right in zip(periods, periods[1:])):
        raise RuleNeedsReview("规则时段有重叠，请核对后手动设置。")
    return periods


def _weekdays(value):
    if not isinstance(value, list) or not value or any(type(day) is not int or day not in range(7) for day in value):
        raise RuleNeedsReview("规则没有明确的每周工作日，请手动设置休息日期。")
    return set(value)


def _special_days(rows):
    if not isinstance(rows, list):
        raise RuleNeedsReview("特殊日期格式不可用，请核对规则。")
    result = {}
    for row in rows:
        if not isinstance(row, dict) or type(row.get("timestamp")) is not int or not 0 < row["timestamp"] < 253402214400:
            raise RuleNeedsReview("特殊日期不完整，请核对规则。")
        day = datetime.fromtimestamp(row["timestamp"], BEIJING).date()
        if day in result:
            raise RuleNeedsReview("规则存在重复的特殊日期，请核对后手动设置。")
        result[day] = row
    return result


def _rule_days(group, month):
    if group.get("grouptype") != 1:
        raise RuleNeedsReview("按班次或自由打卡规则不能直接变为全员统一月安排，请手动设置。")
    blocks = group.get("checkindate")
    if not isinstance(blocks, list) or not blocks:
        raise RuleNeedsReview("规则未返回工作日设置。")
    rules = []
    for block in blocks:
        if not isinstance(block, dict):
            raise RuleNeedsReview("工作日设置格式不可用。")
        biweekly = block.get("biweekly", {})
        if not isinstance(biweekly, dict):
            raise RuleNeedsReview("大小周设置格式不可用。")
        if biweekly.get("enable_weekday_recurrence") is True:
            odd, even = _weekdays(biweekly.get("odd_workdays")), _weekdays(biweekly.get("even_workdays"))
        else:
            odd = even = _weekdays(block.get("workdays"))
        rules.append((odd, even, _periods(block.get("checkintime"))))
    work = _special_days(group.get("spe_workdays", []))
    rest = _special_days(group.get("spe_offdays", []))
    if set(work) & set(rest):
        raise RuleNeedsReview("同一天同时设置为特殊工作与休息，请核对企业微信规则。")
    result = []
    for day in month_days(month):
        periods = []
        weekday = day.isoweekday() % 7
        week = (day - date(2024, 1, 1)).days // 7 + 1
        for odd, even, candidate in rules:
            if weekday in (odd if week % 2 else even):
                if periods and periods != candidate:
                    raise RuleNeedsReview("同一天存在不同的基础时段，请核对后手动设置。")
                periods = candidate
        if day in work:
            periods = _periods(work[day].get("checkintime"))
        if day in rest:
            periods = []
        result.append({"date": day.isoformat(), "kind": "WORK" if periods else "REST", "periods": periods})
    return result


def _import_token(source, corp_id, month):
    return signing.dumps({"corp_id": corp_id, "month": month.strftime("%Y-%m"), "source": source},
                         salt=IMPORT_SALT, compress=True) if source else None


def rule_options(groups, month, corp_id):
    fetched_at = timezone.now().isoformat()
    result = []
    for group in groups:
        warnings = ["读取的是当前企微规则，不能证明所选月份的历史排班；请核对后保存。"]
        if group.get("sync_holidays") is True:
            warnings.append("该规则启用法定节假日同步；接口没有完整节假日表，请核对当月休息和调休日期。")
        item = {"id": group["groupid"], "name": group["groupname"], "type": group["grouptype"],
                "can_import": True, "reason": "", "days": [], "warnings": warnings, "import_token": None}
        try:
            item["days"] = _rule_days(group, month)
        except RuleNeedsReview as error:
            item.update(can_import=False, reason=str(error))
        if item["can_import"]:
            source = {"rule_id": item["id"], "rule_name": item["name"], "fetched_at": fetched_at, "warnings": warnings}
            item["import_token"] = _import_token(source, corp_id, month)
        result.append(item)
    return {"rules": result, "fetched_at": fetched_at}


def schedule_etag(instance, corp_id, month):
    if instance is not None:
        return etag_for_instance(instance)
    digest = hashlib.sha256(f"schedule:new:{corp_id}:{month.isoformat()}".encode()).hexdigest()
    return f'"{digest}"'


def _source(instance):
    if instance is None or instance.source_rule_id is None:
        return None
    return {"rule_id": instance.source_rule_id, "rule_name": instance.source_rule_name,
            "fetched_at": instance.source_fetched_at.isoformat(), "warnings": instance.source_warnings}


def get_schedule(corp_id, month):
    from .models import AttendanceSchedule
    instance = AttendanceSchedule.objects.filter(corp_id=corp_id, month=month).first()
    source = _source(instance)
    return {"month": month.strftime("%Y-%m"), "configured": instance is not None,
            "days": instance.days if instance else empty_days(month), "source": source,
            "import_token": _import_token(source, corp_id, month), "etag": schedule_etag(instance, corp_id, month)}


def require_schedule_access(request):
    from apps.access_control import module_policy
    from .services import require_access
    require_access(request, fresh=True)
    if not module_policy.has_permission(request, "attendance.manage_schedule"):
        raise PermissionDenied("当前账号没有月度安排管理权限。")


@transaction.atomic
def save_schedule(request, corp_id, month, data):
    from .models import AttendanceSchedule
    from .models import AttendanceMonth
    from apps.wecom.models import WeComConfig
    from apps.core.api.exceptions import Conflict
    require_schedule_access(request)
    config = WeComConfig.objects.select_for_update().first()
    if config is None or config.corp_id != corp_id:
        raise Conflict("企业微信企业配置已变化，请刷新后重试。")
    # 与同步共用企业月份行锁，安全串行化首次创建；不锁企微网络请求。
    month_key = month.strftime("%Y-%m")
    AttendanceMonth.objects.get_or_create(corp_id=corp_id, month=month_key)
    AttendanceMonth.objects.select_for_update().get(corp_id=corp_id, month=month_key)
    instance = AttendanceSchedule.objects.select_for_update().filter(corp_id=corp_id, month=month).first()
    supplied = request.headers.get("If-Match")
    if not supplied:
        raise PreconditionRequired()
    if supplied != schedule_etag(instance, corp_id, month):
        raise PreconditionFailed()
    source = None
    token = data.get("import_token")
    if token:
        try:
            value = signing.loads(token, salt=IMPORT_SALT, max_age=3600)
        except signing.BadSignature:
            raise ValidationError({"import_token": "规则来源已失效，请重新读取安排或规则。"}) from None
        if not isinstance(value, dict) or value.get("corp_id") != corp_id or value.get("month") != month.strftime("%Y-%m"):
            raise ValidationError({"import_token": "规则来源与当前企业或月份不一致。"})
        source = value["source"]
    before = {"days": instance.days, "source": _source(instance)} if instance else {}
    if instance is None:
        instance = AttendanceSchedule(corp_id=corp_id, month=month)
    instance.days = data["days"]
    instance.source_rule_id = source["rule_id"] if source else None
    instance.source_rule_name = source["rule_name"] if source else ""
    instance.source_fetched_at = datetime.fromisoformat(source["fetched_at"]) if source else None
    instance.source_warnings = source["warnings"] if source else []
    instance.save()
    write_audit_log(object_type="ATTENDANCE_SCHEDULE", object_id=instance.pk, action="UPDATE",
                    actor_employee=request.employee, before_data=before,
                    after_data={"days": instance.days, "source": _source(instance)}, request=request)
    return get_schedule(corp_id, month)


def decorate_calendar(payload, corp_id):
    from .models import AttendanceSchedule
    month = date.fromisoformat(payload["month"] + "-01")
    instance = AttendanceSchedule.objects.filter(corp_id=corp_id, month=month).first()
    plans = {day["date"]: day for day in instance.days} if instance else {}
    for day in payload["days"]:
        day["schedule"] = plans.get(day["date"])
        if day["schedule"] and day["schedule"]["kind"] == "REST" and "rest" not in day["states"]:
            day["states"].append("rest")
    return payload
