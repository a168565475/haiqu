from uuid import UUID

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.views.decorators.debug import sensitive_variables
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.access_control.management_permissions import can_manage
from apps.access_control.permissions import AccessManagementUnavailable
from apps.core.api.concurrency import PreconditionFailed, PreconditionRequired
from apps.core.api.exceptions import Conflict
from apps.core.audit import write_audit_log
from apps.core.auth import active_employee_for
from .models import ACTIVE_STATES, RUNNING_STATES, CodexConnection, CodexOperation
from .runtime_client import RuntimeClient, RuntimeFailure
from .selectors import connection_etag


PERMISSION = 'access_control.manage_codex_connection'


def require_actor(request):
    # 不能沿用跨外部调用前缓存的员工/角色状态。
    user = get_user_model().objects.filter(pk=request.user.pk).first()
    actor = active_employee_for(user)
    if actor is None or not can_manage(user, PERMISSION):
        raise PermissionDenied('需要 Codex 连接管理权限。')
    if not settings.ACCESS_MANAGEMENT_ENABLED:
        raise AccessManagementUnavailable()
    return actor


def require_etag(request, connection):
    expected = request.headers.get('If-Match')
    if not expected:
        raise PreconditionRequired()
    if expected != connection_etag(connection):
        raise PreconditionFailed()


def locked_connection(request):
    connection = CodexConnection.objects.select_for_update().first()
    if connection is None:
        require_etag(request, CodexConnection())
        connection, created = CodexConnection.objects.get_or_create(singleton=1)
        connection = CodexConnection.objects.select_for_update().get(pk=connection.pk)
        if not created:
            require_etag(request, connection)
    else:
        require_etag(request, connection)
    return connection


def audit_operation(connection, operation, event, *, request=None):
    # 只保留动作与结果；设备码、授权URL、账号内容、原始 RPC 均不在白名单。
    return write_audit_log(object_type='CODEX_CONNECTION', object_id=connection.id,
        action=event, actor_employee=operation.actor, request=request,
        after_data={'operation_id': str(operation.id), 'action': operation.action,
                    'state': operation.state, 'generation': operation.generation,
                    'attempt_no': operation.attempt_no, 'error_code': operation.error_code})


def request_id(request):
    try:
        return UUID(str(request.request_id))
    except (AttributeError, ValueError, TypeError):
        return None


@transaction.atomic
def enqueue(request, action):
    actor = require_actor(request)
    connection = locked_connection(request)
    active = list(connection.operations.filter(state__in=ACTIVE_STATES))
    if connection.status == 'UNKNOWN' and not active and action not in ('refresh', 'disconnect'):
        raise Conflict('上次运行结果尚未核实，请先刷新连接状态。')
    if active:
        draining = (len(active) == 1 and active[0].state == 'RUNNING' and active[0].action in ('test', 'discover', 'extract')
                    and action in ('switch', 'disconnect'))
        if not draining:
            raise Conflict('已有操作正在处理，请等待结束或取消当前授权。')
        connection.status = 'DRAINING'
    elif action == 'login':
        if connection.account is not None:
            raise Conflict('已有连接，请使用更换账号。')
        connection.status = 'LOGIN_PENDING'
    elif action == 'switch':
        connection.status = 'LOGIN_PENDING'
    elif action == 'disconnect':
        connection.status = 'DRAINING'
    if action == 'test':
        if connection.account is None:
            raise Conflict('请先完成账号授权。')
        if not connection.selected_model or connection.selected_model not in {item['id'] for item in connection.available_models}:
            raise ValidationError({'model': '请从已读取的可用模型中选择一个模型。'})
    operation = CodexOperation.objects.create(connection=connection, actor=actor, action=action,
        generation=connection.config_generation, model=connection.selected_model, request_id=request_id(request))
    connection.paused = True
    connection.error_code = ''
    connection.save(update_fields=['status', 'paused', 'error_code', 'updated_at'])
    audit_operation(connection, operation, 'CODEX_OPERATION_QUEUED', request=request)
    return connection


@transaction.atomic
def cancel_login(request, operation_id):
    actor = require_actor(request)
    connection = locked_connection(request)
    operation = connection.operations.filter(id=operation_id, state__in=ACTIVE_STATES, action__in=('login', 'switch')).first()
    if operation is None:
        raise Conflict('该登录操作已结束或不是当前登录。')
    if operation.actor_id != actor.id:
        raise PermissionDenied('仅发起管理员可以取消本次授权。')
    if operation.state != 'CANCELING':
        behind_test = operation.state == 'QUEUED' and connection.operations.filter(state__in=RUNNING_STATES).exists()
        operation.state = 'CANCELED' if behind_test else 'CANCELING'
        if behind_test:
            operation.completed_at = timezone.now()
            connection.status = 'CONNECTED' if connection.account else 'DISCONNECTED'
        operation.save(update_fields=['state', 'completed_at', 'updated_at'])
        connection.paused = True
        connection.save(update_fields=['status', 'paused', 'updated_at'])
        audit_operation(connection, operation, 'CODEX_CANCEL_REQUESTED', request=request)
    return connection


@transaction.atomic
def select_model(request, model):
    actor = require_actor(request)
    connection = locked_connection(request)
    if connection.operations.filter(state__in=ACTIVE_STATES).exists():
        raise Conflict('操作正在处理中，暂不能切换模型。')
    if model not in {item['id'] for item in connection.available_models}:
        raise ValidationError({'model': '模型不在最近一次读取的可用列表中，请刷新后选择。'})
    if model == connection.selected_model:
        return connection
    connection.selected_model = model
    connection.config_generation += 1
    connection.status = 'CONNECTED' if connection.account else 'DISCONNECTED'
    connection.paused = True
    connection.error_code = ''
    connection.save(update_fields=['selected_model', 'config_generation', 'status', 'paused', 'error_code', 'updated_at'])
    write_audit_log(object_type='CODEX_CONNECTION', object_id=connection.id, action='CODEX_MODEL_SELECTED',
        actor_employee=actor, request=request,
        after_data={'model': model, 'generation': connection.config_generation})
    return connection


@sensitive_variables()
def login_challenge(request, operation_id):
    actor = require_actor(request)
    operation = CodexOperation.objects.filter(id=operation_id, state__in=ACTIVE_STATES, action__in=('login', 'switch')).first()
    if operation is None:
        raise Conflict('该登录操作已结束或不是当前登录。')
    if operation.actor_id != actor.id:
        raise PermissionDenied('仅发起管理员可以查看本次授权码。')
    if operation.state != 'RUNNING' or operation.runtime_boot_id is None:
        raise Conflict('授权码尚未就绪或正在取消。')
    challenge = RuntimeClient().call('challenge', {'operation_id': str(operation.id), 'generation': operation.generation})
    # 外部读取期间可能已取消/换号或撤权，不能把迟到验证码重新显示出来。
    require_actor(request)
    if not CodexOperation.objects.filter(id=operation.id, state='RUNNING', generation=operation.generation,
            connection__config_generation=operation.generation, runtime_boot_id=operation.runtime_boot_id).exists():
        raise Conflict('该登录操作已变更，请刷新。')
    if parse_datetime(challenge['expires_at']) <= timezone.now():
        raise RuntimeFailure('NOT_READY')
    return challenge
