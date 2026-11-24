from django.db import models

from apps.core.models import TimeStampedModel


class AiImportState(models.TextChoices):
    REVIEW = "REVIEW", "待核对"
    FAILED = "FAILED", "失败"
    TASK_DRAFT = "TASK_DRAFT", "任务草稿已创建"
    BOM_PENDING = "BOM_PENDING", "BOM待确认"


class AiProductionImport(TimeStampedModel):
    owner = models.ForeignKey(
        "organizations.Employee",
        on_delete=models.PROTECT,
        related_name="ai_production_imports",
    )
    client_request_id = models.UUIDField()
    original_name = models.CharField(max_length=255)
    sha256 = models.CharField(max_length=64)
    size_bytes = models.PositiveIntegerField()
    state = models.CharField(max_length=20, choices=AiImportState.choices, default=AiImportState.REVIEW)
    model = models.CharField(max_length=100, blank=True)
    source = models.JSONField(default=dict)
    result = models.JSONField(default=dict)
    issues = models.JSONField(default=list)
    error_code = models.CharField(max_length=64, blank=True)
    task_id = models.UUIDField(null=True, blank=True)
    task_number = models.CharField(max_length=50, blank=True)
    bom_id = models.UUIDField(null=True, blank=True)
    bom_ids = models.JSONField(default=list)
    created_by_employee_id = models.UUIDField(null=True, blank=True)

    class Meta:
        db_table = "ai_production_import"
        default_permissions = ()
        constraints = [
            models.UniqueConstraint(fields=["owner", "client_request_id"], name="ai_import_request_unique"),
        ]
        indexes = [models.Index(fields=["owner", "-created_at"], name="ai_import_owner_created_idx")]

