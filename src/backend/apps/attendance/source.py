"""企微来源边界：仅接纳已核实字段，不从缺失值推算考勤结论。"""
import calendar
import re
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from apps.wecom.client import WeComError


BEIJING = ZoneInfo("Asia/Shanghai")
EXCEPTION_STATES = {1: "late", 2: "early", 3: "missing", 4: "absent", 5: "location", 6: "device"}
DAILY_OVERTIME_FIELDS = (
    "workday_over_as_vacation", "workday_over_as_money", "restday_over_as_vacation",
    "restday_over_as_money", "holiday_over_as_vacation", "holiday_over_as_money",
)
MONTHLY_OVERTIME_FIELDS = (
    "workday_over_sec", "restdays_over_sec", "holidays_over_sec", "workdays_over_as_vacation",
    "workdays_over_as_money", "restdays_over_as_vacation", "restdays_over_as_money",
    "holidays_over_as_vacation", "holidays_over_as_money",
)


def source_error():
    return WeComError("INVALID_SOURCE_DATA", "企业微信返回的数据格式或人员范围不符合接口约定，未保存本步骤。")


def month_dates(month):
    if not isinstance(month, str) or not re.fullmatch(r"20\d{2}-(0[1-9]|1[0-2])", month):
        raise ValueError("月份必须为 2000 至 2099 年内的 YYYY-MM。")
    year, number = map(int, month.split("-"))
    first = date(year, number, 1)
    last = date(year, number, calendar.monthrange(year, number)[1])
    return first, last


def build_record_steps(month, user_ids):
    first, last = month_dates(month)
    start = int(datetime.combine(first, datetime.min.time(), BEIJING).timestamp())
    end = int(datetime.combine(last + timedelta(days=1), datetime.min.time(), BEIJING).timestamp())
    steps = []
    for offset in range(0, len(user_ids), 20):
        batch = user_ids[offset:offset + 20]
        for raw_start in range(start, end, 30 * 86400):
            steps.append({"phase": "records", "kind": "raw", "starttime": raw_start,
                          "endtime": min(raw_start + 30 * 86400, end) - 1, "userids": batch})
        for kind in ("daily", "monthly"):
            steps.append({"phase": "records", "kind": kind, "starttime": start,
                          "endtime": end - 86400, "userids": batch})
    return steps


def _object(value):
    if not isinstance(value, dict):
        raise source_error()
    return value


def _text(value, limit=250):
    if not isinstance(value, str) or len(value) > limit or any(ord(char) < 32 for char in value):
        raise source_error()
    return value


def _number(value):
    if value is not None and (type(value) is not int or value < 0 or value > 10 ** 12):
        raise source_error()
    return value


def _timestamp(value):
    if type(value) is not int or not 0 <= value <= 4102444799:
        raise source_error()
    return datetime.fromtimestamp(value, BEIJING)


def _exceptions(row):
    if "exception_infos" not in row:
        return None
    values = row["exception_infos"]
    if not isinstance(values, list) or len(values) > 100:
        raise source_error()
    result = []
    for value in values:
        value = _object(value)
        kind = value.get("exception")
        if type(kind) is not int or kind not in EXCEPTION_STATES:
            raise source_error()
        result.append({"type": kind, "count": _number(value.get("count"))})
    return result


def _source_integer(value, signed=False):
    if value is not None and (type(value) is not int or not (-(2 ** 31) if signed else 0) <= value < (2 ** 31 if signed else 2 ** 32)):
        raise source_error()
    return value


def normalize_supplements(kind, row):
    items = row.get("sp_items")
    if items is not None:
        if not isinstance(items, list):
            raise source_error()
        normalized = []
        for item in items:
            item = _object(item)
            if item.get("type") is None:
                raise source_error()
            value = {field: _source_integer(item.get(field)) for field in ("type", "vacation_id", "count", "duration", "time_type")}
            value["name"] = _text(item["name"], 250) if item.get("name") is not None else None
            normalized.append(value)
        items = normalized
    field = "ot_info" if kind == "daily" else "overwork_info"
    overtime = row.get(field)
    if overtime is not None:
        overtime = _object(overtime)
        names = DAILY_OVERTIME_FIELDS if kind == "daily" else MONTHLY_OVERTIME_FIELDS
        value = {name: _source_integer(overtime.get(name), signed=True) for name in names}
        if kind == "daily":
            value.update({name: _source_integer(overtime.get(name)) for name in ("ot_status", "ot_duration")})
            shortages = overtime.get("exception_duration")
            if shortages is not None:
                if not isinstance(shortages, list) or any(item is None for item in shortages):
                    raise source_error()
                shortages = [_source_integer(item) for item in shortages]
            value["exception_duration"] = shortages
        overtime = value
    return {"sp_items": items, field: overtime}


def normalize_record(kind, row, allowed_users, month):
    row = _object(row)
    first, last = month_dates(month)
    if kind == "raw":
        user_id = _text(row.get("userid"), 64)
        checkin_time = _timestamp(row.get("checkin_time"))
        record_date = checkin_time.date()
        exception = _text(row.get("exception_type", ""), 1000)
        payload = {"name": "", "department_name": "", "checkin_time": checkin_time.isoformat(),
                   "checkin_type": _text(row.get("checkin_type", "")),
                   "group_name": _text(row.get("groupname", "")),
                   "exceptions": [item.strip() for item in exception.split(";") if item.strip()]}
    elif kind in {"daily", "monthly"}:
        base = _object(row.get("base_info"))
        summary = _object(row.get("summary_info", {}))
        rule = _object(base.get("rule_info", {}))
        user_id = _text(base.get("acctid"), 64)
        record_date = _timestamp(base.get("date")).date() if kind == "daily" else first
        departments = base.get("departs_name", "")
        payload = {"name": _text(base.get("name", ""), 150), "department_name": _text(departments, 2000),
                   "group_name": _text(rule.get("groupname", "")),
                   "standard_work_sec": _number(summary.get("standard_work_sec")),
                   "regular_work_sec": _number(summary.get("regular_work_sec")), "exceptions": _exceptions(row)}
        if kind == "daily":
            payload.update(schedule_name=_text(rule.get("schedulename", "")),
                           checkin_count=_number(summary.get("checkin_count")))
        else:
            payload["work_days"] = _number(summary.get("work_days"))
        payload.update(normalize_supplements(kind, row))
    else:
        raise source_error()
    if not user_id or user_id.lower() not in {item.lower() for item in allowed_users} or not first <= record_date <= last:
        raise source_error()
    return {"kind": kind, "user_id": user_id.lower(), "date": record_date, "payload": payload}


def calendar_day(day, daily_rows, raw_rows, today):
    exceptions = None
    complete_exceptions = bool(daily_rows) and all(row["exceptions"] is not None for row in daily_rows)
    if any(row["exceptions"] is not None for row in daily_rows):
        exceptions = [item for row in daily_rows for item in (row["exceptions"] or [])]
    count = daily_rows[0]["checkin_count"] if len(daily_rows) == 1 else None
    states = []
    for item in exceptions or []:
        if item["count"] is None or item["count"] > 0:
            state = EXCEPTION_STATES[item["type"]]
            if state not in states:
                states.append(state)
    if day > today:
        states.append("future")
    elif len(daily_rows) == 1 and count == 0:
        states.append("zero")
    elif (len(daily_rows) == 1 and count is not None and count > 0 and exceptions is not None
          and all(item["count"] == 0 for item in exceptions)):
        states.append("normal")
    if not daily_rows:
        if raw_rows:
            states.append("recorded")
        if day <= today:
            states.append("unknown")
    elif count is None or not complete_exceptions or any(item["count"] is None for item in exceptions):
        states.append("unknown")
    return {"date": day.isoformat(), "report_returned": bool(daily_rows), "checkin_count": count,
            "states": states, "exceptions": exceptions, "raw": raw_rows,
            "source_summaries": [{"record_id": row.get("id"), "sp_items": row.get("sp_items"),
                                  "ot_info": row.get("ot_info")} for row in daily_rows]}
