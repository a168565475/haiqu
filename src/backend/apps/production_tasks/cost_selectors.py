"""读取当前保存的订单成本；调用方负责生产任务权限与数据范围。"""
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP, localcontext
from urllib.parse import urlencode

from django.db.models import Exists, F, OuterRef, Q

from apps.outsourcing.models import OutsourcingFactoryAllocation, TubePlanReceiptLine
from apps.outsourcing.part_flow_prices import PART_RECEIPT, delivered_price_data, receipt_price_data
from apps.outsourcing.tube_models import TubeOutsourcingInput, TubeOutsourcingLine, TubeOutsourcingOrder
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
    receipt_priced_plans = TubeOutsourcingOrder.objects.filter(product_line__production_task=task,
        is_plan=True, source_snapshot__part_flow=True, source_snapshot__billing_basis=PART_RECEIPT).values('pk')
    dispatched_batches = TubeOutsourcingOrder.objects.filter(plan_id=OuterRef('pk'), is_plan=False,
        status__in=['PROCESSING', 'COMPLETED'], actions__kind='DISPATCH')
    received_lines = TubePlanReceiptLine.objects.filter(receipt__order_id=OuterRef('pk'),
        receipt__voided_at__isnull=True, received_quantity__gt=0)
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
        # 总单是计划，不计实际成本；新子单只计确认发出，旧单保留原记录成本口径。
        'tube': TubeOutsourcingLine.objects.filter(order__product_line__production_task=task, order__is_plan=False).filter(
            Q(order__plan__isnull=True) | Q(order__status__in=['PROCESSING', 'COMPLETED'], order__actions__kind='DISPATCH')
        ).exclude(order__status='CANCELLED').exclude(order__plan_id__in=receipt_priced_plans).select_related('order'),
        # 部位按每次有效实收及当次冻结价计费，不能再叠加对应发出批次费用。
        'part_receipts': TubePlanReceiptLine.objects.filter(receipt__order_id__in=receipt_priced_plans,
            receipt__voided_at__isnull=True, received_quantity__gt=0).exclude(receipt__order__status='CANCELLED'
            ).select_related('receipt__order', 'order_line'),
        'print_transfers': TubeOutsourcingInput.objects.filter(print_order_line__order_id__in=receipt_priced_plans,
            source_kind='PROCESSOR', order__status__in=['PROCESSING', 'COMPLETED'], order__actions__kind='DISPATCH'
            ).annotate(delivered_on=F('order__actions__actual_dispatch_date')).select_related('order', 'print_order_line__order'),
        # 新车缝批次只保存投入裁片，费用暂缓按整批列一项未知金额，不按片数计价。
        'deferred_sewing': TubeOutsourcingOrder.objects.filter(product_line__production_task=task,
            is_plan=False, plan__is_plan=True, status__in=['PROCESSING', 'COMPLETED'], actions__kind='DISPATCH',
            source_snapshot__part_flow=True, source_snapshot__sewing_inputs=True, source_snapshot__fees_deferred=True
        ).exclude(plan_id__in=receipt_priced_plans),
        # 总单可先收后发：有实际回货但尚无有效实发时，仅按总单提示一次未知费用。
        'receipt_only_deferred': TubeOutsourcingOrder.objects.filter(product_line__production_task=task,
            is_plan=True, source_snapshot__part_flow=True, source_snapshot__fees_deferred=True
        ).exclude(status='CANCELLED').exclude(pk__in=receipt_priced_plans).alias(has_dispatch=Exists(dispatched_batches),
            has_receipt=Exists(received_lines)).filter(has_dispatch=False, has_receipt=True),
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
    for line in sources.get('part_receipts', []):
        order = line.receipt.order
        value = receipt_price_data(line)['received_amount']
        amount = Decimal(value) if value is not None else None
        part_name = line.snapshot.get('part_name') or line.order_line.snapshot.get('part_name', '部位')
        label = '裁片丝印回仓加工费' if order.source_snapshot.get('screen_print_pieces') else '部位回货加工费'
        add(outsourcing, 'TUBE_OUTSOURCING', order, line.receipt.receipt_number, f'{label}：{part_name}', amount,
            'CNY', f'/workshop/outsourcing/tube/{order.pk}', line.receipt.receipt_date,
            item_id=f'TUBE_OUTSOURCING:RECEIPT_LINE:{line.pk}')
    for line in sources.get('print_transfers', []):
        origin = line.print_order_line.order
        value = delivered_price_data(line.snapshot.get('print_price', {}), line.quantity)['received_amount']
        name = line.snapshot.get('part_name', '裁片')
        add(outsourcing, 'TUBE_OUTSOURCING', origin, line.order.order_number, f'裁片丝印直送加工费：{name}',
            Decimal(value) if value is not None else None, 'CNY', f'/workshop/outsourcing/tube/{origin.pk}',
            line.delivered_on, item_id=f'TUBE_OUTSOURCING:PRINT_TRANSFER:{line.pk}')
    for order in sources['deferred_sewing']:
        add(outsourcing, 'TUBE_OUTSOURCING', order, order.order_number, '车缝加工费暂缓', None,
            'CNY', f'/workshop/outsourcing/tube/{order.plan_id}', order.created_at,
            item_id=f'TUBE_OUTSOURCING:DEFERRED:{order.pk}')
    for order in sources['receipt_only_deferred']:
        add(outsourcing, 'TUBE_OUTSOURCING', order, order.order_number, '部位加工费暂缓', None,
            'CNY', f'/workshop/outsourcing/tube/{order.pk}', order.created_at,
            item_id=f'TUBE_OUTSOURCING:RECEIPT_ONLY:{order.pk}')
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
