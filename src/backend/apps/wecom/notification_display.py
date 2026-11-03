from django.utils import timezone
from django.utils.dateparse import parse_datetime

from .notification_catalog import VARIABLE


TIME_VARIABLES = {"occurred_at", "confirmed_at"}


def format_notification_value(name, value):
    text = str(value)
    if name not in TIME_VARIABLES:
        return text
    try:
        instant = parse_datetime(text)
        if instant is None or timezone.is_naive(instant):
            return text
        return timezone.localtime(instant, timezone.get_default_timezone()).strftime("%Y-%m-%d %H:%M:%S")
    except (ValueError, OverflowError):
        return text


def render_notification_template(template, context, *, format_times=True):
    return VARIABLE.sub(
        lambda match: format_notification_value(match.group(1), context[match.group(1)])
        if format_times else str(context[match.group(1)]), template,
    )


def saved_notification_body(body, definition, context):
    if not isinstance(context, dict):
        return body
    # 历史记录没有保存原模板；只识别完整默认正文，不猜改自定义内容。
    for template in (definition["default_body"], definition["legacy_default_body"]):
        names = VARIABLE.findall(template)
        if any(name not in context or context[name] is None for name in names):
            continue
        if body == render_notification_template(template, context, format_times=False):
            return render_notification_template(template, context)
    return body
