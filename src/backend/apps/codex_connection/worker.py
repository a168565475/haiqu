"""每次只执行一次短 RPC；等待授权时仍能处理取消，不在事务内等待上游。"""
from datetime import timedelta
from uuid import UUID, uuid4

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from apps.access_control.management_permissions import can_manage
from .models import RUNNING_STATES, CodexConnection, CodexOperation
from .runtime_client import RuntimeClient, RuntimeFailure, clean_snapshot
from .services import PERMISSION, audit_operation


LEASE_SECONDS = 30
FILE_TRANSFER_LEASE_SECONDS = 90
NEST_TASK_ERRORS = frozenset({
    'UNSUPPORTED_CAPABILITY', 'CODEX_INVALID_PROPOSAL', 'DXF_INVALID', 'DXF_BINARY', 'DXF_TOO_LARGE',
    'DXF_UNIT_UNKNOWN', 'DXF_UNSUPPORTED', 'DXF_COMPLEXITY', 'DXF_OPEN_CONTOUR', 'DXF_INVALID_CONTOUR',
    'DXF_AMBIGUOUS_CONTOUR', 'DXF_NO_PIECES', 'NEST_PARAMETERS', 'NEST_TOO_MANY_PIECES', 'NEST_TOO_WIDE',
    'NEST_TIMEOUT', 'NEST_VALIDATION', 'SOURCE_CHANGED', 'SOURCE_MISSING', 'RESULT_LIMIT', 'TOOL_SEQUENCE', 'TOOL_LIMIT',
    'PERMISSION_REVOKED', 'STORAGE_UNAVAILABLE',
})


def _matches(connection, operation, attempt_no, lease_id):
    return (operation.state in RUNNING_STATES and operation.attempt_no == attempt_no
            and operation.lease_id == lease_id and connection.config_generation == operation.generation)


def _save_snapshot(connection, snapshot, *, checked=False):
    changed = (connection.account != snapshot['account'] or connection.cli_version != snapshot['cli_version'])
    connection.cli_version = snapshot['cli_version']
    connection.account = snapshot['account']
    connection.available_models = snapshot['models']
    connection.rate_limits = snapshot['rate_limits']
    connection.limits_updated_at = parse_datetime(snapshot['limits_updated_at']) if snapshot['limits_updated_at'] else None
    if checked:
        connection.last_checked_at = timezone.now()
    if connection.status == 'READY' and (changed or connection.selected_model not in {item['id'] for item in snapshot['models']}):
        connection.status = 'CONNECTED' if connection.account else 'DISCONNECTED'


def _finish(connection, operation, state, code=''):
    operation.state = state
    operation.error_code = code
    operation.completed_at = timezone.now()
    operation.lease_expires_at = None
    operation.save()
    connection.error_code = code
    queued = connection.operations.filter(state='QUEUED').first()
    if queued:
        connection.status = 'DRAINING'
        connection.paused = True
    elif state == 'INTERRUPTED':
        connection.status = 'UNKNOWN'
        connection.paused = True
    elif (state == 'FAILED' and operation.action == 'nest'
            and code in NEST_TASK_ERRORS
            and connection.status == 'READY' and connection.account):
        # 源文件、几何或工具顺序错误只失败本任务，不阻断其他排料任务。
        connection.error_code = ''
        connection.paused = False
    elif state == 'FAILED':
        connection.status = 'ERROR'
        connection.paused = True
    elif state == 'SUCCEEDED' and operation.action == 'test' and connection.account:
        connection.status = 'READY'
        connection.last_test_at = timezone.now()
        connection.paused = False
    elif state in ('SUCCEEDED', 'CANCELED') and operation.action == 'nest' and connection.account:
        connection.status = 'READY'
        connection.paused = False
    elif state == 'SUCCEEDED' and operation.action == 'refresh' and connection.status == 'READY' and connection.account:
        connection.paused = False
    else:
        connection.status = 'CONNECTED' if connection.account else 'DISCONNECTED'
        connection.paused = True
    connection.save()
    audit_operation(connection, operation, 'CODEX_OPERATION_FINISHED')


@transaction.atomic
def claim_tick(owner_id):
    connection = CodexConnection.objects.select_for_update().first()
    if connection is None:
        return None
    operations = connection.operations.exclude(action__in=('discover', 'extract'))
    operation = operations.filter(state__in=RUNNING_STATES).first()
    now = timezone.now()
    if operation:
        if operation.lease_id != owner_id and operation.lease_expires_at and operation.lease_expires_at > now:
            return None
        if operation.lease_id != owner_id:
            operation.attempt_no += 1
        operation.lease_id = owner_id
        operation.lease_expires_at = now + timedelta(seconds=LEASE_SECONDS)
        operation.save(update_fields=['attempt_no', 'lease_id', 'lease_expires_at', 'updated_at'])
        return operation, False
    operation = operations.filter(state='QUEUED').select_related('actor__user').first()
    if operation is None:
        return None
    # 入队后撤权不能继续开始外部操作。
    if operation.action == 'nest':
        from apps.boms.nesting_codex import operation_allowed
        allowed = operation_allowed(operation)
    else:
        allowed = (settings.ACCESS_MANAGEMENT_ENABLED and operation.actor.user_id
                   and can_manage(operation.actor.user, PERMISSION))
    if not allowed:
        if operation.action == 'nest':
            from apps.boms.nesting_codex import finish_codex_operation
            finish_codex_operation(operation, None, 'PERMISSION_REVOKED')
        _finish(connection, operation, 'FAILED', 'PERMISSION_REVOKED')
        return None
    if operation.action in ('login', 'switch', 'disconnect'):
        connection.config_generation += 1
    operation.generation = connection.config_generation
    operation.attempt_no += 1
    operation.lease_id = owner_id
    operation.lease_expires_at = now + timedelta(seconds=LEASE_SECONDS)
    operation.state = 'RUNNING'
    operation.save()
    if operation.action in ('login', 'switch'):
        connection.status = 'LOGIN_PENDING'
    elif operation.action == 'disconnect':
        connection.status = 'DRAINING'
    connection.save(update_fields=['config_generation', 'status', 'updated_at'])
    return operation, True


@transaction.atomic
def bind_boot(operation_id, attempt_no, lease_id, boot_id):
    connection = CodexConnection.objects.select_for_update().get(singleton=1)
    operation = connection.operations.get(id=operation_id)
    if not _matches(connection, operation, attempt_no, lease_id):
        return False
    operation.runtime_boot_id = UUID(boot_id)
    fields = ['runtime_boot_id', 'updated_at']
    if operation.action == 'nest':
        operation.lease_expires_at = timezone.now() + timedelta(seconds=FILE_TRANSFER_LEASE_SECONDS)
        fields.append('lease_expires_at')
    operation.save(update_fields=fields)
    return True


@transaction.atomic
def reserve_artifact_transfer(operation):
    connection = CodexConnection.objects.select_for_update().get(singleton=1)
    current = connection.operations.get(pk=operation.pk)
    if not _matches(connection, current, operation.attempt_no, operation.lease_id):
        return False
    current.lease_expires_at = timezone.now() + timedelta(seconds=FILE_TRANSFER_LEASE_SECONDS)
    current.save(update_fields=['lease_expires_at', 'updated_at'])
    return True


@transaction.atomic
def apply_result(operation_id, attempt_no, lease_id, snapshot, parsing_result=None):
    snapshot = clean_snapshot(snapshot)
    connection = CodexConnection.objects.select_for_update().get(singleton=1)
    operation = connection.operations.get(id=operation_id)
    if not _matches(connection, operation, attempt_no, lease_id):
        return False
    result = snapshot['operation']
    if (result is None or result['id'] != str(operation.id) or result['generation'] != operation.generation
            or result['action'] != operation.action or str(operation.runtime_boot_id) != snapshot['boot_id']):
        return False
    before = (connection.cli_version, connection.account, connection.available_models, connection.rate_limits,
              connection.limits_updated_at, connection.error_code, connection.status, connection.paused)
    _save_snapshot(connection, snapshot, checked=result['state'] != 'RUNNING')
    if result['state'] == 'RUNNING':
        connection.error_code = ''
        if connection.operations.filter(state='QUEUED').exists() or operation.action == 'disconnect':
            connection.status = 'DRAINING'
        elif operation.action in ('login', 'switch'):
            connection.status = 'LOGIN_PENDING'
        elif connection.status == 'UNKNOWN':
            connection.status = 'CONNECTED' if connection.account else 'DISCONNECTED'
        connection.paused = True
        after = (connection.cli_version, connection.account, connection.available_models, connection.rate_limits,
                 connection.limits_updated_at, connection.error_code, connection.status, connection.paused)
        # 纯心跳不改 ETag，否则用户每次点击都可能撞上后台轮询的版本更新。
        if before != after:
            connection.save()
    else:
        if operation.action == 'nest':
            from apps.boms.nesting_codex import finish_codex_operation
            code = finish_codex_operation(operation, parsing_result if result['state'] == 'SUCCEEDED' else None,
                result['error_code'] or ('' if result['state'] == 'SUCCEEDED' else 'INTERRUPTED'))
            if code:
                _finish(connection, operation, 'FAILED', code)
                return True
        if operation.action == 'test':
            connection.last_test_at = timezone.now()
        if result['state'] == 'SUCCEEDED' and operation.action == 'test' and not connection.account:
            _finish(connection, operation, 'FAILED', 'AUTH_REQUIRED')
        else:
            _finish(connection, operation, result['state'], result['error_code'])
    return True


@transaction.atomic
def finish_without_result(operation_id, attempt_no, lease_id, state, code=''):
    connection = CodexConnection.objects.select_for_update().get(singleton=1)
    operation = connection.operations.get(id=operation_id)
    if not _matches(connection, operation, attempt_no, lease_id):
        return False
    if operation.action == 'nest':
        from apps.boms.nesting_codex import finish_codex_operation
        finish_codex_operation(operation, None, code or 'INTERRUPTED')
    _finish(connection, operation, state, code)
    return True


@transaction.atomic
def mark_unknown(operation_id, attempt_no, lease_id, code):
    connection = CodexConnection.objects.select_for_update().get(singleton=1)
    operation = connection.operations.get(id=operation_id)
    if not _matches(connection, operation, attempt_no, lease_id):
        return False
    connection.status = 'UNKNOWN'
    connection.error_code = code
    connection.paused = True
    connection.save(update_fields=['status', 'error_code', 'paused', 'updated_at'])
    return True


@transaction.atomic
def mark_cancel_sent(operation_id, attempt_no, lease_id):
    connection = CodexConnection.objects.select_for_update().get(singleton=1)
    operation = connection.operations.get(id=operation_id)
    if _matches(connection, operation, attempt_no, lease_id):
        operation.cancel_sent = True
        operation.save(update_fields=['cancel_sent', 'updated_at'])


def process_tick(runtime=None, *, owner_id=None):
    from apps.boms.nesting_storage import NestingFailure
    if transaction.get_connection().in_atomic_block:
        raise RuntimeError('Codex worker cannot call runtime inside a database transaction')
    runtime = runtime or RuntimeClient()
    owner_id = owner_id or uuid4()
    claimed = claim_tick(owner_id)
    if claimed is None:
        return False
    operation, is_new = claimed
    key = (operation.id, operation.attempt_no, operation.lease_id)
    params = {'operation_id': str(operation.id), 'generation': operation.generation}
    # 排队期间取消且尚未派发的登录无需接触运行进程。
    if operation.state == 'CANCELING' and operation.runtime_boot_id is None and operation.attempt_no <= 1:
        finish_without_result(*key, 'CANCELED')
        return True
    if is_new:
        payload = {}
        if operation.action == 'nest':
            from apps.boms.nesting_codex import runtime_payload
            from apps.boms.nesting_storage import NestingFailure
            try:
                payload = {'payload': runtime_payload(operation)}
            except NestingFailure as exc:
                finish_without_result(*key, 'FAILED', exc.code)
                return True
        try:
            snapshot = runtime.call('status', {})
        except RuntimeFailure as exc:
            finish_without_result(*key, 'FAILED', exc.code)
            return True
        if operation.action == 'nest' and 'nest_tools_v1' not in snapshot.get('capabilities', []):
            finish_without_result(*key, 'FAILED', 'UNSUPPORTED_CAPABILITY')
            return True
        if not bind_boot(*key, snapshot['boot_id']):
            return True
        try:
            snapshot = runtime.call('start', {**params, 'action': operation.action, 'model': operation.model, **payload})
        except RuntimeFailure as exc:
            # 请求可能已被对端接受，保持占用，下一轮只按原ID查询，不重发 start。
            mark_unknown(*key, exc.code)
            return True
        try:
            apply_result(*key, snapshot, read_parsing_result(runtime, operation, params, snapshot))
        except NestingFailure as exc:
            finish_without_result(*key, 'FAILED', exc.code)
        except RuntimeFailure as exc:
            mark_unknown(*key, exc.code)
        return True
    try:
        result = runtime.call('operation', params)
        if str(operation.runtime_boot_id) != result['boot_id'] or result['operation'] is None:
            finish_without_result(*key, 'INTERRUPTED', 'INTERRUPTED')
            return True
        snapshot = {**result['snapshot'], 'operation': result['operation']}
        if operation.state == 'CANCELING' and not operation.cancel_sent and result['operation']['state'] == 'RUNNING':
            snapshot = runtime.call('cancel', params)
            mark_cancel_sent(*key)
        apply_result(*key, snapshot, read_parsing_result(runtime, operation, params, snapshot))
    except NestingFailure as exc:
        finish_without_result(*key, 'FAILED', exc.code)
    except RuntimeFailure as exc:
        mark_unknown(*key, exc.code)
    return True


def read_parsing_result(runtime, operation, params, snapshot):
    result = snapshot.get('operation')
    if operation.action != 'nest' or not result or result['state'] != 'SUCCEEDED':
        return None
    value = runtime.call('result', params)
    if value['boot_id'] != snapshot['boot_id']:
        raise RuntimeFailure('INTERRUPTED')
    from apps.boms.nesting_codex import prepare_codex_result
    if not reserve_artifact_transfer(operation):
        return None
    return prepare_codex_result(operation, runtime, value['result'], snapshot['boot_id'])
