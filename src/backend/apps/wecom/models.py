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


class OAuthState(TimeStampedModel):
    state_digest = models.CharField(max_length=64, unique=True)
    session_digest = models.CharField(max_length=64)
    initiator_user_id = models.PositiveBigIntegerField(null=True, blank=True)
    config_etag = models.CharField(max_length=80)
    expires_at = models.DateTimeField(db_index=True)
    consumed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "wecom_oauth_state"
