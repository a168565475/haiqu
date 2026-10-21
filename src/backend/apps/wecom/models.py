from django.db import models
from django.db.models import Q
from django.db.models.functions import Lower

from apps.core.models import TimeStampedModel


class WeComConfig(TimeStampedModel):
    singleton = models.PositiveSmallIntegerField(default=1, unique=True)
    corp_id = models.CharField(max_length=100, default="ww08890a52e3ab432d")
    agent_id = models.CharField(max_length=30, default="1000010")
    erp_origin = models.URLField(max_length=255, default="https://erp.cnhitree.com")
    enabled = models.BooleanField(default=False)
    secret_ciphertext = models.TextField(blank=True)
    callback_token_ciphertext = models.TextField(blank=True)
    callback_aes_key_ciphertext = models.TextField(blank=True)
    last_check_status = models.CharField(max_length=20, default="NOT_CHECKED", choices=[
        ("NOT_CHECKED", "未检查"), ("SUCCESS", "成功"), ("FAILED", "失败"),
    ])
    last_check_message = models.CharField(max_length=250, blank=True)
    last_checked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "wecom_config"
        constraints = [
            models.CheckConstraint(condition=Q(singleton=1), name="wecom_config_singleton"),
            models.CheckConstraint(condition=Q(last_check_status__in=["NOT_CHECKED", "SUCCESS", "FAILED"]), name="wecom_check_status_valid"),
        ]


class WeComBinding(TimeStampedModel):
    corp_id = models.CharField(max_length=100)
    user_id = models.CharField(max_length=64)
    member_name = models.CharField(max_length=150)
    employee = models.OneToOneField("organizations.Employee", on_delete=models.PROTECT, related_name="wecom_binding")
    source = models.CharField(max_length=10, choices=[("AUTO", "自动建档"), ("MANUAL", "管理员绑定")])
    created_account = models.BooleanField(default=False)
    created_by_employee = models.ForeignKey("organizations.Employee", null=True, blank=True,
                                             on_delete=models.PROTECT, related_name="wecom_bindings_created")

    class Meta:
        db_table = "wecom_binding"
        ordering = ["-created_at", "-id"]
        constraints = [
            models.UniqueConstraint("corp_id", Lower("user_id"), name="wecom_corp_user_ci_unique"),
            models.CheckConstraint(condition=Q(source__in=["AUTO", "MANUAL"]), name="wecom_binding_source_valid"),
        ]


class WeComDepartmentMapping(TimeStampedModel):
    corp_id = models.CharField(max_length=100)
    wecom_department_id = models.PositiveBigIntegerField()
    wecom_department_name = models.CharField(max_length=768)
    organization_unit = models.ForeignKey(
        "organizations.OrganizationUnit", null=True, blank=True, on_delete=models.PROTECT,
        related_name="wecom_department_mappings",
    )

    class Meta:
        db_table = "wecom_department_mapping"
        ordering = ["wecom_department_id"]
        constraints = [
            models.UniqueConstraint(fields=["corp_id", "wecom_department_id"], name="wecom_department_source_unique"),
            models.CheckConstraint(condition=Q(wecom_department_id__gte=1, wecom_department_id__lt=4294967296),
                                   name="wecom_department_uint32"),
        ]


class OAuthState(TimeStampedModel):
    state_digest = models.CharField(max_length=64, unique=True)
    session_digest = models.CharField(max_length=64)
    initiator_user_id = models.PositiveBigIntegerField(null=True, blank=True)
    config_etag = models.CharField(max_length=80)
    expires_at = models.DateTimeField(db_index=True)
    consumed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "wecom_oauth_state"


class WeComMessageTemplate(TimeStampedModel):
    singleton = models.PositiveSmallIntegerField(default=1)
    name = models.CharField(max_length=50)
    body = models.TextField()
    updated_by_employee = models.ForeignKey("organizations.Employee", on_delete=models.PROTECT,
                                            related_name="wecom_templates_updated")

    class Meta:
        db_table = "wecom_message_template"
        constraints = [
            models.UniqueConstraint(fields=["singleton"], name="wecom_msg_template_singleton_uniq"),
            models.CheckConstraint(condition=Q(singleton=1), name="wecom_msg_template_singleton"),
        ]


class WeComMessageAttempt(TimeStampedModel):
    class Status(models.TextChoices):
        PROCESSING = "PROCESSING", "发送处理中"
        ACCEPTED = "ACCEPTED", "企业微信已接受"
        FAILED = "FAILED", "确认失败"
        UNCERTAIN = "UNCERTAIN", "结果待核对"

    template = models.ForeignKey(WeComMessageTemplate, on_delete=models.PROTECT, related_name="attempts")
    binding = models.ForeignKey(WeComBinding, on_delete=models.PROTECT, related_name="message_attempts")
    requested_by_employee = models.ForeignKey("organizations.Employee", on_delete=models.PROTECT,
                                              related_name="wecom_message_attempts")
    idempotency_key = models.UUIDField(unique=True)
    request_hash = models.CharField(max_length=64)
    payload_hash = models.CharField(max_length=64)
    template_name = models.CharField(max_length=50)
    recipient_name = models.CharField(max_length=150)
    corp_id = models.CharField(max_length=100)
    agent_id = models.CharField(max_length=30)
    user_id = models.CharField(max_length=64)
    rendered_body = models.TextField()
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PROCESSING)
    error_code = models.CharField(max_length=80, blank=True)
    msgid = models.CharField(max_length=512, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "wecom_message_attempt"
        ordering = ["-created_at", "-id"]
        constraints = [models.CheckConstraint(condition=Q(status__in=["PROCESSING", "ACCEPTED", "FAILED", "UNCERTAIN"]),
                                              name="wecom_msg_attempt_status")]
        indexes = [models.Index(fields=["payload_hash", "status"], name="wecom_msg_pending_idx")]


class NotificationRule(TimeStampedModel):
    """每个已登记业务事件的一份当前配置。"""

    event_code = models.CharField(max_length=80, unique=True)
    name = models.CharField(max_length=100)
    title_template = models.CharField(max_length=200)
    body_template = models.TextField()
    allowed_variables = models.JSONField(default=list)
    recipient_role_codes = models.JSONField(default=list)
    recipient_scope = models.CharField(max_length=20)
    enabled = models.BooleanField(default=False)
    version = models.PositiveIntegerField(default=1)
    updated_by_employee = models.ForeignKey("organizations.Employee", on_delete=models.PROTECT,
                                            related_name="notification_rules_updated")

    class Meta:
        db_table = "wecom_notification_rule"
        ordering = ["event_code"]
        constraints = [
            models.CheckConstraint(condition=Q(version__gte=1), name="wecom_notification_rule_version_positive"),
        ]


class NotificationEvent(TimeStampedModel):
    """业务事务内保存的事件及模板/接收人快照。"""

    event_code = models.CharField(max_length=80)
    idempotency_key = models.CharField(max_length=180, unique=True)
    object_type = models.CharField(max_length=100)
    object_id = models.CharField(max_length=100, blank=True)
    object_version = models.CharField(max_length=80, blank=True)
    context = models.JSONField(default=dict)
    rule_version = models.PositiveIntegerField()
    template_name = models.CharField(max_length=100)
    rendered_title = models.CharField(max_length=200)
    rendered_body = models.TextField()
    target = models.JSONField(null=True, blank=True)
    status = models.CharField(max_length=20, default="CREATED")

    class Meta:
        db_table = "wecom_notification_event"
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=["event_code", "created_at"], name="wecom_notify_event_idx")]


class NotificationRecipient(TimeStampedModel):
    event = models.ForeignKey(NotificationEvent, on_delete=models.CASCADE, related_name="recipients")
    employee = models.ForeignKey("organizations.Employee", on_delete=models.PROTECT, related_name="notification_recipients")
    employee_name = models.CharField(max_length=150)
    role_codes = models.JSONField(default=list)
    scope = models.CharField(max_length=20)
    read_at = models.DateTimeField(null=True, blank=True)
    eligibility_snapshot = models.JSONField(default=dict)

    class Meta:
        db_table = "wecom_notification_recipient"
        constraints = [models.UniqueConstraint(fields=["event", "employee"], name="wecom_notify_recipient_unique")]
        indexes = [models.Index(fields=["employee", "read_at", "created_at"], name="wecom_notify_inbox_idx")]


class NotificationDelivery(TimeStampedModel):
    class Channel(models.TextChoices):
        IN_APP = "IN_APP", "ERP站内"
        WECOM = "WECOM", "企业微信"

    class Status(models.TextChoices):
        PENDING = "PENDING", "待投递"
        PROCESSING = "PROCESSING", "投递处理中"
        ACCEPTED = "ACCEPTED", "企业微信已接受"
        FAILED = "FAILED", "确认失败"
        UNCERTAIN = "UNCERTAIN", "结果待核对"
        SKIPPED = "SKIPPED", "跳过"

    recipient = models.ForeignKey(NotificationRecipient, on_delete=models.CASCADE, related_name="deliveries")
    channel = models.CharField(max_length=10, choices=Channel.choices)
    idempotency_key = models.CharField(max_length=220, unique=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    error_code = models.CharField(max_length=80, blank=True)
    msgid = models.CharField(max_length=512, blank=True)
    attempt_count = models.PositiveIntegerField(default=0)
    last_attempt_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    user_id_snapshot = models.CharField(max_length=64, blank=True)

    class Meta:
        db_table = "wecom_notification_delivery"
        constraints = [models.UniqueConstraint(fields=["recipient", "channel"], name="wecom_notify_delivery_unique")]
        indexes = [models.Index(fields=["channel", "status", "created_at"], name="wecom_notify_deliv_queue")]
