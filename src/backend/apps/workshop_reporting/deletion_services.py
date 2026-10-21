"""Physical report deletion, retaining independent audit and request history."""
import json

from django.core.serializers.json import DjangoJSONEncoder
from django.db import transaction
from django.db.models import Sum
from django.http import Http404
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.core.api.concurrency import require_matching_etag
from apps.core.audit import write_audit_log
from apps.core.api.exceptions import Conflict

from .models import (
    WageScheme, WageSchemeLineStatus, WorkReport, WorkReportLine,
    WorkshopPlanExecution, WorkshopPlanStatus, WorkReportHistory,
)
from .report_history import can_delete_report, remember_report
from .services import _locked_schedule_product, _lock_tube_report_scope, _lock_sewing_report_scope


def _snapshot(report):
    data = {field.attname: getattr(report, field.attname) for field in report._meta.concrete_fields}
    data['workshop_name'] = report.workshop.name
    data['scheme_number'] = report.scheme.scheme_number
    data['scope_craft_id'] = report.scheme.scope_craft_id
    data['scope_craft_name'] = report.scheme.scope_craft.name
    data['lines'] = list(report.lines.order_by('line_number', 'id').values())
    return json.loads(json.dumps(data, cls=DjangoJSONEncoder))


def _completion_scheme(execution, report):
    """Use the version that established completion, never today's replacement version."""
    candidates = []
    reports = WorkReport.objects.filter(
        schedule_product_id=execution.schedule_product_id,
        scheme__scope_craft_id=execution.craft_id, completed_plan=True,
    )
    if execution.completed_at:
        reports = reports.filter(updated_at__lte=execution.completed_at)
    last = reports.order_by('-updated_at', '-pk').first()
    if last:
        candidates.append((last.updated_at, last.scheme_id))
    # A prior deletion may have left enough quantity. Its completion basis survives too.
    histories = WorkReportHistory.objects.filter(
        deleted_at__isnull=False,
        deletion_snapshot__schedule_product_id=str(execution.schedule_product_id),
        deletion_snapshot__scope_craft_id=str(execution.craft_id),
        deletion_snapshot__completed_plan=True,
    )
    for history in histories:
        snapshot = history.deletion_snapshot
        updated = parse_datetime(snapshot['updated_at'])
        if updated and (execution.completed_at is None or updated <= execution.completed_at):
            candidates.append((updated, snapshot['scheme_id']))
    if not candidates:
        raise Conflict('无法确定已完成计划的工价版本，请先核对计划完成记录。')
    scheme_id = max(candidates, key=lambda item: item[0])[1]
    return WageScheme.objects.get(pk=scheme_id)


def _reopen_incomplete_plans(report):
    # Quantities are shared by product/workshop/work item in existing reporting.
    executions = list(WorkshopPlanExecution.objects.select_for_update(of=('self',)).filter(
        schedule_product__product_line_id=report.product_line_id,
        craft_id=report.scheme.scope_craft_id,
        status=WorkshopPlanStatus.COMPLETED,
    ).order_by('pk'))
    if not executions:
        return []
    changes = []
    for execution in executions:
        scheme = _completion_scheme(execution, report)
        required = list(scheme.lines.filter(status=WageSchemeLineStatus.ACTIVE))
        quantities = {
            row['work_item_id']: row['quantity'] for row in WorkReportLine.objects.filter(
                report__product_line_id=report.product_line_id, report__workshop_id=report.workshop_id,
                work_item_id__in=[line.work_item_id for line in required],
            ).values('work_item_id').annotate(quantity=Sum('quantity'))
        }
        complete = bool(required) and all(
            line.required_quantity_snapshot is not None
            and line.required_quantity_snapshot > 0
            and quantities.get(line.work_item_id, 0) >= line.required_quantity_snapshot
            for line in required
        )
        if not complete:
            changes.append({
                'id': str(execution.pk), 'schedule_product_id': str(execution.schedule_product_id),
                'before': {'status': execution.status, 'completed_at': execution.completed_at,
                           'completed_by_employee_id': execution.completed_by_employee_id},
                'after': {'status': WorkshopPlanStatus.IN_PROGRESS},
            })
            execution.status = WorkshopPlanStatus.IN_PROGRESS
            execution.completed_at = None
            execution.completed_by_employee = None
            execution.save(update_fields=['status', 'completed_at', 'completed_by_employee', 'updated_at'])
    return changes


@transaction.atomic
def delete_work_report(*, report_id, reason, actor, request):
    reason = (reason or '').strip()
    if not reason or len(reason) > 1000:
        raise ValidationError({'reason': '请填写删除原因，最多1000字。'})
    current = WorkReport.objects.select_related('scheme').filter(pk=report_id).first()
    if current is None:
        raise Http404('报工记录不存在或已删除。')
    if not can_delete_report(request, current) or actor.pk != request.employee.pk:
        raise PermissionDenied('当前账号不能删除该车间的报工。')
    tube_scope = _lock_tube_report_scope(current.schedule_product_id, current.scheme)
    sewing_scope = _lock_sewing_report_scope(current.schedule_product_id, current.scheme)
    _locked_schedule_product(current.schedule_product_id)
    report = WorkReport.objects.select_for_update().filter(pk=report_id).first()
    if report is None:
        raise Http404('报工记录不存在或已删除。')
    if not can_delete_report(request, report):
        raise PermissionDenied('当前账号不能删除该车间的报工。')
    require_matching_etag(request, report)
    history = remember_report(report)
    before = _snapshot(report)
    report.lines.all().delete()
    from apps.inventory.assembly_reporting_limits import is_assembly_report, assert_reports_cover_receipts
    if is_assembly_report(report):
        assert_reports_cover_receipts(report.product_line)
    if tube_scope:
        from apps.inventory.tube_processing_services import assert_tube_reports_cover_usage
        assert_tube_reports_cover_usage(report.product_line_id)
    if sewing_scope:
        from apps.inventory.sewing_processing_services import assert_sewing_reports_cover_usage
        assert_sewing_reports_cover_usage(report.product_line_id)
    changes = _reopen_incomplete_plans(report)
    history.deleted_at = timezone.now()
    history.deleted_by_employee_id = actor.pk
    history.deleted_by_name = actor.display_name
    history.deletion_reason = reason
    history.deletion_snapshot = before
    history.save(update_fields=[
        'deleted_at', 'deleted_by_employee_id', 'deleted_by_name', 'deletion_reason',
        'deletion_snapshot', 'updated_at',
    ])
    write_audit_log(
        object_type='WORK_REPORT', object_id=report.pk, action='DELETE', actor_employee=actor,
        before_data=before, after_data={'reason': reason, 'deleted_at': history.deleted_at,
                                     'plan_changes': changes}, request=request,
    )
    # Keep model-level direct deletion blocked; only this audited transaction removes the row.
    WorkReport.objects.filter(pk=report.pk).delete()
    from apps.wecom.workshop_change_notifications import report_deleted
    report_deleted(history, actor)
