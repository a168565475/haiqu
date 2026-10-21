"""样品采购按采购剩余量一次入库，数量由服务端计算。"""
from decimal import Decimal

from django.db import IntegrityError, transaction
from rest_framework.exceptions import NotFound, ValidationError

from apps.core.api.concurrency import PreconditionRequired, require_matching_etag
from apps.core.api.exceptions import Conflict
from apps.procurement.models import PurchaseOrder
from apps.procurement.source_access import purchase_order_access
from apps.production_tasks.selectors import accessible_production_tasks
from apps.samples.models import SampleMaterialPurchaseSource, SampleRequest

from .models import MaterialInbound, MaterialInboundStatus
from .public_stock_cutover import stock_write_transaction
from .selectors import material_received_totals
from .services import create_material_inbound
from .stock_services import credit_confirmed_inbound_line


def _matches_receipt(inbound, *, purchase_order_id, inbound_date, remark, items):
    expected = sorted((str(row['purchase_order_line_id']), str(row['zone_id']),
                       str(row.get('location_id') or ''), row.get('remark', '')) for row in items)
    actual = sorted((str(row.purchase_order_line_id), str(row.zone_id),
                     str(row.location_id or ''), row.remark) for row in inbound.lines.all())
    return (inbound.purchase_order_id == purchase_order_id
            and inbound.status == MaterialInboundStatus.CONFIRMED
            and inbound.quality_confirmed_at is None
            and inbound.inbound_date == inbound_date and inbound.remark == remark
            and expected == actual)


@stock_write_transaction
def receive_sample_purchase(*, purchase_order_id, client_request_id, inbound_date, remark, items,
                            actor_employee, request):
    from apps.samples.material_arrival_services import receive_material_arrival

    access = purchase_order_access(accessible_production_tasks(request).values_list('id', flat=True), request)
    candidate = PurchaseOrder.objects.filter(access, pk=purchase_order_id, archived_at__isnull=True).first()
    if candidate is None:
        raise NotFound('采购单不存在或无权访问。')
    if candidate.source_type != 'SAMPLE':
        raise ValidationError({'purchase_order_id': '仅样品采购可以直接全部入库。'})
    # 与样品建单、到货及领料一致，先锁样品再锁采购单。
    sample = SampleRequest.objects.select_for_update(of=('self',)).filter(
        material_request__procurement_request__pk=candidate.sample_procurement_request_id).first()
    if sample is None:
        raise Conflict('采购单的样品来源已变化，请刷新后重试。')
    order = PurchaseOrder.objects.select_for_update().filter(pk=candidate.pk).first()
    if order is None or not PurchaseOrder.objects.filter(access, pk=order.pk, archived_at__isnull=True).exists():
        raise NotFound('采购单不存在或无权访问。')
    if not request.headers.get('If-Match'):
        raise PreconditionRequired()
    existing = MaterialInbound.objects.filter(client_request_id=client_request_id).first()
    if existing:
        if not _matches_receipt(existing, purchase_order_id=order.pk, inbound_date=inbound_date,
                                remark=remark, items=items):
            raise Conflict('同一提交标识不能用于不同的样品入库内容。')
        return existing, False
    require_matching_etag(request, order)
    if MaterialInbound.objects.filter(purchase_order=order, status=MaterialInboundStatus.PENDING_QUALITY).exists():
        raise Conflict('该采购单仍有原待检批次，请先处理原批次，再将剩余材料全部入库。')
    lines = list(order.lines.select_for_update().order_by('id'))
    totals = material_received_totals([line.pk for line in lines])
    remaining = {line.pk: line.actual_purchase_quantity - totals.get(line.pk, Decimal('0'))
                 for line in lines if line.actual_purchase_quantity is not None
                 and line.actual_purchase_quantity > totals.get(line.pk, Decimal('0'))}
    if not remaining:
        raise Conflict('该样品采购单已全部入库，请勿重复入库。')
    submitted = [item['purchase_order_line_id'] for item in items]
    if len(submitted) != len(set(submitted)) or set(submitted) != set(remaining):
        raise ValidationError({'items': '必须完整选择该样品采购单全部剩余明细，每行只能选择一个入库库区。'})
    bindings = {row.purchase_order_line_id: row for row in SampleMaterialPurchaseSource.objects.filter(
        procurement_request_id=order.sample_procurement_request_id, purchase_order_line_id__in=remaining)}
    if set(bindings) != set(remaining):
        raise Conflict('样品采购来源不完整，请先核对采购单。')
    line_map = {line.pk: line for line in lines}
    prepared = []
    for item in items:
        line_id = item['purchase_order_line_id']
        line = line_map[line_id]
        row = {**item, 'received_quantity': remaining[line_id], 'expected_remaining_quantity': remaining[line_id]}
        if line.section_type_snapshot == 'PROFILE':
            length = line.raw_bar_length_m
            if not length or remaining[line_id] % length:
                raise Conflict('管材剩余数量与采购单根长度不一致，请先核对根数和米数。')
            row.update(received_bar_count=int(remaining[line_id] / length), raw_bar_length_m=length)
        prepared.append(row)
    try:
        with transaction.atomic():
            inbound = create_material_inbound(inbound_date=inbound_date, remark=remark, items=prepared,
                actor_employee=actor_employee, request=request, sample_direct=True,
                client_request_id=client_request_id)
    except IntegrityError as error:
        if MaterialInbound.objects.filter(client_request_id=client_request_id).exists():
            raise Conflict('该提交标识已被其他入库使用，请刷新后重试。') from error
        raise
    for line in inbound.lines.select_related('zone__warehouse', 'raw_material_information').order_by(
            'raw_material_information_id', 'zone_id', 'id'):
        credit_confirmed_inbound_line(line=line, actor_employee=actor_employee)
        binding = bindings[line.purchase_order_line_id]
        receive_material_arrival(procurement_request_id=binding.procurement_request_id,
            line_key=binding.line_key, inbound_line_id=line.pk, request=request, direct_receipt=True)
    order.save(update_fields=['updated_at'])
    return inbound, True
