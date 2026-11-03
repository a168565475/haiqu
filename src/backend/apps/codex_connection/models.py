from django.db import models
from django.db.models import Q

from apps.core.models import TimeStampedModel


class ConnectionStatus(models.TextChoices):
    DISCONNECTED = 'DISCONNECTED', '未连接'
    CONNECTED = 'CONNECTED', '已连接未测试'
    READY = 'READY', '可用'
    LOGIN_PENDING = 'LOGIN_PENDING', '等待授权'
    DRAINING = 'DRAINING', '等待当前操作结束'
    ERROR = 'ERROR', '失败'
    UNKNOWN = 'UNKNOWN', '待核实'


class CodexConnection(TimeStampedModel):
    singleton = models.PositiveSmallIntegerField(default=1, unique=True)
    config_generation = models.PositiveBigIntegerField(default=1)
    status = models.CharField(max_length=20, choices=ConnectionStatus.choices, default=ConnectionStatus.DISCONNECTED)
    selected_model = models.CharField(max_length=200, blank=True)
    cli_version = models.CharField(max_length=64, blank=True)
    account = models.JSONField(null=True, blank=True, default=None)
    available_models = models.JSONField(default=list)
    rate_limits = models.JSONField(null=True, blank=True, default=None)
    limits_updated_at = models.DateTimeField(null=True, blank=True)
    last_checked_at = models.DateTimeField(null=True, blank=True)
    last_test_at = models.DateTimeField(null=True, blank=True)
    error_code = models.CharField(max_length=64, blank=True)
    paused = models.BooleanField(default=True)

    class Meta:
        db_table = 'codex_connection'
        default_permissions = ()
        constraints = [
            models.CheckConstraint(condition=Q(singleton=1), name='codex_connection_singleton'),
            models.CheckConstraint(condition=Q(config_generation__gte=1), name='codex_generation_positive'),
            models.CheckConstraint(condition=Q(status__in=ConnectionStatus.values), name='codex_connection_status_valid'),
        ]


class OperationState(models.TextChoices):
    QUEUED = 'QUEUED', '待执行'
    RUNNING = 'RUNNING', '执行中'
    CANCELING = 'CANCELING', '正在取消'
    SUCCEEDED = 'SUCCEEDED', '已完成'
    FAILED = 'FAILED', '失败'
    CANCELED = 'CANCELED', '已取消'
    INTERRUPTED = 'INTERRUPTED', '中断待核实'


ACTIVE_STATES = (OperationState.QUEUED, OperationState.RUNNING, OperationState.CANCELING)
RUNNING_STATES = (OperationState.RUNNING, OperationState.CANCELING)


class CodexOperation(TimeStampedModel):
    connection = models.ForeignKey(CodexConnection, on_delete=models.PROTECT, related_name='operations')
    actor = models.ForeignKey('organizations.Employee', on_delete=models.PROTECT, related_name='codex_operations')
    action = models.CharField(max_length=12, choices=[(value, value) for value in ('login', 'switch', 'disconnect', 'refresh', 'test', 'discover', 'extract')])
    state = models.CharField(max_length=16, choices=OperationState.choices, default=OperationState.QUEUED)
    generation = models.PositiveBigIntegerField(default=1)
    model = models.CharField(max_length=200, blank=True)
    attempt_no = models.PositiveIntegerField(default=0)
    lease_id = models.UUIDField(null=True, blank=True)
    lease_expires_at = models.DateTimeField(null=True, blank=True)
    runtime_boot_id = models.UUIDField(null=True, blank=True)
    cancel_sent = models.BooleanField(default=False)
    error_code = models.CharField(max_length=64, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    request_id = models.UUIDField(null=True, blank=True)

    class Meta:
        db_table = 'codex_operation'
        default_permissions = ()
        ordering = ['created_at', 'id']
        constraints = [
            models.UniqueConstraint(fields=['connection'], condition=Q(state__in=RUNNING_STATES), name='codex_one_running_operation'),
            models.UniqueConstraint(fields=['connection'], condition=Q(state=OperationState.QUEUED), name='codex_one_queued_operation'),
            models.CheckConstraint(condition=Q(state__in=OperationState.values), name='codex_operation_state_valid'),
            models.CheckConstraint(condition=Q(action__in=('login', 'switch', 'disconnect', 'refresh', 'test', 'discover', 'extract')), name='codex_operation_action_valid'),
            models.CheckConstraint(condition=Q(generation__gte=1), name='codex_operation_generation_positive'),
        ]
