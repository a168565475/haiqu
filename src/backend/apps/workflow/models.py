from django.db import connection, models
from django.db.models import F, Q
from django.utils import timezone

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


class TaskType(models.TextChoices):
    CUSTOMER_FOLLOW_UP = "CUSTOMER_FOLLOW_UP", "客户跟进"
    COMMUNICATION_FOLLOW_UP = "COMMUNICATION_FOLLOW_UP", "沟通跟进"
    INQUIRY_RESPONSE = "INQUIRY_RESPONSE", "询盘响应"
    QUOTATION_FOLLOW_UP = "QUOTATION_FOLLOW_UP", "报价跟进"
    SAMPLE_FEEDBACK = "SAMPLE_FEEDBACK", "样品反馈"
    OTHER = "OTHER", "其他"


class TaskOriginType(models.TextChoices):
    MANUAL = "MANUAL", "手工创建"
    BUSINESS_EVENT = "BUSINESS_EVENT", "业务事件"
    AUTOMATION = "AUTOMATION", "自动化"
    SLA = "SLA", "SLA"


class TaskWorkState(models.TextChoices):
    NORMAL = "NORMAL", "正常"
    WAITING_CUSTOMER = "WAITING_CUSTOMER", "待客户反馈"
    BLOCKED = "BLOCKED", "阻塞"


class BusinessTask(ArchivableModel):
    task_number = models.CharField(max_length=50, unique=True, editable=False)
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
    task_type = models.CharField(max_length=40, choices=TaskType.choices, default=TaskType.OTHER)
    origin_type = models.CharField(max_length=30, choices=TaskOriginType.choices, default=TaskOriginType.MANUAL)
    origin_code = models.CharField(max_length=100, blank=True)
    contact = models.ForeignKey(
        "customers.CustomerContact",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="business_tasks",
    )
    work_state = models.CharField(max_length=30, choices=TaskWorkState.choices, default=TaskWorkState.NORMAL)
    work_state_reason = models.CharField(max_length=500, blank=True)
    next_check_at = models.DateTimeField(null=True, blank=True)
    due_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    completion_result = models.TextField(blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancel_reason = models.CharField(max_length=500, blank=True)
    reschedule_count = models.PositiveIntegerField(default=0)
    business_version = models.PositiveIntegerField(default=1)
    automation_key = models.CharField(max_length=200, null=True, blank=True, unique=True)

    def save(self, *args, **kwargs):
        if self._state.adding and not self.task_number:
            with connection.cursor() as cursor:
                cursor.execute("SELECT nextval('workflow_task_number_seq')")
                sequence = cursor.fetchone()[0]
            self.task_number = f"TASK-{timezone.localtime().year}-{sequence:04d}"
        super().save(*args, **kwargs)

    class Meta:
        db_table = "business_task"
        permissions = [
            ("view_team_businesstask", "可查看团队任务"),
            ("view_all_businesstask", "可查看全部任务"),
            ("bulk_change_businesstask", "可批量处理任务"),
            ("reassign_businesstask", "可转交任务"),
        ]
        constraints = [
            models.CheckConstraint(condition=Q(status__in=TaskStatus.values), name="task_status_valid"),
            models.CheckConstraint(condition=Q(priority__in=TaskPriority.values), name="task_priority_valid"),
            models.CheckConstraint(
                condition=Q(status=TaskStatus.COMPLETED, completed_at__isnull=False)
                | ~Q(status=TaskStatus.COMPLETED),
                name="task_completed_has_time",
            ),
            models.CheckConstraint(condition=Q(task_type__in=TaskType.values), name="task_type_valid"),
            models.CheckConstraint(condition=Q(origin_type__in=TaskOriginType.values), name="task_origin_type_valid"),
            models.CheckConstraint(condition=Q(work_state__in=TaskWorkState.values), name="task_work_state_valid"),
            models.CheckConstraint(
                condition=Q(status=TaskStatus.CANCELLED, cancelled_at__isnull=False)
                | ~Q(status=TaskStatus.CANCELLED),
                name="task_cancelled_has_time",
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
            models.Index(fields=["task_type", "status", "due_at", "id"], name="task_type_status_due_idx"),
            models.Index(fields=["work_state", "status", "due_at", "id"], name="task_work_state_due_idx"),
        ]


class TaskReminderStatus(models.TextChoices):
    SCHEDULED = "SCHEDULED", "待执行"
    SENT = "SENT", "已发送"
    CLOSED = "CLOSED", "已关闭"
    CANCELLED = "CANCELLED", "已取消"


class TaskReminder(TimeStampedModel):
    business_task = models.ForeignKey(BusinessTask, on_delete=models.CASCADE, related_name="reminders")
    remind_at = models.DateTimeField()
    status = models.CharField(max_length=20, choices=TaskReminderStatus.choices, default=TaskReminderStatus.SCHEDULED)
    sent_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    close_reason = models.CharField(max_length=500, blank=True)

    class Meta:
        db_table = "task_reminder"
        constraints = [
            models.CheckConstraint(condition=Q(status__in=TaskReminderStatus.values), name="task_reminder_status_valid"),
            models.CheckConstraint(
                condition=Q(status=TaskReminderStatus.SENT, sent_at__isnull=False)
                | ~Q(status=TaskReminderStatus.SENT),
                name="task_reminder_sent_has_time",
            ),
        ]
        indexes = [models.Index(fields=["status", "remind_at", "id"], name="task_reminder_ready_idx")]


class TaskChecklistItem(TimeStampedModel):
    business_task = models.ForeignKey(BusinessTask, on_delete=models.CASCADE, related_name="checklist_items")
    content = models.CharField(max_length=500)
    sort_order = models.PositiveIntegerField(default=0)
    is_completed = models.BooleanField(default=False)
    completed_at = models.DateTimeField(null=True, blank=True)
    completed_by_employee = models.ForeignKey(
        "organizations.Employee", null=True, blank=True, on_delete=models.SET_NULL, related_name="completed_task_checklist_items"
    )

    class Meta:
        db_table = "task_checklist_item"
        ordering = ["sort_order", "created_at", "id"]
        constraints = [
            models.CheckConstraint(
                condition=Q(is_completed=True, completed_at__isnull=False) | Q(is_completed=False, completed_at__isnull=True),
                name="task_checklist_completed_time",
            ),
        ]
        indexes = [models.Index(fields=["business_task", "sort_order", "id"], name="task_checklist_task_order_idx")]


class TaskCollaborator(TimeStampedModel):
    business_task = models.ForeignKey(BusinessTask, on_delete=models.CASCADE, related_name="collaborators")
    employee = models.ForeignKey("organizations.Employee", on_delete=models.PROTECT, related_name="collaborative_tasks")
    added_by_employee = models.ForeignKey(
        "organizations.Employee", null=True, blank=True, on_delete=models.SET_NULL, related_name="task_collaborators_added"
    )

    class Meta:
        db_table = "task_collaborator"
        constraints = [models.UniqueConstraint(fields=["business_task", "employee"], name="task_collaborator_unique")]


class TaskBatchOperation(TimeStampedModel):
    event_id = models.UUIDField(unique=True)
    action = models.CharField(max_length=40)
    actor_employee = models.ForeignKey("organizations.Employee", on_delete=models.PROTECT, related_name="task_batch_operations")
    request_data = models.JSONField(default=dict, blank=True)
    result_data = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "task_batch_operation"
        indexes = [models.Index(fields=["actor_employee", "created_at", "id"], name="task_batch_actor_created_idx")]


class TaskEvent(TimeStampedModel):
    business_task = models.ForeignKey(BusinessTask, on_delete=models.CASCADE, related_name="events")
    event_type = models.CharField(max_length=50)
    actor_employee = models.ForeignKey(
        "organizations.Employee", null=True, blank=True, on_delete=models.SET_NULL, related_name="task_events_created"
    )
    batch_operation = models.ForeignKey(
        TaskBatchOperation, null=True, blank=True, on_delete=models.SET_NULL, related_name="task_events"
    )
    note = models.TextField(blank=True)
    before_data = models.JSONField(default=dict, blank=True)
    after_data = models.JSONField(default=dict, blank=True)
    occurred_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "task_event"
        indexes = [models.Index(fields=["business_task", "-occurred_at", "-id"], name="task_event_task_time_idx")]


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
