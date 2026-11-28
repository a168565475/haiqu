from datetime import date
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.utils import timezone


BEIJING = ZoneInfo("Asia/Shanghai")
PRIORITY = {"OVERDUE": 0, "DUE_TODAY": 1, "NEAR_DUE": 2, "REVIEW": 3, "UPCOMING": 4}
FOLLOW_UP_FILTERS = ("ALL", "FOLLOW_UP", "OVERDUE", "DUE_TODAY", "NEAR_DUE", "REVIEW")


def business_today():
    return timezone.localdate(timezone=BEIJING)


def delivery_reminder(*, today, window, due, quantity, unit, action, owner, reference, review="", reason="", shared=False):
    if quantity is not None and quantity <= 0:
        return None
    if review or quantity is None or not unit:
        status, label = "REVIEW", review or "数量待核"
    elif due is None:
        status, label = "REVIEW", "未约定交期"
    else:
        days = (due - today).days
        if days < 0:
            status, label = "OVERDUE", f"逾期 {-days} 天"
        elif days == 0:
            status, label = "DUE_TODAY", "今天到期"
        elif days <= window:
            status, label = "NEAR_DUE", f"临期 · {days} 天"
        else:
            status, label = "UPCOMING", "未到提醒窗口"
    return {
        "status": status, "label": label, "due": due,
        "quantity": format(quantity, "f") if isinstance(quantity, Decimal) else quantity,
        "unit": unit, "action": action, "owner": owner, "reference": reference, "reason": reason, "shared": shared,
    }


def reminder_matches(reminder, follow_up, owner):
    if reminder is None:
        return follow_up == "ALL" and not owner
    status = reminder["status"]
    if owner and owner.casefold() not in reminder["owner"].casefold():
        return False
    return follow_up == "ALL" or status == follow_up or (follow_up == "FOLLOW_UP" and status != "UPCOMING")


def reminder_order(reminder):
    if reminder is None:
        return len(PRIORITY), date.max
    return PRIORITY[reminder["status"]], reminder["due"] or date.max


def matching_reminder(reminders, follow_up, owner):
    return min((item for item in reminders if item is not None and reminder_matches(item, follow_up, owner)),
               key=reminder_order, default=None)
