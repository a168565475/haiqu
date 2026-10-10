import re

from django.db import connection
from django.utils import timezone
from rest_framework.exceptions import ValidationError


PRODUCTION_TASK_NUMBER_PATTERN = re.compile(r"^HT(?P<year>[0-9]{2})(?P<sequence>[0-9]{3})$")
PRODUCTION_TASK_YEARLY_LIMIT = 999


def lock_production_task_number_year(number_date):
    """锁定一个年份的生产任务编号分配；调用方必须处于数据库事务中。"""
    if not connection.in_atomic_block:
        raise RuntimeError("生产任务单号必须在数据库事务中生成。")
    prefix = f"HT{number_date:%y}"
    if connection.vendor == "postgresql":
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT pg_advisory_xact_lock(hashtext(%s))",
                [f"PRODUCTION_TASK_NUMBER:{prefix}"],
            )
    return prefix


def next_production_task_number(business_date=None):
    """生成 HT + 两位年份 + 三位年度流水，例如 HT26202。"""
    from apps.production_tasks.models import ProductionTask

    number_date = business_date or timezone.localdate()
    year_text = f"{number_date:%y}"
    prefix = lock_production_task_number_year(number_date)

    current_max = 0
    for task_number in ProductionTask.objects.filter(
        task_number__startswith=prefix,
    ).values_list("task_number", flat=True):
        matched = PRODUCTION_TASK_NUMBER_PATTERN.fullmatch(task_number)
        if matched and matched.group("year") == year_text:
            current_max = max(current_max, int(matched.group("sequence")))

    next_value = current_max + 1
    if next_value > PRODUCTION_TASK_YEARLY_LIMIT:
        raise ValidationError({"task_number": f"{number_date.year} 年生产任务单已达到 999 张。"})
    return f"{prefix}{next_value:03d}"
