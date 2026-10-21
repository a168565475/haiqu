"""打样既有成功节点的事实快照；不发送外部消息、不改变库存或审批。"""
import hashlib
import json
from decimal import Decimal

from apps.audit.models import AuditLog
from apps.wecom.notification_services import register_business_event
from .models import SampleMaterialIssue, SampleMaterialProcurementRequest, SampleRequest


ACTION_EVENTS = {
    'SAMPLE_SUBMITTED': ('DIRECTOR_REVIEW', ('APPLICATION_SUBMITTED', 'APPLICATION_RESUBMITTED')),
    'SAMPLE_EFFECTIVE': ('PENDING_COMPLETION', ('APPLICATION_EFFECTIVE', 'DIRECTOR_APPROVED')),
    'SAMPLE_RETURNED': ('APPLICATION_RETURNED', ('DIRECTOR_RETURNED',)),
    'SAMPLE_REQUIREMENTS_COMPLETED': ('MATERIALS_PENDING', ('REQUIREMENTS_COMPLETED',)),
    'SAMPLE_MATERIALS_SUBMITTED': ('WAREHOUSE_PENDING', ('MATERIALS_SUBMITTED',)),
    'SAMPLE_PRODUCTION_READY': (None, ('NO_MATERIALS_CONFIRMED',)),
}
SAMPLE_EVENTS = set(ACTION_EVENTS) | {
    'SAMPLE_MATERIAL_SHORTAGE', 'SAMPLE_MATERIALS_AVAILABLE',
    'SAMPLE_MATERIAL_ISSUE_SUBMITTED', 'SAMPLE_MATERIAL_ISSUED', 'SAMPLE_COMPLETED',
}


def sample_for_event(code, object_id):
    if code in {'SAMPLE_MATERIAL_ISSUE_SUBMITTED', 'SAMPLE_MATERIAL_ISSUED'}:
        obj = SampleMaterialIssue.objects.select_related('material_request__sample_request').filter(pk=object_id).first()
        return (obj.material_request.sample_request, obj) if obj else (None, None)
    if code == 'SAMPLE_MATERIAL_SHORTAGE':
        obj = SampleMaterialProcurementRequest.objects.select_related('material_request__sample_request').filter(pk=object_id).first()
        return (obj.material_request.sample_request, obj) if obj else (None, None)
    sample = SampleRequest.objects.filter(pk=object_id).first()
    return sample, sample


def available_material_version(sample):
    """只读复用领料计划，核库不扣库；同原料多行累计核对真实库存。"""
    from .sample_issue_services import ISSUE_START_STATUSES, _available_rows, _pipe_plans
    from apps.inventory.models import MaterialStockBalance
    from apps.inventory.tube_outsourcing_reservations import tube_material_reserved_quantities
    from rest_framework.exceptions import ValidationError
    from apps.core.api.exceptions import Conflict
    if sample.status not in ISSUE_START_STATUSES or SampleMaterialIssue.objects.filter(material_request__sample_request=sample).exists():
        return None
    try:
        rows = _available_rows(sample)
        _, blockers = _pipe_plans(sample.material_request, rows)
    except (Conflict, ValidationError):
        # 业务门槛不满足不是可领料成功；数据库/内部异常仍上抛。
        return None
    if blockers:
        return None
    totals = {}
    for item in rows:
        if item['row'].get('category') != 'tube':
            key = (item['material'].pk, item['material'].unit_id)
            totals[key] = totals.get(key, Decimal('0')) + item['available']
    _, reserved = tube_material_reserved_quantities(raw_material_ids=[key[0] for key in totals])
    for (material_id, unit_id), quantity in totals.items():
        balances = MaterialStockBalance.objects.filter(raw_material_id=material_id, unit_id=unit_id,
            measurement_kind='OTHER', quality='AVAILABLE', quantity__gt=0,
            zone__status='ACTIVE', zone__warehouse__status='ACTIVE')
        free = sum((max(row.quantity - reserved.get((str(material_id), str(unit_id), str(row.zone_id)), Decimal('0')), Decimal('0')) for row in balances), Decimal('0'))
        if free < quantity:
            return None
    facts = sorted((str(item['row']['key']), str(item['material'].pk), str(item['warehouse']), str(item['arrived'])) for item in rows)
    return hashlib.sha256(json.dumps(facts, separators=(',', ':')).encode()).hexdigest()


def current_sample_object(code, object_id, version=None):
    sample, obj = sample_for_event(code, object_id)
    if sample is None or not sample.application_payload_hash or sample.archived_at or sample.customer_account.archived_at:
        return None
    actual = None
    if code in ACTION_EVENTS:
        status, actions = ACTION_EVENTS[code]
        if status and sample.status != status:
            return None
        if code == 'SAMPLE_PRODUCTION_READY' and sample.status not in {'METALWORK_PENDING', 'CUTTING_PENDING', 'PRODUCTION_PENDING'}:
            return None
        audit = AuditLog.objects.filter(object_type='SAMPLE_REQUEST', object_id=sample.pk, action__in=actions).order_by('-occurred_at', '-id').first()
        actual = str(audit.pk) if audit else None
    elif code == 'SAMPLE_MATERIAL_SHORTAGE':
        if sample.status == 'PROCUREMENT_PENDING' and not obj.purchase_sources.exists() and obj.lines:
            actual = '1'
    elif code == 'SAMPLE_MATERIALS_AVAILABLE':
        actual = available_material_version(sample)
    elif code in {'SAMPLE_MATERIAL_ISSUE_SUBMITTED', 'SAMPLE_MATERIAL_ISSUED'}:
        expected = 'PENDING_CONFIRMATION' if code.endswith('SUBMITTED') else 'ISSUED'
        valid_stage = sample.status == 'MATERIAL_ISSUE_REVIEW' if code.endswith('SUBMITTED') else sample.status in {'METALWORK_PENDING', 'CUTTING_PENDING', 'PRODUCTION_PENDING'}
        if obj.status == expected and valid_stage:
            actual = str(obj.version)
    elif code == 'SAMPLE_COMPLETED' and sample.status == 'FINISHED':
        from .production_services import PARAMETER_STAGES, parameter_stage_ready
        record = sample.workflow_records.filter(stage='WORKFLOW_FINISHED').first()
        if record and all(parameter_stage_ready(sample, stage) for stage in PARAMETER_STAGES) and sample.items.exists() and not sample.items.filter(metalwork_completed=False).exists() and not sample.items.filter(cutting_completed=False).exists():
            actual = record.operated_at.isoformat()
    return obj if actual is not None and (version is None or str(version) == actual) else None


def _register(code, obj, sample, version, actor, occurred_at):
    products = list(sample.products.order_by('line_number').values_list('product_name', flat=True))
    if not products:
        products = list(sample.items.order_by('line_number').values_list('product_description_snapshot', flat=True))
    context = {'document_no': sample.request_number, 'operator': actor.display_name,
               'occurred_at': occurred_at.isoformat(), 'status': sample.get_status_display()}
    if products and products[0].strip():
        context['product_name'] = products[0] if len(products) == 1 else f'{products[0]}等{len(products)}项产品'
    if sample.requested_by_employee_id:
        context.update(submitter=sample.requested_by_employee.display_name, submitter_id=str(sample.requested_by_employee_id))
    return register_business_event(event_code=code, idempotency_key=f'{code}:{obj.pk}:{version}',
        object_type=obj._meta.label, object_id=obj.pk, object_version=version,
        context=context)


def action_recorded(sample, audit, actor):
    for code, (_, actions) in ACTION_EVENTS.items():
        if audit.action in actions:
            _register(code, sample, sample, str(audit.pk), actor, audit.occurred_at)
    if audit.action == 'WAREHOUSE_CONFIRMED':
        procurement = SampleMaterialProcurementRequest.objects.filter(material_request__sample_request=sample).first()
        if procurement:
            _register('SAMPLE_MATERIAL_SHORTAGE', procurement, sample, '1', actor, audit.occurred_at)
    if audit.action in {'WAREHOUSE_CONFIRMED', 'MATERIALS_ARRIVED'}:
        version = available_material_version(sample)
        if version:
            _register('SAMPLE_MATERIALS_AVAILABLE', sample, sample, version, actor, audit.occurred_at)
    issue_code = {'SAMPLE_MATERIAL_ISSUE_INITIATED': 'SAMPLE_MATERIAL_ISSUE_SUBMITTED',
                  'SAMPLE_MATERIAL_ISSUE_CONFIRMED': 'SAMPLE_MATERIAL_ISSUED'}.get(audit.action)
    if issue_code:
        issue = SampleMaterialIssue.objects.get(material_request__sample_request=sample)
        _register(issue_code, issue, sample, str(issue.version), actor, issue.initiated_at if issue.version == 1 else issue.confirmed_at)


def production_completed(sample, actor):
    record = sample.workflow_records.get(stage='WORKFLOW_FINISHED')
    return _register('SAMPLE_COMPLETED', sample, sample, record.operated_at.isoformat(), actor, record.operated_at)
