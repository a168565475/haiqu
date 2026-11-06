"""采购跟踪状态与通知覆盖；数量账本仍属于原业务单据。"""
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator
from django.db import models
from django.db.models import Q

from apps.core.models import TimeStampedModel
from apps.material_catalog.definitions import CATEGORY_CHOICES


def default_tracking_category_lead_days():
    return {key: 2 for key, _label in CATEGORY_CHOICES}


def validate_tracking_category_lead_days(value):
    expected = {key for key, _label in CATEGORY_CHOICES}
    if not isinstance(value, dict) or set(value) != expected:
        raise ValidationError("采购提前期必须包含全部有效材料分类。")
    if any(days is not None and (type(days) is not int or not 0 <= days <= 365) for days in value.values()):
        raise ValidationError("采购提前期须为 0 至 365 天的整数，未设置时留空。")


class PurchaseTrackingPolicy(TimeStampedModel):
    key = models.CharField(max_length=16, unique=True, default="default", editable=False)
    bom_timeout_days = models.PositiveSmallIntegerField(default=2, null=True, blank=True, validators=[MaxValueValidator(365)])
    category_lead_days = models.JSONField(default=default_tracking_category_lead_days, validators=[validate_tracking_category_lead_days])
    updated_by_employee = models.ForeignKey("organizations.Employee", null=True, blank=True, on_delete=models.PROTECT)

    class Meta:
        db_table = "procurement_tracking_policy"
        default_permissions = ()
        constraints = [
            models.CheckConstraint(condition=Q(key="default"), name="tracking_policy_singleton_key"),
            models.CheckConstraint(condition=Q(bom_timeout_days__isnull=True) | Q(bom_timeout_days__gte=0, bom_timeout_days__lte=365), name="tracking_policy_bom_days_range"),
        ]


class PurchaseTrackingIssue(TimeStampedModel):
    source_key = models.CharField(max_length=240, unique=True)
    production_task = models.ForeignKey("production_tasks.ProductionTask", on_delete=models.PROTECT)
    kind = models.CharField(max_length=16)
    row_key = models.CharField(max_length=240)
    code = models.CharField(max_length=40)
    rank = models.PositiveIntegerField()
    active = models.BooleanField(default=True)
    cycle = models.PositiveIntegerField(default=1)
    transition = models.PositiveIntegerField(default=1)
    revision = models.PositiveIntegerField(default=1)
    # 降级仍保留状态变化序号，但不建立新的即时提醒机会。
    notify_transition = models.PositiveIntegerField(default=1)
    fingerprint = models.CharField(max_length=64)
    snapshot = models.JSONField(default=dict)
    first_seen_at = models.DateTimeField()
    evaluated_at = models.DateTimeField()
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolution_reason = models.CharField(max_length=100, blank=True)

    class Meta:
        db_table = "procurement_tracking_issue"
        constraints = [models.CheckConstraint(condition=Q(cycle__gte=1, transition__gte=1, revision__gte=1), name="tracking_issue_versions_positive")]
        indexes = [models.Index(fields=["production_task", "active"], name="tracking_issue_task_active")]


class PurchaseTrackingDigest(TimeStampedModel):
    employee = models.ForeignKey("organizations.Employee", on_delete=models.PROTECT)
    business_date = models.DateField()
    evaluated_at = models.DateTimeField()
    item_count = models.PositiveIntegerField(default=0)
    event = models.OneToOneField("wecom.NotificationEvent", null=True, blank=True, on_delete=models.PROTECT)

    class Meta:
        db_table = "procurement_tracking_digest"
        constraints = [models.UniqueConstraint(fields=["employee", "business_date"], name="tracking_digest_employee_day")]


class PurchaseTrackingNotice(TimeStampedModel):
    """逐员工、渠道的覆盖记录；摘要与即时生产者在同一锁下认领。"""
    issue = models.ForeignKey(PurchaseTrackingIssue, on_delete=models.PROTECT, related_name="notices")
    cycle = models.PositiveIntegerField()
    transition = models.PositiveIntegerField()
    employee = models.ForeignKey("organizations.Employee", on_delete=models.PROTECT)
    channel = models.CharField(max_length=10, choices=[("IN_APP", "ERP站内"), ("WECOM", "企业微信")])
    digest = models.ForeignKey(PurchaseTrackingDigest, null=True, blank=True, on_delete=models.PROTECT)
    delivery = models.ForeignKey("wecom.NotificationDelivery", on_delete=models.PROTECT, related_name="tracking_notices")

    class Meta:
        db_table = "procurement_tracking_notice"
        constraints = [
            models.UniqueConstraint(fields=["issue", "cycle", "transition", "employee", "channel"], condition=Q(digest__isnull=True), name="tracking_instant_once"),
            models.UniqueConstraint(fields=["digest", "issue", "cycle", "transition", "channel"], condition=Q(digest__isnull=False), name="tracking_digest_item_once"),
        ]


class PurchaseTrackingContent(TimeStampedModel):
    """仅追加的渠道正文版本；已尝试渠道的选定版本不再修订。"""
    delivery = models.ForeignKey("wecom.NotificationDelivery", on_delete=models.PROTECT, related_name="tracking_contents")
    revision = models.PositiveIntegerField()
    items = models.JSONField(default=list)
    title = models.CharField(max_length=200)
    body = models.TextField()
    parts = models.JSONField(default=list)
    target = models.JSONField(default=dict)

    class Meta:
        db_table = "procurement_tracking_content"
        ordering = ["-revision"]
        constraints = [models.UniqueConstraint(fields=["delivery", "revision"], name="tracking_content_version_once")]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("采购通知内容版本仅允许追加。")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("采购通知内容版本不能删除。")
