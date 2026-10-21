from apps.access_control import module_policy
"""新版打样的材料齐备、参数与报工门槛；历史流程独立保留。"""
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.core.api.concurrency import require_matching_etag
from apps.core.api.exceptions import Conflict
from apps.customers.services import model_snapshot
from .models import SampleRequest, SampleRequestStatus as Status, SampleWorkflowStage as Stage
from .services import SAMPLE_FIELDS, _record_workflow_stage, _write_sample_records, _finish_sla

REPORT_STATUSES = {Status.METALWORK_PENDING, Status.CUTTING_PENDING, Status.PRODUCTION_PENDING}
PARAMETER_STAGES = {Stage.METALWORK_PARAMETERS, Stage.CUTTING_PARAMETERS}


def production_ready(sample):
    return sample.workflow_records.filter(stage=Stage.MATERIALS_READY).exists()


def parameter_stage_ready(sample, stage):
    """新图片记录为准，同时兼容历史单据的旧单文件流程记录。"""
    parameter_type = "METALWORK" if stage == Stage.METALWORK_PARAMETERS else "CUTTING"
    if sample.parameter_images.filter(
        parameter_type=parameter_type,
        archived_at__isnull=True,
    ).exists():
        return True
    return sample.workflow_records.filter(stage=stage, business_file__isnull=False).exists()


def can_report_production(sample, request):
    return bool(request and getattr(request, 'employee', None)
                and module_policy.can_report_sample(request, sample)
                and sample.application_payload_hash and sample.archived_at is None
                and sample.customer_account.archived_at is None
                and sample.status in REPORT_STATUSES and production_ready(sample))


def enter_parameter_stage(sample, *, actor_employee, note):
    """调用方持有样品锁，且已验证材料齐备依据。"""
    if sample.status not in {Status.MATERIALS_PENDING, Status.WAREHOUSE_PENDING,
                             Status.PROCUREMENT_PENDING, Status.MATERIALS_READY,
                             Status.MATERIAL_ISSUE_REVIEW}:
        raise Conflict('当前样品不在材料处理阶段。')
    _record_workflow_stage(sample_request=sample, stage=Stage.MATERIALS_READY,
                           actor_employee=actor_employee, note=note, operated_at=timezone.now())
    sample.status = Status.METALWORK_PENDING
    sample.save(update_fields=['status', 'updated_at'])


def finish_production_if_ready(sample, *, actor_employee):
    if not all(parameter_stage_ready(sample, stage) for stage in PARAMETER_STAGES):
        return
    items = list(sample.items.all())
    complete = bool(items) and all(item.metalwork_completed and item.cutting_completed for item in items)
    sample.status = Status.FINISHED if complete else Status.PRODUCTION_PENDING
    sample.save(update_fields=['status', 'updated_at'])
    if complete:
        now = timezone.now()
        _record_workflow_stage(sample_request=sample, stage=Stage.WORKFLOW_FINISHED,
                               actor_employee=actor_employee, note='金工、裁剪参数齐全且生产均已确认完成。', operated_at=now)
        _finish_sla(sample, False, now)
        from .notification_events import production_completed
        production_completed(sample, actor_employee)


@transaction.atomic
def report_production(*, sample_id, data, request):
    sample = SampleRequest.objects.select_for_update().get(pk=sample_id)
    if not getattr(request, 'employee', None) or not module_policy.can_report_sample(request, sample):
        raise PermissionDenied('当前账号没有报工权限或有效员工档案。')
    require_matching_etag(request, sample)
    if not can_report_production(sample, request):
        raise Conflict('当前样品尚未允许生产或已结束，不能报工。')
    items = {str(item.pk): item for item in sample.items.select_for_update().all()}
    ids = [str(row['id']) for row in data['items']]
    if len(ids) != len(set(ids)) or set(ids) != set(items):
        raise ValidationError('报工项目必须与当前样品一致，不能增删或重复。')
    module_policy.require_sample_reporting_changes(request, sample, data['items'])
    before = model_snapshot(sample, SAMPLE_FIELDS)
    changes = []
    for row in data['items']:
        item = items[str(row['id'])]
        fields = ['metalwork_reported_quantity', 'cutting_reported_quantity', 'metalwork_completed', 'cutting_completed']
        values = {field: row.get(field, getattr(item, field)) for field in fields}
        for quantity_field, completed_field in (
            ('metalwork_reported_quantity', 'metalwork_completed'),
            ('cutting_reported_quantity', 'cutting_completed'),
        ):
            quantity = values[quantity_field] or 0
            if values[completed_field] and quantity <= 0:
                raise ValidationError(f'{completed_field}为完成时，{quantity_field}必须大于 0。')
            if quantity > (item.sample_quantity or 0):
                raise ValidationError('报工数量不能超过打样数量。')
        changes.append({'id': str(item.pk), 'before': {field: getattr(item, field) for field in fields},
                        'after': values})
        for field in fields:
            setattr(item, field, values[field])
        item.save(update_fields=fields + ['updated_at'])
    finish_production_if_ready(sample, actor_employee=request.employee)
    sample.save(update_fields=['updated_at'])
    before['production_reports'] = changes
    _write_sample_records(sample_request=sample, action='PRODUCTION_REPORTED', actor_employee=request.employee,
                          request=request, before_data=before, note='更新金工、裁剪报工数量及完成状态。')
    return sample
