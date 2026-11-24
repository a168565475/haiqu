from django.conf import settings
from django.db import models
from django.db.models import Q

from apps.core.models import TimeStampedModel


class BomNestingJob(TimeStampedModel):
    class Status(models.TextChoices):
        QUEUED = "QUEUED", "等待处理"
        RUNNING = "RUNNING", "处理中"
        NEEDS_PARAMETERS = "NEEDS_PARAMETERS", "待确认裁片和参数"
        SUCCEEDED = "SUCCEEDED", "排料完成"
        FAILED = "FAILED", "处理失败"
        CANCELED = "CANCELED", "已取消"

    class Phase(models.TextChoices):
        EXTRACT = "EXTRACT", "提取轮廓"
        NEST = "NEST", "排料"
        CODEX = "CODEX", "Codex 优化建议"
        REFINE = "REFINE", "验证优化排料"

    bom = models.ForeignKey("boms.Bom", on_delete=models.PROTECT, related_name="nesting_jobs")
    owner_user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="bom_nesting_jobs")
    requested_by_user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="requested_bom_nesting_jobs")
    # 记录原目标身份；不能因排料历史而阻断既有 BOM 删行。
    line_id = models.UUIDField(null=True, blank=True)
    draft_key = models.UUIDField(null=True, blank=True)
    target_snapshot = models.JSONField(default=dict)
    original_name = models.CharField(max_length=255)
    size_bytes = models.PositiveIntegerField()
    sha256 = models.CharField(max_length=64)
    scan_status = models.CharField(max_length=20)
    source_unit = models.CharField(max_length=10, default="auto")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.QUEUED)
    phase = models.CharField(max_length=10, choices=Phase.choices, default=Phase.EXTRACT)
    analysis = models.JSONField(default=dict)
    analysis_digest = models.CharField(max_length=64, blank=True)
    execution = models.JSONField(default=dict)
    artifacts = models.JSONField(default=list)
    parameters = models.JSONField(default=dict)
    result = models.JSONField(default=dict)
    optimization = models.JSONField(default=dict)
    operation = models.OneToOneField("codex_connection.CodexOperation", null=True, blank=True,
                                    on_delete=models.PROTECT, related_name="nesting_job")
    attempt_no = models.PositiveIntegerField(default=1)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    error_code = models.CharField(max_length=50, blank=True)
    error_message = models.CharField(max_length=300, blank=True)

    class Meta:
        db_table = "bom_nesting_job"
        ordering = ["-created_at", "-id"]
        constraints = [
            models.CheckConstraint(condition=(Q(line_id__isnull=False, draft_key__isnull=True)
                | Q(line_id__isnull=True, draft_key__isnull=False)), name="bom_nesting_target_exclusive"),
            models.CheckConstraint(condition=Q(status__in=["QUEUED", "RUNNING", "NEEDS_PARAMETERS", "SUCCEEDED", "FAILED", "CANCELED"]), name="bom_nesting_status_valid"),
            models.CheckConstraint(condition=Q(phase__in=["EXTRACT", "NEST", "CODEX", "REFINE"]), name="bom_nesting_phase_valid"),
            models.CheckConstraint(condition=Q(size_bytes__gt=0, size_bytes__lte=5 * 1024 * 1024), name="bom_nesting_file_size_valid"),
        ]
        indexes = [
            models.Index(fields=["status", "created_at"], name="bom_nesting_queue_idx"),
            models.Index(fields=["bom", "line_id", "-created_at"], name="bom_nesting_line_idx"),
            models.Index(fields=["bom", "owner_user", "draft_key"], name="bom_nesting_draft_idx"),
        ]
