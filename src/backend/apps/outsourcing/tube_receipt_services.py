"""D3整单一次回货：实收数量入对应加工半成品库存，不返还已发生占用。"""
import hashlib

from django.db import connection
from django.shortcuts import get_object_or_404
from rest_framework.exceptions import ValidationError

from apps.boms.models import Bom, BomLine
from apps.core.api.concurrency import PreconditionRequired, require_matching_etag
from apps.core.api.exceptions import Conflict
from apps.core.audit import write_audit_log
from apps.core.numbering import next_business_number
from apps.inventory.models import PublicStockBalance
from apps.inventory.public_stock_cutover import stock_write_transaction
from apps.inventory.public_stock_identity import validate_public_identity
from apps.inventory.public_stock_services import _lock_source, credit_public_stock, lock_public_stock_locations
from apps.reference_data.models import ProductionUnit

from .material_flow import lock_request
from .models import TubeOutsourcingOrder, TubeOutsourcingReceipt, TubeOutsourcingReceiptLine
from .services import _json_hash
from .tube_receipt_selectors import dispatch_evidence_blockers
from .tube_selectors import RETURN_PERMISSION, require_saved_order_access, require_tube_feature
from .tube_services import _json
from .tube_kinds import CUTTING_SOURCES, lock_source_product, output_unit


MOVEMENT_SOURCE = 'TUBE_OUTSOURCING_RETURN'


def _fail(detail):
    raise ValidationError({'detail': detail})


def _lock_receipt_stock(positive):
    """与领料相同：公共池→事件→仓/区→余额，先全单取齐锁再入账。"""
    pools = sorted({(identity['stock_kind'], identity['identity_key'], str(identity['unit_id']))
                    for _, _, identity in positive})
    for pool in pools:
        token = 'public-issue-pool:' + ':'.join(pool)
        value = int.from_bytes(hashlib.sha256(token.encode()).digest()[:8], 'big', signed=True)
        with connection.cursor() as cursor:
            cursor.execute('SELECT pg_advisory_xact_lock(%s)', [value])
    for row, _, _ in sorted(positive, key=lambda item: str(item[0].pk)):
        _lock_source({'source_type': MOVEMENT_SOURCE, 'source_line_id': row.pk}, 'IN')
    # 同池所有现存库区也纳入位置锁，避免与跨库区领料的父子锁反向等待。
    balance_filter = None
    from django.db.models import Q
    for kind, key, unit in pools:
        clause = Q(stock_kind=kind, identity_key=key, unit_id=unit, quality='AVAILABLE')
        balance_filter = clause if balance_filter is None else balance_filter | clause
    balances = PublicStockBalance.objects.filter(balance_filter) if balance_filter is not None else PublicStockBalance.objects.none()
    locations = lock_public_stock_locations(set(balances.values_list('zone_id', flat=True))
                                            | {entered['zone_id'] for _, entered, _ in positive})
    list(balances.order_by('pk').select_for_update(of=('self',)).values_list('pk', flat=True))
    return locations


@stock_write_transaction
def confirm_tube_final_receipt(*, order_id, data, request):
    require_tube_feature()
    if not request.headers.get('If-Match'):
        raise PreconditionRequired()
    lock_request('tube-final-receipt', data['client_request_id'])
    payload_hash = _json_hash({'order_id': str(order_id), 'actor_id': str(request.employee.pk), 'data': data})
    existing = TubeOutsourcingReceipt.objects.select_related('order').filter(
        client_request_id=data['client_request_id']).first()
    if existing:
        require_saved_order_access(request, existing.order, RETURN_PERMISSION)
        if existing.order_id != order_id or existing.request_payload_hash != payload_hash:
            raise Conflict('相同提交标识已用于不同原单、回货内容或操作人。')
        return existing, False
    initial = get_object_or_404(TubeOutsourcingOrder.objects.select_related('schedule_product'), pk=order_id)
    require_saved_order_access(request, initial, RETURN_PERMISSION)
    lock_source_product(initial.product_line_id, initial.source_kind)
    order = TubeOutsourcingOrder.objects.select_for_update(of=('self',)).select_related(
        'schedule_product__schedule__production_task').get(pk=order_id)
    require_saved_order_access(request, order, RETURN_PERMISSION)
    require_matching_etag(request, order)
    if order.status != 'PROCESSING' or TubeOutsourcingReceipt.objects.filter(order=order).exists():
        raise Conflict('仅已实际发出且未最终登记的原单可回货；一单只登记一次。')
    lines = list(order.lines.select_for_update(of=('self',)).order_by('pk'))
    blockers = dispatch_evidence_blockers(order)
    if blockers:
        _fail('；'.join(blockers))
    dispatch = order.actions.get(kind='DISPATCH')
    if data['receipt_date'] < dispatch.actual_dispatch_date:
        _fail(f'回货日期不能早于实际发出日期{dispatch.actual_dispatch_date}。')
    entered_by_id = {row['order_line_id']: row for row in data['lines']}
    if len(entered_by_id) != len(data['lines']) or set(entered_by_id) != {line.pk for line in lines}:
        _fail('必须完整且唯一地提交原单全部加工明细，包括实收0的部位。')
    pending = []
    for line in lines:
        entered = entered_by_id[line.pk]
        quantity = entered['received_quantity']
        if quantity < 0 or quantity > line.quantity:
            _fail(f'“{line.snapshot.get("part_name", "部位")}”实收须为0至实发{line.quantity}{output_unit(order.source_kind)}的整数。')
        reason = entered.get('shortage_reason', '').strip()
        if quantity < line.quantity and not reason:
            _fail(f'“{line.snapshot.get("part_name", "部位")}”少回{line.quantity - quantity}{output_unit(order.source_kind)}，必须填写差额原因。')
        row = TubeOutsourcingReceiptLine(order_line=line, dispatched_quantity=line.quantity,
            received_quantity=quantity, shortage_quantity=line.quantity - quantity,
            shortage_reason=reason, snapshot=_json({**line.snapshot,
                'unit_price': str(line.unit_price) if line.unit_price is not None else None}))
        identity = validate_public_identity(line.snapshot['public_output_identity'])
        if (identity['identity_snapshot']['completed_craft']['id'] != str(order.craft_id)
                or identity['identity_snapshot'].get('semi_kind') != ('CUTTING' if order.source_kind in CUTTING_SOURCES else 'PIPE')):
            _fail('原单完成身份不属于该加工工艺，不能登记回货。')
        pending.append((row, entered, identity))
    positive = [item for item in pending if item[0].received_quantity > 0]
    # 回货使用保存时的实物与工艺，不依赖当前BOM/报工或备料换算参数。
    list(Bom.objects.filter(pk=order.bom_id).order_by('pk').select_for_update(of=('self',)))
    list(BomLine.objects.filter(pk__in=[line.bom_line_id for line in lines]).order_by('pk').select_for_update(of=('self',)))
    if positive:
        list(ProductionUnit.objects.filter(pk__in={identity['unit_id'] for _, _, identity in positive})
             .order_by('pk').select_for_update(of=('self',), no_key=True))
    locations = _lock_receipt_stock(positive)
    warehouse = None
    for row, entered, _ in positive:
        zone = locations[entered['zone_id']]
        if (zone.warehouse_id != data['warehouse_id'] or zone.status != 'ACTIVE'
                or zone.warehouse.status != 'ACTIVE' or zone.warehouse.warehouse_type != 'SEMI_FINISHED'):
            _fail('正数实收库区必须属于所选有效半成品仓；请刷新仓库和库区。')
        warehouse = zone.warehouse
        row.zone = zone
        row.snapshot['zone_name'] = zone.zone_name
    before = {'status': order.status, 'version': order.version}
    header = TubeOutsourcingReceipt.objects.create(order=order,
        receipt_number=next_business_number('TUBE_OUTSOURCING_RECEIPT'),
        client_request_id=data['client_request_id'], request_payload_hash=payload_hash,
        receipt_date=data['receipt_date'], warehouse=warehouse, actor_employee=request.employee,
        remark=data.get('remark', ''), snapshot={'order_number': order.order_number,
            'actor_name': request.employee.display_name, 'warehouse_name': warehouse.warehouse_name if warehouse else '',
            'source_kind': order.source_kind, 'actual_dispatch_action_id': str(dispatch.pk)})
    for row, _, identity in pending:
        row.receipt = header
        if row.received_quantity > 0:
            row.stock_movement = credit_public_stock(identity=identity, zone=row.zone, quantity=row.received_quantity,
                source_type=MOVEMENT_SOURCE, source_id=header.pk, source_line_id=row.pk, actor_employee=request.employee,
                production_task=order.schedule_product.schedule.production_task_id,
                product_line=order.product_line_id, bom_line=row.order_line.bom_line_id,
                snapshot=_json({'source': '外发入库', 'source_kind': order.source_kind,
                    'order_id': str(order.pk), 'order_number': order.order_number,
                    'order_line_id': str(row.order_line_id), 'receipt_number': header.receipt_number,
                    'receipt_date': str(header.receipt_date), 'actor_name': request.employee.display_name,
                    'client_request_id': str(header.client_request_id), 'quantity': str(row.received_quantity),
                    'dispatched_quantity': str(row.dispatched_quantity), 'shortage_quantity': str(row.shortage_quantity),
                    'shortage_reason': row.shortage_reason, 'public_identity': identity, 'remark': header.remark,
                    'factory_id': str(row.order_line.factory_id), 'factory_name': row.snapshot.get('factory_name', '')}))
        row.save(force_insert=True)
    # 完成状态仍使用原实发数量占订单/首次产出额度，缺额不会变成可补登记额度。
    order.status = 'COMPLETED'
    order.version += 1
    order.updated_by_employee = request.employee
    order.save(update_fields=['status', 'version', 'updated_by_employee', 'updated_at'])
    write_audit_log(object_type='TUBE_OUTSOURCING_ORDER', object_id=order.pk, action='RETURN_COMPLETED',
        actor_employee=request.employee, before_data=before,
        after_data={'order_number': order.order_number, 'status': order.status, 'version': order.version,
            'receipt_id': str(header.pk), 'receipt_number': header.receipt_number,
            'client_request_id': str(header.client_request_id), 'receipt_date': str(header.receipt_date),
            'warehouse_id': str(header.warehouse_id) if header.warehouse_id else None,
            'total_dispatched_quantity': sum(row.dispatched_quantity for row, _, _ in pending),
            'total_received_quantity': sum(row.received_quantity for row, _, _ in pending),
            'total_shortage_quantity': sum(row.shortage_quantity for row, _, _ in pending),
            'lines': [{'order_line_id': str(row.order_line_id), 'quantity': row.received_quantity,
                'shortage_reason': row.shortage_reason, 'zone_id': str(row.zone_id) if row.zone_id else None,
                'movement_id': str(row.stock_movement_id) if row.stock_movement_id else None} for row, _, _ in pending]},
        context_type='PRODUCTION_SCHEDULE', context_id=order.schedule_product.schedule_id, request=request)
    from apps.wecom.workshop_change_notifications import tube_shortages
    tube_shortages(header, request.employee)
    return header, True
