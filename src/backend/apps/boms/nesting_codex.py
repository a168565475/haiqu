"""只提交真实文件并接收 Codex 工具成果；ERP 不参与排料或重新计算单耗。"""
import base64
from copy import deepcopy
from datetime import timedelta
import hashlib

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.codex_connection.models import ACTIVE_STATES, CodexConnection, CodexOperation
from apps.codex_connection.services import audit_operation
from apps.organizations.models import Employee
from .nesting_executor_contract import validate_envelope
from .nesting_models import BomNestingJob
from .nesting_services import worker_allowed
from .nesting_storage import NestingFailure, source_path, write_artifacts
from .nesting_worker import fail


CODEX_WAIT_SECONDS = 1200


@transaction.atomic
def cancel_operation(operation_id):
    # BOM 事务提交后再取连接锁，保持 connection→operation→job 锁序。
    connection = CodexConnection.objects.select_for_update().first()
    if connection is None:
        return
    operation = connection.operations.select_for_update().filter(pk=operation_id, action='nest').first()
    if operation is None or operation.state not in ACTIVE_STATES:
        return
    if operation.state == 'QUEUED':
        operation.state, operation.completed_at = 'CANCELED', timezone.now()
        operation.save(update_fields=['state', 'completed_at', 'updated_at'])
        if not connection.operations.filter(state__in=ACTIVE_STATES).exists() and connection.status == 'READY':
            connection.paused = False
            connection.save(update_fields=['paused', 'updated_at'])
    else:
        operation.state = 'CANCELING'
        operation.save(update_fields=['state', 'updated_at'])
    audit_operation(connection, operation, 'CODEX_OPERATION_CANCEL_REQUESTED')


@transaction.atomic
def enqueue_next():
    connection = CodexConnection.objects.select_for_update().first()
    cutoff = timezone.now() - timedelta(seconds=CODEX_WAIT_SECONDS)
    job = (BomNestingJob.objects.select_for_update(skip_locked=True)
        .filter(phase__in=['EXTRACT', 'NEST'])
        .filter(Q(status='QUEUED') | Q(status='RUNNING', started_at__lt=cutoff))
        .order_by('created_at', 'id').first())
    if job is None:
        return False
    error_code = ''
    if not worker_allowed(job):
        error_code = 'PERMISSION_REVOKED'
    elif (job.started_at or job.updated_at) < cutoff:
        error_code = 'TIMEOUT'
    if error_code:
        fail(job, error_code)
        if job.operation_id:
            transaction.on_commit(lambda key=job.operation_id: cancel_operation(key))
        return True
    if connection and connection.operations.filter(state__in=ACTIVE_STATES).exists():
        return False
    if (connection is None or connection.paused or connection.status != 'READY'
            or not connection.account or not connection.selected_model):
        fail(job, 'NOT_READY')
        return True
    actor = Employee.objects.get(user_id=job.requested_by_user_id)
    operation = CodexOperation.objects.create(connection=connection, actor=actor, action='nest',
        generation=connection.config_generation, model=connection.selected_model)
    job.operation, job.status, job.started_at = operation, 'RUNNING', timezone.now()
    job.save()
    connection.paused = True
    connection.save(update_fields=['paused', 'updated_at'])
    audit_operation(connection, operation, 'CODEX_OPERATION_QUEUED')
    return True


def _operation_job(operation, *, lock=False):
    query = BomNestingJob.objects
    if lock:
        query = query.select_for_update()
    return query.filter(operation=operation, phase__in=['EXTRACT', 'NEST'], status='RUNNING',
                        requested_by_user_id=operation.actor.user_id).first()


def operation_allowed(operation):
    job = _operation_job(operation)
    return job is not None and worker_allowed(job)


def runtime_payload(operation):
    job = _operation_job(operation)
    if job is None or not worker_allowed(job):
        raise NestingFailure('PERMISSION_REVOKED')
    raw = source_path(job).read_bytes()
    if len(raw) != job.size_bytes or hashlib.sha256(raw).hexdigest() != job.sha256:
        raise NestingFailure('SOURCE_CHANGED')
    payload = {'schema_version': 2, 'phase': job.phase.lower(),
               'source': {'data_base64': base64.b64encode(raw).decode('ascii'),
                          'size_bytes': job.size_bytes, 'sha256': job.sha256, 'unit': job.source_unit}}
    if job.phase == 'NEST':
        if not job.analysis_digest:
            raise NestingFailure('EXECUTOR_RESULT_INVALID')
        payload.update(parameters=deepcopy(job.parameters), analysis_digest=job.analysis_digest)
    return payload


def prepare_codex_result(operation, runtime, data, boot_id):
    """网络取文件只能在事务外；不在此处写文件或修改任务。"""
    if transaction.get_connection().in_atomic_block:
        raise RuntimeError('Codex artifacts cannot be downloaded in a database transaction')
    job = _operation_job(operation)
    if job is None:
        return None
    if not worker_allowed(job):
        raise NestingFailure('PERMISSION_REVOKED')
    source_path(job)
    validate_envelope(job, operation, data)
    artifacts = {}
    for entry in data['artifacts']:
        from apps.codex_connection.runtime_client import RuntimeFailure
        try:
            artifacts[entry['name']] = runtime.fetch_artifact({
                'operation_id': str(operation.pk), 'generation': operation.generation,
                'boot_id': boot_id, 'name': entry['name']}, entry)
        except RuntimeFailure as exc:
            if exc.code in ('INVALID_RESPONSE', 'INVALID_REQUEST'):
                raise NestingFailure('ARTIFACT_INVALID') from exc
            raise
    return {**deepcopy(data), '_artifact_bytes': artifacts}


@transaction.atomic
def finish_codex_operation(operation, result, error_code):
    job = _operation_job(operation, lock=True)
    if job is None:
        return ''
    if not worker_allowed(job):
        fail(job, 'PERMISSION_REVOKED')
        return 'PERMISSION_REVOKED'
    if error_code:
        fail(job, error_code)
        return ''
    try:
        source_path(job)
        if not isinstance(result, dict):
            raise NestingFailure('EXECUTOR_RESULT_INVALID')
        data = {key: value for key, value in result.items() if key != '_artifact_bytes'}
        validate_envelope(job, operation, data)
        if job.phase == 'NEST':
            write_artifacts(job, data['artifacts'], result.get('_artifact_bytes'))
        elif result.get('_artifact_bytes') != {}:
            raise NestingFailure('ARTIFACT_INVALID')
    except NestingFailure as exc:
        fail(job, exc.code)
        return exc.code
    job.analysis = data['analysis']
    job.analysis_digest = data['analysis_digest']
    job.execution, job.artifacts = data['execution'], data['artifacts']
    job.result = data['result'] or {}
    job.optimization = job.result.get('optimization', {})
    job.status = 'NEEDS_PARAMETERS' if job.phase == 'EXTRACT' else 'SUCCEEDED'
    job.finished_at = timezone.now()
    job.error_code, job.error_message = '', ''
    job.save()
    return ''
