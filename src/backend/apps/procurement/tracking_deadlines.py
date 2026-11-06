"""未买足材料的采购期限判断；不查询数据库，也不登记提醒。"""
from datetime import timedelta, timezone

from apps.material_catalog.definitions import CATEGORY_CHOICES

from .tracking_rules import BEIJING, risk


CATEGORY_KEYS = frozenset(key for key, _ in CATEGORY_CHOICES)


def _configured_days(value):
    return value if isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= 365 else None


def coverage_timing(*, now, bom_confirmed_at, bom_verified, scheduled, material_inbound_date,
                    order_delivery_date, category_key, policy):
    if now.utcoffset() is None:
        raise ValueError('采购期限判断需要带时区的当前时间。')
    risks = []
    bom_due_at = None
    latest_purchase_date = None
    days_remaining = None

    if bom_verified:
        timeout_days = _configured_days(policy.get('bom_timeout_days'))
        confirmation_known = bom_confirmed_at is not None and bom_confirmed_at.utcoffset() is not None
        if not confirmation_known:
            risks.append(risk('BOM_CONFIRMATION_UNKNOWN'))
        if timeout_days is None:
            risks.append(risk('PURCHASE_RULE_UNKNOWN'))
        if confirmation_known and timeout_days is not None:
            # 先转换到 UTC，确保每一天都按完整 24 小时计算。
            bom_due_at = (bom_confirmed_at.astimezone(timezone.utc) + timedelta(days=timeout_days)).astimezone(BEIJING)
            if now >= bom_due_at:
                risks.append(risk('BOM_PURCHASE_TIMEOUT'))

    if scheduled:
        category_lead_days = policy.get('category_lead_days') or {}
        lead_days = _configured_days(category_lead_days.get(category_key)) if category_key in CATEGORY_KEYS else None
        if material_inbound_date is None:
            risks.append(risk('SCHEDULE_DATE_UNKNOWN'))
        if lead_days is None:
            risks.append(risk('PURCHASE_RULE_UNKNOWN'))
        if material_inbound_date is not None and lead_days is not None:
            latest_purchase_date = material_inbound_date - timedelta(days=lead_days)
            days_remaining = (latest_purchase_date - now.astimezone(BEIJING).date()).days
            if days_remaining < 0:
                risks.append(risk('PURCHASE_OVERDUE', f'已超最晚采购日{-days_remaining}天'))
            elif days_remaining == 0:
                risks.append(risk('PURCHASE_DUE_TODAY'))
            else:
                risks.append(risk('PURCHASE_UPCOMING', f'还剩{days_remaining}天采购'))

    if order_delivery_date is None:
        risks.append(risk('ORDER_DELIVERY_UNKNOWN'))

    unique_risks = {item['code']: item for item in risks}
    return {
        'bom_purchase_due_at': bom_due_at.isoformat() if bom_due_at is not None else None,
        'latest_purchase_date': latest_purchase_date.isoformat() if latest_purchase_date is not None else None,
        'purchase_days_remaining': days_remaining,
        'timing_risks': sorted(unique_risks.values(), key=lambda item: -item['rank']),
    }
