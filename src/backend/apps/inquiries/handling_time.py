"""询盘阶段时限事件。跨模块只传真实业务事件，不修改报价、样品或订单状态。"""
from django.db import transaction
from django.db.models import Q, Min
from django.utils import timezone

from .models import Inquiry


STAGE_LABELS = {
    'ASSIGNMENT': '分配负责人', 'FIRST_RESPONSE': '首次回复',
    'REQUIREMENT_CONFIRMATION': '需求确认', 'QUOTE_CREATION': '创建报价',
    'QUOTE_DELIVERY': '完成并发送报价', 'CUSTOMER_FOLLOW_UP': '报价后跟进',
    'POST_ACCEPTANCE': '报价接受后推进', 'SAMPLE_FOLLOW_UP': '样品进度跟进',
}


def has_sales_order(inquiry):
    from apps.sales_orders.models import SalesOrder
    return SalesOrder.objects.filter(source_quotation_version__quotation__source_inquiry=inquiry, archived_at__isnull=True).exclude(status='CANCELLED').exists()


def has_submitted_sample(inquiry):
    from apps.samples.models import SampleRequest
    return SampleRequest.objects.filter(
        Q(source_inquiry=inquiry) | Q(source_quotation_version__quotation__source_inquiry=inquiry),
        archived_at__isnull=True,
    ).exclude(status__in=['DRAFT', 'CANCELLED']).exists()


def stages_for_enrollment(inquiry):
    if inquiry.status in {'DRAFT', 'CONVERTED', 'LOST', 'CLOSED', 'CANCELLED'} or has_sales_order(inquiry):
        return []
    # 已有主阶段优先：再次报价不会把询盘主状态退回 QUOTING。
    stages = list(inquiry.sla_links.filter(is_current=True).exclude(stage_code='ASSIGNMENT').values_list('stage_code', flat=True))
    if stages:
        return (['ASSIGNMENT'] if not inquiry.owner_employee_id else []) + stages
    stages = {'NEW': ['FIRST_RESPONSE'], 'ANALYZING': ['REQUIREMENT_CONFIRMATION'],
              'READY_FOR_QUOTE': ['QUOTE_CREATION'], 'QUOTING': ['QUOTE_DELIVERY'],
              'QUOTED': ['CUSTOMER_FOLLOW_UP'], 'FOLLOW_UP': ['CUSTOMER_FOLLOW_UP']}.get(inquiry.status, [])
    if inquiry.status == 'QUOTE_ACCEPTED':
        stages = ['SAMPLE_FOLLOW_UP' if has_submitted_sample(inquiry) else 'POST_ACCEPTANCE']
    elif inquiry.status in {'READY_FOR_QUOTE', 'QUOTING', 'QUOTED', 'FOLLOW_UP'}:
        from apps.quotations.models import QuotationVersion, QuotationDispatchRecord
        versions = QuotationVersion.objects.filter(quotation__source_inquiry=inquiry, quotation__archived_at__isnull=True)
        # 每版本仅首次真实发送算阶段事件，旧版本重发不能盖过新草稿。
        last_sent = QuotationDispatchRecord.objects.filter(quotation_version__in=versions, is_simulated=False).values('quotation_version_id').annotate(first_sent_at=Min('dispatched_at')).order_by('-first_sent_at').first()
        pending = versions.filter(quotation__outcome_status='OPEN', status__in=['DRAFT', 'LOCKED', 'ISSUED'])
        if last_sent:
            pending = pending.filter(created_at__gt=last_sent['first_sent_at'])
        if pending.exists():
            stages = ['QUOTE_DELIVERY']
        elif last_sent:
            stages = ['CUSTOMER_FOLLOW_UP']
    if not inquiry.owner_employee_id:
        stages = ['ASSIGNMENT', *stages]
    return stages


@transaction.atomic
def handle_time_event(inquiry_id, event, *, key='', now=None, context=None):
    from .services import _start_sla, _finish_sla
    inquiry = Inquiry.objects.select_for_update().get(pk=inquiry_id)
    now = now or timezone.now()
    context = {**(context or {}), 'event_key': key}
    if event == 'ORDER_CREATED' or inquiry.status in {'CONVERTED', 'LOST', 'CLOSED', 'CANCELLED'}:
        _finish_sla(inquiry, 'MET' if event == 'ORDER_CREATED' or inquiry.status == 'CONVERTED' else 'CANCELLED', now, reason='已移交销售订单' if event == 'ORDER_CREATED' else '询盘流程结束')
        return
    if has_sales_order(inquiry):
        return
    if key and inquiry.sla_links.filter(sla_tracking__tracking_data__event_key=key).exists():
        return

    def finish(stage, result='MET', reason=''):
        _finish_sla(inquiry, result, now, stage, reason=reason)

    def start(stage):
        return _start_sla(inquiry, now, stage, context=context)

    if event == 'QUOTE_CREATED' and inquiry.status in {'READY_FOR_QUOTE', 'QUOTING', 'QUOTED', 'FOLLOW_UP'}:
        finish('QUOTE_CREATION')
        # 草稿修改/重复创建不重置现有报价期限；完成一轮后才启动下一轮。
        if not inquiry.sla_links.filter(stage_code='QUOTE_DELIVERY', is_current=True).exists():
            finish('CUSTOMER_FOLLOW_UP', 'CANCELLED', '进入新一轮报价，保留上轮跟进结果')
            start('QUOTE_DELIVERY')
    elif event == 'QUOTE_SENT' and inquiry.status in {'READY_FOR_QUOTE', 'QUOTING', 'QUOTED', 'FOLLOW_UP'}:
        finish('QUOTE_CREATION')
        finish('QUOTE_DELIVERY')
        start('CUSTOMER_FOLLOW_UP')
    elif event == 'FOLLOW_UP':
        for stage in ['CUSTOMER_FOLLOW_UP', 'SAMPLE_FOLLOW_UP']:
            if inquiry.sla_links.filter(stage_code=stage, is_current=True).exists():
                finish(stage)
                start(stage)
    elif event == 'SAMPLE_SUBMITTED' and inquiry.status == 'QUOTE_ACCEPTED':
        finish('POST_ACCEPTANCE')
        start('SAMPLE_FOLLOW_UP')


def sample_submitted(sample):
    inquiry_id = sample.source_inquiry_id
    if not inquiry_id and sample.source_quotation_version_id:
        inquiry_id = sample.source_quotation_version.quotation.source_inquiry_id
    if inquiry_id:
        handle_time_event(inquiry_id, 'SAMPLE_SUBMITTED', key=f'SAMPLE:{sample.pk}', context={'source_label': sample.request_number})


def quote_created(version):
    if version.quotation.source_inquiry_id:
        handle_time_event(version.quotation.source_inquiry_id, 'QUOTE_CREATED', key=f'QUOTE_CREATED:{version.pk}', context={'quotation_id': str(version.quotation_id), 'source_label': f'{version.quotation.quotation_number} V{version.version_number}'})
