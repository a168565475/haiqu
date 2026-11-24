"""采购跟踪的纯判断：不写业务数据，也不登记通知。"""
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo


BEIJING = ZoneInfo('Asia/Shanghai')
RISK_DEFINITIONS = {
    'NEAR_DUE': ('临近交期', 'warning', 60),
    'DUE_TODAY': ('今天到期', 'warning', 70),
    'OVERDUE': ('已逾期', 'danger', 80),
    'DELIVERY_UNKNOWN': ('交期待核对', 'warning', 65),
    'CLASSIFICATION_UNKNOWN': ('分类待核对', 'warning', 65),
    'ARRIVAL_UNKNOWN': ('到货数据待核对', 'warning', 65),
    'RETURN_PENDING': ('退货待处理', 'warning', 75),
    'ARRIVED': ('已到齐', 'success', 10),
    'OUTSIDE_WINDOW': ('未到提醒窗口', 'info', 0),
    'ENDED': ('已结束', 'info', 0),
    'SCHEDULED_UNPURCHASED': ('已排产未采购', 'danger', 90),
    'SCHEDULED_SHORT': ('已排产未买足', 'danger', 90),
    'PENDING_PURCHASE': ('普通待采购', 'info', 20),
    'COVERED': ('采购足量', 'success', 10),
    'DEMAND_UNKNOWN': ('需求待核对', 'warning', 85),
    'DEMAND_CHANGED': ('需求变化待核对', 'warning', 85),
    'PURCHASE_OVERDUE': ('已超最晚采购日', 'danger', 110),
    'PURCHASE_DUE_TODAY': ('今天最晚采购', 'danger', 100),
    'PURCHASE_UPCOMING': ('尚有采购时间', 'info', 40),
    'BOM_PURCHASE_TIMEOUT': ('BOM确认后已超采购期限', 'warning', 90),
    'BOM_CONFIRMATION_UNKNOWN': ('BOM确认时间待核对', 'warning', 95),
    'SCHEDULE_DATE_UNKNOWN': ('排产入库日期待核对', 'warning', 95),
    'PURCHASE_RULE_UNKNOWN': ('采购提醒规则待设置', 'warning', 95),
    'ORDER_DELIVERY_UNKNOWN': ('订单交期待核对', 'warning', 95),
}
ARRIVAL_ACTIVE_CODES = frozenset({'NEAR_DUE', 'DUE_TODAY', 'OVERDUE', 'DELIVERY_UNKNOWN',
                                 'CLASSIFICATION_UNKNOWN', 'ARRIVAL_UNKNOWN'})
COVERAGE_ACTIVE_CODES = frozenset({'SCHEDULED_UNPURCHASED', 'SCHEDULED_SHORT', 'DEMAND_UNKNOWN', 'DEMAND_CHANGED'})
COVERAGE_TIMING_ACTIVE_CODES = frozenset({'PURCHASE_OVERDUE', 'PURCHASE_DUE_TODAY', 'BOM_PURCHASE_TIMEOUT',
    'BOM_CONFIRMATION_UNKNOWN', 'SCHEDULE_DATE_UNKNOWN', 'PURCHASE_RULE_UNKNOWN', 'ORDER_DELIVERY_UNKNOWN'})


def beijing_today():
    return datetime.now(BEIJING).date()


def decimal_value(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        number = Decimal(str(value))
    except (ValueError, ArithmeticError):
        return None
    return number if number.is_finite() and number >= 0 else None


def quantity_text(value):
    return format(value, 'f') if value is not None else None


def root_count_value(value):
    number = decimal_value(value)
    if number is None or not 0 < number <= 9223372036854775807 or number != number.to_integral_value():
        return None
    return int(number)


def risk(code, label=None):
    text, level, rank = RISK_DEFINITIONS[code]
    return {'code': code, 'label': label or text, 'level': level, 'rank': rank}


def arrival_risks(*, status, archived, unreceived, delivery_date, is_pipe, today,
                  return_pending, source_reliable):
    rows = []
    active = not archived and status in {'SUBMITTED', 'PURCHASING'}
    if not active:
        rows.append(risk('ENDED'))
    else:
        if not source_reliable:
            rows.append(risk('ARRIVAL_UNKNOWN'))
        if unreceived is not None and unreceived == 0:
            rows.append(risk('ARRIVED'))
        else:
            if is_pipe is None:
                rows.append(risk('CLASSIFICATION_UNKNOWN'))
            if delivery_date is None:
                rows.append(risk('DELIVERY_UNKNOWN'))
            elif unreceived is not None and unreceived > 0:
                days = (delivery_date - today).days
                if days < 0:
                    rows.append(risk('OVERDUE', f'逾期 {-days} 天'))
                elif days == 0:
                    rows.append(risk('DUE_TODAY'))
                elif is_pipe is not None:
                    rows.append(risk('NEAR_DUE', f'{days} 天后到期') if days <= (5 if is_pipe else 3)
                                else risk('OUTSIDE_WINDOW'))
    if return_pending:
        rows.append(risk('RETURN_PENDING'))
    return sorted(rows, key=lambda item: -item['rank'])


def coverage_risks(*, required, purchased, scheduled, reliable, changed, history):
    if history:
        return [risk('ENDED')]
    if changed:
        return [risk('DEMAND_CHANGED')]
    if not reliable or required is None or purchased is None:
        return [risk('DEMAND_UNKNOWN')]
    if purchased >= required:
        return [risk('COVERED')]
    if scheduled:
        return [risk('SCHEDULED_UNPURCHASED' if purchased == 0 else 'SCHEDULED_SHORT')]
    return [risk('PENDING_PURCHASE')]


def issue_candidates(rows, kind):
    if kind not in {'arrival', 'coverage'}:
        raise ValueError('未知采购跟踪类型。')
    candidates = []
    for row in rows:
        risks = row['risks']
        if kind == 'arrival':
            groups = [('arrival:' + row['purchase_order_line_id'],
                       [item for item in risks if item['code'] in ARRIVAL_ACTIVE_CODES and not row['is_history']]),
                      ('return:' + row['purchase_order_line_id'],
                       [item for item in risks if item['code'] == 'RETURN_PENDING'])]
        else:
            groups = [('coverage:' + row['row_key'], [item for item in risks
                       if not row['is_history'] and (
                           item['code'] in COVERAGE_TIMING_ACTIVE_CODES
                           or (item['code'] in COVERAGE_ACTIVE_CODES and row['scheduled']
                               and item.get('level') != 'info'))])]
        for key, matching in groups:
            if matching:
                highest = max(matching, key=lambda item: item['rank'])
                candidates.append({'source_key': key, 'kind': kind, 'code': highest['code'], 'rank': highest['rank'],
                    'production_task_id': row['production_task_id'], 'row_key': row['row_key'], 'snapshot': row})
    return candidates
