from datetime import date, datetime
from zoneinfo import ZoneInfo

from django.db import connection
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from .models import DailyBusinessNumberCounter


DAILY_NUMBER_RULES = {
    "FINANCE_ACCOUNT": "ZH",
    "RECEIVABLE_STATEMENT": "YSDZD",
    "FINANCE_RECEIPT": "SKQRD",
    "BOM": "BOM",
    "PURCHASE_ORDER": "CGDD",
    "PURCHASE_REQUEST": "PR",
    "PURCHASE_RETURN": "TH",
    "PRODUCTION_SCHEDULE": "PC",
    "MATERIAL_INBOUND": "CLRK",
    "MATERIAL_ISSUE": "LL",
    "INTERNAL_SEMI_RECEIPT": "BNRK",
    "FINISHED_GOODS_RECEIPT": "CPRK",
    "FINISHED_GOODS_OUTBOUND": "CPCK",
    "OUTSOURCING_ORDER": "WF",
    "OUTSOURCING_DISPATCH": "FL",
    "OUTSOURCING_RETURN": "WH",
    "TUBE_OUTSOURCING_RECEIPT": "WFHK",
    "WORK_REPORT": "BG",
}


def next_daily_business_number(number_type, business_date=None):
    """在业务事务内分配前缀 + YYMMDD + 至少三位流水，失败随业务回滚。"""
    if number_type not in DAILY_NUMBER_RULES:
        raise ValueError(f"不支持的日流水编号类型：{number_type}")
    if business_date is None:
        business_date = timezone.localdate(timezone=ZoneInfo("Asia/Shanghai"))
    if not isinstance(business_date, date) or isinstance(business_date, datetime):
        raise ValueError("业务编号日期必须是 date 类型。")
    if not 2000 <= business_date.year <= 2099:
        raise ValidationError("两位年份日流水仅支持 2000–2099 年的业务日期。")
    if not connection.in_atomic_block:
        raise RuntimeError("日流水业务编号必须在数据库事务中生成。")

    table = connection.ops.quote_name(DailyBusinessNumberCounter._meta.db_table)
    # 同日同类型的 UPSERT 会锁定同一行；不扫描业务表，也不使用不能回滚的 PG 序列。
    with connection.cursor() as cursor:
        cursor.execute(
            f"INSERT INTO {table} (number_type, business_date, last_value) VALUES (%s, %s, 1) "
            "ON CONFLICT (number_type, business_date) DO UPDATE "
            f"SET last_value = {table}.last_value + 1 RETURNING last_value",
            [number_type, business_date],
        )
        sequence = cursor.fetchone()[0]
    return f"{DAILY_NUMBER_RULES[number_type]}{business_date:%y%m%d}{sequence:03d}"
