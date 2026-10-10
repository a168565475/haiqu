from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q

from apps.core.models import TimeStampedModel


class SmtpSecurity(models.TextChoices):
    STARTTLS = "STARTTLS", "STARTTLS"
    SSL = "SSL", "SSL/TLS"


class EmailAccountTestStatus(models.TextChoices):
    NOT_TESTED = "NOT_TESTED", "未测试"
    SUCCESS = "SUCCESS", "测试成功"
    FAILED = "FAILED", "测试失败"


class EmailAccount(TimeStampedModel):
    employee = models.ForeignKey(
        "organizations.Employee",
        on_delete=models.PROTECT,
        related_name="email_accounts",
    )
    display_name = models.CharField(max_length=100)
    sender_name = models.CharField(max_length=150, blank=True)
    sender_email = models.EmailField(max_length=254)
    smtp_host = models.CharField(max_length=255)
    smtp_port = models.PositiveIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(65535)],
    )
    smtp_username = models.CharField(max_length=254)
    smtp_password_ciphertext = models.TextField()
    smtp_security = models.CharField(max_length=20, choices=SmtpSecurity.choices)
    is_enabled = models.BooleanField(default=True)
    is_default = models.BooleanField(default=False)
    last_test_status = models.CharField(
        max_length=20,
        choices=EmailAccountTestStatus.choices,
        default=EmailAccountTestStatus.NOT_TESTED,
    )
    last_tested_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "email_account"
        ordering = ["employee", "-is_default", "display_name", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["employee", "display_name"],
                name="email_account_employee_display_name_uniq",
            ),
            models.UniqueConstraint(
                fields=["employee"],
                condition=Q(is_default=True),
                name="email_account_one_default_per_employee",
            ),
            models.CheckConstraint(
                condition=Q(smtp_port__gte=1) & Q(smtp_port__lte=65535),
                name="email_account_smtp_port_valid",
            ),
            models.CheckConstraint(
                condition=Q(is_default=False) | Q(is_enabled=True),
                name="email_account_default_requires_enabled",
            ),
        ]
        indexes = [
            models.Index(
                fields=["employee", "is_enabled", "is_default"],
                name="email_acct_sender_idx",
            ),
        ]

    def clean(self):
        super().clean()
        if self.is_default and not self.is_enabled:
            raise ValidationError({"is_default": "默认邮箱必须处于启用状态。"})

    def __str__(self):
        return f"{self.employee_id} - {self.display_name}"
