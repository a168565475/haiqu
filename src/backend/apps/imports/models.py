from django.db import models
from django.db.models import F, Q

from apps.core.models import TimeStampedModel, uppercase_code_validator


class ImportBatchStatus(models.TextChoices):
    PENDING = "PENDING", "待处理"
    PROCESSING = "PROCESSING", "处理中"
    COMPLETED = "COMPLETED", "已完成"
    PARTIAL_FAILED = "PARTIAL_FAILED", "部分失败"
    FAILED = "FAILED", "失败"
    CANCELLED = "CANCELLED", "已取消"


class ImportBatch(TimeStampedModel):
    source_file = models.ForeignKey(
        "files.BusinessFile",
        on_delete=models.PROTECT,
        related_name="import_batches",
    )
    created_by_employee = models.ForeignKey(
        "organizations.Employee",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="created_import_batches",
    )
    import_type = models.CharField(max_length=80, validators=[uppercase_code_validator])
    status = models.CharField(
        max_length=30,
        choices=ImportBatchStatus.choices,
        default=ImportBatchStatus.PENDING,
    )
    total_count = models.PositiveIntegerField(default=0)
    success_count = models.PositiveIntegerField(default=0)
    failure_count = models.PositiveIntegerField(default=0)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    config_data = models.JSONField(default=dict, blank=True)
    error_summary = models.TextField(blank=True)

    class Meta:
        db_table = "import_batch"
        constraints = [
            models.CheckConstraint(condition=Q(status__in=ImportBatchStatus.values), name="import_batch_status_valid"),
            models.CheckConstraint(
                condition=Q(total_count__gte=F("success_count") + F("failure_count")),
                name="import_batch_counts_within_total",
            ),
            models.CheckConstraint(
                condition=Q(finished_at__isnull=True)
                | Q(started_at__isnull=True)
                | Q(finished_at__gte=F("started_at")),
                name="import_batch_valid_times",
            ),
        ]
        indexes = [models.Index(fields=["status", "-created_at", "-id"], name="import_batch_status_idx")]


class ImportRecordStatus(models.TextChoices):
    PENDING = "PENDING", "待处理"
    SUCCEEDED = "SUCCEEDED", "成功"
    FAILED = "FAILED", "失败"
    SKIPPED = "SKIPPED", "已跳过"


class ImportRecord(TimeStampedModel):
    import_batch = models.ForeignKey(ImportBatch, on_delete=models.PROTECT, related_name="records")
    row_number = models.PositiveIntegerField()
    status = models.CharField(
        max_length=20,
        choices=ImportRecordStatus.choices,
        default=ImportRecordStatus.PENDING,
    )
    raw_data = models.JSONField(default=dict)
    warning_messages = models.JSONField(default=list, blank=True)
    error_message = models.TextField(blank=True)
    target_type = models.CharField(max_length=80, blank=True, validators=[uppercase_code_validator])
    target_id = models.UUIDField(null=True, blank=True)

    class Meta:
        db_table = "import_record"
        constraints = [
            models.CheckConstraint(condition=Q(status__in=ImportRecordStatus.values), name="import_record_status_valid"),
            models.UniqueConstraint(fields=["import_batch", "row_number"], name="import_record_row_uniq"),
            models.CheckConstraint(
                condition=Q(target_type="", target_id__isnull=True)
                | (~Q(target_type="") & Q(target_id__isnull=False)),
                name="import_record_target_pair_consistent",
            ),
        ]
        indexes = [
            models.Index(fields=["import_batch", "status", "row_number"], name="import_record_batch_status_idx"),
            models.Index(
                fields=["target_type", "target_id"],
                condition=~Q(target_type="") & Q(target_id__isnull=False),
                name="import_record_target_idx",
            ),
        ]
