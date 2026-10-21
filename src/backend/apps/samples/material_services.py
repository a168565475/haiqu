"""打样材料交接：服务端冻结需求快照、校验数量、串行更新版本。"""
from apps.access_control.module_policy import can_sample
from copy import deepcopy
from decimal import Decimal
import re
import uuid

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError
from apps.core.api.concurrency import etag_for_instance, require_matching_etag
from apps.core.api.exceptions import Conflict
from apps.customers.services import model_snapshot
from apps.reference_data.models import ProductionUnit
from .models import SampleMaterialRequest, SampleMaterialProcurementRequest, SampleRequest, SampleRequestStatus
from .services import SAMPLE_FIELDS, _write_sample_records
from .procurement_status import sample_status_display


def material_actions(sample, request):
    active = bool(request and getattr(request, 'employee', None) and sample.application_payload_hash and sample.archived_at is None and sample.customer_account.archived_at is None)
    return {
        'can_edit_materials': bool(active and sample.status == SampleRequestStatus.MATERIALS_PENDING and can_sample(request, sample, 'samples.edit_sample_materials')),
        'can_review_materials': bool(active and sample.status == SampleRequestStatus.WAREHOUSE_PENDING and can_sample(request, sample, 'samples.review_sample_materials')),
    }


def quantity_value(value, *, allow_blank=False, positive=False):
    if value == '' and allow_blank:
        return None
    if not re.fullmatch(r'\d{1,14}(?:\.\d{1,4})?', value):
        raise ValidationError('数量最多 14 位整数、4 位小数，不支持负数或科学计数法。')
    result = Decimal(value)
    if positive and result <= 0:
        raise ValidationError('需求数量必须大于 0。')
    return result


def _record(sample):
    return SampleMaterialRequest.objects.filter(sample_request=sample).first()


def material_response(sample, request):
    from .material_arrival_services import material_progress
    if not sample.application_payload_hash:
        return {'available': False, 'reason': '历史申请不使用新版材料交接流程。'}
    record = _record(sample)
    procurement = SampleMaterialProcurementRequest.objects.filter(material_request=record).first() if record else None
    return {'available': True, 'draft': deepcopy(record.draft) if record else {'lines': [], 'notes': ''},
            'noMaterials': bool(record and record.no_materials), 'progress': material_progress(sample),
            'procurementRequest': {'id': str(procurement.pk), 'submittedAt': procurement.created_at.isoformat()} if procurement else None,
            'etag': etag_for_instance(sample), 'status': sample.status, 'statusLabel': sample_status_display(sample),
            'canEdit': material_actions(sample, request)['can_edit_materials'],
            'submittedAt': record.submitted_at.isoformat() if record and record.submitted_at else None}


def warehouse_response(sample, request):
    from .material_arrival_services import material_progress
    record = _record(sample)
    if record and record.no_materials:
        return {'available': False, 'reason': '打样部已确认无需用料，无需仓库核对。'}
    if not sample.application_payload_hash or not record or not record.submitted_at:
        return {'available': False, 'reason': '打样部尚未提交材料需求。'}
    supply = {line['key']: line['supplyQuantity'] for line in record.warehouse_draft.get('lines', [])}
    lines = [{**line, 'supplyQuantity': supply.get(line['key'], '')} for line in deepcopy(record.draft['lines'])]
    procurement = SampleMaterialProcurementRequest.objects.filter(material_request=record).first()
    return {'available': True, 'draft': {'lines': lines, 'notes': record.warehouse_draft.get('notes', '')},
            'progress': material_progress(sample),
            'procurementRequest': {'id': str(procurement.pk), 'lines': procurement.lines, 'submittedAt': procurement.created_at.isoformat()} if procurement else None,
            'etag': etag_for_instance(sample), 'canEdit': material_actions(sample, request)['can_review_materials'],
            'status': sample.status, 'statusLabel': sample_status_display(sample),
            'submittedAt': record.submitted_at.isoformat(), 'reviewedAt': record.reviewed_at.isoformat() if record.reviewed_at else None,
            }


def _locked_sample(sample_id, request, permission, capability):
    if not getattr(request, 'employee', None) or not request.user.has_perm('samples.' + permission):
        raise PermissionDenied('当前账号没有此材料操作权限或有效员工档案。')
    sample = SampleRequest.objects.select_for_update().get(pk=sample_id)
    require_matching_etag(request, sample)
    if not material_actions(sample, request)[capability]:
        raise Conflict('当前流程已变更或不可编辑，请刷新后核对。')
    return sample


@transaction.atomic
def save_materials(*, sample_id, data, request):
    sample = _locked_sample(sample_id, request, 'edit_sample_materials', 'can_edit_materials')
    before = model_snapshot(sample, SAMPLE_FIELDS)
    draft, submit = deepcopy(data['draft']), data['submit']
    keys = [str(line['key']) for line in draft['lines']]
    if len(keys) != len(set(keys)):
        raise ValidationError('材料行标识重复，请重新加载。')
    if submit and not keys:
        raise ValidationError('请至少填写一项材料需求。')
    for line in draft['lines']:
        line['key'] = str(line['key'])
        if line['category'] == 'tube':
            from .pipe_materials import normalize_sample_pipe
            normalize_sample_pipe(line, submit=submit)
            continue
        if line.get('rawMaterialId'):
            line['rawMaterialId'] = str(line['rawMaterialId'])
        quantity_value(line['quantity'], allow_blank=not submit, positive=True)
        unit = None
        if line['unitId']:
            try:
                unit_id = uuid.UUID(line['unitId'])
            except ValueError as exc:
                raise ValidationError('材料单位无效。') from exc
            unit = ProductionUnit.objects.filter(pk=unit_id, status='ACTIVE', archived_at__isnull=True).first()
            if not unit:
                raise ValidationError('材料单位已停用或不存在，请重新选择。')
        if submit and (not line['name'] or not line['specification'] or not unit):
            raise ValidationError('请填写每项材料名称、规格、需求数量和有效单位。')
        line['unitLabel'] = unit.unit_name if unit else ''
        if submit:
            from .material_identity import sample_material_snapshot
            # 提交仓库前发现缺失关联，避免进入采购后才发现无法入库。
            sample_material_snapshot(sample, line)
    record, _ = SampleMaterialRequest.objects.get_or_create(sample_request=sample)
    record.draft = draft
    if submit:
        record.submitted_at = timezone.now()
        record.submitted_by = request.employee
        sample.status = SampleRequestStatus.WAREHOUSE_PENDING
    record.save()
    sample.save(update_fields=['status', 'updated_at'])
    _write_sample_records(sample_request=sample, action='MATERIALS_SUBMITTED' if submit else 'MATERIALS_DRAFT_SAVED', actor_employee=request.employee, request=request, before_data=before, note='材料需求已提交仓库。' if submit else '保存材料需求草稿。')
    return sample


@transaction.atomic
def save_warehouse(*, sample_id, data, request):
    sample = _locked_sample(sample_id, request, 'review_sample_materials', 'can_review_materials')
    record = _record(sample)
    if not record or not record.submitted_at:
        raise Conflict('没有已提交的材料需求。')
    before = model_snapshot(sample, SAMPLE_FIELDS)
    draft, submit = deepcopy(data['draft']), data['submit']
    required = {line['key']: line for line in record.draft['lines']}
    keys = [str(line['key']) for line in draft['lines']]
    if len(keys) != len(set(keys)) or set(keys) != set(required):
        raise ValidationError('仓库材料行必须与已提交需求一致，不能新增、删除或重复。')
    shortages = []
    for line in draft['lines']:
        line['key'] = str(line['key'])
        supply = quantity_value(line['supplyQuantity'], allow_blank=not submit)
        if required[line['key']]['category'] == 'tube' and supply is not None:
            # 新口径管材需求、仓库可供和缺料均按总米数；旧快照仍按整支校验。
            from .pipe_materials import is_total_meter_pipe
            if not is_total_meter_pipe(required[line['key']]) and supply != supply.to_integral_value():
                raise ValidationError('旧口径管材可供数量按整数支填写。')
        need = Decimal(required[line['key']]['quantity'])
        if supply is not None and supply > need:
            raise ValidationError('本次可供数量不能超过需求数量。')
        if supply is not None and need > supply:
            shortages.append({**required[line['key']], 'supplyQuantity': line['supplyQuantity'], 'shortageQuantity': format(need - supply, 'f')})
    if submit:
        if shortages:
            SampleMaterialProcurementRequest.objects.create(material_request=record, lines=shortages, notes=draft['notes'])
        if shortages:
            sample.status = SampleRequestStatus.PROCUREMENT_PENDING
        else:
            # 仓库只确认可供数量；实际库存扣减必须在样品领料确认时发生。
            sample.status = SampleRequestStatus.MATERIAL_ISSUE_PENDING
        record.reviewed_at = timezone.now()
        record.reviewed_by = request.employee
    record.warehouse_draft = draft
    record.save()
    sample.save(update_fields=['status', 'updated_at'])
    _write_sample_records(sample_request=sample, action='WAREHOUSE_CONFIRMED' if submit else 'WAREHOUSE_DRAFT_SAVED', actor_employee=request.employee, request=request, before_data=before, note='已核实本次材料可供数量；未执行库存扣减。' if submit else '保存仓库核对草稿。')
    return sample


@transaction.atomic
def confirm_no_materials(*, sample_id, request):
    sample = _locked_sample(sample_id, request, 'edit_sample_materials', 'can_edit_materials')
    before = model_snapshot(sample, SAMPLE_FIELDS)
    record, _ = SampleMaterialRequest.objects.get_or_create(sample_request=sample)
    # 保留原草稿以便追溯；显式标识无需用料，不把草稿中的材料当作已提交需求。
    record.no_materials = True
    record.submitted_at = timezone.now()
    record.submitted_by = request.employee
    record.save()
    from .production_services import enter_parameter_stage
    enter_parameter_stage(sample, actor_employee=request.employee, note='打样部确认无需用料，允许生产。')
    _write_sample_records(sample_request=sample, action='NO_MATERIALS_CONFIRMED', actor_employee=request.employee,
                          request=request, before_data=before, note='打样部确认无需用料，跳过仓库及采购。')
    return sample
