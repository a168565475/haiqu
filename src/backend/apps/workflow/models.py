from django.db import models
from django.db.models import F, Q

from apps.core.models import ArchivableModel, TimeStampedModel, uppercase_code_condition, uppercase_code_validator


class TaskStatus(models.TextChoices):
    PENDING = "PENDING", "待处理"
    IN_PROGRESS = "IN_PROGRESS", "处理中"
    COMPLETED = "COMPLETED", "已完成"
    CANCELLED = "CANCELLED", "已取消"


class TaskPriority(models.TextChoices):
    LOW = "LOW", "低"
    NORMAL = "NORMAL", "普通"
    HIGH = "HIGH", "高"
    URGENT = "URGENT", "紧急"


class BusinessTask(ArchivableModel):
    assignee_employee = models.ForeignKey(
        "organizations.Employee",
        on_delete=models.PROTECT,
        related_name="assigned_tasks",
    )
    created_by_employee = models.ForeignKey(
        "organizations.Employee",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="created_tasks",
    )
    title = models.CharField(max_length=250)
    description = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=TaskStatus.choices, default=TaskStatus.PENDING)
    priority = models.CharField(max_length=20, choices=TaskPriority.choices, default=TaskPriority.NORMAL)
    due_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    automation_key = models.CharField(max_length=200, null=True, blank=True, unique=True)

    class Meta:
        db_table = "business_task"
        constraints = [
            models.CheckConstraint(condition=Q(status__in=TaskStatus.values), name="task_status_valid"),
            models.CheckConstraint(condition=Q(priority__in=TaskPriority.values), name="task_priority_valid"),
            models.CheckConstraint(
                condition=Q(status=TaskStatus.COMPLETED, completed_at__isnull=False)
                | ~Q(status=TaskStatus.COMPLETED),
                name="task_completed_has_time",
            ),
        ]
        indexes = [
            models.Index(
                fields=["assignee_employee", "due_at", "id"],
                condition=Q(
                    archived_at__isnull=True,
                    status__in=[TaskStatus.PENDING, TaskStatus.IN_PROGRESS],
                ),
                name="task_assignee_open_due_idx",
            ),
            models.Index(
                fields=["status", "due_at", "id"],
                condition=Q(
                    archived_at__isnull=True,
                    status__in=[TaskStatus.PENDING, TaskStatus.IN_PROGRESS],
                ),
                name="task_open_due_idx",
            ),
        ]


class SlaPolicy(ArchivableModel):
    policy_code = models.CharField(max_length=50, unique=True, validators=[uppercase_code_validator])
    display_name = models.CharField(max_length=150)
    target_type = models.CharField(max_length=50, validators=[uppercase_code_validator])
    response_minutes = models.PositiveIntegerField(null=True, blank=True)
    resolution_minutes = models.PositiveIntegerField(null=True, blank=True)
    is_enabled = models.BooleanField(default=False)
    config_data = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "sla_policy"
        permissions = [
            ("manage_sla_policy", "可管理 SLA 策略"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=uppercase_code_condition("policy_code"),
                name="sla_policy_code_uppercase",
            ),
        ]


class SlaTrackingStatus(models.TextChoices):
    RUNNING = "RUNNING", "运行中"
    MET = "MET", "已达成"
    BREACHED = "BREACHED", "已超时"
    CANCELLED = "CANCELLED", "已取消"


class SlaTracking(TimeStampedModel):
    sla_policy = models.ForeignKey(SlaPolicy, on_delete=models.PROTECT, related_name="tracking_records")
    status = models.CharField(
        max_length=20,
        choices=SlaTrackingStatus.choices,
        default=SlaTrackingStatus.RUNNING,
    )
    started_at = models.DateTimeField()
    next_deadline_at = models.DateTimeField(null=True, blank=True)
    breached_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    tracking_data = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "sla_tracking"
        constraints = [
            models.CheckConstraint(condition=Q(status__in=SlaTrackingStatus.values), name="sla_tracking_status_valid"),
            models.CheckConstraint(
                condition=Q(next_deadline_at__isnull=True) | Q(next_deadline_at__gte=F("started_at")),
                name="sla_deadline_after_start",
            ),
        ]
        indexes = [
            models.Index(
                fields=["status", "next_deadline_at", "id"],
                condition=Q(status=SlaTrackingStatus.RUNNING),
                name="sla_running_deadline_idx",
            ),
        ]


class ApprovalStatus(models.TextChoices):
    PENDING = "PENDING", "待审批"
    APPROVED = "APPROVED", "已通过"
    REJECTED = "REJECTED", "已拒绝"
    CANCELLED = "CANCELLED", "已取消"


class ApprovalRequest(TimeStampedModel):
    current_approver_employee = models.ForeignKey(
        "organizations.Employee",
        on_delete=models.PROTECT,
        related_name="approval_inbox",
    )
    requested_by_employee = models.ForeignKey(
        "organizations.Employee",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="approval_requests_created",
    )
    approval_type = models.CharField(max_length=50, validators=[uppercase_code_validator])
    status = models.CharField(max_length=20, choices=ApprovalStatus.choices, default=ApprovalStatus.PENDING)
    request_reason = models.TextField(blank=True)
    decision_note = models.TextField(blank=True)
    submitted_at = models.DateTimeField()
    decided_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "approval_request"
        constraints = [
            models.CheckConstraint(condition=Q(status__in=ApprovalStatus.values), name="approval_status_valid"),
            models.CheckConstraint(
                condition=Q(status=ApprovalStatus.PENDING, decided_at__isnull=True)
                | Q(status__in=[ApprovalStatus.APPROVED, ApprovalStatus.REJECTED], decided_at__isnull=False)
                | Q(status=ApprovalStatus.CANCELLED),
                name="approval_decision_time_consistent",
            ),
        ]
        indexes = [
            models.Index(
                fields=["current_approver_employee", "submitted_at", "id"],
                condition=Q(status=ApprovalStatus.PENDING),
                name="approval_pending_inbox_idx",
            ),
        ]


class AutomationStatus(models.TextChoices):
    PENDING = "PENDING", "待执行"
    RUNNING = "RUNNING", "执行中"
    SUCCEEDED = "SUCCEEDED", "成功"
    RETRY = "RETRY", "等待重试"
    FAILED = "FAILED", "失败"


class AutomationExecution(TimeStampedModel):
    automation_code = models.CharField(max_length=80, validators=[uppercase_code_validator])
    idempotency_key = models.CharField(max_length=200, unique=True)
    status = models.CharField(max_length=20, choices=AutomationStatus.choices, default=AutomationStatus.PENDING)
    attempt_count = models.PositiveIntegerField(default=0)
    next_retry_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True)
    input_data = models.JSONField(default=dict, blank=True)
    result_data = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "automation_execution"
        constraints = [
            models.CheckConstraint(condition=Q(status__in=AutomationStatus.values), name="automation_status_valid"),
            models.CheckConstraint(
                condition=uppercase_code_condition("automation_code"),
                name="automation_code_uppercase",
            ),
        ]
        indexes = [
            models.Index(
                fields=["status", "next_retry_at", "id"],
                condition=Q(status__in=[AutomationStatus.PENDING, AutomationStatus.RETRY]),
                name="automation_ready_retry_idx",
            ),
        ]
