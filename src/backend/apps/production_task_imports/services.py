from datetime import timedelta
from uuid import UUID

from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from rest_framework import serializers

from apps.core.api.concurrency import require_matching_etag
from apps.core.api.exceptions import Conflict
from apps.core.audit import write_audit_log
from apps.organizations.models import Employee
from .access import require_actor
from .models import ProductionTaskImport
from .storage import remove_files, upload_bytes, write_source


def audit(record, action, request=None):
    write_audit_log(object_type='PRODUCTION_TASK_IMPORT', object_id=record.pk, action=action,
                   actor_employee=record.owner, request=request,
                   after_data={'state': record.state, 'attempt_no': record.attempt_no,
                               'result_revision': record.result_revision, 'error_code': record.error_code})


def create_import(request, upload, request_key):
    actor = require_actor(request)
    name, data, digest = upload_bytes(upload)
    record = None
    written = False
    try:
        with transaction.atomic():
            # 同员工的重试与选定对象复用共用锁；并发重复请求不会写出两份原件。
            Employee.objects.select_for_update(no_key=True).get(pk=actor.pk)
            existing = ProductionTaskImport.objects.filter(owner=actor, client_request_id=request_key).first()
            if existing:
                if existing.sha256 != digest:
                    raise Conflict('同一上传请求编号不能改用另一个文件。')
                return existing, True
            record = ProductionTaskImport.objects.create(owner=actor, client_request_id=request_key,
                original_name=name, sha256=digest, size_bytes=len(data), expires_at=timezone.now() + timedelta(days=7))
            write_source(record, data)
            written = True
            audit(record, 'IMPORT_UPLOADED', request)
        return record, False
    except BaseException:
        if written:
            remove_files(record)
        raise


def owned(request, record_id, *, lock=False):
    actor = require_actor(request)
    record_id = serializers.UUIDField().run_validation(record_id)
    queryset = ProductionTaskImport.objects.filter(owner=actor)
    if lock:
        queryset = queryset.select_for_update()
    return get_object_or_404(queryset, pk=record_id)


def editable(request, record_id, states):
    record = owned(request, record_id, lock=True)
    require_matching_etag(request, record)
    if record.state not in states or record.saved_at or record.expires_at <= timezone.now():
        raise Conflict('当前导入状态不允许此操作，请刷新。')
    return record


@transaction.atomic
def select_candidate(request, record_id, object_id):
    actor = require_actor(request)
    Employee.objects.select_for_update(no_key=True).get(pk=actor.pk)
    record = editable(request, record_id, ('NEEDS_SELECTION', 'REVIEW'))
    candidate = next((item for item in record.candidates if item['object_id'] == object_id), None)
    if candidate is None:
        raise ValidationError({'object_id': '请选择此文件的有效任务/版本。'})
    previous = ProductionTaskImport.objects.filter(owner=actor, sha256=record.sha256, object_key=object_id).exclude(pk=record.pk).first()
    if previous:
        return previous
    record.selected_candidate = candidate
    record.object_key = object_id
    record.phase, record.state = 'extraction', 'QUEUED'
    record.attempt_no += 1
    record.extraction, record.review, record.matching = {}, {}, {}
    record.error_code = ''
    record.operation = None
    record.save()
    audit(record, 'IMPORT_OBJECT_SELECTED', request)
    return record


@transaction.atomic
def cancel_import(request, record_id):
    # 与 worker 一致：先锁连接，再锁导入记录，避免换号/写回的锁序相反。
    from apps.codex_connection.models import CodexConnection
    connection = CodexConnection.objects.select_for_update().first()
    record = editable(request, record_id, ('CHECKING', 'SCANNING', 'QUEUED', 'PARSING', 'NEEDS_SELECTION', 'REVIEW', 'FAILED'))
    if record.operation_id:
        operation = record.operation
        if operation.state in ('QUEUED', 'RUNNING'):
            if operation.state == 'QUEUED':
                from apps.codex_connection.worker import _finish
                _finish(connection, operation, 'CANCELED')
            else:
                operation.state = 'CANCELING'
                operation.save(update_fields=['state', 'updated_at'])
    record.state = 'CANCELED'
    record.attempt_no += 1
    record.save()
    audit(record, 'IMPORT_CANCELED', request)
    return record


@transaction.atomic
def retry_import(request, record_id):
    record = editable(request, record_id, ('FAILED', 'CANCELED'))
    if record.operation_id and record.operation.state in ('RUNNING', 'CANCELING'):
        raise Conflict('上次解析仍在停止，请稍后重试。')
    record.state = 'QUEUED' if record.manifest and record.scan_status == 'CLEAN' else 'CHECKING'
    record.attempt_no += 1
    record.error_code = ''
    record.operation = None
    record.save()
    audit(record, 'IMPORT_RETRY_REQUESTED', request)
    return record
