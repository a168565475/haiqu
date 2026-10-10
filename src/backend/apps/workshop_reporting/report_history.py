"""Durable creation identities and scheme usage, independent of live reports."""
from django.conf import settings
from rest_framework.exceptions import PermissionDenied

from apps.access_control.module_policy import has_permission
from apps.access_control.resource_scopes import require_workshop
from apps.core.api.exceptions import Conflict
from apps.core.auth import active_employee_for

from .models import WorkReport, WorkReportHistory


def deletion_enabled():
    return bool(getattr(settings, 'WORK_REPORT_DELETION_ENABLED', False))


def history_enabled():
    return deletion_enabled() or bool(getattr(settings, 'WORK_REPORT_HISTORY_ENABLED', False))


def can_delete_report(request, report):
    if not deletion_enabled() or request is None or active_employee_for(request.user) is None:
        return False
    if not has_permission(request, 'workshop_reporting.delete_workreport'):
        return False
    try:
        require_workshop(request, 'workshop_reporting.delete_workreport', report.workshop_id)
    except PermissionDenied:
        return False
    from .selectors import allowed_workshop_ids
    ids = allowed_workshop_ids(request, for_work_reports=True, permission='workshop_reporting.delete_workreport')
    return ids is None or str(report.workshop_id) in {str(pk) for pk in ids}


def remember_report(report):
    if not history_enabled():
        return None
    history, _ = WorkReportHistory.objects.select_for_update().get_or_create(
        client_request_id=report.client_request_id,
        defaults={
            'report_id': report.pk, 'report_number': report.report_number,
            'request_payload_hash': report.request_payload_hash,
            'used_scheme_ids': [str(report.scheme_id)],
        },
    )
    if history.deleted_at or history.report_id != report.pk:
        raise Conflict('该提交标识对应的报工已删除，不能重新创建。')
    scheme_id = str(report.scheme_id)
    if scheme_id not in history.used_scheme_ids:
        history.used_scheme_ids = [*history.used_scheme_ids, scheme_id]
        history.save(update_fields=['used_scheme_ids', 'updated_at'])
    return history


def existing_submission(request_id, request_hash):
    if history_enabled():
        history = WorkReportHistory.objects.select_for_update().filter(client_request_id=request_id).first()
        if history:
            if history.deleted_at:
                raise Conflict('该提交标识对应的报工已删除，不能重新创建。')
            if history.request_payload_hash != request_hash:
                raise Conflict('同一提交标识不能用于不同的报工内容。')
            if not WorkReport.objects.filter(pk=history.report_id).exists():
                raise Conflict('该报工历史已存在但原记录不可用，请核对记录。')
    report = WorkReport.objects.filter(client_request_id=request_id).first()
    if report:
        if report.request_payload_hash != request_hash:
            raise Conflict('同一提交标识不能用于不同的报工内容。')
        remember_report(report)
    return report


def scheme_was_used(scheme):
    return scheme.work_reports.exists() or (
        history_enabled()
        and WorkReportHistory.objects.filter(used_scheme_ids__contains=[str(scheme.pk)]).exists()
    )
