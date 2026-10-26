"""读取当前保存的订单成本；调用方负责生产任务权限与数据范围。"""
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP, localcontext
from urllib.parse import urlencode

from apps.outsourcing.models import OutsourcingFactoryAllocation
from apps.outsourcing.tube_models import TubeOutsourcingLine
from apps.procurement.models import PurchaseOrder, PurchaseRequestAllocation, SupplierPurchaseSheet
from apps.workshop_reporting.models import WorkReport


ZERO = Decimal('0')
CENT = Decimal('0.01')


def _money(value):
    return format(Decimal(value).quantize(CENT, rounding=ROUND_HALF_UP), '.2f')


def _date(value):
    return value.date().isoformat() if hasattr(value, 'date') else value.isoformat() if value else None


def _saved_line_amount(value):
    if value in (None, ''):
        return None
    try:
        amount = Decimal(str(value))
    except InvalidOperation:
        return None
    # 采购表是历史JSON边界，损坏或超出正式金额字段范围时明确列缺口。
    return amount if amount.is_finite() and ZERO <= amount < Decimal('1e18') else None


def _cost_sources(task):
    return {
        'products': task.products.select_related('currency').all(),
        # 旧采购单自身保存完整采购金额，不再叠加其供应商采购表。
        'purchases': PurchaseOrder.objects.filter(production_task=task, archived_at__isnull=True
                                                 ).select_related('currency').prefetch_related('lines'),
        'sheets': SupplierPurchaseSheet.objects.filter(
            purchase_request__production_task=task, purchase_request__archived_at__isnull=True,
            archived_at__isnull=True, is_current=True, purchase_order__isnull=True),
        'allocations': PurchaseRequestAllocation.objects.filter(
            purchase_request_line__purchase_request__production_task=task,
            purchase_request_line__purchase_request__archived_at__isnull=True,
            supplier_purchase_sheet__isnull=True).exclude(status='CANCELLED').select_related(
                'purchase_request_line__purchase_request'),
        'reports': WorkReport.objects.filter(product_line__production_task=task),
        'outsourcing': OutsourcingFactoryAllocation.objects.filter(
            processing_item__order_product__order__schedule__production_task=task
        ).exclude(processing_item__order_product__order__status='CANCELLED').select_related(
            'processing_item__order_product__order'),
        'tube': TubeOutsourcingLine.objects.filter(order__product_line__production_task=task).exclude(
            order__status='CANCELLED').select_related('order'),
        'expenses': task.cost_expenses.filter(voided_at__isnull=True),
    }


def task_cost_summary(*, task):
    # 金额最多22位、汇率最多25位；保留乘积和跨行合计所需精度，不影响全局Decimal环境。
    with localcontext() as context:
        context.prec = 64
        return _task_cost_summary(task=task)


def _task_cost_summary(*, task):
    sources = _cost_sources(task)
    categories = [dict(key=key, label=label, amount='0.00', count=0, missing_count=0, items=[])
                  for key, label in [('purchase', '采购'), ('labor', '报工'),
                                     ('outsourcing', '外发'), ('other', '其他费用')]]
    warnings = []
    order_amount = ZERO
    products = list(sources['products'])
    order_missing = 0
    if not products:
        warnings.append('生产任务尚无产品金额，订单金额未确定。')
        order_missing += 1
    for product in products:
        code = product.currency.code
        if code == 'CNY':
            order_amount += product.total_amount
        elif product.exchange_rate_snapshot and product.exchange_rate > ZERO:
            order_amount += product.total_amount * product.exchange_rate
        else:
            order_missing += 1
            warnings.append('订单产品缺少已保存人民币汇率快照。')
    # 任务运费和其他收费沿用任务币种；不拿某条产品汇率替整单收费换算。
    extra = task.freight_amount + task.other_fee_amount
    if extra and (not task.currency or task.currency.code != 'CNY'):
        order_missing += 1
        warnings.append('订单运费或其他收费缺少人民币换算依据。')
    else:
        order_amount += extra
    # 差额和比例均以接口展示的分金额计算，避免半分钱使三项金额无法相互核对。
    order_amount = order_amount.quantize(CENT, rounding=ROUND_HALF_UP)

    def add(category, source_type, source, number, label, amount, currency, href, date=None, item_id=None):
        reason = None
        if amount is None:
            reason = '金额尚未保存、格式无效或价格未完善。'
        elif currency != 'CNY':
            reason = '来源未保存币种。' if not currency else '外币来源未保存人民币汇率快照，未计入。'
        item = dict(id=item_id or f'{source_type}:{source.pk}', source_type=source_type,
                    source_id=str(source.pk), number=number, label=label,
                    amount=_money(amount) if amount is not None else None, currency=currency,
                    amount_cny=_money(amount) if reason is None else None,
                    missing_reason=reason, href=href, occurred_on=_date(date))
        category['items'].append(item)

    purchase, labor, outsourcing, other = categories
    for order in sources['purchases']:
        currency = order.currency_code_snapshot or getattr(getattr(order, 'currency', None), 'code', None)
        href = f'/purchase-orders/{order.pk}/details'
        lines = list(order.lines.all()) if order.total_amount is None else []
        if lines:
            for line in lines:
                add(purchase, 'PURCHASE', order, order.order_number, f'采购单第{line.line_number}行',
                    line.amount, currency, href, order.created_at, item_id=f'PURCHASE:LINE:{line.pk}')
        else:
            add(purchase, 'PURCHASE', order, order.order_number, '采购单', order.total_amount,
                currency, href, order.created_at)
    # 新版采购申请的采购表没有币种字段；现行编辑器和原版导出均明确金额单位为元。
    for sheet in sources['sheets']:
        lines = sheet.content_snapshot.get('lines', []) if sheet.total_amount is None else []
        href = f'/supplier-purchase-sheets/{sheet.pk}'
        if lines:
            for index, line in enumerate(lines, 1):
                amount = _saved_line_amount(line.get('amount'))
                line_id = line.get('source_purchase_order_line_id') or line.get('source_purchase_request_line_id') or index
                add(purchase, 'PURCHASE', sheet, sheet.sheet_number, f'供应商采购表第{index}行',
                    amount, 'CNY', href, sheet.created_at,
                    item_id=f'PURCHASE:SHEET:{sheet.pk}:LINE:{line_id}')
        else:
            add(purchase, 'PURCHASE', sheet, sheet.sheet_number, '供应商采购表', sheet.total_amount,
                'CNY', href, sheet.created_at, item_id=f'PURCHASE:SHEET:{sheet.pk}')
    for allocation in sources['allocations']:
        request = allocation.purchase_request_line.purchase_request
        add(purchase, 'PURCHASE', request, request.request_number, '已分配采购尚未保存采购表金额',
            None, 'CNY', None, item_id=f'PURCHASE:ALLOCATION:{allocation.pk}')
    for report in sources['reports']:
        href = None
        if report.production_date:
            href = f'/workshop/work-reports/days/{report.production_date.isoformat()}'
            href += '?' + urlencode({'schedule_product_id': str(report.schedule_product_id)})
        add(labor, 'REPORT', report, report.report_number, '车间报工', report.total_amount,
            'CNY', href, report.production_date)
    for allocation in sources['outsourcing']:
        order = allocation.processing_item.order_product.order
        amount = allocation.allocated_quantity * allocation.unit_price
        add(outsourcing, 'OUTSOURCING', order, order.order_number, '外发加工分配', amount,
            'CNY', f'/workshop/outsourcing/{order.pk}', order.created_at,
            item_id=f'OUTSOURCING:ALLOCATION:{allocation.pk}')
    for line in sources['tube']:
        order = line.order
        amount = line.quantity * line.unit_price if line.unit_price is not None else None
        add(outsourcing, 'TUBE_OUTSOURCING', order, order.order_number, '管材/裁片外发', amount,
            'CNY', f'/workshop/outsourcing/tube/{order.pk}', order.created_at,
            item_id=f'TUBE_OUTSOURCING:LINE:{line.pk}')
    for expense in sources['expenses']:
        add(other, 'EXPENSE', expense, '', expense.description, expense.amount,
            'CNY', None, expense.occurred_on)
    for category in categories:
        category['count'] = len(category['items'])
        category['missing_count'] = sum(item['amount_cny'] is None for item in category['items'])
        category['amount'] = _money(sum((Decimal(item['amount_cny']) for item in category['items']
                                         if item['amount_cny'] is not None), ZERO))
    total = sum((Decimal(category['amount']) for category in categories), ZERO)
    missing = order_missing + sum(category['missing_count'] for category in categories)
    if any(category['missing_count'] for category in categories):
        warnings.append('存在未计入金额，当前记录成本仅为已知部分。')
    complete = missing == 0
    return dict(task_id=str(task.pk), currency='CNY',
                order_amount=None if order_missing else _money(order_amount), recorded_cost=_money(total),
                current_difference=_money(order_amount - total) if complete else None,
                cost_ratio=_money(total / order_amount * 100) if complete and order_amount else None,
                complete=complete, missing_count=missing, warnings=list(dict.fromkeys(warnings)),
                categories=categories)
