"""询盘工作时钟；日历保存在阶段快照中，规则更新不改变历史截止时间。"""
from datetime import date, datetime, time, timedelta, timezone as datetime_timezone
from zoneinfo import ZoneInfo

from django.db.models import Q


def validate_calendar(calendar):
    if not isinstance(calendar, dict) or calendar.get("mode") != "ALTERNATING_WEEKS_V1" or calendar.get("timezone") != "Asia/Shanghai":
        raise ValueError("询盘工作日历格式不正确。")
    anchor = date.fromisoformat(calendar["rest_saturday"])
    if anchor.weekday() != 5:
        raise ValueError("双休周基准必须是星期六。")
    periods = calendar.get('periods')
    if not isinstance(periods, list) or len(periods) != 2:
        raise ValueError('请设置上午、下午两个工作时段。')
    previous_end = -1
    for period in periods:
        if not isinstance(period, list) or len(period) != 2 or any(type(value) is not int for value in period):
            raise ValueError('工作时段必须为整数分钟。')
        start, end = period
        if not 0 <= start < end <= 1440 or start < previous_end:
            raise ValueError('工作时段须按先后排列，不能重叠或跨天。')
        previous_end = end
    return anchor


def work_periods(day, calendar):
    anchor = validate_calendar(calendar)
    if day.weekday() == 6 or (day.weekday() == 5 and ((day - anchor).days // 7) % 2 == 0):
        return []
    midnight = datetime.combine(day, time(), ZoneInfo(calendar["timezone"]))
    return [(midnight + timedelta(minutes=start), midnight + timedelta(minutes=end)) for start, end in calendar["periods"]]


def add_work_minutes(start, minutes, calendar):
    validate_calendar(calendar)
    if start.utcoffset() is None or not isinstance(minutes, int) or isinstance(minutes, bool) or not 0 <= minutes <= 527040:
        raise ValueError("开始时间须含时区，目标分钟数须在 0—527040 内。")
    cursor = start.astimezone(ZoneInfo(calendar["timezone"]))
    remaining = minutes * 60
    # 上限防止异常规则导致无限循环，设置保存时也验证目标能在此范围内完成。
    for _ in range(3660):
        for begin, end in work_periods(cursor.date(), calendar):
            begin = max(begin, cursor)
            if begin >= end:
                continue
            available = (end - begin).total_seconds()
            if remaining <= available:
                return (begin + timedelta(seconds=remaining)).astimezone(datetime_timezone.utc)
            remaining -= available
        cursor = datetime.combine(cursor.date() + timedelta(days=1), time(), cursor.tzinfo)
    raise ValueError("无法在有效工作日历范围内计算截止时间。")


def working_seconds(start, end, calendar):
    validate_calendar(calendar)
    if start.utcoffset() is None or end.utcoffset() is None:
        raise ValueError("工作时间计算需要明确时区。")
    if start > end:
        return -working_seconds(end, start, calendar)
    zone = ZoneInfo(calendar["timezone"])
    first, last = start.astimezone(zone).date(), end.astimezone(zone).date()
    days = (last - first).days
    if days > 36600:
        raise ValueError("工作时间跨度超过有效范围。")
    total = 0
    for offset in range(days + 1):
        for begin, finish in work_periods(first + timedelta(days=offset), calendar):
            total += max(0, (min(end, finish) - max(start, begin)).total_seconds())
    return int(total)


def remaining_seconds(tracking, now):
    if tracking.next_deadline_at is None:
        return None
    calendar = tracking.tracking_data.get("work_calendar")
    end = tracking.completed_at or now
    return working_seconds(end, tracking.next_deadline_at, calendar) if calendar else int((tracking.next_deadline_at - end).total_seconds())


def due_soon_query(now):
    """新记录使用冻结的工作时间提醒点；旧记录保留连续时间规则。"""
    prefix = "sla_links__sla_tracking__"
    warning = prefix + "tracking_data__warning_at"
    return Q(**{prefix + "status": "RUNNING", prefix + "next_deadline_at__gte": now}) & (
        Q(**{warning + "__lte": now.astimezone(datetime_timezone.utc).isoformat()}) |
        (Q(**{warning + "__isnull": True}) & Q(**{prefix + "next_deadline_at__lte": now + timedelta(minutes=30)}))
    )


def breached_query(now):
    return Q(sla_links__sla_tracking__status="BREACHED") | Q(
        sla_links__sla_tracking__status="RUNNING", sla_links__sla_tracking__next_deadline_at__lt=now,
    )
