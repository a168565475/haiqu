"""按真实采购来源区分等待建单与采购中，保留原材料到货流程门禁。"""
from .models import SampleMaterialPurchaseSource, SampleRequestStatus


PROCUREMENT_IN_PROGRESS = 'PROCUREMENT_IN_PROGRESS'


def ordered_sample_ids():
    return SampleMaterialPurchaseSource.objects.filter(
        purchase_order_line__purchase_order__archived_at__isnull=True,
    ).values('procurement_request__material_request__sample_request_id')


def has_purchase_order(sample):
    record = getattr(sample, 'material_request', None)
    procurement = getattr(record, 'procurement_request', None) if record else None
    if not procurement:
        return False
    # 列表预取来源及订单，避免每条申请额外查询。
    return any(source.purchase_order_line.purchase_order.archived_at is None
               for source in procurement.purchase_sources.all())


def sample_status_display(sample):
    if sample.status == SampleRequestStatus.PROCUREMENT_PENDING:
        return '采购中' if has_purchase_order(sample) else '等待采购'
    return sample.get_status_display()
