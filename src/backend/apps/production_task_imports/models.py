from django.db import models
from django.db.models import Q

from apps.core.models import TimeStampedModel


class ImportState(models.TextChoices):
    CHECKING = 'CHECKING', '待检查'
    SCANNING = 'SCANNING', '安全检查中'
    QUEUED = 'QUEUED', '等待解析'
    PARSING = 'PARSING', '解析中'
    NEEDS_SELECTION = 'NEEDS_SELECTION', '请选择任务和版本'
    REVIEW = 'REVIEW', '待核对'
    FAILED = 'FAILED', '失败'
    CANCELED = 'CANCELED', '已取消'
    SAVED = 'SAVED', '已保存'
    EXPIRED = 'EXPIRED', '资料已过期'


class ProductionTaskImport(TimeStampedModel):
    owner = models.ForeignKey('organizations.Employee', on_delete=models.PROTECT, related_name='production_task_imports')
    client_request_id = models.UUIDField()
    original_name = models.CharField(max_length=255)
    sha256 = models.CharField(max_length=64)
    size_bytes = models.PositiveIntegerField()
    state = models.CharField(max_length=24, choices=ImportState.choices, default=ImportState.CHECKING)
    phase = models.CharField(max_length=16, default='discovery')
    scan_status = models.CharField(max_length=16, default='PENDING')
    expires_at = models.DateTimeField()
    processing_started_at = models.DateTimeField(null=True)
    attempt_no = models.PositiveIntegerField(default=1)
    result_revision = models.PositiveIntegerField(default=0)
    operation = models.OneToOneField('codex_connection.CodexOperation', null=True, blank=True,
                                    on_delete=models.SET_NULL, related_name='production_import')
    manifest = models.JSONField(default=dict)
    discovery = models.JSONField(default=dict)
    candidates = models.JSONField(default=list)
    selected_candidate = models.JSONField(default=dict)
    object_key = models.CharField(max_length=64, blank=True)
    extraction = models.JSONField(default=dict)
    matching = models.JSONField(default=dict)
    review = models.JSONField(default=dict)
    error_code = models.CharField(max_length=64, blank=True)
    saved_task = models.ForeignKey('production_tasks.ProductionTask', null=True, blank=True,
                                  on_delete=models.SET_NULL, related_name='ai_imports')
    saved_task_id_snapshot = models.UUIDField(null=True, blank=True)
    saved_task_number = models.CharField(max_length=50, blank=True)
    saved_at = models.DateTimeField(null=True, blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'production_task_import'
        default_permissions = ()
        permissions = [('import_production_task', '导入生产任务单')]
        constraints = [
            models.UniqueConstraint(fields=['owner', 'client_request_id'], name='prod_import_request_unique'),
            models.UniqueConstraint(fields=['owner', 'sha256', 'object_key'],
                                    condition=~Q(object_key=''), name='prod_import_object_unique'),
            models.CheckConstraint(condition=Q(state__in=ImportState.values), name='prod_import_state_valid'),
            models.CheckConstraint(condition=Q(phase__in=['discovery', 'extraction']), name='prod_import_phase_valid'),
            models.CheckConstraint(condition=Q(attempt_no__gte=1), name='prod_import_attempt_positive'),
        ]
        indexes = [models.Index(fields=['state', 'created_at'], name='prod_import_queue_idx'),
                   models.Index(fields=['expires_at'], name='prod_import_expiry_idx')]
