"""采购后续调用的内部衔接；只采信已确认入库行，不开放人工到货接口。"""
from decimal import Decimal
from django.db import transaction
from rest_framework.exceptions import ValidationError
from apps.core.api.exceptions import Conflict
from apps.customers.services import model_snapshot
from apps.inventory.models import MaterialInbound, MaterialInboundLine
from .models import SampleMaterialArrival, SampleMaterialIssue, SampleMaterialIssueStatus, SampleMaterialProcurementRequest, SampleMaterialPurchaseSource, SampleRequest, SampleRequestStatus
from .services import SAMPLE_FIELDS, _write_sample_records
from .procurement_status import has_purchase_order


def material_progress(sample):
    record = getattr(sample, 'material_request', None)
    if not record:
        return {'label': '未填写', 'status': 'DRAFT', 'lines': []}
    if record.no_materials:
        return {'label': '无需用料', 'status': 'MATERIALS_READY', 'lines': []}
    procurement = getattr(record, 'procurement_request', None)
    procurement_quantities = {str(row['key']): row['shortageQuantity'] for row in procurement.lines} if procurement else {}
    arrivals = list(procurement.arrivals.all()) if procurement else []
    received = {}
    for arrival in arrivals:
        key = str(arrival.line_key)
        received[key] = received.get(key, Decimal('0')) + arrival.accepted_quantity
    supply = {line['key']: Decimal(line['supplyQuantity'] or '0') for line in record.warehouse_draft.get('lines', [])}
    lines = []
    for row in record.draft.get('lines', []):
        need = Decimal(row['quantity'] or '0')
        supplied = supply.get(row['key'], Decimal('0'))
        arrived = received.get(row['key'], Decimal('0'))
        lines.append({**row, 'supplyQuantity': str(supplied), 'arrivedQuantity': str(arrived),
                      'procurementQuantity': str(procurement_quantities.get(str(row['key']), '0')) if record.reviewed_at else None,
                      'remainingQuantity': str(max(Decimal('0'), need - supplied - arrived))})
    issue = getattr(record, 'issue', None)
    if issue:
        issue_lines = {str(line.line_key): line for line in issue.lines.select_related('unit').all()}
        for line in lines:
            frozen = issue_lines.get(str(line['key']))
            if frozen:
                line['availableQuantity'] = str(frozen.available_quantity)
                line['issuedQuantity'] = None if frozen.issued_quantity is None else str(frozen.issued_quantity)
                line['shortageQuantity'] = str(frozen.shortage_quantity)
        if issue.status == SampleMaterialIssueStatus.ISSUED:
            return {'label': '已领料', 'status': 'MATERIALS_ISSUED', 'lines': lines}
        return {'label': '待仓库确认领料', 'status': 'MATERIAL_ISSUE_REVIEW', 'lines': lines}
    if not record.submitted_at:
        label, status = ('填写中' if lines else '未填写'), 'DRAFT'
    elif not record.reviewed_at:
        label, status = f'待核对 {len(lines)} 项', 'WAREHOUSE_PENDING'
    elif sample.status == SampleRequestStatus.MATERIAL_ISSUE_PENDING and all(Decimal(line['remainingQuantity']) == 0 for line in lines):
        label, status = '材料齐备，待领料', 'MATERIAL_ISSUE_PENDING'
    elif sample.status == SampleRequestStatus.MATERIAL_ISSUE_PENDING and any(Decimal(line['arrivedQuantity']) > 0 for line in lines):
        label, status = '部分入库', 'MATERIAL_ISSUE_PENDING'
    elif sample.status == SampleRequestStatus.MATERIAL_ISSUE_PENDING:
        label, status = '待发起领料', 'MATERIAL_ISSUE_PENDING'
    elif all(Decimal(line['remainingQuantity']) == 0 for line in lines):
        label, status = '全部齐备', 'MATERIALS_READY'
    elif arrivals:
        label, status = '部分入库', 'PROCUREMENT_PENDING'
    else:
        # 仓库提交缺料后，采购尚未建单时显示“等待采购”；
        # 已存在真实采购单时统一显示“采购中”，与样品列表状态保持一致。
        label, status = ('采购中' if has_purchase_order(sample) else '等待采购'), 'PROCUREMENT_PENDING'
    return {'label': label, 'status': status, 'lines': lines}


@transaction.atomic
def receive_material_arrival(*, procurement_request_id, line_key, inbound_line_id, request, direct_receipt=False):
    """内部调用方必须先建立采购来源对应关系；数量直接读取真实入库行。

    当前约定一个入库行仅分配一个缺料行；拆单、多样品合并采购须在采购阶段拆分来源。
    """
    if not request or not getattr(request, 'employee', None) or not (
        request.user.has_perm('samples.review_sample_materials') or request.user.has_perm('inventory.quality_confirm_material')
        or (direct_receipt and request.user.has_perm('inventory.receive_material'))
    ):
        from rest_framework.exceptions import PermissionDenied
        raise PermissionDenied('到货衔接需要有效员工及对应的材料核对、收货或品质确认权限。')
    procurement = SampleMaterialProcurementRequest.objects.select_related('material_request').get(pk=procurement_request_id)
    sample = SampleRequest.objects.select_for_update().get(pk=procurement.material_request.sample_request_id)
    inbound_id = MaterialInboundLine.objects.values_list('inbound_id', flat=True).get(pk=inbound_line_id)
    inbound = MaterialInbound.objects.select_for_update().get(pk=inbound_id)
    line = MaterialInboundLine.objects.select_for_update().get(pk=inbound_line_id)
    demand = next((row for row in procurement.lines if row['key'] == str(line_key)), None)
    if not demand:
        raise ValidationError('入库来源没有对应的样品缺料行。')
    if not SampleMaterialPurchaseSource.objects.filter(procurement_request=procurement, line_key=line_key,
                                                       purchase_order_line_id=line.purchase_order_line_id).exists():
        raise Conflict('采购行尚未绑定此样品缺料来源，不能按同规格猜测关联。')
    if inbound.status != 'CONFIRMED' or line.accepted_quantity <= 0:
        raise Conflict('材料必须完成验收入库且合格数量大于 0。')
    accepted_quantity = line.accepted_quantity
    if demand['category'] == 'tube':
        from .pipe_materials import sample_pipe_arrival_quantity
        accepted_quantity = sample_pipe_arrival_quantity(line, procurement, demand)
    if (line.part_name_snapshot != demand['name'] or line.specification_snapshot != demand['specification']
            or line.raw_material_snapshot != demand['material']
            or (demand['category'] != 'tube' and line.source_unit_text_snapshot != demand['unitLabel'])):
        raise ValidationError('入库材料名称、规格、材质或单位与缺料需求不一致。')
    existing = SampleMaterialArrival.objects.filter(inbound_line=line).first()
    if existing:
        if (existing.procurement_request_id != procurement.pk or str(existing.line_key) != str(line_key)
                or existing.accepted_quantity != accepted_quantity):
            raise Conflict('该入库行已关联其他缺料或入库数量发生变化，需要核对来源。')
        return sample
    # 已按现有材料领料的样品仍可完成原采购入库，不回退生产，也不自动补发。
    keep_production_stage = sample.status in {'METALWORK_PENDING', 'CUTTING_PENDING', 'PRODUCTION_PENDING', 'FINISHED'}
    if not sample.application_payload_hash or (
        sample.status not in {
            SampleRequestStatus.PROCUREMENT_PENDING,
            SampleRequestStatus.MATERIAL_ISSUE_PENDING,
            SampleRequestStatus.MATERIAL_ISSUE_REVIEW,
        } and not keep_production_stage
    ) or sample.archived_at or sample.customer_account.archived_at:
        raise Conflict('当前样品不在等待采购到货阶段。')
    before = model_snapshot(sample, SAMPLE_FIELDS)
    SampleMaterialArrival.objects.create(procurement_request=procurement, line_key=line_key,
                                        inbound_line=line, accepted_quantity=accepted_quantity)
    # 到货只代表材料可以进入领料，不能直接扣库存或跳过领料确认。
    issue = SampleMaterialIssue.objects.filter(material_request=procurement.material_request).first()
    progress_after = material_progress(sample)
    has_available = any(
        Decimal(row['supplyQuantity']) + Decimal(row['arrivedQuantity']) > 0
        for row in progress_after['lines']
    )
    if not keep_production_stage and issue is None and has_available:
        sample.status = SampleRequestStatus.MATERIAL_ISSUE_PENDING
        sample.save(update_fields=['status', 'updated_at'])
    else:
        sample.save(update_fields=['updated_at'])
    _write_sample_records(sample_request=sample, action='MATERIALS_ARRIVED', actor_employee=request.employee,
                          request=request, before_data=before,
                          note=f'材料验收入库 {line.accepted_quantity} {line.source_unit_text_snapshot}；回写需求 {accepted_quantity} {demand["unitLabel"]}；来源 {inbound.pk} / {line.pk}。')
    return sample
