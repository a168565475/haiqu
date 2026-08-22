from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from apps.core.models import UUIDPrimaryKeyModel, uppercase_code_validator


class AuditLog(UUIDPrimaryKeyModel):
    actor_employee = models.ForeignKey(
        "organizations.Employee",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="audit_logs",
    )
    actor_employee_code_snapshot = models.CharField(max_length=50, blank=True)
    actor_name_snapshot = models.CharField(max_length=150, blank=True)
    object_type = models.CharField(max_length=80, validators=[uppercase_code_validator])
    object_id = models.UUIDField()
    context_type = models.CharField(max_length=80, blank=True, validators=[uppercase_code_validator])
    context_id = models.UUIDField(null=True, blank=True)
    action = models.CharField(max_length=80, validators=[uppercase_code_validator])
    before_data = models.JSONField(default=dict, blank=True)
    after_data = models.JSONField(default=dict, blank=True)
    request_id = models.UUIDField(null=True, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=500, blank=True)
    occurred_at = models.DateTimeField()

    class Meta:
        db_table = "audit_log"
        default_permissions = ("add", "view")
        permissions = [
            ("view_all_auditlog", "可查看全部审计日志"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(context_type="", context_id__isnull=True)
                | (~Q(context_type="") & Q(context_id__isnull=False)),
                name="audit_context_pair_consistent",
            ),
        ]
        indexes = [
            models.Index(fields=["object_type", "object_id", "-occurred_at", "-id"], name="audit_object_history_idx"),
            models.Index(fields=["context_type", "context_id", "-occurred_at", "-id"], name="audit_context_history_idx"),
            models.Index(fields=["actor_employee", "-occurred_at", "-id"], name="audit_actor_history_idx"),
        ]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("审计日志只允许新增，不允许修改。")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("审计日志不允许删除。")
