from django.db import models
from django.db.models import Q
from django.db.models.functions import Lower

from apps.core.models import TimeStampedModel


class AttendanceMonth(TimeStampedModel):
    corp_id = models.CharField(max_length=100)
    month = models.CharField(max_length=7)
    active_run = models.ForeignKey("AttendanceSyncRun", null=True, blank=True, on_delete=models.PROTECT,
                                   related_name="visible_months")
    current_run = models.ForeignKey("AttendanceSyncRun", null=True, blank=True, on_delete=models.PROTECT,
                                    related_name="advancing_months")

    class Meta:
        db_table = "attendance_month"
        constraints = [models.UniqueConstraint(fields=["corp_id", "month"], name="attendance_corp_month_unique")]
        default_permissions = ()
        permissions = [("view_attendance", "查看考勤"), ("sync_attendance", "同步考勤"),
                       ("manage_schedule", "设置月度上班时间")]


class AttendanceSyncRun(TimeStampedModel):
    class Status(models.TextChoices):
        PENDING = "PENDING", "待开始"
        RUNNING = "RUNNING", "进行中"
        FAILED = "FAILED", "失败可重试"
        SUCCESS = "SUCCESS", "成功"
        INVALIDATED = "INVALIDATED", "已失效"

    period = models.ForeignKey(AttendanceMonth, on_delete=models.PROTECT, related_name="runs")
    idempotency_key = models.UUIDField(unique=True)
    config_version = models.CharField(max_length=64)
    requested_by = models.CharField(max_length=64)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    steps = models.JSONField(default=list)
    completed_steps = models.PositiveIntegerField(default=0)
    roster = models.JSONField(default=dict)
    scope = models.JSONField(default=dict)
    scanned_members = models.PositiveIntegerField(default=0)
    lease_token = models.UUIDField(null=True, blank=True)
    lease_expires_at = models.DateTimeField(null=True, blank=True)
    error_code = models.CharField(max_length=80, blank=True)
    error_message = models.CharField(max_length=250, blank=True)
    retry_after = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "attendance_sync_run"
        default_permissions = ()
        constraints = [models.CheckConstraint(condition=Q(status__in=["PENDING", "RUNNING", "FAILED", "SUCCESS", "INVALIDATED"]),
                                             name="attendance_run_status_valid")]


class AttendancePerson(TimeStampedModel):
    corp_id = models.CharField(max_length=100)
    user_id = models.CharField(max_length=64)

    class Meta:
        db_table = "attendance_person"
        default_permissions = ()
        constraints = [models.UniqueConstraint("corp_id", Lower("user_id"), name="attendance_person_identity")]


class AttendanceMember(TimeStampedModel):
    run = models.ForeignKey(AttendanceSyncRun, on_delete=models.PROTECT, related_name="members")
    person = models.ForeignKey(AttendancePerson, on_delete=models.PROTECT, related_name="snapshots")
    user_id = models.CharField(max_length=64)
    name = models.CharField(max_length=150, blank=True)

    class Meta:
        db_table = "attendance_member"
        default_permissions = ()
        constraints = [models.UniqueConstraint(fields=["run", "person"], name="attendance_run_person_unique")]
        indexes = [models.Index(fields=["run", "user_id"], name="attendance_member_user_idx")]


class AttendanceRecord(TimeStampedModel):
    run = models.ForeignKey(AttendanceSyncRun, on_delete=models.PROTECT, related_name="records")
    kind = models.CharField(max_length=10, choices=[("raw", "打卡"), ("daily", "日报"), ("monthly", "月报")])
    step_index = models.PositiveIntegerField()
    row_index = models.PositiveIntegerField()
    user_id = models.CharField(max_length=64)
    date = models.DateField()
    payload = models.JSONField()

    class Meta:
        db_table = "attendance_record"
        default_permissions = ()
        constraints = [models.UniqueConstraint(fields=["run", "step_index", "row_index"], name="attendance_record_step_row"),
                       models.CheckConstraint(condition=Q(kind__in=["raw", "daily", "monthly"]), name="attendance_record_kind_valid")]
        indexes = [models.Index(fields=["run", "kind", "date", "user_id"], name="attendance_record_query_idx")]


class AttendanceSchedule(TimeStampedModel):
    corp_id = models.CharField(max_length=100)
    month = models.DateField()
    days = models.JSONField(default=list)
    source_rule_id = models.PositiveBigIntegerField(null=True, blank=True)
    source_rule_name = models.CharField(max_length=150, blank=True)
    source_fetched_at = models.DateTimeField(null=True, blank=True)
    source_warnings = models.JSONField(default=list)

    class Meta:
        db_table = "attendance_schedule"
        default_permissions = ()
        constraints = [models.UniqueConstraint(fields=["corp_id", "month"], name="attendance_schedule_month_unique")]
